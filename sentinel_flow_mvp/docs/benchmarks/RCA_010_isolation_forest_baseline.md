# Anomaly Detection Baselines (Isolation Forest)
**Methodology:** 90-day base data fitted to Isolation Forest (contamination=0.01). Evaluation of injected anomalous patterns. Model tuned to eliminate alert fatigue.

| Test Case | Injected Pattern | True Positives (Caught) | False Positives (Erroneous Flags) |
|---|---|---|---|
| 1. The False Positive Test | Pure Normal Data (90 days) | N/A | 0 |
| 2. The Stockout Crash | 80% Drop in 48 hours | 2/2 | 0 |
| 3. The Data Glitch | 5000% Spike (1 day) | 1/1 | 0 |
