import importlib, sys
mods = sys.argv[1:]
for m in mods:
    try:
        importlib.import_module(m)
        print(m, 'OK')
    except Exception as e:
        print(m, 'FAIL', e)