import torch, os
print('torch.__file__=', torch.__file__)
base = os.path.dirname(torch.__file__)
libdir = os.path.join(base,'lib')
print('libdir=', libdir)
print('exists libdir', os.path.isdir(libdir))
if os.path.isdir(libdir):
    print('lib entries sample:', os.listdir(libdir)[:50])
else:
    print('torch folder entries sample:', os.listdir(base)[:50])
