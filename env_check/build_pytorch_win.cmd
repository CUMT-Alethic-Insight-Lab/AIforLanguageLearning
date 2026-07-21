@echo off
setlocal

REM Configure VS2022 build environment
call "D:\VisualStudio\2022Community\VC\Auxiliary\Build\vcvars64.bat"

REM Prefer CUDA 12.9 (supports Blackwell sm_120) over system 12.4
set "CUDA_PATH=D:\softwares\cuda"
set "CUDACXX=%CUDA_PATH%\bin\nvcc.exe"
set "PATH=%CUDA_PATH%\bin;%CUDA_PATH%\libnvvp;%PATH%"

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"
set "PYTORCH_SRC=%REPO_ROOT%\third_party\pytorch"

REM Use a short, ASCII-only temp directory to avoid toolchain issues
set "_LOCAL_TMP=%PYTORCH_SRC%\build_tmp"
if not exist "%_LOCAL_TMP%" mkdir "%_LOCAL_TMP%"
set "TMP=%_LOCAL_TMP%"
set "TEMP=%_LOCAL_TMP%"

REM Compiler memory and single-thread build
set CL=/Zm2000
set MAX_JOBS=1

REM Limit CUDA arch to Blackwell sm_120
set TORCH_CUDA_ARCH_LIST=12.0
set CMAKE_CUDA_ARCHITECTURES=120
set CMAKE_ARGS=-DCMAKE_CUDA_ARCHITECTURES=120 -DCMAKE_CUDA_FLAGS=-Xcompiler=/Zm2000 -DCMAKE_CUDA_COMPILER="%CUDACXX%" -DCMAKE_CUDA_HOST_COMPILER="D:\VisualStudio\2022Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe" -DCMAKE_VERBOSE_MAKEFILE=ON -DCMAKE_MSVC_DEBUG_INFORMATION_FORMAT=None -DCMAKE_SHARED_LINKER_FLAGS="/DEBUG:FASTLINK /INCREMENTAL:NO"

REM Start from clean build dir
cd /d "%PYTORCH_SRC%"
if exist build rmdir /s /q build

pip install -v -e .
endlocal
