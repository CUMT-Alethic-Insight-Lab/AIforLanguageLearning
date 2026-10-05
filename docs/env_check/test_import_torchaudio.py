import os,sys,traceback
libp = r'C:\Users\74090\Miniconda3\envs\torchnb311\Lib\site-packages\torch\lib'
print('Prepend PATH with', libp)
os.environ['PATH'] = libp + os.pathsep + os.environ.get('PATH','')
try:
    import _torchaudio
    print('Imported _torchaudio from', _torchaudio.__file__)
except Exception as e:
    traceback.print_exc()
    print('FAILED_IMPORT:', e)
