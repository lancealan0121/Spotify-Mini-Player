@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "APP_NAME=MiniSP"
set "ENTRY=main.py"
set "PYTHON=python"
set "ROOT=%CD%"
set "BUILD_WORK=%TEMP%\%APP_NAME%_build_%RANDOM%%RANDOM%"
set "BUILD_DIST=%TEMP%\%APP_NAME%_dist_%RANDOM%%RANDOM%"

where %PYTHON% >nul 2>nul
if errorlevel 1 (
    echo Python is not installed or not in PATH.
    pause
    exit /b 1
)

%PYTHON% -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo Installing PyInstaller...
    %PYTHON% -m pip install -U pyinstaller
    if errorlevel 1 (
        echo Failed to install PyInstaller.
        pause
        exit /b 1
    )
)

for /f %%i in ('%PYTHON% -c "import datetime;print(datetime.date.today().strftime('%%Y%%m%%d'))"') do set "TODAY=%%i"
set "OUT_NAME=%APP_NAME%_%TODAY%"

if not exist "%ENTRY%" (
    echo Missing %ENTRY%.
    pause
    exit /b 1
)

if not exist "app.ico" (
    echo Missing app.ico.
    pause
    exit /b 1
)

%PYTHON% -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "%OUT_NAME%" ^
    --icon "%ROOT%\app.ico" ^
    --distpath "%BUILD_DIST%" ^
    --workpath "%BUILD_WORK%" ^
    --specpath "%BUILD_WORK%" ^
    --add-data "%ROOT%\spt.png;." ^
    --add-data "%ROOT%\i18n.json;." ^
    --hidden-import PySide6.QtNetwork ^
    --hidden-import winrt.windows.media ^
    --hidden-import winrt.windows.media.control ^
    --hidden-import winrt.windows.storage.streams ^
    --hidden-import winrt.windows.foundation ^
    --hidden-import winrt.windows.foundation.collections ^
    --exclude-module PySide6.Qt3DAnimation ^
    --exclude-module PySide6.Qt3DCore ^
    --exclude-module PySide6.Qt3DExtras ^
    --exclude-module PySide6.Qt3DInput ^
    --exclude-module PySide6.Qt3DLogic ^
    --exclude-module PySide6.Qt3DRender ^
    --exclude-module PySide6.QtCharts ^
    --exclude-module PySide6.QtDataVisualization ^
    --exclude-module PySide6.QtDesigner ^
    --exclude-module PySide6.QtHelp ^
    --exclude-module PySide6.QtMultimedia ^
    --exclude-module PySide6.QtMultimediaWidgets ^
    --exclude-module PySide6.QtOpenGL ^
    --exclude-module PySide6.QtOpenGLWidgets ^
    --exclude-module PySide6.QtPdf ^
    --exclude-module PySide6.QtPdfWidgets ^
    --exclude-module PySide6.QtPositioning ^
    --exclude-module PySide6.QtPrintSupport ^
    --exclude-module PySide6.QtQml ^
    --exclude-module PySide6.QtQuick ^
    --exclude-module PySide6.QtQuick3D ^
    --exclude-module PySide6.QtQuickControls2 ^
    --exclude-module PySide6.QtQuickWidgets ^
    --exclude-module PySide6.QtRemoteObjects ^
    --exclude-module PySide6.QtScxml ^
    --exclude-module PySide6.QtSensors ^
    --exclude-module PySide6.QtSerialPort ^
    --exclude-module PySide6.QtSpatialAudio ^
    --exclude-module PySide6.QtSql ^
    --exclude-module PySide6.QtSvg ^
    --exclude-module PySide6.QtSvgWidgets ^
    --exclude-module PySide6.QtTest ^
    --exclude-module PySide6.QtTextToSpeech ^
    --exclude-module PySide6.QtUiTools ^
    --exclude-module PySide6.QtWebChannel ^
    --exclude-module PySide6.QtWebEngineCore ^
    --exclude-module PySide6.QtWebEngineQuick ^
    --exclude-module PySide6.QtWebEngineWidgets ^
    --exclude-module PySide6.QtWebSockets ^
    --exclude-module PySide6.QtXml ^
    --exclude-module tkinter ^
    --exclude-module unittest ^
    --exclude-module pytest ^
    --exclude-module IPython ^
    --exclude-module pandas ^
    --exclude-module matplotlib ^
    --exclude-module PIL ^
    "%ENTRY%"

if errorlevel 1 (
    echo Build failed.
    if exist "%BUILD_WORK%" rmdir /s /q "%BUILD_WORK%" >nul 2>nul
    if exist "%BUILD_DIST%" rmdir /s /q "%BUILD_DIST%" >nul 2>nul
    if /i not "%~1"=="--no-pause" pause
    exit /b 1
)

if not exist "dist" mkdir "dist"
copy /Y "%BUILD_DIST%\%OUT_NAME%.exe" "dist\%OUT_NAME%.exe" >nul
if errorlevel 1 (
    echo Failed to copy final exe to dist.
    if exist "%BUILD_WORK%" rmdir /s /q "%BUILD_WORK%" >nul 2>nul
    if exist "%BUILD_DIST%" rmdir /s /q "%BUILD_DIST%" >nul 2>nul
    if /i not "%~1"=="--no-pause" pause
    exit /b 1
)

if exist "%BUILD_WORK%" rmdir /s /q "%BUILD_WORK%" >nul 2>nul
if exist "%BUILD_DIST%" rmdir /s /q "%BUILD_DIST%" >nul 2>nul
echo Build complete: dist\%OUT_NAME%.exe
if /i not "%~1"=="--no-pause" pause
