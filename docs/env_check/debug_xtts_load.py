#!/usr/bin/env python3
import os
import time
import sys

# 禁用 fake tensor 模式
os.environ.setdefault('PYTORCH_FAKE_TENSOR_ENABLED', '0')

print('PID', os.getpid())
print('PYTHON:', sys.executable)
print('Start time:', time.strftime('%Y-%m-%d %H:%M:%S'))

import torch

# 包装 torch.load
_original_torch_load = torch.load

def _wrapped_torch_load(*args, **kwargs):
    # Force legacy/pickle loading when needed (weights_only False)
    kwargs.setdefault('weights_only', False)
    try:
        path = args[0] if args else kwargs.get('f', '<unknown>')
    except Exception:
        path = '<unknown>'
    try:
        path_str = path if isinstance(path, str) else getattr(path, '__str__', lambda: '<obj>')()
    except Exception:
        path_str = '<unknown>'
    print('[torch.load] start:', time.strftime('%H:%M:%S'), 'path=', path_str, 'weights_only=', kwargs.get('weights_only'))
    t0 = time.time()
    res = _original_torch_load(*args, **kwargs)
    t1 = time.time()
    print('[torch.load] end:', time.strftime('%H:%M:%S'), f'duration={t1-t0:.2f}s')
    return res

torch.load = _wrapped_torch_load
print('Patched torch.load wrapper (defaults weights_only=False)')

# 为避免在导入 heavy 包时卡住，跳过直接 patch Xtts.load_checkpoint 的尝试。
print('Skipping direct Xtts.load_checkpoint patch to avoid heavy imports')

# 尝试导入 TTS 并实例化模型（只做加载，不合成）
try:
    # 为了在不导入整个 heavy TTS 包的情况下，使反序列化找到所需类型，
    # 我们向 sys.modules 注入一个临时 shim 模块：TTS.tts.configs.xtts_config
    import types
    shim_name = 'TTS.tts.configs.xtts_config'
    if shim_name not in sys.modules:
        shim = types.ModuleType(shim_name)
        class XttsConfig:
            pass
        shim.XttsConfig = XttsConfig
        sys.modules[shim_name] = shim

    from TTS.api import TTS
    print('Imported TTS.api')
    model_name = 'tts_models/multilingual/multi-dataset/xtts_v2'
    print('Instantiating TTS with model:', model_name)
    t0 = time.time()
    tts = TTS(model_name)
    t1 = time.time()
    print('TTS instantiation done, duration=', t1-t0)
    print('Available devices:', torch.cuda.is_available())
except Exception as e:
    print('Error during TTS init:', e)

print('End time:', time.strftime('%Y-%m-%d %H:%M:%S'))
