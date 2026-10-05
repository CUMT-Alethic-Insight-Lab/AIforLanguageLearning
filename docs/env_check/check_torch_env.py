import json
import platform

out = {
    "python": platform.python_version(),
    "platform": platform.platform(),
}

try:
    import torch
    out["torch_import"] = True
    out["torch_version"] = getattr(torch, "__version__", None)
    out["torch_compiled_cuda"] = getattr(torch.version, "cuda", None)
    out["torch_debug_build"] = getattr(torch.version, "debug", None)
    out["torch_git_version"] = getattr(torch.version, "git_version", None)

    # CUDA
    cuda = {
        "available": bool(torch.cuda.is_available()),
        "device_count": int(torch.cuda.device_count()) if torch.cuda.is_available() else 0,
        "devices": [],
    }
    if cuda["device_count"] > 0:
        for i in range(cuda["device_count"]):
            props = torch.cuda.get_device_properties(i)
            cuda["devices"].append({
                "index": i,
                "name": props.name,
                "total_memory_GB": round(props.total_memory / (1024**3), 2),
                "capability": f"{props.major}.{props.minor}",
            })
        cuda["current_device"] = int(torch.cuda.current_device())
        cuda["current_name"] = torch.cuda.get_device_name(cuda["current_device"])
    cuda["cudnn_available"] = bool(torch.backends.cudnn.is_available())
    try:
        cuda["cudnn_version"] = int(torch.backends.cudnn.version()) if torch.backends.cudnn.is_available() else None
    except Exception:
        cuda["cudnn_version"] = None
    out["cuda"] = cuda

    # MPS (Apple)
    mps = getattr(torch.backends, "mps", None)
    out["mps_available"] = bool(mps.is_available()) if mps else False

    # Intel XPU (oneAPI)
    xpu = getattr(torch, "xpu", None)
    out["xpu_available"] = bool(xpu.is_available()) if xpu else False

    # XLA (TPU)
    try:
        import torch_xla.core.xla_model as xm  # type: ignore
        xla_devices = xm.get_xla_supported_devices() or []
        out["xla_available"] = len(xla_devices) > 0
        out["xla_devices"] = xla_devices
    except Exception:
        out["xla_available"] = False
        out["xla_devices"] = []

    # DirectML (Windows)
    try:
        import importlib
        dml_spec = importlib.util.find_spec("torch_directml")
        if dml_spec is None:
            out["directml_installed"] = False
            out["directml_device"] = None
        else:
            import torch_directml as dml  # type: ignore
            out["directml_installed"] = True
            try:
                out["directml_device"] = str(dml.device())
                # optional: device_count may exist in newer versions
                dc = getattr(dml, "device_count", None)
                out["directml_device_count"] = int(dc()) if callable(dc) else None
            except Exception:
                out["directml_device"] = None
                out["directml_device_count"] = None
    except Exception:
        out["directml_installed"] = False
        out["directml_device"] = None
        out["directml_device_count"] = None

except Exception as e:
    out["torch_import"] = False
    out["error"] = str(e)

print(json.dumps(out, ensure_ascii=False, indent=2))
