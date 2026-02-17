@echo off
cd /d "%~dp0"
if not exist venv\Scripts\activate.bat goto :NO_VENV
call venv\Scripts\activate.bat
python run_research.py --interactive --auto
pause
goto :EOF

:NO_VENV
echo [ERROR] venv not found
pause
