@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

title SMS Sender Tool

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
set "ADB_EXE="
set "ADB_DIR="

:: 1. Kiem tra va khoi tao ADB
call :find_adb

:: 2. Kiem tra va khoi tao moi truong Python
call :ensure_python
if errorlevel 1 (
    echo [LOI] Khong the khoi dong moi truong Python.
    pause
    exit /b 1
)

echo ========================================================
echo   SMS SENDER TOOL - KHOI DONG HE THONG
echo ========================================================
if defined ADB_EXE (
    echo [ADB] Da tim thay: !ADB_EXE!
) else (
    echo [ADB] Chua tim thay ADB tren he thong.
)
echo [PYTHON] Su dung: %PYTHON_EXE%
echo [WEB SERVER] Dang khoi chay tren cong 5000...
echo ========================================================
echo.

"%PYTHON_EXE%" launcher.py
if errorlevel 1 (
    echo.
    echo [THONG BAO] Ung dung da dung lai.
    pause
)
goto :eof


:ensure_python
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" -c "import numpy, pandas, flask, serial, requests, openpyxl" >nul 2>nul
    if !errorlevel!==0 exit /b 0

    :: .venv ton tai nhung thu vien hong (thuong gap: numpy thieu DLL sau khi cai).
    :: Pip bo qua vi thay numpy da "duoc cai" nen phai ep cai lai.
    echo [SUA LOI] Thu vien trong .venv bi hong. Dang cai lai numpy, pandas...
    "%PYTHON_EXE%" -m pip install --disable-pip-version-check --upgrade pip >nul 2>nul
    "%PYTHON_EXE%" -m pip install --disable-pip-version-check --force-reinstall --no-cache-dir numpy pandas
    "%PYTHON_EXE%" -c "import numpy, pandas, flask, serial, requests, openpyxl" >nul 2>nul
    if !errorlevel!==0 (
        echo [OK] Da cai lai thu vien thanh cong.
        exit /b 0
    )
    echo [LOI] Cai lai thu vien van khong duoc. Hay xoa thu muc .venv va chay lai run.bat.
    exit /b 1
)

echo Dang thiet lap moi truong Python (.venv)...
set "SYS_PY="
where python >nul 2>nul
if !errorlevel!==0 (
    set "SYS_PY=python"
) else (
    where py >nul 2>nul
    if !errorlevel!==0 set "SYS_PY=py -3"
)

if not defined SYS_PY (
    echo [LOI] Khong tim thay Python tren may. Vui long cai dat Python 3.10+ tu python.org va tich chon "Add Python to PATH"!
    exit /b 1
)

echo Tao moi truong ao .venv...
%SYS_PY% -m venv .venv
if not exist "%PYTHON_EXE%" (
    echo [LOI] Tao moi truong ao .venv that bai.
    exit /b 1
)

echo Cai dat cac thu vien can thiet tu requirements.txt...
"%PYTHON_EXE%" -m pip install --disable-pip-version-check -r requirements.txt
if !errorlevel!==0 (
    echo Cai dat thu vien thanh cong.
    exit /b 0
) else (
    echo [LOI] Cai dat thu vien that bai.
    exit /b 1
)


:find_adb
:: 1. Kiem tra adb trong thu muc goc project
if exist "%~dp0platform-tools\adb.exe" (
    set "ADB_EXE=%~dp0platform-tools\adb.exe"
    goto :adb_set
)
if exist "%~dp0adb.exe" (
    set "ADB_EXE=%~dp0adb.exe"
    goto :adb_set
)

:: 2. Kiem tra adb trong PATH
for /f "delims=" %%I in ('where adb 2^>nul') do (
    set "ADB_EXE=%%I"
    goto :adb_set
)

:: 3. Kiem tra cac duong dan Android SDK tieu chuan
if defined ADB_PATH if exist "%ADB_PATH%" (
    set "ADB_EXE=%ADB_PATH%"
    goto :adb_set
)
if defined ANDROID_HOME if exist "%ANDROID_HOME%\platform-tools\adb.exe" (
    set "ADB_EXE=%ANDROID_HOME%\platform-tools\adb.exe"
    goto :adb_set
)
if defined ANDROID_SDK_ROOT if exist "%ANDROID_SDK_ROOT%\platform-tools\adb.exe" (
    set "ADB_EXE=%ANDROID_SDK_ROOT%\platform-tools\adb.exe"
    goto :adb_set
)
if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" (
    set "ADB_EXE=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"
    goto :adb_set
)
if exist "C:\Android\Sdk\platform-tools\adb.exe" (
    set "ADB_EXE=C:\Android\Sdk\platform-tools\adb.exe"
    goto :adb_set
)
if exist "C:\platform-tools\adb.exe" (
    set "ADB_EXE=C:\platform-tools\adb.exe"
    goto :adb_set
)

exit /b 0

:adb_set
for %%J in ("%ADB_EXE%") do set "ADB_DIR=%%~dpJ"
set "PATH=%ADB_DIR%;%PATH%"
set "ADB_PATH=%ADB_EXE%"
exit /b 0
