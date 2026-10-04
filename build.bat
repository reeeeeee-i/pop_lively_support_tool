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

echo Building pop_lively_support_tool (.exe) with cx_Freeze...
"%VENV%" setup.py build_exe

if %ERRORLEVEL% equ 0 (
    if not exist "dist\pop_lively_support_tool\log" mkdir "dist\pop_lively_support_tool\log"
    echo.
    echo ==============================================
    echo Build completed successfully!
    echo Output directory: dist\pop_lively_support_tool\
    echo Executable: dist\pop_lively_support_tool\pop_lively_support_tool.exe
    echo ==============================================
) else (
    echo.
    echo Build failed with error code %ERRORLEVEL%.
)

endlocal
pause
