@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "APP_NAME=SpotifyMini"
set "ENTRY=main.py"
set "PYTHON=python"

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

if not exist "%ENTRY%" (
    echo Missing %ENTRY%.
    pause
    exit /b 1
)

%PYTHON% -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --windowed ^
    --name "%APP_NAME%" ^
    --distpath dist ^
    --workpath build ^
    --specpath build ^
    --add-data "spt.png;." ^
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
    --exclude-module numpy ^
    --exclude-module pandas ^
    --exclude-module matplotlib ^
    --exclude-module PIL ^
    "%ENTRY%"

if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

for %%D in (
    "dist\%APP_NAME%\_internal\PySide6\Qt6\qml"
    "dist\%APP_NAME%\_internal\PySide6\Qt6\translations"
    "dist\%APP_NAME%\_internal\PySide6\Qt6\resources"
) do (
    if exist %%~D rmdir /s /q %%~D
)

echo Build complete: dist\%APP_NAME%\%APP_NAME%.exe
pause
