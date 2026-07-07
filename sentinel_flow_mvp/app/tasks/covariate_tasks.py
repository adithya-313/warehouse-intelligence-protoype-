import logging
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import insert
from app.core.celery_app import celery_application as celery_app
from app.infrastructure.database import SessionLocal
from app.infrastructure.models import Tenant, ExogenousCovariateModel
from app.services.covariates.parsers import CovariateParser
from app.core.config import get_application_settings

settings = get_application_settings()

logger = logging.getLogger(__name__)

@celery_app.task(name="fetch_exogenous_covariates_task")
def fetch_exogenous_covariates_task():
    """
    Background job to fetch weather and trends for all active pincodes.
    Runs periodically via Celery Beat.
    """
    logger.info("Starting exogenous covariate ingestion cycle.")
    db = SessionLocal()
    try:
        # 1. Get unique pincodes from all tenants to avoid redundant API calls
        unique_pincodes = db.query(Tenant.pincode).filter(
            Tenant.pincode.isnot(None), 
            Tenant.is_active == True
        ).distinct().all()
        
        pincodes = [p[0] for p in unique_pincodes]
        logger.info(f"Found {len(pincodes)} unique active pincodes.")

        keywords_to_track = ["dengue symptoms", "viral fever treatments"]
        current_time = datetime.now(timezone.utc)

        for pin in pincodes:
            # 2. Fetch Data
            weather_data = CovariateParser.fetch_weather_by_pincode(pin, settings.WEATHER_API_KEY)
            
            for keyword in keywords_to_track:
                trend_data = CovariateParser.fetch_trends_by_pincode(pin, keyword, settings.TRENDS_API_KEY)
                
                # 3. Idempotent Upsert (Insert, or Update if exists)
                stmt = insert(ExogenousCovariateModel).values(
                    pincode=pin,
                    timestamp=current_time,
                    humidity_percent=weather_data.get("humidity_percent"),
                    rain_mm=weather_data.get("rain_mm"),
                    symptom_keyword=trend_data.get("symptom_keyword"),
                    trend_score=trend_data.get("trend_score")
                )
                
                # If this exact pincode, time, and keyword exists, update the metrics
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
        logger.info("Successfully ingested exogenous covariates.")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to ingest covariates: {str(e)}")
        raise e
    finally:
        db.close()
