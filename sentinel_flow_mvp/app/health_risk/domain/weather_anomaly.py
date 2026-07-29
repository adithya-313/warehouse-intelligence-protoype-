"""
Calculates a weather anomaly score for disease risk assessment.

WHY A SEPARATE FUNCTION INSTEAD OF INLINE IN THE SCORER:
Keeping weather logic in its own pure function makes it independently
testable and replaceable. If we later add more weather signals (wind
speed, temperature), we can change this function without touching the
scorer or the risk score dataclass.

THRESHOLD RATIONALE:
Kerala's monsoon season typically brings humidity above 80% and daily
rainfall exceeding 10mm. These conditions directly drive disease risk:

- DENGUE: Aedes mosquitoes breed in standing water. Humidity >80%
  increases mosquito survival and biting rates. Rain >10mm creates
  the standing water pools where mosquitoes lay eggs.
- LEPTOSPIROSIS: Leptospira bacteria spread through floodwater.
  Heavy rain (>10mm) causes urban flooding, and humidity >80% keeps
  surfaces wet longer, prolonging bacterial survival outside a host.

Scoring tiers:
  HIGH    (90) — humidity >80% AND rain >10mm
                 Both conditions met → full outbreak potential
  MODERATE (60) — humidity >80% OR rain >10mm
                 One condition met → elevated but not critical
  LOW     (20) — neither condition met
                 Weather is not amplifying disease risk

These are deliberately round numbers so a pharmacist can easily reason
about them: 90 is "high concern", 60 is "keep an eye on it", 20 is
"weather is fine".
"""

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Well-documented threshold constants so anyone can adjust them without
# reading through the whole function body.
# ---------------------------------------------------------------------------
HIGH_HUMIDITY_THRESHOLD: float = 80.0   # Percent relative humidity
HIGH_RAIN_THRESHOLD: float = 10.0       # Millimetres of precipitation
NEUTRAL_SCORE: float = 50.0             # Value returned when data is missing

HIGH_ANOMALY_SCORE: float = 90.0       # Both thresholds exceeded
MODERATE_ANOMALY_SCORE: float = 60.0   # One threshold exceeded
LOW_ANOMALY_SCORE: float = 20.0        # Neither threshold exceeded


def calculate_weather_anomaly(
    humidity_percent: float | None,
    rain_mm: float | None,
) -> float:
    """
    Returns a 0-100 score representing how abnormal the weather is for disease risk.

    Parameters match what the ingestion pipeline (trend_fetcher + parsers.py)
    provides, so callers can pass their data directly without transformation.

    Args:
        humidity_percent: Relative humidity (0-100), or None if missing.
        rain_mm:          Precipitation in millimetres, or None if missing.

    Returns:
        Float between 0.0 and 100.0. Higher = more conducive to disease spread.
        Returns 50.0 (neutral) if any input is None — never crashes.
    """
    # ------------------------------------------------------------------
    # Guard: if either weather signal is missing, we cannot make a
    # meaningful assessment. Return neutral instead of guessing.
    # ------------------------------------------------------------------
    if humidity_percent is None or rain_mm is None:
        logger.info(
            "Weather data incomplete — humidity=%s, rain=%s. "
            "Returning neutral anomaly=50.0.",
            humidity_percent,
            rain_mm,
        )
        return NEUTRAL_SCORE

    # ------------------------------------------------------------------
    # HIGH anomaly: both humidity AND rain are elevated.
    # This is the classic "monsoon conditions" scenario where both
    # dengue (mosquito breeding) and leptospirosis (floodwater) risk
    # are amplified simultaneously.
    # ------------------------------------------------------------------
    if humidity_percent > HIGH_HUMIDITY_THRESHOLD and rain_mm > HIGH_RAIN_THRESHOLD:
        logger.info(
            "Weather anomaly: HIGH (humidity=%.1f%% > %.0f%%, rain=%.1fmm > %.0fmm). "
            "Returning score=%.0f.",
            humidity_percent,
            HIGH_HUMIDITY_THRESHOLD,
            rain_mm,
            HIGH_RAIN_THRESHOLD,
            HIGH_ANOMALY_SCORE,
        )
        return HIGH_ANOMALY_SCORE

    # ------------------------------------------------------------------
    # MODERATE anomaly: one of the two conditions is elevated.
    # For example, high humidity alone means mosquitoes survive longer,
    # but without standing water (low rain) their breeding is limited.
    # ------------------------------------------------------------------
    if humidity_percent > HIGH_HUMIDITY_THRESHOLD or rain_mm > HIGH_RAIN_THRESHOLD:
        logger.info(
            "Weather anomaly: MODERATE (humidity=%.1f%%, rain=%.1fmm). "
            "Returning score=%.0f.",
            humidity_percent,
            rain_mm,
            MODERATE_ANOMALY_SCORE,
        )
        return MODERATE_ANOMALY_SCORE

    # ------------------------------------------------------------------
    # LOW anomaly: neither condition is elevated.
    # Weather is normal for the region and is not contributing to
    # disease spread risk.
    # ------------------------------------------------------------------
    logger.info(
        "Weather anomaly: LOW (humidity=%.1f%%, rain=%.1fmm). "
        "Returning score=%.0f.",
        humidity_percent,
        rain_mm,
        LOW_ANOMALY_SCORE,
    )
    return LOW_ANOMALY_SCORE
