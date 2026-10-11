@echo off
rem 双击本文件即可启动校园 AI 客服（内部调用 run.ps1）。
rem 提示文字用 ASCII，避免 cmd 中文编码在不同机器上乱码。
chcp 65001 >nul
cd /d "%~dp0"

echo ==================================================
echo   Campus AI Assistant - starting
echo ==================================================
echo.
echo   This computer  :  http://127.0.0.1:8000
echo   Other devices  :  http://YOUR-IP:8000   (same Wi-Fi)
echo.
echo   Your IPv4 address:
powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Format-Table IPAddress,InterfaceAlias -AutoSize"
echo   Keep this window open while others are using it.
echo   Press Ctrl+C here to stop.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"

echo.
echo Service stopped.
pause
