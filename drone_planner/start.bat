@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

set "PY=C:\Python314\python.exe"
if not exist "%PY%" set "PY=python"

if not exist ".venv\Scripts\python.exe" (
  echo Создаю виртуальное окружение...
  "%PY%" -m venv .venv
  if errorlevel 1 (
    echo Не удалось создать виртуальное окружение. Нужен Python 3.14.
    exit /b 1
  )
)

echo Устанавливаю зависимости...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo Карта: http://127.0.0.1:8765
".venv\Scripts\python.exe" web_server.py
