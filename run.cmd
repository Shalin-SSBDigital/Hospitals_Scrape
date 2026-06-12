@echo off
REM One-click launcher for the HEM hospital scraper
cd /d "%~dp0"
if not exist ".venv\" (
    echo Creating virtual environment...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    echo Installing dependencies...
    pip install --upgrade pip
    pip install -r requirements.txt
    playwright install chromium
) else (
    call .venv\Scripts\activate.bat
)
python scrape_hem.py
pause
