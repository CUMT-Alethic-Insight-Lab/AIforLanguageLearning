import torch
print('torch', torch.__version__)
print('torch.version.cuda', getattr(torch.version, 'cuda', None))
print('cuda_available', torch.cuda.is_available())
try:
    n = torch.cuda.device_count()
    print('device_count', n)
    if n>0:
        props = torch.cuda.get_device_properties(0)
        print('device0 name:', props.name)
        print('device0 major,minor:', props.major, props.minor)
except Exception as e:
    print('error querying cuda props:', e)
