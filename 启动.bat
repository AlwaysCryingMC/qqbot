@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo ========================================================
echo   QQ Group Manager Bot - Launcher (Keep-Alive Mode)
echo ========================================================

REM ---- locate python ----
set "PY="
where py >nul 2>&1 && set "PY=py"
if "%PY%"=="" where python >nul 2>&1 && set "PY=python"
if "%PY%"=="" if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if "%PY%"=="" if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"

if "%PY%"=="" (
  echo [ERROR] Python not found.
  echo Please install Python 3.12+ first:  winget install Python.Python.3.12
  pause
  exit /b 1
)

echo Using Python: %PY%
echo.
echo Installing / updating dependencies...
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] pip install failed. Check your network / pip.
  pause
  exit /b 1
)
echo.
echo Starting bot (auto-restart on crash, type 'r'+Enter to reload, Ctrl+C to stop)
echo ========================================================

set restart_count=0
set last_restart=0

:run
set /a restart_count+=1
echo [%date% %time%] Bot start #%restart_count%
"%PY%" bot.py
set exit_code=%errorlevel%

if "%exit_code%"=="0" (
  echo.
  echo [%date% %time%] Bot stopped normally (exit 0).
  pause
  exit /b 0
)

if "%exit_code%"=="2" (
  echo.
  echo [%date% %time%] Reload requested - restarting immediately...
  goto run
)

REM ---- crash / unexpected exit: restart after delay ----
echo.
echo [%date% %time%] Bot exited with code %exit_code% - restarting in 5s...
timeout /t 5 >nul
goto run
