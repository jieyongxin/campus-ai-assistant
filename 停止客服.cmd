@echo off
rem 双击本文件结束占用 8000 端口的服务进程。
chcp 65001 >nul
echo Stopping Campus AI Assistant (port 8000) ...
powershell -NoProfile -Command "$p = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue; if ($p) { $p | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force; Write-Host ('stopped PID ' + $_.OwningProcess) } } else { Write-Host 'not running' }"
echo Done.
pause
