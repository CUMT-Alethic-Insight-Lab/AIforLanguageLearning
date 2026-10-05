import ctypes,sys,os,traceback
paths = [r'E:\projects\torchaudio\build\src\libtorchaudio\_torchaudio.pyd', r'E:\projects\torchaudio\build\src\libtorchaudio\libtorchaudio.pyd']
for p in paths:
    print('\nTrying LoadLibrary on', p)
    try:
        ctypes.WinDLL(p)
        print('LoadLibrary succeeded for', p)
    except Exception as e:
        traceback.print_exc()
        print('FAILED:', e)
print('\nNow try adding torch lib to PATH and retry')
libp = r'C:\Users\74090\Miniconda3\envs\torchnb311\Lib\site-packages\torch\lib'
os.environ['PATH'] = libp + os.pathsep + os.environ.get('PATH','')
for p in paths:
    print('\nTrying LoadLibrary on', p)
    try:
        ctypes.WinDLL(p)
        print('LoadLibrary succeeded for', p)
    except Exception as e:
        traceback.print_exc()
        print('FAILED:', e)
