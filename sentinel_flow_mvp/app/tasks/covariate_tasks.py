import logging
import json
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import insert
import redis

from app.core.celery_app import celery_app
from app.infrastructure.database import SessionLocal
from app.infrastructure.models import Tenant, ExogenousCovariateModel
from app.services.covariates.parsers import CovariateParser
from app.core.config import get_application_settings

logger = logging.getLogger(__name__)
settings = get_application_settings()

# Initialize Redis client for caching (using standard config)
redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)

@celery_app.task(name="fetch_exogenous_covariates_task")
def fetch_exogenous_covariates_task():
    """
    Production background job:
    1. Resolves Pincodes to Cities (Cached).
    2. Fetches Weather per Pincode (Cached).
    3. Fetches Trends per City (Cached).
    4. Upserts to PostgreSQL.
    """
    logger.info("Starting production exogenous covariate ingestion cycle.")
    db = SessionLocal()
    try:
        unique_pincodes = db.query(Tenant.pincode).filter(
            Tenant.pincode.isnot(None), Tenant.is_active == True
        ).distinct().all()
        
        pincodes = [p[0] for p in unique_pincodes]
        keywords_to_track = ["viral fever treatments", "dengue symptoms"]
        current_time = datetime.now(timezone.utc)

        # Dictionaries to hold aggregated data
        city_trends_cache = {}

        for pin in pincodes:
            # --- 1. GEOCODING (With Redis Cache) ---
            geo_cache_key = f"geo:{pin}"
            cached_geo = redis_client.get(geo_cache_key)
            
            if cached_geo:
                lat, lon, city = json.loads(cached_geo)
            else:
                lat, lon, city = CovariateParser.get_location_details(pin)
                redis_client.setex(geo_cache_key, 86400, json.dumps([lat, lon, city])) # Cache for 24 hours

            # --- 2. WEATHER FETCH (With Redis Cache) ---
            weather_cache_key = f"weather:{pin}"
            cached_weather = redis_client.get(weather_cache_key)
            
            if cached_weather:
                weather_data = json.loads(cached_weather)
            else:
                weather_data = CovariateParser.fetch_weather_by_coords(lat, lon)
                redis_client.setex(weather_cache_key, 21600, json.dumps(weather_data)) # Cache for 6 hours

            # --- 3. TREND FETCH (City-Level Aggregation) ---
            for keyword in keywords_to_track:
                trend_cache_key = f"trend:{city}:{keyword}"
                
                # Check local memory cache first, then Redis
                if trend_cache_key not in city_trends_cache:
                    cached_trend = redis_client.get(trend_cache_key)
                    if cached_trend:
                        city_trends_cache[trend_cache_key] = json.loads(cached_trend)
                    else:
                        trend_data = CovariateParser.fetch_trends_by_city(city, keyword)
                        redis_client.setex(trend_cache_key, 21600, json.dumps(trend_data))
                        city_trends_cache[trend_cache_key] = trend_data
                
                trend_data = city_trends_cache[trend_cache_key]

                # --- 4. IDEMPOTENT UPSERT ---
                stmt = insert(ExogenousCovariateModel).values(
                    pincode=pin,
                    timestamp=current_time,
                    humidity_percent=weather_data.get("humidity_percent"),
                    rain_mm=weather_data.get("rain_mm"),
                    symptom_keyword=trend_data.get("symptom_keyword"),
                    trend_score=trend_data.get("trend_score")
                )
                
                upsert_stmt = stmt.on_conflict_do_update(
                    index_elements=['pincode', 'timestamp', 'symptom_keyword'],
                    set_={
                        'humidity_percent': stmt.excluded.humidity_percent,
                        'rain_mm': stmt.excluded.rain_mm,
                        'trend_score': stmt.excluded.trend_score
                    }
                )
                db.execute(upsert_stmt)
        
        db.commit()
        logger.info("Successfully ingested production covariates.")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to ingest covariates: {str(e)}")
    finally:
        db.close()
