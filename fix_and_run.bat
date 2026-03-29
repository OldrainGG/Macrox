@echo off
cd /d "%~dp0"
echo ================================
echo  MacroX - Fix and Run
echo ================================
echo.

:: Find python that has PyQt6
set PYTHON_CMD=

:: Check all possible python commands
for %%P in (python python3 py) do (
    %%P -c "import PyQt6" 2>nul && (
        set PYTHON_CMD=%%P
        echo [OK] Found working Python: %%P
        goto :found
    )
)

:: Try common install paths
for %%D in (
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
    "C:\Python311\python.exe"
    "C:\Python312\python.exe"
    "C:\Python310\python.exe"
) do (
    if exist %%D (
        %%D -c "import PyQt6" 2>nul && (
            set PYTHON_CMD=%%D
            echo [OK] Found working Python: %%D
            goto :found
        )
    )
)

echo [!!] Could not find Python with PyQt6 installed.
echo.
echo Trying to install PyQt6 into current Python...
python -m pip install PyQt6 --quiet
if %ERRORLEVEL% == 0 (
    echo [OK] PyQt6 installed. Retrying...
    set PYTHON_CMD=python
    goto :found
)
echo [!!] Install failed. Please run install.ps1 again.
pause
exit /b 1

:found
echo.
echo Starting MacroX with: %PYTHON_CMD%
echo ================================
%PYTHON_CMD% main.py
echo.
echo Exit code: %ERRORLEVEL%
echo ================================
pause
