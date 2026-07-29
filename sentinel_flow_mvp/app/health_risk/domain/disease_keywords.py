"""
Maps each DiseaseCategory to the Google Trends search keyword used to fetch its trend score.

WHY A SEPARATE DICT INSTEAD OF A FIELD ON THE ENUM ITSELF:
The DiseaseCategory enum lives in the domain layer and should not depend on
external search behaviour. The keyword is an operational detail (what people
actually search on Google), not a property of the disease itself. Keeping them
separate means changing keywords doesn't touch the domain enum, and we can
have multiple keywords per disease later (e.g. "dengue fever", "dengue symptoms").

CURRENT KEYWORD RATIONALE:
  DENGUE:        "dengue symptoms" — matches the existing keyword in
                 app/tasks/covariate_tasks.py line 36.
  VIRAL_FEVER:   "viral fever treatments" — matches the existing keyword in
                 app/tasks/covariate_tasks.py line 36.
  LEPTOSPIROSIS: "leptospirosis symptoms" — no existing keyword in the old
                 codebase, but this is the most natural search term users
                 would type when experiencing symptoms of leptospirosis
                 (fever + muscle pain + red eyes after floodwater exposure).
"""

from app.health_risk.domain.disease_category import DiseaseCategory

# Map each disease to the Google Trends keyword we search for.
# These should match the keywords used by the existing covariate ingestion
# pipeline so we don't double-fetch different keywords for the same disease.
DISEASE_KEYWORDS: dict[DiseaseCategory, str] = {
    DiseaseCategory.DENGUE: "dengue symptoms",
    DiseaseCategory.LEPTOSPIROSIS: "leptospirosis symptoms",
    DiseaseCategory.VIRAL_FEVER: "viral fever treatments",
}
