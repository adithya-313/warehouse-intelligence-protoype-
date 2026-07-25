import requests, json

def fetch(url):
    print(f'Fetching: {url}')
    r = requests.get(url, timeout=10)
    if r.status_code == 200:
        data = r.json()
        print(f'  Match! Found {len(data.get("results", []))} results.')
        if data.get("results"):
            first = data["results"][0]
            openfda = first.get("openfda", {})
            print(f'  Brand name: {openfda.get("brand_name")}')
            print(f'  Generic name: {openfda.get("generic_name")}')
            print(f'  Substance name: {openfda.get("substance_name")}')
            return first
    else:
        print(f'  Failed with status: {r.status_code}')
    return None

print('--- Try 1: Brand name Verzenios ---')
url1 = 'https://api.fda.gov/drug/label.json?search=openfda.brand_name:"Verzenios"&limit=1'
res1 = fetch(url1)

print('\n--- Try 2: Substance name abemaciclib ---')
url2 = 'https://api.fda.gov/drug/label.json?search=openfda.substance_name:"abemaciclib"&limit=1'
res2 = fetch(url2)
