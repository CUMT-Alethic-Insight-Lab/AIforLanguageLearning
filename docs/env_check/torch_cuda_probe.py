import os, sys, time

print("Python:", sys.version)
try:
    import torch
except Exception as e:
    print("Import torch FAILED:", e)
    sys.exit(1)

print("torch:", torch.__version__)
print("CUDA compiled with:", getattr(torch.version, "cuda", None))
print("cuDNN:", getattr(torch.backends.cudnn, "version", lambda: None)())
print("CUDA available:", torch.cuda.is_available())

if torch.cuda.is_available():
    dev = torch.device("cuda")
    idx = torch.cuda.current_device()
    print("Device index:", idx)
    print("Device name:", torch.cuda.get_device_name(idx))
    cap = torch.cuda.get_device_capability(idx)
    print("Compute capability:", cap)
    # Small CUDA matmul sanity check
    torch.cuda.synchronize()
    a = torch.randn(2048, 2048, device=dev, dtype=torch.float16)
    b = torch.randn(2048, 2048, device=dev, dtype=torch.float16)
    torch.cuda.synchronize()
    t0 = time.time()
    c = (a @ b).float()  # force HMMA then convert
    torch.cuda.synchronize()
    dt = time.time() - t0
    tflops = (2 * 2048**3) / dt / 1e12
    print(f"Matmul OK: {c.shape}, time={dt:.3f}s, approx TFLOPS={tflops:.2f}")
else:
    print("CUDA not available; skipping matmul.")
