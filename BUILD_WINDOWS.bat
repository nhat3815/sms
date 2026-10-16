@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "APP_EXE=%~dp0..\SMS_Sender_App_Windows\SmsSenderTool.exe"
set "ADB_EXE=%~dp0..\SMS_Sender_App_Windows\_internal\platform-tools\adb.exe"
set "BUILD_LOG=%~dp0build_windows.log"

if not exist ".force_rebuild" if exist "%APP_EXE%" if exist "%ADB_EXE%" (
    start "" "%APP_EXE%"
    exit /b 0
)

echo Dang dong goi lan dau. Vui long cho...
echo Build started %date% %time% > "%BUILD_LOG%"

set "PYTHON_CMD=py -3"
py -3 --version >nul 2>&1
if errorlevel 1 (
    set "PYTHON_CMD=python"
    python --version >nul 2>&1
    if errorlevel 1 (
        echo Khong tim thay Python 3. Cai Python roi chay lai.
        pause
        exit /b 1
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Tao Python environment...
    %PYTHON_CMD% -m venv .venv >> "%BUILD_LOG%" 2>&1
    if errorlevel 1 goto :error
)

call .venv\Scripts\activate.bat
if errorlevel 1 goto :error

echo [2/3] Cai dependency. Toi da 30 giay moi lan tai...
python -m pip install --disable-pip-version-check --timeout 30 --retries 1 --upgrade pip >> "%BUILD_LOG%" 2>&1
if errorlevel 1 goto :error
python -m pip install --disable-pip-version-check --timeout 30 --retries 1 -r requirements.txt pyinstaller >> "%BUILD_LOG%" 2>&1
if errorlevel 1 goto :error

echo [3/3] Dong goi EXE va ADB. Khong dong cua so nay...
python build_exe.py >> "%BUILD_LOG%" 2>&1
if errorlevel 1 goto :error

if not exist "%APP_EXE%" goto :missing
if not exist "%ADB_EXE%" goto :missing

echo Hoan tat. Dang mo ung dung...
del /q ".force_rebuild" >nul 2>&1
start "" "%APP_EXE%"
exit /b 0

:missing
echo Dong goi loi: thieu SmsSenderTool.exe hoac adb.exe.
start "" notepad "%BUILD_LOG%"
pause
exit /b 1

:error
echo Dong goi loi. Da mo file build_windows.log.
start "" notepad "%BUILD_LOG%"
pause
exit /b 1
echo [ERROR] Dong goi that bai.
pause
exit /b 1
