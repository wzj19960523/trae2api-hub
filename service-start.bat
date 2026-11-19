@echo off
REM trae2api-hub gateway watchdog (ASCII only, called by Task Scheduler)
REM - exits immediately if port 8791 is already served (no duplicate instance)
REM - otherwise launches pythonw hidden with log redirection, then returns
cd /d D:\phpstudy_pro\WWW\trae2api-hub
netstat -ano | findstr /C:":8791 " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 exit /b 0
start "" /b "C:\Users\1\AppData\Local\Programs\Python\Python312\pythonw.exe" trae_proxy.py >> gateway.log 2>&1
exit /b 0
