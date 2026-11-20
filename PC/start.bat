@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe app.py
if errorlevel 1 goto failed
exit /b 0
:failed
 echo Startup failed. Install Python 3.11 or 3.12 with the Python launcher and check your network.
pause
exit /b 1
