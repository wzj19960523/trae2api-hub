@echo off
REM trae2api-hub gateway STOP helper (ASCII only, CRLF)
REM Note: Task Scheduler "End" only ends the task instance, it does NOT kill
REM the pythonw child it spawned. Kill the listener by port explicitly.
REM The watchdog restarts the gateway within 5 minutes; disable task
REM trae2api-hub-gateway first if you need a long-term stop.
setlocal enabledelayedexpansion
set FOUND=0
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /C:":8791 " ^| findstr "LISTENING"') do (
  echo killing gateway PID %%p
  taskkill /PID %%p /F >nul 2>&1
  set FOUND=1
)
if "!FOUND!"=="0" echo no listener on 8791
exit /b 0
