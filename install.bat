@echo off
REM AlgoLang installer for Windows
REM Usage:  double-click install.bat      (offline/mock mode only)
REM         install.bat --live            (also installs the anthropic SDK)
setlocal
cd /d "%~dp0"
chcp 65001 >nul
echo == AlgoLang installer ==

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo [X] Python 3.9 or newer is required.
  echo     Install it from https://www.python.org/downloads/
  echo     and tick "Add python.exe to PATH" during setup. Then run this again.
  pause
  exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)"
if errorlevel 1 (
  echo [X] Your Python is older than 3.9. Please install a newer one.
  pause
  exit /b 1
)
%PY% --version

echo -^> creating virtual environment in .venv
%PY% -m venv .venv
if errorlevel 1 ( echo [X] could not create .venv & pause & exit /b 1 )
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip

if /I "%~1"=="--live" (
  echo -^> installing lark + anthropic
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements-live.txt
) else (
  echo -^> installing lark
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
)
if errorlevel 1 ( echo [X] package install failed - check your internet connection & pause & exit /b 1 )

echo.
call "%~dp0algo.bat" doctor
echo.
echo To use the 'algo' command from any folder, add this folder to your PATH:
echo     %~dp0
echo   (Start - "Edit environment variables for your account" - Path - New)
echo.
echo Try it now, in this folder:
echo     algo run examples\research_brief.algo --arg "topic=Blockchain data integrity"
echo.
pause
