@echo off
REM trae2api-hub gateway service launcher (ASCII only, called by Task Scheduler)
cd /d D:\phpstudy_pro\WWW\trae2api-hub
"C:\Users\1\AppData\Local\Programs\Python\Python312\pythonw.exe" trae_proxy.py >> gateway.log 2>&1
