@echo off
REM `algo` command - Windows launcher for the AlgoLang toolchain
setlocal
set "ALGO_HOME=%~dp0"
if "%ALGO_HOME:~-1%"=="\" set "ALGO_HOME=%ALGO_HOME:~0,-1%"
set "PYTHONIOENCODING=utf-8"
if exist "%ALGO_HOME%\.venv\Scripts\python.exe" (
  "%ALGO_HOME%\.venv\Scripts\python.exe" "%ALGO_HOME%\algoc.py" %*
) else (
  python "%ALGO_HOME%\algoc.py" %*
)
exit /b %errorlevel%
