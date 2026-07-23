import requests, json

# Check amoxycillin (which matched via step_d — transform_spelling turned "amoxycillin" -> "amoxicillin")
url = 'https://api.fda.gov/drug/label.json?search=openfda.generic_name:"amoxicillin"&limit=5'
r = requests.get(url, timeout=10)
data = r.json()

for res in data['results']:
    openfda = res.get('openfda', {})
    gnames = openfda.get('generic_name', [])
    if len(gnames) == 1 and 'amoxicillin' in gnames[0].lower():
        print('Found single-ingredient amoxicillin label')
        clinical_keys = ['dosage_and_administration','pregnancy','pregnancy_or_breast_feeding',
                         'pediatric_use','warnings','warnings_and_cautions',
                         'drug_interactions','contraindications']
        for k in clinical_keys:
            present = k in res
            val_preview = str(res[k])[:100] if present else 'ABSENT'
            print(f"  {k}: {val_preview}")
        break

# Also check a combo product
print("\n--- Checking a combo product (amoxycillin matched via AMOXICILLIN AND CLAVULANATE) ---")
url2 = 'https://api.fda.gov/drug/label.json?search=openfda.generic_name:"amoxicillin+and+clavulanate"&limit=1'
r2 = requests.get(url2, timeout=10)
data2 = r2.json()
if data2.get('results'):
    res2 = data2['results'][0]
    print('Combo label keys present:')
    clinical_keys = ['dosage_and_administration','pregnancy','pediatric_use','warnings','warnings_and_cautions','drug_interactions','contraindications']
    for k in clinical_keys:
        present = k in res2
        print(f"  {k}: {'PRESENT' if present else 'ABSENT'}")
