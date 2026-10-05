import importlib
mods = ['torch', 'torchaudio', 'soundfile']
for m in mods:
    try:
        mod = importlib.import_module(m)
        ver = getattr(mod, '__version__', 'unknown')
        print(f'{m}: OK {ver}')
    except Exception as e:
        print(f'{m}: MISSING ({e})')
