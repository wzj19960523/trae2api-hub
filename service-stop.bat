@echo off
REM trae2api-hub gateway STOP helper (ASCII only)
REM 说明：任务计划程序的「结束」只会结束 bat/任务实例，不会杀掉它拉起的
REM pythonw 子进程；需要显式按端口结束监听者。停完后看门狗会在 5 分钟内
REM 重新拉起网关（如需长期停机，请先禁用计划任务 trae2api-hub-gateway）。
setlocal enabledelayedexpansion
set FOUND=0
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8791 " ^| findstr "LISTENING"') do (
  echo killing gateway PID %%p
  taskkill /PID %%p /F >nul 2>&1
  set FOUND=1
)
if "!FOUND!"=="0" echo no listener on 8791
exit /b 0
