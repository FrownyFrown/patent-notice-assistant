@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 -X utf8 -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>&1
if not errorlevel 1 goto use_py
python -X utf8 -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>&1
if not errorlevel 1 goto use_python
echo Python 3.10 이상을 설치하세요: https://www.python.org/downloads/
pause
exit /b 1
:use_py
py -3 -X utf8 scripts/work.py doctor
goto done
:use_python
python -X utf8 scripts/work.py doctor
:done
set "result=%errorlevel%"
pause
exit /b %result%
