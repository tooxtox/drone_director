@echo off
setlocal
chcp 65001 >nul
if exist "%~dp0.venv-demo\Scripts\python.exe" (
  "%~dp0.venv-demo\Scripts\python.exe" -X utf8 "%~dp0scripts\start_demo.py" %*
) else if exist "%~dp0.venv-runtime\Scripts\python.exe" (
  "%~dp0.venv-runtime\Scripts\python.exe" -X utf8 "%~dp0scripts\start_demo.py" %*
) else (
  where py >nul 2>nul
  if errorlevel 1 (
    python -X utf8 "%~dp0scripts\start_demo.py" %*
  ) else (
    py -3 -X utf8 "%~dp0scripts\start_demo.py" %*
  )
)
if errorlevel 1 (
  echo.
  echo Startup failed. Review the error above, then press a key to close.
  pause >nul
  exit /b 1
)
endlocal
