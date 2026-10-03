@echo off
set VENV=%~dp0.venv\Scripts\pythonw.exe
set SCRIPT=%~dp0popn_counter.pyw
if not exist "%VENV%" (echo .venv not found. Run "uv sync" first. && pause && exit /b 1)
start "" "%VENV%" "%SCRIPT%"
