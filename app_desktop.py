"""
Desktop Application Entrypoint for SMS Sender Tool.
Uses Native WebView2 (pywebview) for a seamless desktop experience,
with robust browser fallback if webview2 runtime is absent.
"""

import os
import sys
import time
import socket
import subprocess
import threading
import urllib.request
import urllib.error
import platform

# Ensure working directory is correctly set
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
    BUNDLE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = APP_DIR

os.chdir(APP_DIR)
if BUNDLE_DIR not in sys.path:
    sys.path.insert(0, BUNDLE_DIR)
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import launcher


def find_free_port(start_port=5000):
    for port in range(start_port, start_port + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 5000


def wait_for_server(port, timeout=12):
    start = time.time()
    url = f"http://127.0.0.1:{port}/log"
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def run_backend(port):
    import logging
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)
    # Start background signal polling loop and device auto-init
    threading.Thread(target=launcher.update_signal_loop, daemon=True).start()
    threading.Thread(target=auto_init_scan, daemon=True).start()
    try:
        launcher.app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        with open("app_error.log", "a", encoding="utf-8") as f:
            f.write(f"Flask run error: {e}\n")


def auto_init_scan():
    time.sleep(1)
    try:
        launcher.connect()
    except Exception:
        pass


def find_browser_executable():
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local_app_data = os.environ.get("LOCALAPPDATA", "")

    candidates = [
        os.path.join(program_files_x86, "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(program_files, "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(local_app_data, "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(local_app_data, "Google", "Chrome", "Application", "chrome.exe"),
    ]

    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def main():
    port = find_free_port(5000)

    # Start Flask backend in daemon thread
    backend_thread = threading.Thread(target=run_backend, args=(port,), daemon=True)
    backend_thread.start()

    # Wait for backend to be fully responsive
    wait_for_server(port, timeout=15)

    app_url = f"http://127.0.0.1:{port}"

    # 1. Try Native WebView2 Desktop Window
    try:
        import webview
        window = webview.create_window(
            title="SMS Sender Tool",
            url=app_url,
            width=1300,
            height=850,
            min_size=(800, 550),
            resizable=True,
            background_color="#0d1117",
        )
        if platform.system() == "Windows":
            webview.start(gui="edgechromium", debug=False)
        else:
            webview.start(debug=False)
        # When webview window closes, exit
        os._exit(0)
    except Exception as e:
        with open("app_error.log", "a", encoding="utf-8") as f:
            f.write(f"WebView error: {e}\n")

    # 2. Fallback: Edge/Chrome App Mode
    browser_exe = find_browser_executable()
    user_data_dir = os.path.join(os.environ.get("TEMP", APP_DIR), f"SmsSenderProfile_{port}")
    os.makedirs(user_data_dir, exist_ok=True)

    if browser_exe:
        cmd = [
            browser_exe,
            f"--app={app_url}",
            "--window-size=1300,850",
            f"--user-data-dir={user_data_dir}",
            "--disable-extensions",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        try:
            subprocess.Popen(cmd)
        except Exception:
            import webbrowser
            webbrowser.open(app_url)
    else:
        import webbrowser
        webbrowser.open(app_url)

    # Keep server running until process interrupted
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    os._exit(0)


if __name__ == "__main__":
    main()
