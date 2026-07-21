@echo off
setlocal
call "D:\VisualStudio\2022Community\VC\Auxiliary\Build\vcvars64.bat"
set "CUDA_PATH=D:\softwares\cuda"
set "PATH=%CUDA_PATH%\bin;%CUDA_PATH%\libnvvp;%PATH%"
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%") do set "ENV_CHECK_DIR=%%~fI"
set "LOG_FILE=%ENV_CHECK_DIR%\test_nvcc.log"
set "TEST_CU=%ENV_CHECK_DIR%\test.cu"
set "TEST_OBJ=%ENV_CHECK_DIR%\test.obj"
set "TEST_EXE=%ENV_CHECK_DIR%\test.exe"
set "TEST_SM89_OBJ=%ENV_CHECK_DIR%\test_sm89.obj"
set "TEST_SM89_EXE=%ENV_CHECK_DIR%\test_sm89.exe"
REM Force local temp to avoid path/ACL issues
set "_LOCAL_TMP=%ENV_CHECK_DIR%\tmp"
if not exist "%_LOCAL_TMP%" mkdir "%_LOCAL_TMP%"
set "TMP=%_LOCAL_TMP%"
set "TEMP=%_LOCAL_TMP%"
echo ===== NVCC TOOLCHAIN SANITY CHECK ===== > "%LOG_FILE%"
echo DATE: %DATE% %TIME% >> "%LOG_FILE%"
echo CUDA_PATH=%CUDA_PATH% >> "%LOG_FILE%"
echo VCToolsInstallDir=%VCToolsInstallDir% >> "%LOG_FILE%"
echo VisualStudioVersion=%VisualStudioVersion% >> "%LOG_FILE%"
echo WindowsSdkDir=%WindowsSdkDir% >> "%LOG_FILE%"
echo WindowsSDKVersion=%WindowsSDKVersion% >> "%LOG_FILE%"
echo --------------------------------------- >> "%LOG_FILE%"

echo where nvcc >> "%LOG_FILE%"
where nvcc >> "%LOG_FILE%" 2>&1
echo nvcc --version >> "%LOG_FILE%"
"%CUDA_PATH%\bin\nvcc.exe" --version >> "%LOG_FILE%" 2>&1

echo where cl >> "%LOG_FILE%"
where cl >> "%LOG_FILE%" 2>&1
echo cl /Bv >> "%LOG_FILE%"
cl /Bv >> "%LOG_FILE%" 2>&1

set "CCBIN_EXE=%VCToolsInstallDir%bin\Hostx64\x64\cl.exe"
echo Using -ccbin "%CCBIN_EXE%" >> "%LOG_FILE%"

echo --- NVCC COMPILE (obj, sm_120) --- >> "%LOG_FILE%"
echo (dryrun) "%CUDA_PATH%\bin\nvcc.exe" --dryrun -v -ccbin="%CCBIN_EXE%" -arch=sm_120 -c "%TEST_CU%" -o "%TEST_OBJ%" >> "%LOG_FILE%"
"%CUDA_PATH%\bin\nvcc.exe" --dryrun -v -ccbin="%CCBIN_EXE%" -arch=sm_120 -c "%TEST_CU%" -o "%TEST_OBJ%" >> "%LOG_FILE%" 2>&1
echo "%CUDA_PATH%\bin\nvcc.exe" -v -ccbin="%CCBIN_EXE%" -arch=sm_120 -Xcompiler="/Zm2000 /EHsc /MD" -c "%TEST_CU%" -o "%TEST_OBJ%" >> "%LOG_FILE%"
"%CUDA_PATH%\bin\nvcc.exe" -v -ccbin="%CCBIN_EXE%" -arch=sm_120 -Xcompiler="/Zm2000 /EHsc /MD" -c "%TEST_CU%" -o "%TEST_OBJ%" >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :fail
echo --- NVCC LINK (exe, sm_120) --- >> "%LOG_FILE%"
echo "%CUDA_PATH%\bin\nvcc.exe" -v -ccbin="%CCBIN_EXE%" -arch=sm_120 "%TEST_CU%" -o "%TEST_EXE%" >> "%LOG_FILE%"
"%CUDA_PATH%\bin\nvcc.exe" -v -ccbin="%CCBIN_EXE%" -arch=sm_120 "%TEST_CU%" -o "%TEST_EXE%" >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :fail
echo --- NVCC COMPILE (obj, sm_89) --- >> "%LOG_FILE%"
echo "%CUDA_PATH%\bin\nvcc.exe" -v -ccbin="%CCBIN_EXE%" -arch=sm_89 -c "%TEST_CU%" -o "%TEST_SM89_OBJ%" >> "%LOG_FILE%"
"%CUDA_PATH%\bin\nvcc.exe" -v -ccbin="%CCBIN_EXE%" -arch=sm_89 -c "%TEST_CU%" -o "%TEST_SM89_OBJ%" >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :fail

echo --- NVCC LINK (exe, sm_89) --- >> "%LOG_FILE%"
echo "%CUDA_PATH%\bin\nvcc.exe" -v -ccbin="%CCBIN_EXE%" -arch=sm_89 "%TEST_CU%" -o "%TEST_SM89_EXE%" >> "%LOG_FILE%"
"%CUDA_PATH%\bin\nvcc.exe" -v -ccbin="%CCBIN_EXE%" -arch=sm_89 "%TEST_CU%" -o "%TEST_SM89_EXE%" >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto :fail

echo NVCC_OK >> "%LOG_FILE%"
exit /b 0

:fail
echo NVCC_FAIL >> "%LOG_FILE%"
exit /b 1
endlocal
