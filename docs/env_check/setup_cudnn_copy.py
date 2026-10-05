import os, sys, shutil
import site

# Copy cuDNN 9 DLLs from pip-installed nvidia-cudnn-cu12 to current env's Library/bin

def find_cudnn_bin():
    for sp in site.getsitepackages():
        cand = os.path.join(sp, 'nvidia', 'cudnn', 'bin')
        if os.path.isdir(cand):
            return cand
    # Try user-site
    sp = site.getusersitepackages()
    cand = os.path.join(sp, 'nvidia', 'cudnn', 'bin')
    if os.path.isdir(cand):
        return cand
    return None

def main():
    src = find_cudnn_bin()
    if not src:
        print('cuDNN bin not found under site-packages/nvidia/cudnn/bin')
        sys.exit(1)
    # Guess conda env root from sys.executable
    # sys.executable -> .../envs/<name>/python.exe
    # We want .../envs/<name>/Library/bin
    py = sys.executable
    env_dir = os.path.dirname(py)  # .../envs/<name>
    # Fallback: if this looks like a base install without envs/<name>, keep previous behavior
    if os.path.basename(os.path.dirname(env_dir)).lower() != 'envs':
        env_dir = os.path.dirname(os.path.dirname(py))
    dst = os.path.join(env_dir, 'Library', 'bin')
    os.makedirs(dst, exist_ok=True)
    copied = []
    for fn in os.listdir(src):
        if fn.lower().endswith('.dll') and 'cudnn' in fn.lower():
            s = os.path.join(src, fn)
            d = os.path.join(dst, fn)
            shutil.copy2(s, d)
            copied.append(fn)
    print('Copied DLLs:', copied)
    print('Dst:', dst)

if __name__ == '__main__':
    main()
