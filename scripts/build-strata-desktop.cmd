@echo off
setlocal
set "ROOT=C:\Users\danfl\dev\LocalAI"
set "SRC=%ROOT%\apps\Strata"
set "ROCM_VENV=%ROOT%\toolchains\rocm-strata"
call "%ROOT%\toolchains\vs2022\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
set "PATH=%SRC%\.venv\Scripts;%ROCM_VENV%\Scripts;%PATH%"
for /f "delims=" %%R in ('"%ROCM_VENV%\Scripts\rocm-sdk.exe" path --root') do set "ROCM=%%R"
set "ROCM_F=%ROCM:\=/%"
set "HIP_PLATFORM=amd"
set "HIP_PATH=%ROCM%"
set "ROCM_PATH=%ROCM%"
set "PATH=%ROCM%\bin;%ROCM%\lib\llvm\bin;%PATH%"
cmake -G Ninja -S "%SRC%" -B "%SRC%\build-desktop-hip" -DCMAKE_BUILD_TYPE=Release -DSTRATA_ENABLE_HIP=ON -DSTRATA_ENABLE_CUDA=OFF -DSTRATA_BUILD_TESTS=OFF -DSTRATA_PREFILL_MMQ=ON -DSTRATA_NATIVE_EXPERTS=ON -DSTRATA_PORTABLE=ON -DCMAKE_HIP_ARCHITECTURES=gfx1100 "-DSTRATA_GGML_DIR=%ROOT%/toolchains/llama.cpp-3cf03257f219afbe7334045ff7c6a06ac68c627d" "-DCMAKE_C_COMPILER=%ROCM_F%/lib/llvm/bin/clang.exe" "-DCMAKE_CXX_COMPILER=%ROCM_F%/lib/llvm/bin/clang++.exe" "-DCMAKE_HIP_COMPILER=%ROCM_F%/lib/llvm/bin/clang++.exe" "-DCMAKE_HIP_COMPILER_ROCM_ROOT=%ROCM_F%" "-DCMAKE_PREFIX_PATH=%ROCM_F%" "-DCMAKE_HIP_FLAGS=--rocm-path=%ROCM_F% --rocm-device-lib-path=%ROCM_F%/lib/llvm/amdgcn/bitcode"
if errorlevel 1 exit /b 1
cmake --build "%SRC%\build-desktop-hip" --target strata strata-device -j 4
exit /b %errorlevel%
