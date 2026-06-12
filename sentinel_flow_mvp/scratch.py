from app.ml.fraud_model import FraudDetectionModel
model = FraudDetectionModel()
print("Normal 300:", model.predict("inventory", 300))
print("Crash 60:", model.predict("inventory", 60))
print("Glitch 15000:", model.predict("inventory", 15000))
