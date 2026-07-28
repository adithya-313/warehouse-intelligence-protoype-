from app.services.sanitizer import QuerySanitizer
import difflib

sanitizer = QuerySanitizer()
valid_names = ["AMOXYCILLIN", "AMPICILLIN", "AUGMENTIN625", "GENERIC_REF_AMOXYCILLIN"]
print("difflib match:", difflib.get_close_matches("AMOXICILLIN", [n.upper() for n in valid_names], n=1, cutoff=0.6))

res = sanitizer.clean_drug_names("what is amoxicillin used for", valid_names)
print("Result:", res)
