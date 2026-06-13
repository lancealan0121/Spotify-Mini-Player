@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

where git >nul 2>nul
if errorlevel 1 (
    echo Git is not installed or not in PATH.
    pause
    exit /b 1
)

if not exist ".git" (
    echo Initializing git repository...
    git init
    git branch -M main
)

git remote get-url origin >nul 2>nul
if errorlevel 1 (
    echo Missing remote "origin".
    echo.
    set /p "GH_NAME=GitHub name: "
    set /p "GH_REPO=Repository name: "
    if "!GH_NAME!"=="" (
        echo GitHub name is required.
        pause
        exit /b 1
    )
    if "!GH_REPO!"=="" (
        echo Repository name is required.
        pause
        exit /b 1
    )
    set "REMOTE_URL=https://github.com/!GH_NAME!/!GH_REPO!.git"
    echo.
    echo Using remote: !REMOTE_URL!
    git remote add origin "!REMOTE_URL!"
    if errorlevel 1 (
        echo Failed to add remote.
        pause
        exit /b 1
    )
)

git add .

set "MSG=%~1"
if "%MSG%"=="" set "MSG=update spotify mini"

git diff --cached --quiet
if errorlevel 1 (
    git commit -m "%MSG%"
) else (
    echo Nothing to commit.
)

for /f "delims=" %%b in ('git branch --show-current') do set "BRANCH=%%b"
if "%BRANCH%"=="" set "BRANCH=main"

git push -u origin "%BRANCH%"
pause
