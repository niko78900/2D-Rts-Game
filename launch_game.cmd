@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo Could not find .venv\Scripts\activate.bat
    echo Run setup from the project folder first.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"
python -m house_of_wolves
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Game exited with error code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
