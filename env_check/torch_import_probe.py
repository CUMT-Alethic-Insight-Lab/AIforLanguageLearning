import os
from pathlib import Path

lib_dir = Path(__file__).resolve().parent.parent / "third_party" / "pytorch" / "torch" / "lib"
try:
    if hasattr(os, 'add_dll_directory'):
        os.add_dll_directory(str(lib_dir))
except Exception as e:
    print('add_dll_directory failed:', e)

try:
    import torch
    print('torch.version:', torch.__version__)
    print('cuda.is_available:', torch.cuda.is_available())
    if torch.cuda.is_available():
        print('device:', torch.cuda.get_device_name(0), 'cap', torch.cuda.get_device_capability(0))
        x = torch.randn(512,512, device='cuda')
        y = torch.randn(512,512, device='cuda')
        z = x @ y
        torch.cuda.synchronize()
        print('matmul OK, mean:', float(z.mean().cpu()))
except Exception as e:
    import traceback
    traceback.print_exc()