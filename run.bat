@echo off
set VENV=F:\Develop\inf_daken_counter_obsw\.venv\Scripts\pythonw.exe
set SCRIPT=F:\Develop\popn_daken_counter\popn_counter.pyw
if not exist "%VENV%" (echo .venv not found && pause && exit /b 1)
start "" "%VENV%" "%SCRIPT%"
