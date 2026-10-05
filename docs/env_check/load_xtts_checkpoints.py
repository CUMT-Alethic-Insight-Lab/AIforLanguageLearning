#!/usr/bin/env python3
import os, sys, time
import torch
import types

MODEL_DIR = os.path.expanduser(r'C:\Users\74090\AppData\Local\tts\tts_models--multilingual--multi-dataset--xtts_v2')
print('Model dir:', MODEL_DIR)

# shim for unpickler
shim_name = 'TTS.tts.configs.xtts_config'
if shim_name not in sys.modules:
    shim = types.ModuleType(shim_name)
    class XttsConfig: pass
    shim.XttsConfig = XttsConfig
    sys.modules[shim_name] = shim
    print('Inserted shim:', shim_name)

# wrapper
_orig = torch.load
def _wrap(*args, **kwargs):
    kwargs.setdefault('weights_only', False)
    path = args[0] if args else kwargs.get('f', '<unknown>')
    print('\n[torch.load] loading', path)
    t0 = time.time()
    try:
        res = _orig(*args, **kwargs)
        print('[torch.load] ok duration=', time.time()-t0)
    except Exception as e:
        print('[torch.load] EXCEPTION', e)
        raise
    return res

torch.load = _wrap

for root, dirs, files in os.walk(MODEL_DIR):
    for f in files:
        if f.endswith('.pth') or f.endswith('.pt'):
            p = os.path.join(root, f)
            try:
                _ = torch.load(p, map_location='cpu')
            except Exception as e:
                print('Failed loading', p, '->', e)

print('done')
