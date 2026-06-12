import time
import os
import psutil
import torch
import numpy as np
from chronos import ChronosPipeline

def run_ml_audit():
    print("Starting ML Engine Profiling...")
    
    process = psutil.Process(os.getpid())
    base_mem = process.memory_info().rss / (1024 * 1024)
    
    # 1. Cold-Start Latency
    cold_start_begin = time.perf_counter()
    pipeline = ChronosPipeline.from_pretrained(
        "amazon/chronos-t5-mini",
        device_map="cpu",  # Using CPU as standard baseline
        torch_dtype=torch.bfloat16,
    )
    cold_start_latency = time.perf_counter() - cold_start_begin
    
    # Context tensor mimicking 90 days of inventory data
    # Create a simple synthetic sine wave + noise to avoid all zeros
    t = np.linspace(0, 4*np.pi, 90)
    synthetic_data = 50 + 20 * np.sin(t) + np.random.normal(0, 5, 90)
    synthetic_data = np.clip(synthetic_data, 0, None)
    context_tensor = torch.tensor(synthetic_data, dtype=torch.float32).view(1, 90)
    
    # 2 & 3. Peak Tensor Memory Spike & Warm-Start Latency
    warm_start_times = []
    peak_mem_spike_mb = 0.0
    
    # Warm up run
    _ = pipeline.predict(context_tensor, prediction_length=5)
    
    for i in range(5):
        mem_before = process.memory_info().rss / (1024 * 1024)
        
        start_time = time.perf_counter()
        forecast = pipeline.predict(context_tensor, prediction_length=5)
        exec_time = time.perf_counter() - start_time
        
        mem_after = process.memory_info().rss / (1024 * 1024)
        spike = max(0, mem_after - mem_before)
        if spike > peak_mem_spike_mb:
            peak_mem_spike_mb = spike
            
        warm_start_times.append(exec_time)
        
    avg_warm_start_latency = sum(warm_start_times) / len(warm_start_times)
    
    # 4. Array Continuity Check
    array_validation_pass = True
    
    if isinstance(forecast[0], torch.Tensor):
        try:
            forecast_trajectory = forecast[0].median(dim=0).values.tolist()
        except Exception:
            forecast_trajectory = forecast[0].mean(dim=0).tolist()
    else:
        try:
            forecast_trajectory = np.median(forecast[0], axis=0).tolist()
        except Exception:
            forecast_trajectory = np.mean(forecast[0], axis=0).tolist()
            
    # Check length
    if len(forecast_trajectory) != 5:
        array_validation_pass = False
        print(f"Array Continuity Check Failed: Expected length 5, got {len(forecast_trajectory)}")
        
    # Check for NaNs or Nulls
    for val in forecast_trajectory:
        if val is None or np.isnan(val) or np.isinf(val):
            array_validation_pass = False
            print(f"Array Continuity Check Failed: Contains invalid value -> {val}")
            
    # Output the required Markdown table
    print("\n")
    print("| Metric | Value |")
    print("|---|---|")
    print(f"| Cold-Start Latency (seconds) | {cold_start_latency:.2f} |")
    print(f"| Avg Warm-Start Latency (seconds) | {avg_warm_start_latency:.2f} |")
    print(f"| Peak Tensor RAM Usage (MB) | {peak_mem_spike_mb:.2f} |")
    print(f"| Array Math Validation | {'Pass' if array_validation_pass else 'Fail'} |")
    print("\nML ENGINE PROFILING COMPLETE. BASELINE METRICS CAPTURED.")

if __name__ == "__main__":
    run_ml_audit()
