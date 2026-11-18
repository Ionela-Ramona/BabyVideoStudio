@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Baby Video Studio

if not exist ".venv\Scripts\python.exe" (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python nu este instalat. Ruleaza: winget install Python.Python.3.12
        pause
        exit /b 1
    )
    echo Prima pornire: pregatesc aplicatia, dureaza cateva minute...
    python -m venv .venv
    if errorlevel 1 goto :failed
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 goto :failed
)

echo Baby Video Studio porneste. Lasa aceasta fereastra deschisa cat timp folosesti aplicatia.
start "" /min cmd /c "timeout /t 5 /nobreak >nul & start http://localhost:8501"
".venv\Scripts\python.exe" -m streamlit run app.py --server.headless true --server.port 8501 --browser.gatherUsageStats false --client.toolbarMode minimal
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo A aparut o eroare. Citeste mesajele de mai sus.
pause
exit /b 1
