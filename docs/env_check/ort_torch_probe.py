import sys, os

print('python', sys.version)
try:
    import onnxruntime as ort
    print('onnxruntime', ort.__version__)
    print('providers', ort.get_available_providers())
except Exception as e:
    print('onnxruntime failed:', e)

import torch
print('torch', torch.__version__)
print('cuda.is_available', torch.cuda.is_available())
if torch.cuda.is_available():
    print('gpu', torch.cuda.get_device_name(0))
