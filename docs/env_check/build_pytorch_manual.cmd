@echo off
setlocal
call "D:\VisualStudio\2022Community\VC\Auxiliary\Build\vcvars64.bat"
set "CUDA_PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.0"
set "PATH=%CUDA_PATH%\bin;%CUDA_PATH%\libnvvp;%PATH%"
set "TORCH_CUDA_ARCH_LIST=12.0"
set "MAX_JOBS=2"
set "USE_CUDA=1"
set "USE_CUDNN=1"
set "USE_NINJA=1"
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%\pytorch-main"
conda run -n torch311 python -m pip install -v -e .
endlocal
