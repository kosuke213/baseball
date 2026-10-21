@echo off
setlocal
cd /d "%~dp0"
set PIP_DISABLE_PIP_VERSION_CHECK=1

if exist ".venv\Scripts\python.exe" goto dependencies
where py >nul 2>&1
if errorlevel 1 goto plain_python
py -3 -c "import sys; raise SystemExit(sys.version_info < (3, 11))"
if errorlevel 1 goto need_python
py -3 -m venv .venv
if errorlevel 1 goto failed
goto dependencies

:plain_python
where python >nul 2>&1
if errorlevel 1 goto need_python
python -c "import sys; raise SystemExit(sys.version_info < (3, 11))"
if errorlevel 1 goto need_python
python -m venv .venv
if errorlevel 1 goto failed

:dependencies
echo Preparing Baseball Simulation Lab. First launch needs Internet access.
".venv\Scripts\python.exe" -m pip install --require-hashes -r requirements.txt
if errorlevel 1 goto failed
if exist "data\lab.sqlite3" goto launch
".venv\Scripts\python.exe" -m baseball_simulation_lab init
if errorlevel 1 goto failed

:launch
echo Starting the app. Keep this window open while using it.
echo Close this window or press Ctrl+C to stop the app.
".venv\Scripts\python.exe" -m streamlit run baseball_simulation_lab/app.py --server.address 127.0.0.1 --server.headless false --browser.gatherUsageStats false
if errorlevel 1 goto failed
exit /b 0

:need_python
echo Python 3.11 or newer is required.
echo Install Python from https://www.python.org/downloads/ and try again.
pause
exit /b 1

:failed
echo.
echo Startup failed. Please copy the error above when asking for help.
pause
exit /b 1
