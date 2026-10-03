@echo off
setlocal
cd /d "%~dp0"

set VENV=%~dp0.venv\Scripts\python.exe
if not exist "%VENV%" (
    echo .venv not found: %VENV%
    echo Run "uv sync" first.
    pause
    exit /b 1
)

echo Building popn_daken_counter (.exe) with cx_Freeze...
"%VENV%" setup.py build_exe

if %ERRORLEVEL% equ 0 (
    if not exist "dist\popn_daken_counter\log" mkdir "dist\popn_daken_counter\log"
    echo.
    echo ==============================================
    echo Build completed successfully!
    echo Output directory: dist\popn_daken_counter\
    echo Executable: dist\popn_daken_counter\popn_counter.exe
    echo ==============================================
) else (
    echo.
    echo Build failed with error code %ERRORLEVEL%.
)

endlocal
pause
