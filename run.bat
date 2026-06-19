@echo off
cd /d "%~dp0"
python main.py
set "EXITCODE=%ERRORLEVEL%"
echo.
echo Process exited with code %EXITCODE%.
pause
exit /b %EXITCODE%
