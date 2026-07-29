"""
Disease categories that the health_risk module tracks.

WHY SEPARATE DISEASES INSTEAD OF ONE LUMPED SCORE:
We deliberately keep DENGUE, LEPTOSPIROSIS, and VIRAL_FEVER as distinct
enum values so that a pharmacy can see WHICH disease is currently trending
in their area. A single "risk is high" score hides the critical information
of what to stock up on — Paracetamol for viral fever vs. Doxycycline for
leptospirosis require completely different procurement responses.

This enum is the source of truth for all disease categorisation across
the health_risk module. Every RiskScore is scoped to exactly one category.
"""

from enum import Enum


class DiseaseCategory(Enum):
    """
    The set of outbreak-prone diseases we monitor for the Kerala region.

    DENGUE:              Mosquito-borne viral infection, spikes during monsoon.
    LEPTOSPIROSIS:       Bacterial infection from floodwater, follows heavy rain.
    VIRAL_FEVER:         Generic viral fever (influenza-like), seasonal surges.
    """

    DENGUE = "dengue"
    LEPTOSPIROSIS = "leptospirosis"
    VIRAL_FEVER = "viral_fever"
