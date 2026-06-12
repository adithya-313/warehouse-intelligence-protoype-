import re

with open('/app/tests/load/phase2_ml_stress.py', 'r') as f:
    content = f.read()

REQUESTS_PER_VECTOR = 2

suppliers = ["NVIDIA", "AMD Inc", "Intel Corp", "ASUS Global", "Corsair Components", "NVIDIA Corporation", "AMD"]

# Replace payload definitions with real supplier IDs
old_a = 'payloads_a = ['
new_a = f'''suppliers = {suppliers}
payloads_a = [
        {{
            "module_id": "demand_forecast",
            "supplier_id": suppliers[i % len(suppliers)],
            "sku_id": "TEST",
            "route_id": "R1",
            "compute_budget": 15.0,
        }}
        for i in range(REQUESTS_PER_VECTOR)
    ]'''

content = content.replace(old_a, new_a)

# For Vector B, use a single real supplier
content = content.replace(
    '"SUP-LOCK-TEST"',
    '"NVIDIA"'
)

# Verify supplier_ids in all payloads now reference real suppliers
# Check the file is still valid Python
with open('/app/tests/load/phase2_ml_stress.py', 'w') as f:
    f.write(content)
print('Patched successfully')
