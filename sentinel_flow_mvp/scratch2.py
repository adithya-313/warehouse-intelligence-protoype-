import numpy as np
from sklearn.ensemble import IsolationForest

base_data = np.random.normal(300, 30, 90).reshape(-1, 1)

model = IsolationForest(contamination=0.01, random_state=42)
model.fit(base_data)

glitch_val = 15000
print("Glitch predict:", model.predict([[glitch_val]]))
print("Decision function glitch:", model.decision_function([[glitch_val]]))
print("Decision function normal:", model.decision_function([[300]]))
