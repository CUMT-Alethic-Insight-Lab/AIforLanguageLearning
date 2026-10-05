"""
Quick ONNX Runtime GPU providers probe (Linux/Windows).
- Prints available providers
- Optionally tries to create sessions with CUDA/TRT/TensorRT-RTX EPs
- Runs a tiny MatMul on GPU with IO binding if CUDA is present

Usage (Python 3.10+):
  python env_check/ort_gpu_probe.py

Environment knobs (optional):
  ORT_TRY_TRT=1          # Try TensorrtExecutionProvider
  ORT_TRY_TRT_RTX=1      # Try TensorRTRTXExecutionProvider
  ORT_TRY_CUDA=1         # Try CUDAExecutionProvider
"""
from __future__ import annotations
import os
import sys
import numpy as np

try:
    import onnxruntime as ort
except Exception as e:
    print("[probe] onnxruntime import failed:", e)
    sys.exit(1)


def fmt(title: str):
    print("\n== {} ==".format(title))


def print_providers():
    fmt("onnxruntime providers")
    print("available:", ort.get_available_providers())
    print("built-in:", ort.get_all_providers())


def try_session(providers: list[str]):
    fmt(f"create session with providers={providers}")
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    # Build a trivial onnx model in memory via ORT's internal helper (use numpy as input to run())
    # Use ORT's built-in test model path if available is complex; instead, run a dummy compute via IO binding
    # Here we simply create an empty session to check provider init; for real run, use io-binding on a tiny matmul if CUDA
    try:
        # Create minimal session that doesn't load a model, but ORT requires a model. So we fallback to provider init via InferenceSession on a fake bytes?
        # Simpler path: if CUDA exists, just test io binding by creating an OrtValue manually is not supported without session.
        # Therefore, we'll skip actual run here and just report provider init success/failure.
        sess = ort.InferenceSession(
            os.path.join(os.path.dirname(__file__), "..", "..", "third_party", "CosyVoice", "cosyvoice", "cli", "__init__.py"),
            sess_options=so,
            providers=providers,
        )
        print("[probe] Unexpected: session created with non-onnx path (should fail).")
    except Exception as e:
        # The goal is to trigger provider loading errors distinctly
        print("[probe] provider init attempt result:", str(e)[:300])


def tiny_cuda_iobind_run():
    # Build and run a tiny ONNX matmul on CUDA using IO binding
    fmt("tiny CUDA IO-binding run")
    import tempfile
    import onnx
    from onnx import helper, TensorProto

    try:
        # Graph: Y = MatMul(X, W)
        X = helper.make_tensor_value_info("X", TensorProto.FLOAT, [1, 4])
        W = helper.make_tensor_value_info("W", TensorProto.FLOAT, [4, 1])
        Y = helper.make_tensor_value_info("Y", TensorProto.FLOAT, [1, 1])
        node = helper.make_node("MatMul", ["X", "W"], ["Y"])
        graph = helper.make_graph([node], "tiny-mm", [X, W], [Y])
        # Force older IR/opset to match older ORT installations on Windows
        opset = helper.make_operatorsetid("", 11)
        model = helper.make_model(graph, producer_name="ort-probe", opset_imports=[opset])
        model.ir_version = 7  # Compatible IR version for older ORT builds
        onnx.checker.check_model(model)
        with tempfile.NamedTemporaryFile(suffix=".onnx", delete=False) as f:
            onnx.save(model, f.name)
            path = f.name
        providers = [("CUDAExecutionProvider", {"use_tf32": 1})]
        so = ort.SessionOptions()
        sess = ort.InferenceSession(path, sess_options=so, providers=providers)
        io = sess.io_binding()
        # Prepare inputs on CUDA via OrtValue helpers
        x = np.array([[1, 2, 3, 4]], dtype=np.float32)
        w = np.array([[1], [0], [0], [0]], dtype=np.float32)
        # Use OrtValue helpers
        xv = ort.OrtValue.ortvalue_from_numpy(x, "cuda", 0)
        wv = ort.OrtValue.ortvalue_from_numpy(w, "cuda", 0)
        yv = ort.OrtValue.ortvalue_from_shape_and_type([1, 1], np.float32, "cuda", 0)
        io.bind_ortvalue_input("X", xv)
        io.bind_ortvalue_input("W", wv)
        io.bind_ortvalue_output("Y", yv)
        sess.run_with_iobinding(io)
        y = yv.numpy()
        print("[probe] matmul Y:", y)
    except Exception as e:
        print("[probe] tiny CUDA run failed:", e)


def main():
    print_providers()
    if os.getenv("ORT_TRY_TRT", "0") == "1":
        try_session(["TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"])
    if os.getenv("ORT_TRY_TRT_RTX", "0") == "1":
        try_session(["TensorRTRTXExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"])
    if os.getenv("ORT_TRY_CUDA", "1") == "1":
        try_session(["CUDAExecutionProvider", "CPUExecutionProvider"])
        tiny_cuda_iobind_run()


if __name__ == "__main__":
    main()
