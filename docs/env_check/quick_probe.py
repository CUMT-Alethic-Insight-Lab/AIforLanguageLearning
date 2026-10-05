import sys
print(sys.executable)
out = []
try:
    import torch
    out.append(f"torch={torch.__version__}, cuda={getattr(torch.version,'cuda',None)}, available={torch.cuda.is_available()}")
    if torch.cuda.is_available():
        try:
            p = torch.cuda.get_device_properties(0)
            out.append(f"gpu={p.name}, cc={p.major}.{p.minor}, MPs={p.multi_processor_count}")
        except Exception as e:
            out.append(f"torch_cuda_props_error={e}")
    else:
        out.append("torch_cuda_not_available")
except Exception as e:
    out.append(f"torch_import_error={e}")

try:
    import onnxruntime as ort
    prov = ort.get_available_providers()
    out.append("ort_providers="+",".join(prov))
except Exception as e:
    out.append(f"ort_import_error={e}")

print(" | ".join(out))
try:
    import tensorrt as trt  # type: ignore
    print(f"tensorrt={trt.__version__}")
except Exception as e:
    print(f"tensorrt_import_error={e}")
