@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

set "PAUSE_ON_EXIT=1"
set "COMMIT_MSG="
set "BRANCH="
set "REMOTE_URL="
set "LAST_COMMIT="
set "REMOVED_IGNORED=0"
set "DID_COMMIT=No"
set "DID_PUSH=No"

call :parse_args %*
if errorlevel 1 exit /b 1

call :header

if not defined COMMIT_MSG (
    echo Double-click mode: type a short update note, then press Enter.
    echo Leave it blank to use the default message.
    echo.
    set /p "COMMIT_MSG=Update message: "
)
if not defined COMMIT_MSG set "COMMIT_MSG=update spotify mini"

echo.
echo Selected message: %COMMIT_MSG%

echo.
echo [1/7] Checking Git...
where git >nul 2>nul
if errorlevel 1 (
    call :fail "Git is not installed or not in PATH."
    exit /b 1
)

echo [2/7] Checking repository...
if not exist ".git" (
    echo Initializing git repository...
    git init
    if errorlevel 1 (
        call :fail "Failed to initialize git repository."
        exit /b 1
    )
    git branch -M main
)

echo [3/7] Checking remote...
git remote get-url origin >nul 2>nul
if errorlevel 1 (
    call :setup_remote
    if errorlevel 1 exit /b 1
)
for /f "delims=" %%r in ('git remote get-url origin') do set "REMOTE_URL=%%r"

echo [4/7] Removing tracked ignored files...
for /f "usebackq delims=" %%F in (`git ls-files -ci --exclude-standard`) do (
    set "REMOVED_IGNORED=1"
    echo Removing from git tracking: %%F
    git rm --cached --ignore-unmatch "%%F"
    if errorlevel 1 (
        call :fail "Failed to remove an ignored file from git tracking."
        exit /b 1
    )
)
if "%REMOVED_IGNORED%"=="0" echo No tracked ignored files to remove.

echo [5/7] Staging files...
git add -A
if errorlevel 1 (
    call :fail "Failed to stage files."
    exit /b 1
)

echo [6/7] Creating commit...
git diff --cached --quiet
if errorlevel 2 (
    call :fail "Failed to inspect staged changes."
    exit /b 1
)
if errorlevel 1 (
    git commit -m "%COMMIT_MSG%"
    if errorlevel 1 (
        call :fail "Failed to create commit."
        exit /b 1
    )
    set "DID_COMMIT=Yes"
) else (
    echo Nothing to commit.
)

for /f "delims=" %%b in ('git branch --show-current') do set "BRANCH=%%b"
if not defined BRANCH set "BRANCH=main"
for /f "delims=" %%h in ('git rev-parse --short HEAD 2^>nul') do set "LAST_COMMIT=%%h"
if not defined LAST_COMMIT set "LAST_COMMIT=None"

echo [7/7] Pushing to origin/%BRANCH%...
git push -u origin "%BRANCH%"
if errorlevel 1 (
    call :fail "Failed to push to origin."
    exit /b 1
)
set "DID_PUSH=Yes"

call :success
exit /b 0

:parse_args
if "%~1"=="" exit /b 0
if /i "%~1"=="--no-pause" goto arg_no_pause
if /i "%~1"=="--message" goto arg_message
goto arg_text

:arg_no_pause
set "PAUSE_ON_EXIT=0"
shift
goto parse_args

:arg_message
shift
if "%~1"=="" (
    echo Missing value for --message.
    if "%PAUSE_ON_EXIT%"=="1" pause
    exit /b 1
)
goto arg_text

:arg_text
if defined COMMIT_MSG goto arg_append
set "COMMIT_MSG=%~1"
shift
goto parse_args

:arg_append
set "COMMIT_MSG=%COMMIT_MSG% %~1"
shift
goto parse_args

:header
echo ============================================================
echo  Upload
echo ============================================================
echo Double-click this file to upload with an update message prompt.
echo.
echo Optional command line usage:
echo Usage:
echo   upload.bat
echo   upload.bat --message "short update note"
echo   upload.bat --no-pause --message "short update note"
echo ============================================================
exit /b 0

:setup_remote
echo Missing remote "origin".
echo.
set /p "GH_NAME=GitHub name: "
set /p "GH_REPO=Repository name: "
if not defined GH_NAME (
    call :fail "GitHub name is required."
    exit /b 1
)
if not defined GH_REPO (
    call :fail "Repository name is required."
    exit /b 1
)
set "REMOTE_URL=https://github.com/%GH_NAME%/%GH_REPO%.git"
echo.
echo Using remote: %REMOTE_URL%
git remote add origin "%REMOTE_URL%"
if errorlevel 1 (
    call :fail "Failed to add remote."
    exit /b 1
)
exit /b 0

:success
echo.
echo ============================================================
echo  Upload Summary
echo ============================================================
echo Status          : Success
echo Remote          : %REMOTE_URL%
echo Branch          : %BRANCH%
echo Last commit     : %LAST_COMMIT%
echo Created commit  : %DID_COMMIT%
echo Pushed          : %DID_PUSH%
echo Ignored cleanup : %REMOVED_IGNORED%
echo Message         : %COMMIT_MSG%
echo ============================================================
echo.
if "%PAUSE_ON_EXIT%"=="1" pause
exit /b 0

:fail
echo.
echo ============================================================
echo  Upload Failed
echo ============================================================
echo Reason: %~1
echo ============================================================
echo.
if "%PAUSE_ON_EXIT%"=="1" pause
exit /b 1
