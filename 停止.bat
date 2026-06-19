@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在停止后台机器人...

REM Create stop flag so keep-alive loop doesn't restart
type nul > stop.flag

REM Kill all python bot.py processes
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*bot.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

REM Kill wscript.exe (the vbs keep-alive loop)
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*后台运行*' -or ($_.Name -eq 'wscript.exe' -and $_.CommandLine -like '*bot*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

REM Clean up flag after a moment
timeout /t 2 >nul
del stop.flag 2>nul

echo 已停止。
timeout /t 2 >nul
