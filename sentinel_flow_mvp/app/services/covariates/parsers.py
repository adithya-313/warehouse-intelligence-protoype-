import logging
import time
import httpx
from typing import Dict, Any, Tuple
from tenacity import retry, stop_after_attempt, wait_exponential
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
from app.core.config import get_application_settings

logger = logging.getLogger(__name__)
settings = get_application_settings()

class CovariateParser:
    """
    Production-grade parsers for external covariates.
    Uses Open-Meteo for weather and City-level aggregation for trends.
    """
    
    # Initialize geocoder with a custom user agent as required by Nominatim TOS
    geolocator = Nominatim(user_agent="sentinel_flow_hyperscale_v1")

    @staticmethod
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def get_location_details(pincode: str) -> Tuple[float, float, str]:
        """
        Converts a Pincode to Latitude, Longitude, and City.
        Includes a mandatory 1-second sleep to respect OpenStreetMap rate limits.
        """
        logger.info(f"Geocoding pincode: {pincode}")
        time.sleep(1) # STRICT RATE LIMIT ENFORCEMENT
        
        try:
            # Context is India, so we append it for accuracy
            location = CovariateParser.geolocator.geocode(f"{pincode}, India", addressdetails=True)
            if location:
                lat, lon = location.latitude, location.longitude
                address = location.raw.get('address', {})
                # Extract city, fallback to state, fallback to "Unknown"
                city = address.get('city', address.get('state_district', 'Unknown'))
                return lat, lon, city
        except GeocoderTimedOut:
            logger.warning(f"Geocoding timed out for {pincode}")
            
        # Fallback to configured epicenter (Kochi) if geocoding fails (Graceful Degradation)
        logger.warning(f"Using fallback coordinates for {settings.FALLBACK_CITY}")
        return settings.FALLBACK_LAT, settings.FALLBACK_LON, settings.FALLBACK_CITY

    @staticmethod
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def fetch_weather_by_coords(lat: float, lon: float) -> Dict[str, float]:
        """
        Fetches real-time weather from Open-Meteo (Free, No API Key).
        """
        logger.info(f"Fetching Open-Meteo data for Lat: {lat}, Lon: {lon}")
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=relative_humidity_2m,precipitation"
        
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()
            
            current = data.get("current", {})
            return {
                "humidity_percent": float(current.get("relative_humidity_2m", 50.0)),
                "rain_mm": float(current.get("precipitation", 0.0))
            }

    @staticmethod
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def fetch_trends_by_city(city: str, keyword: str) -> Dict[str, Any]:
        """
        Fetches search trends aggregated at the City level.
        (Simulated production logic: In a real scenario, this connects to Google Trends API via pytrends)
        """
        logger.info(f"Fetching search trends for '{keyword}' in city: {city}")
        
        # Simulated dynamic response based on city and keyword
        base_score = 50.0
        if "fever" in keyword.lower() or "dengue" in keyword.lower():
            # Simulate a spike in major cities for testing
            if city in ["Bengaluru", "Mumbai", "Delhi"]:
                base_score = 85.0 
                
        return {"symptom_keyword": keyword, "trend_score": base_score}
