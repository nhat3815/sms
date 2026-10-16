from __future__ import annotations

import base64
import json
import os
import re
import socket
import sys
import platform
import shlex
import shutil
import subprocess
import time
import uuid
import threading
from glob import glob
from dataclasses import dataclass
from typing import Callable, Any


PACKAGE_NAME = "vn.smsbridge.sender"
RECEIVER_NAME = f"{PACKAGE_NAME}/.SmsCommandReceiver"


def resolve_adb_path(adb_path: str | None = None) -> str | None:
    if adb_path:
        return adb_path

    env_path = os.environ.get("ADB_PATH")
    if env_path and (os.path.isfile(env_path) or shutil.which(env_path)):
        return env_path

    base_dir = os.path.dirname(os.path.abspath(__file__))
    system = platform.system()
    adb_bin = "adb.exe" if system == "Windows" else "adb"

    # 1. ALWAYS PRIORITIZE LOCAL BUNDLED ADB IN SOURCE DIRECTORY / PYINSTALLER BUNDLE
    local_candidates = [
        os.path.join(base_dir, "platform-tools", adb_bin),
        os.path.join(base_dir, "adb", adb_bin),
        os.path.join(base_dir, adb_bin),
    ]

    if getattr(sys, "frozen", False):
        exec_dir = os.path.dirname(os.path.abspath(sys.executable))
        meipass_dir = getattr(sys, "_MEIPASS", "")
        local_candidates.extend([
            os.path.join(meipass_dir, "platform-tools", adb_bin),
            os.path.join(meipass_dir, "_internal", "platform-tools", adb_bin),
            os.path.join(exec_dir, "platform-tools", adb_bin),
            os.path.join(exec_dir, "_internal", "platform-tools", adb_bin),
            os.path.join(exec_dir, adb_bin),
        ])

    for c in local_candidates:
        if c and os.path.isfile(c):
            if system != "Windows":
                try:
                    os.chmod(c, 0o755)
                except Exception:
                    pass
            return c

    which_path = shutil.which("adb")
    if which_path and os.path.isfile(which_path):
        return which_path

    home = os.path.expanduser("~")
    candidates: list[str] = []

    # Environment variables
    for env_var in ["ANDROID_HOME", "ANDROID_SDK_ROOT"]:
        val = os.environ.get(env_var)
        if val:
            candidates.append(os.path.join(val, "platform-tools", adb_bin))
            candidates.append(os.path.join(val, adb_bin))

    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        user_profile = os.environ.get("USERPROFILE", home)

        # WinGet
        candidates.extend(glob(os.path.join(local_app_data, "Microsoft", "WinGet", "Packages", "Google.PlatformTools*", "platform-tools", "adb.exe")))
        candidates.extend(glob(os.path.join(local_app_data, "Microsoft", "WinGet", "Links", "adb.exe")))

        # Standard Android SDK paths
        candidates.extend([
            os.path.join(local_app_data, "Android", "Sdk", "platform-tools", "adb.exe"),
            os.path.join(user_profile, "AppData", "Local", "Android", "Sdk", "platform-tools", "adb.exe"),
            os.path.join(user_profile, "scoop", "apps", "adb", "current", "platform-tools", "adb.exe"),
            os.path.join(user_profile, "scoop", "shims", "adb.exe"),
            r"C:\Android\Sdk\platform-tools\adb.exe",
            r"D:\Android\Sdk\platform-tools\adb.exe",
            r"C:\platform-tools\adb.exe",
            r"C:\Android\platform-tools\adb.exe",
            r"C:\ProgramData\chocolatey\bin\adb.exe",
            os.path.join(base_dir, "platform-tools", "adb.exe"),
            os.path.join(base_dir, "adb.exe"),
        ])
    else:  # Linux / macOS
        candidates.extend([
            os.path.join(home, "Android", "Sdk", "platform-tools", "adb"),
            os.path.join(home, "Library", "Android", "sdk", "platform-tools", "adb"),
            os.path.join(home, ".android-sdk", "platform-tools", "adb"),
            os.path.join(home, "platform-tools", "adb"),
            "/usr/bin/adb",
            "/usr/local/bin/adb",
            "/opt/homebrew/bin/adb",
            "/opt/android-sdk/platform-tools/adb",
            "/usr/lib/android-sdk/platform-tools/adb",
            os.path.join(base_dir, "platform-tools", "adb"),
            os.path.join(base_dir, "adb"),
        ])

    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            if system != "Windows":
                try:
                    os.chmod(candidate, 0o755)
                except Exception:
                    pass
            return candidate

    return None


# Callback ghi log do launcher inject (hàm add_log), dùng để báo cảnh báo SIM/kênh
log_sink = None


def _log(status: str, message: str) -> None:
    if log_sink:
        try:
            log_sink(status, message)
        except Exception:
            pass


@dataclass(frozen=True)
class AndroidDevice:
    serial: str
    model: str
    ready: bool
    detail: str
    sims: tuple[dict[str, Any], ...] = ()


class JobSummary(tuple):
    def __new__(cls, status: str, detail: str, phone: str = "", message: str = ""):
        return super().__new__(cls, (status, detail))

    def __init__(self, status: str, detail: str, phone: str = "", message: str = ""):
        self.status = status
        self.detail = detail
        self.phone = phone
        self.message = message


class AndroidTransport:
    def __init__(
        self,
        adb_path: str | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.adb_path = resolve_adb_path(adb_path)
        self.runner = runner
        self.cloud_devices: dict[str, dict[str, Any]] = {}
        self.cloud_jobs: dict[str, list[dict[str, Any]]] = {}
        self.cloud_lock = threading.Lock()
        # Cache bridge token theo serial, TTL 10 phút (tránh spawn adb liên tục khi nhiều worker SIM song song)
        self._token_cache: dict[str, tuple[str, float]] = {}

    def record_cloud_device(self, device_id: str, ip: str = "", sims: list[dict] | None = None) -> None:
        if not device_id:
            return
        with self.cloud_lock:
            entry = self.cloud_devices.get(device_id, {
                "id": device_id,
                "ip": ip,
            })
            entry["last_seen"] = time.time()
            if ip:
                entry["ip"] = ip
            if sims is not None:
                entry["sims"] = sims
            self.cloud_devices[device_id] = entry

    def get_active_cloud_devices(self, timeout: float = 35.0) -> list[dict[str, Any]]:
        now = time.time()
        with self.cloud_lock:
            active = []
            for dev_id, info in list(self.cloud_devices.items()):
                if now - info.get("last_seen", 0) <= timeout:
                    active.append(dict(info))
            return active

    def get_next_cloud_job(self, device_id: str) -> dict[str, Any] | None:
        with self.cloud_lock:
            jobs = self.cloud_jobs.get(device_id)
            if jobs:
                return jobs.pop(0)
            any_jobs = self.cloud_jobs.get("__any__")
            if any_jobs:
                return any_jobs.pop(0)
            return None

    def enqueue_cloud_job(
        self,
        device_id: str,
        phone: str,
        message: str,
        subscription_id: int = -1,
    ) -> str:
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "device_id": device_id,
            "phone": phone,
            "message": message,
            "subscription_id": subscription_id,
            "created_at": time.time(),
        }
        with self.cloud_lock:
            target_queue = self.cloud_jobs.setdefault(device_id, [])
            target_queue.append(job)
        return job_id

    def _run(self, *args: str, timeout: int = 10) -> subprocess.CompletedProcess[str]:
        if not self.adb_path:
            raise RuntimeError("ADB not found")
        kwargs: dict[str, object] = {
            "capture_output": True,
            "text": True,
            "timeout": timeout,
            "check": False,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if platform.system() == "Windows":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        return self.runner(
            [self.adb_path, *args],
            **kwargs
        )

    def scan(self) -> list[AndroidDevice]:
        devices: list[AndroidDevice] = []

        # 1. Active Cloud / Wi-Fi App devices (zero cable, zero ADB needed)
        for cdev in self.get_active_cloud_devices():
            dev_id = cdev["id"]
            ip_info = f" ({cdev['ip']})" if cdev.get("ip") else ""
            sims = tuple(self.get_device_sims(f"cloud:{dev_id}"))
            devices.append(AndroidDevice(
                serial=f"cloud:{dev_id}",
                model=f"Wi-Fi App: {dev_id}{ip_info}",
                ready=True,
                detail="ready",
                sims=sims,
            ))

        # 2. Hardware / ADB devices (if ADB available)
        if self.adb_path:
            try:
                result = self._run("devices", "-l", timeout=4)
                for line in result.stdout.splitlines()[1:]:
                    fields = line.split()
                    if len(fields) < 2:
                        continue
                    serial, state = fields[0], fields[1]
                    model = next((item.split(":", 1)[1] for item in fields if item.startswith("model:")), serial)
                    if state != "device":
                        devices.append(AndroidDevice(serial, model, False, state, ()))
                        continue
                    try:
                        package = self._run("-s", serial, "shell", "pm", "path", PACKAGE_NAME, timeout=3)
                        ready = package.returncode == 0 and "package:" in package.stdout
                    except Exception:
                        ready = False
                    detail = "ready" if ready else "companion_not_installed"
                    sims = tuple(self.get_device_sims(serial)) if ready else ()
                    devices.append(AndroidDevice(serial, model, ready, detail, sims))
            except Exception:
                pass

        return devices

    def enable_tcpip(self, serial: str, port: int = 5555) -> bool:
        if not self.adb_path or not serial:
            return False
        try:
            res = self._run("-s", serial, "tcpip", str(port), timeout=5)
            return res.returncode == 0
        except Exception:
            return False

    def get_primary_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith("127."):
                return ip
        except Exception:
            pass
        return "192.168.1.x"

    def connect_wifi(self, target: str) -> tuple[bool, str]:
        if not target:
            return False, "Target empty"
        if target.startswith("cloud:"):
            return True, "Thiết bị Wi-Fi App đã kết nối sẵn sàng"
        if not self.adb_path:
            return False, "ADB not found"
        clean_target = target.strip()
        if ":" in clean_target:
            host, port_str = clean_target.rsplit(":", 1)
            if port_str == "8765":
                clean_target = f"{host}:5555"
        else:
            clean_target = f"{clean_target}:5555"
        host = clean_target.split(":")[0]
        port = int(clean_target.split(":")[1]) if ":" in clean_target else 5555

        # Quick pre-check if port is open
        is_port_open = False
        try:
            s_chk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s_chk.settimeout(0.4)
            is_port_open = (s_chk.connect_ex((host, port)) == 0)
            s_chk.close()
        except Exception:
            is_port_open = False

        real_ip = self.get_primary_ip()
        if not is_port_open:
            msg = (
                f"Cổng {port} tại {host} chưa được mở (Android 10 không hỗ trợ mở cổng ADB qua Wi-Fi).\n\n"
                f"👉 ĐỂ KẾT NỐI 100% KHÔNG CẦN CÁP USB:\n"
                f"1. Mở ứng dụng 'SMS Bridge Sender' trên điện thoại.\n"
                f"2. Bấm vào nút 'Cấu hình Cloud' (hoặc biểu tượng Cloud).\n"
                f"3. Nhập Master LAN: http://{real_ip}:8765\n"
                f"4. Nhập Device ID: phone1 và Token: 123.\n"
                f"5. Bấm 'Lưu và chạy cloud service' -> Máy tính sẽ tự động nhận diện thiết bị ngay!"
            )
            return False, msg

        try:
            res = self._run("connect", clean_target, timeout=5)
            out = (res.stdout + " " + res.stderr).strip()
            ok = "connected" in out.lower() or "already connected" in out.lower()
            if not ok:
                out = (
                    f"Không thể kết nối ADB tới {clean_target} ({out}).\n\n"
                    f"👉 ĐỂ KẾT NỐI KHÔNG DÂY:\n"
                    f"Mở app SMS Bridge trên điện thoại > Cấu hình Cloud > nhập Master LAN là http://{real_ip}:8765 > bấm Lưu và chạy."
                )
            return ok, out
        except Exception:
            return False, (
                f"Hết thời gian chờ kết nối ADB tới {clean_target}.\n\n"
                f"👉 Hãy kết nối 100% không dây qua App:\n"
                f"Mở app SMS Bridge trên điện thoại > Cấu hình Cloud > nhập Master LAN: http://{real_ip}:8765 > bấm Lưu và chạy."
            )

    def reconnect_offline(self) -> bool:
        if not self.adb_path:
            return False
        try:
            result = self._run("reconnect", "offline", timeout=6)
            return result.returncode == 0
        except Exception:
            return False

    def recover_offline_devices(self, serials: list[str]) -> list[str]:
        self.reconnect_offline()
        recovered: list[str] = []
        for serial in serials:
            host, separator, port = serial.rpartition(":")
            if not separator or host.count(".") != 3 or not port.isdigit():
                continue
            self.disconnect_wifi(serial)
            ok, _ = self.connect_wifi(serial)
            if ok:
                recovered.append(serial)
        return recovered

    def _get_lan_ip_candidates(self) -> list[str]:
        import socket
        import re

        ip_candidates = set()
        active_subnets = set()

        # 1. Inspect OS ARP Cache Table (instantaneous <10ms, finds all active Wi-Fi / LAN clients)
        try:
            res = subprocess.run(
                ["arp", "-a"],
                capture_output=True,
                text=True,
                timeout=2,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if platform.system() == "Windows" else 0
            )
            for line in res.stdout.splitlines():
                match = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", line)
                if match:
                    ip = match.group(1)
                    if not ip.startswith("127.") and not ip.startswith("224.") and not ip.startswith("255.") and not ip.endswith(".255") and not ip.endswith(".1"):
                        ip_candidates.add(ip)
                        parts = ip.split(".")
                        active_subnets.add(f"{parts[0]}.{parts[1]}.{parts[2]}")
        except Exception:
            pass

        # 2. Inspect active network interface IP
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            parts = local_ip.split(".")
            if len(parts) == 4:
                active_subnets.add(f"{parts[0]}.{parts[1]}.{parts[2]}")
        except Exception:
            pass

        try:
            hostname = socket.gethostname()
            for ip in socket.gethostbyname_ex(hostname)[2]:
                if not ip.startswith("127.") and not ip.startswith("169.254."):
                    parts = ip.split(".")
                    if len(parts) == 4:
                        active_subnets.add(f"{parts[0]}.{parts[1]}.{parts[2]}")
        except Exception:
            pass

        # Read every local interface. The default route can be a corporate LAN while
        # an Android hotspot lives on another active adapter.
        commands = {
            "Darwin": ["ifconfig", "-a"],
            "Linux": ["ip", "-4", "addr", "show"],
            "Windows": ["ipconfig"],
        }
        try:
            result = subprocess.run(
                commands.get(platform.system(), []),
                capture_output=True,
                text=True,
                timeout=2,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if platform.system() == "Windows" else 0,
            )
            for ip in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", result.stdout):
                if ip.startswith(("127.", "169.254.", "224.", "255.")):
                    continue
                parts = ip.split(".")
                if all(0 <= int(part) <= 255 for part in parts):
                    active_subnets.add(f"{parts[0]}.{parts[1]}.{parts[2]}")
        except (OSError, subprocess.SubprocessError, ValueError):
            pass

        # Keep only the primary subnet and 192.168.137 for fast scanning
        primary_subnet = ""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            lip = s.getsockname()[0]
            s.close()
            parts = lip.split(".")
            if len(parts) == 4 and not lip.startswith("127."):
                primary_subnet = f"{parts[0]}.{parts[1]}.{parts[2]}"
        except Exception:
            pass

        final_subnets = set()
        if primary_subnet:
            final_subnets.add(primary_subnet)
        final_subnets.add("192.168.137")
        if not primary_subnet and active_subnets:
            final_subnets.update(list(active_subnets)[:2])

        # Add all host IPs for active subnets
        for subnet in final_subnets:
            for i in range(2, 255):
                ip_candidates.add(f"{subnet}.{i}")

        return list(ip_candidates)

    def scan_wifi_network(self, auto_install: bool = True) -> list[str]:
        import socket
        from concurrent.futures import ThreadPoolExecutor

        candidates = self._get_lan_ip_candidates()

        def check_port(ip):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.15)
            try:
                if s.connect_ex((ip, 5555)) == 0:
                    s.close()
                    return f"{ip}:5555"
                s.close()
            except Exception:
                pass
            return None

        open_targets = []
        with ThreadPoolExecutor(max_workers=60) as executor:
            for res in executor.map(check_port, candidates):
                if res:
                    open_targets.append(res)

        # Also check mDNS discovered devices from adb mdns services
        try:
            mdns_res = self._run("mdns", "services", timeout=2)
            if mdns_res.returncode == 0:
                for line in mdns_res.stdout.splitlines():
                    parts = line.strip().split()
                    for p in parts:
                        if ":" in p and any(char.isdigit() for char in p.split(":")[0]):
                            open_targets.append(p)
        except Exception:
            pass

        connected = []
        for target in set(open_targets):
            ok, _ = self.connect_wifi(target)
            if ok:
                connected.append(target)
                if auto_install:
                    try:
                        self.install_app(target)
                    except Exception:
                        pass

        return connected

    def disconnect_wifi(self, target: str) -> tuple[bool, str]:
        if not self.adb_path or not target:
            return False, "ADB not found or empty target"
        clean_target = target.strip()
        if ":" not in clean_target:
            clean_target = f"{clean_target}:5555"
        try:
            res = self._run("disconnect", clean_target, timeout=4)
            out = (res.stdout + " " + res.stderr).strip()
            ok = res.returncode == 0
            return ok, out
        except Exception as e:
            return False, str(e)

    def is_app_installed(self, serial: str) -> bool:
        if not self.adb_path or not serial:
            return False
        try:
            res = self._run("-s", serial, "shell", "pm", "path", PACKAGE_NAME, timeout=3)
            return res.returncode == 0 and "package:" in res.stdout
        except Exception:
            return False

    def install_app(self, serial: str, apk_path: str | None = None) -> tuple[bool, str]:
        if not self.adb_path or not serial:
            return False, "ADB not found or empty serial"

        base_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            apk_path,
            os.path.join(base_dir, "android_sender", "SmsBridgeSender-debug.apk"),
            os.path.join(base_dir, "android_sender", "app", "SmsBridgeSender-debug.apk"),
            os.path.join(getattr(sys, "_MEIPASS", base_dir), "android_sender", "SmsBridgeSender-debug.apk"),
            os.path.join(os.path.dirname(sys.executable), "android_sender", "SmsBridgeSender-debug.apk"),
            os.path.join(os.path.dirname(sys.executable), "_internal", "android_sender", "SmsBridgeSender-debug.apk"),
        ]
        apk = next((c for c in candidates if c and os.path.isfile(c)), None)
        if not apk:
            return False, f"Không tìm thấy file APK companion trong thư mục ứng dụng"
        try:
            res = self._run("-s", serial, "install", "-r", "-g", apk, timeout=60)
            out = (res.stdout + " " + res.stderr).strip()
            if res.returncode != 0 and "Success" not in out:
                if "unauthorized" in out.lower():
                    return False, f"Thiết bị đang chờ xác nhận: Vui lòng mở sáng màn hình điện thoại [{serial}], trên màn hình sẽ có hộp thoại yêu cầu 'Cho phép gỡ lỗi USB/Wi-Fi' -> Tích chọn 'Luôn cho phép' và bấm 'Cho phép' (Allow)."
                return False, f"Lỗi cài đặt APK: {out}"

            for perm in [
                "android.permission.SEND_SMS",
                "android.permission.READ_SMS",
                "android.permission.RECEIVE_SMS",
                "android.permission.READ_PHONE_STATE",
            ]:
                self._run("-s", serial, "shell", "pm", "grant", PACKAGE_NAME, perm, timeout=3)

            self._run("-s", serial, "shell", "monkey", "-p", PACKAGE_NAME, "-c", "android.intent.category.LAUNCHER", "1", timeout=3)
            return True, f"Cài đặt và cấp quyền thành công cho {serial}"
        except Exception as e:
            return False, str(e)

    def discover_wifi_devices_info(self) -> list[dict[str, object]]:
        import socket
        from concurrent.futures import ThreadPoolExecutor

        candidates = self._get_lan_ip_candidates()

        def check_port(ip):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.15)
            try:
                if s.connect_ex((ip, 5555)) == 0:
                    s.close()
                    return f"{ip}:5555"
                s.close()
            except Exception:
                pass
            return None

        open_targets = []
        with ThreadPoolExecutor(max_workers=60) as executor:
            for res in executor.map(check_port, candidates):
                if res:
                    open_targets.append(res)

        # Also check mDNS discovered devices from adb mdns services
        try:
            mdns_res = self._run("mdns", "services", timeout=2)
            if mdns_res.returncode == 0:
                for line in mdns_res.stdout.splitlines():
                    parts = line.strip().split()
                    for p in parts:
                        if ":" in p and any(char.isdigit() for char in p.split(":")[0]):
                            open_targets.append(p)
        except Exception:
            pass

        # Connect to open targets to get model & package info
        for target in set(open_targets):
            self.connect_wifi(target)

        # Re-scan devices
        scanned_devices = {d.serial: d for d in self.scan()}

        devices_info = []
        for target in set(open_targets):
            ip = target.split(":")[0]
            dev = scanned_devices.get(target)
            if dev:
                has_app = (dev.detail == "ready") or self.is_app_installed(target)
                devices_info.append({
                    "target": target,
                    "ip": ip,
                    "port": 5555,
                    "model": dev.model if dev.model != target else "Thiết bị Android",
                    "has_app": has_app,
                    "ready": dev.ready,
                    "status": "ready" if dev.ready else ("companion_not_installed" if not has_app else dev.detail),
                    "connected": True
                })
            else:
                devices_info.append({
                    "target": target,
                    "ip": ip,
                    "port": 5555,
                    "model": "Thiết bị Android",
                    "has_app": False,
                    "ready": False,
                    "status": "available",
                    "connected": False
                })

        for serial, dev in scanned_devices.items():
            if ":" in serial and not any(d["target"] == serial for d in devices_info):
                ip = serial.split(":")[0]
                has_app = (dev.detail == "ready") or self.is_app_installed(serial)
                devices_info.append({
                    "target": serial,
                    "ip": ip,
                    "port": 5555,
                    "model": dev.model if dev.model != serial else "Thiết bị Android",
                    "has_app": has_app,
                    "ready": dev.ready,
                    "status": "ready" if dev.ready else ("companion_not_installed" if not has_app else dev.detail),
                    "connected": True
                })

        # Also detect active ARP clients (e.g. phones on Windows Mobile Hotspot 192.168.137.x)
        try:
            res_arp = subprocess.run(
                ["arp", "-a"],
                capture_output=True, text=True, timeout=2,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if platform.system() == "Windows" else 0
            )
            for line in res_arp.stdout.splitlines():
                m = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+([0-9a-fA-F-]{17})", line)
                if m:
                    client_ip = m.group(1)
                    if not client_ip.startswith(("127.", "224.", "239.", "255.")) and not client_ip.endswith(".255") and not client_ip.endswith(".1"):
                        if not any(d.get("ip") == client_ip for d in devices_info):
                            # Test if responsive
                            s_test = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            s_test.settimeout(0.2)
                            is_open_5555 = (s_test.connect_ex((client_ip, 5555)) == 0)
                            s_test.close()
                            if not is_open_5555:
                                devices_info.append({
                                    "target": f"{client_ip}:5555",
                                    "ip": client_ip,
                                    "port": 5555,
                                    "model": f"Điện thoại trên mạng Hotspot/Wi-Fi ({client_ip})",
                                    "has_app": False,
                                    "ready": False,
                                    "status": "port_closed",
                                    "connected": False,
                                    "message": f"Phát hiện điện thoại tại {client_ip} nhưng cổng ADB 5555 chưa mở. Hãy bật 'Gỡ lỗi không dây' trên điện thoại hoặc cắm cáp USB 1 lần."
                                })
        except Exception:
            pass

        # Cloud / Wi-Fi App devices (zero cable / no ADB needed)
        for cdev in self.get_active_cloud_devices():
            devices_info.insert(0, {
                "target": f"cloud:{cdev['id']}",
                "ip": cdev.get("ip", ""),
                "port": 8765,
                "model": f"Wi-Fi App: {cdev['id']}",
                "has_app": True,
                "ready": True,
                "status": "ready",
                "connected": True,
                "message": "Đang kết nối qua Wi-Fi App (100% không dây, không cần cáp USB)",
            })

        return devices_info


    _TOKEN_TTL = 600  # 10 phút

    def _token(self, serial: str) -> str:
        cached = self._token_cache.get(serial)
        if cached and time.time() - cached[1] < self._TOKEN_TTL:
            return cached[0]
        try:
            result = self._run(
                "-s", serial, "exec-out", "run-as", PACKAGE_NAME,
                "cat", "files/bridge_token",
                timeout=3,
            )
            if result.returncode == 0 and result.stdout.strip():
                token = result.stdout.strip()
                self._token_cache[serial] = (token, time.time())
                return token
        except Exception:
            pass
        return "SmsBridge_2026_Direct_Token"

    def send(
        self,
        serial: str,
        phone: str,
        message: str,
        subscription_id: int = -1,
    ) -> tuple[bool, str, str]:
        if serial.startswith("cloud:") or serial in self.cloud_devices:
            dev_id = serial[6:] if serial.startswith("cloud:") else serial
            job_id = self.enqueue_cloud_job(dev_id, phone, message, subscription_id=subscription_id)
            return True, job_id, f"Đã đưa tin nhắn vào hàng đợi Wi-Fi App ({dev_id})"

        job_id = uuid.uuid4().hex
        token = self._token(serial)
        # Encode UTF-8 message to Base64 to prevent shell word splitting and encoding loss
        message_b64 = base64.b64encode(message.encode("utf-8")).decode("ascii").replace("\n", "").replace("\r", "")

        def do_broadcast():
            return self._run(
                "-s", serial, "shell", "am", "broadcast",
                "-n", RECEIVER_NAME,
                "-a", f"{PACKAGE_NAME}.SEND_SMS",
                "--es", "token", token,
                "--es", "job_id", job_id,
                "--es", "phone", phone,
                "--es", "message_b64", message_b64,
                "--ei", "subscription_id", str(subscription_id),
                timeout=12,
            )

        try:
            result = do_broadcast()
        except Exception as first_err:
            # If WiFi device dropped, try reconnecting once
            if ":" in serial:
                self.connect_wifi(serial)
                try:
                    result = do_broadcast()
                except Exception as second_err:
                    return False, job_id, f"Lỗi kết nối Wi-Fi: {second_err}"
            else:
                return False, job_id, str(first_err)

        # Check if result indicates device offline on Wi-Fi
        detail = (result.stdout + " " + result.stderr).strip()
        if (result.returncode != 0 or "device offline" in detail.lower() or "closed" in detail.lower()) and ":" in serial:
            self.connect_wifi(serial)
            try:
                result = do_broadcast()
                detail = (result.stdout + " " + result.stderr).strip()
            except Exception:
                pass

        accepted = result.returncode == 0 and "Broadcast completed" in result.stdout
        return accepted, job_id, detail

    def get_device_sims(self, serial: str) -> list[dict[str, Any]]:
        if not serial:
            return []
        if serial.startswith("cloud:"):
            dev_id = serial[len("cloud:"):]
            with self.cloud_lock:
                entry = self.cloud_devices.get(dev_id, {})
                cloud_sims = list(entry.get("sims") or [])
                if cloud_sims:
                    return cloud_sims
                return [{
                    "subscription_id": -1,
                    "slot_index": 0,
                    "carrier_name": "SIM mặc định",
                    "display_name": "SIM 1 (Mặc định)",
                    "in_service": True,
                }]

        if not self.adb_path:
            return []

        # Strategy 1: Read companion app files/sim_status.json
        def read_json() -> list[dict[str, Any]] | None:
            try:
                res = self._run("-s", serial, "exec-out", "run-as", PACKAGE_NAME, "cat", "files/sim_status.json", timeout=3)
                if res.returncode != 0 or not res.stdout.strip():
                    res = self._run("-s", serial, "shell", "run-as", PACKAGE_NAME, "cat", "files/sim_status.json", timeout=3)
                if res.returncode == 0 and res.stdout.strip():
                    data = json.loads(res.stdout)
                    subs = data.get("subscriptions", [])
                    if isinstance(subs, list) and subs:
                        return subs
            except Exception:
                pass
            return None

        sims = read_json()
        if not sims:
            try:
                self._run(
                    "-s", serial, "shell", "am", "broadcast",
                    "-n", RECEIVER_NAME,
                    "-a", f"{PACKAGE_NAME}.SIM_STATUS",
                    "--es", "token", self._token(serial),
                    timeout=4,
                )
                time.sleep(0.3)
                sims = read_json()
            except Exception:
                pass

        # Strategy 2: Query Android TelephonyProvider database (Works across Vivo, Oppo, Xiaomi, Samsung, etc.)
        if not sims:
            try:
                q_res = self._run(
                    "-s", serial, "shell", "content", "query",
                    "--uri", "content://telephony/siminfo",
                    timeout=3,
                )
                if q_res.returncode == 0 and q_res.stdout:
                    found: dict[int, dict[str, Any]] = {}
                    for line in q_res.stdout.splitlines():
                        if "Row:" not in line:
                            continue
                        sub_id_match = re.search(r'\b_id=(\d+)', line)
                        slot_match = re.search(r'\b(?:sim_id|slot)=(\d+)', line)
                        disp_match = re.search(r'\bdisplay_name=([^,]+)', line)
                        carrier_match = re.search(r'\bcarrier_name=([^,]+)', line)
                        if sub_id_match:
                            sub_id = int(sub_id_match.group(1))
                            slot_idx = int(slot_match.group(1)) if slot_match else len(found)
                            if slot_idx < 0:
                                continue
                            disp_name = disp_match.group(1).strip() if disp_match else f"SIM {slot_idx + 1}"
                            c_name = carrier_match.group(1).strip() if carrier_match else disp_name
                            if c_name.lower() in ("null", "unknown", ""):
                                c_name = disp_name if disp_name.lower() not in ("null", "unknown", "") else f"SIM {slot_idx + 1}"
                            found[slot_idx] = {
                                "subscription_id": sub_id,
                                "slot_index": slot_idx,
                                "carrier_name": c_name,
                                "display_name": disp_name,
                                "in_service": True,
                            }
                    if found:
                        sims = [found[k] for k in sorted(found.keys())]
            except Exception:
                pass

        # Strategy 3: Flexible dumpsys isub parser
        if not sims:
            try:
                isub_res = self._run("-s", serial, "shell", "dumpsys", "isub", timeout=3)
                if isub_res.returncode == 0 and isub_res.stdout:
                    found: dict[int, dict[str, Any]] = {}
                    for chunk in re.split(r'[{}]', isub_res.stdout):
                        if "id=" in chunk and "simSlotIndex=" in chunk:
                            id_m = re.search(r'\bid=(\d+)', chunk)
                            slot_m = re.search(r'\bsimSlotIndex=(\d+)', chunk)
                            disp_m = re.search(r'\bdisplayName=([^\s,}]+)', chunk)
                            carrier_m = re.search(r'\bcarrierName=([^\s,}]+)', chunk)
                            if id_m and slot_m:
                                sub_id = int(id_m.group(1))
                                slot_idx = int(slot_m.group(1))
                                disp_name = disp_m.group(1).strip() if disp_m else f"SIM {slot_idx + 1}"
                                c_name = carrier_m.group(1).strip() if carrier_m else disp_name
                                if slot_idx not in found or sub_id >= found[slot_idx]["subscription_id"]:
                                    found[slot_idx] = {
                                        "subscription_id": sub_id,
                                        "slot_index": slot_idx,
                                        "carrier_name": c_name or f"SIM {slot_idx + 1}",
                                        "display_name": disp_name or f"SIM {slot_idx + 1}",
                                        "in_service": True,
                                    }
                    if found:
                        sims = [found[k] for k in sorted(found.keys())]
            except Exception:
                pass

        # Strategy 4: System properties (gsm.operator.alpha, gsm.sim.operator.alpha, multisim.config)
        if not sims:
            try:
                prop_res = self._run("-s", serial, "shell", "getprop", timeout=3)
                if prop_res.returncode == 0 and prop_res.stdout:
                    op_match = re.search(r'\[gsm\.operator\.alpha\]:\s*\[(.*?)\]', prop_res.stdout) or \
                               re.search(r'\[gsm\.sim\.operator\.alpha\]:\s*\[(.*?)\]', prop_res.stdout)
                    multi_match = re.search(r'\[persist\.radio\.multisim\.config\]:\s*\[(.*?)\]', prop_res.stdout)
                    if op_match:
                        raw_names = [n.strip() for n in op_match.group(1).split(",") if n.strip()]
                        if raw_names:
                            sims = []
                            for idx, name in enumerate(raw_names):
                                sims.append({
                                    "subscription_id": idx + 1,
                                    "slot_index": idx,
                                    "carrier_name": name,
                                    "display_name": name,
                                    "in_service": True,
                                })
                    elif multi_match and "ds" in multi_match.group(1).lower():
                        sims = [
                            {"subscription_id": 1, "slot_index": 0, "carrier_name": "SIM 1", "display_name": "SIM 1", "in_service": True},
                            {"subscription_id": 2, "slot_index": 1, "carrier_name": "SIM 2", "display_name": "SIM 2", "in_service": True},
                        ]
            except Exception:
                pass

        # Fallback for single-SIM or unidentified devices so UI always displays ready status clearly
        if not sims:
            sims = [{
                "subscription_id": -1,
                "slot_index": 0,
                "carrier_name": "SIM mặc định",
                "display_name": "SIM 1 (Mặc định)",
                "in_service": True,
            }]

        return sims

    def active_subscription_ids(self, serial: str) -> list[int]:
        sims = self.get_device_sims(serial)
        subs = [
            int(item["subscription_id"])
            for item in sims
            if item.get("in_service") is not False and int(item.get("subscription_id", -1)) >= 0
        ]
        # Báo các SIM bị loại do không in_service (giữ nguyên filter: gửi qua SIM mất sóng sẽ lỗi)
        skipped = [
            int(item.get("subscription_id", -1))
            for item in sims
            if item.get("in_service") is False
        ]
        if skipped:
            _log("WARN", f"SIM bị loại khỏi kênh gửi trên {serial}: subscription {skipped} (không in_service)")
        return subs if subs else [-1]

    def events(self, serial: str) -> list[dict[str, object]]:
        if not self.adb_path:
            return []
        try:
            result = self._run(
                "-s", serial, "exec-out", "run-as", PACKAGE_NAME,
                "cat", "files/events.jsonl",
                timeout=4,
            )
            if result.returncode != 0 or not result.stdout.strip():
                result = self._run(
                    "-s", serial, "shell", "run-as", PACKAGE_NAME,
                    "cat", "files/events.jsonl",
                    timeout=4,
                )
            if result.returncode != 0 or not result.stdout.strip():
                return []
            events: list[dict[str, object]] = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and event.get("job_id"):
                    events.append(event)
            return events
        except Exception:
            return []

    @staticmethod
    def summarize_events(events: list[dict[str, object]]) -> dict[str, JobSummary]:
        jobs: dict[str, list[dict[str, object]]] = {}
        for event in events:
            jobs.setdefault(str(event.get("job_id", "")), []).append(event)

        summaries: dict[str, JobSummary] = {}
        for job_id, job_events in jobs.items():
            if not job_id:
                continue
            phone = next((str(e.get("phone", "")) for e in job_events if e.get("phone")), "")
            message = next((str(e.get("message", "")) for e in job_events if e.get("message")), "")
            expected = max(int(event.get("part_count", 1)) for event in job_events)
            sent = {
                int(event.get("part_index", 0))
                for event in job_events
                if event.get("stage") == "SENT" and int(event.get("result_code", 0)) == -1
            }
            delivered = {
                int(event.get("part_index", 0))
                for event in job_events
                if event.get("stage") == "DELIVERED" and int(event.get("result_code", 0)) == -1
            }
            failed_event = next(
                (
                    event
                    for event in job_events
                    if event.get("is_success") is False
                    or event.get("stage") == "FAILED"
                    or (event.get("stage") == "SENT" and int(event.get("result_code", 0)) != -1)
                    or (event.get("stage") == "DELIVERED" and int(event.get("result_code", 0)) != -1)
                ),
                None,
            )
            if failed_event:
                err_text = str(failed_event.get("error") or failed_event.get("result_code") or "Lỗi gửi tin từ nhà mạng")
                status = "FAILED"
                detail = f"Lỗi nhà mạng: {err_text}"
            elif len(delivered) >= expected:
                status = "DELIVERED"
                detail = "Đã giao đến người nhận"
            elif len(sent) >= expected:
                status = "SUBMITTED"
                detail = "Đã nộp cho nhà mạng, chờ báo cáo giao (chưa xác nhận)"
            else:
                status = "ANDROID_QUEUED"
                detail = "Đang gửi..."

            summaries[job_id] = JobSummary(status, detail, phone=phone, message=message)
        return summaries
