import os
import sys
import shutil
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET_PARENT = os.path.dirname(BASE_DIR)
DESTN_DIR = os.path.join(TARGET_PARENT, "SMS_Sender_App_Windows")
OLD_DESTN_DIR = os.path.join(TARGET_PARENT, "SMS_Sender_Tool_Win")


def verify_windows_bundle(bundle_dir: str) -> bool:
    required_files = [
        "SmsSenderTool.exe",
        os.path.join("_internal", "platform-tools", "adb.exe"),
        os.path.join("_internal", "platform-tools", "AdbWinApi.dll"),
        os.path.join("_internal", "platform-tools", "AdbWinUsbApi.dll"),
    ]
    missing = [path for path in required_files if not os.path.isfile(os.path.join(bundle_dir, path))]
    if missing:
        print("[LOI] Bundle thieu file bat buoc:\n- " + "\n- ".join(missing))
        return False
    return True


def build():
    print("=" * 60)
    print("  DANG DONG GOI UNG DUNG WINDOWS DESKTOP (.EXE)")
    print("=" * 60)

    if os.name != "nt":
        print("[LOI] EXE Windows phai duoc dong goi tren may Windows.")
        return False

    pyinstaller_exe = os.path.join(BASE_DIR, ".venv", "Scripts", "pyinstaller.exe")
    if not os.path.isfile(pyinstaller_exe):
        pyinstaller_exe = "pyinstaller"

    cmd = [
        pyinstaller_exe,
        "--noconfirm",
        "--clean",
        "--name=SmsSenderTool",
        "--windowed",
        "--add-data=templates;templates",
        "--add-data=platform-tools;platform-tools",
        "--add-data=android_sender/SmsBridgeSender-debug.apk;android_sender",
        "--add-data=dulieu_mau.xlsx;.",
        "--hidden-import=pandas",
        "--hidden-import=openpyxl",
        "--hidden-import=serial",
        "--hidden-import=serial.tools.list_ports",
        "--hidden-import=flask",
        "--hidden-import=werkzeug",
        "--hidden-import=werkzeug.serving",
        "--hidden-import=requests",
        "--hidden-import=sqlite3",
        "--hidden-import=webview",
        "--collect-all=webview",
        "app_desktop.py",
    ]

    print("Executing command:\n", " ".join(cmd))
    result = subprocess.run(cmd, cwd=BASE_DIR)
    if result.returncode != 0:
        print("[LOI] Dong goi that bai!")
        return False

    print("\n>>> Dang sao chep vao thu muc:", DESTN_DIR)
    dist_src = os.path.join(BASE_DIR, "dist", "SmsSenderTool")
    if not verify_windows_bundle(dist_src):
        return False
    
    subprocess.run(["cmd.exe", "/c", "taskkill /F /IM adb.exe /IM SmsSenderTool.exe 2>nul"], check=False)
    
    # Remove old directory if exists
    if os.path.exists(OLD_DESTN_DIR):
        try:
            shutil.rmtree(OLD_DESTN_DIR, ignore_errors=True)
        except Exception:
            pass

    shutil.copytree(dist_src, DESTN_DIR, dirs_exist_ok=True)
    if not verify_windows_bundle(DESTN_DIR):
        return False

    print("\n[THANH CONG]")
    print("- Thu muc ung dung duy nhat:", DESTN_DIR)
    print("- File chay chinh:", os.path.join(DESTN_DIR, "SmsSenderTool.exe"))
    return True

if __name__ == "__main__":
    raise SystemExit(0 if build() else 1)
