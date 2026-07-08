@echo off
title Paisley Ponytail - the Webshots Resurrector
cd /d "%~dp0"
set PY=
py --version >nul 2>nul
if not errorlevel 1 set PY=py
if not defined PY (
    python --version >nul 2>nul
    if not errorlevel 1 set PY=python
)
if not defined PY goto nopython
echo Checking requirements (first run can take a minute)...
%PY% -m pip install -r requirements.txt --quiet --disable-pip-version-check
if errorlevel 1 goto pipfail
%PY% resurrector.py
goto end

:nopython
echo.
echo  Python isn't installed yet. It's free:
echo.
echo    1. Go to  https://www.python.org/downloads/
echo    2. Download and run the installer
echo    3. IMPORTANT: tick the "Add python.exe to PATH" box
echo    4. Double-click Start_Here.bat again
echo.
goto end

:pipfail
echo.
echo  Couldn't install the requirements. Check your internet connection
echo  and run Start_Here.bat again.
echo.

:end
pause
