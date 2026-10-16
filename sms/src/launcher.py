import subprocess
import sys
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import random
import csv
import json
import io
import sqlite3
import signal
import socket
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from threading import Timer

CURRENT_VERSION = "1.1.0"
VERSION_URL = "https://drive.google.com/uc?id=1ZA3BBK7KmiaJPBkyVwICrJflC2Ku8-qo"
LICENSE_URL = "https://drive.google.com/uc?export=download&id=1F92hsH7P4qPSi99s3eYq1MQLft-hicfG"
CONFIG_FILE = ".sys_config"

import pandas as pd
import serial
import serial.tools.list_ports
from flask import Flask, Response, jsonify, request, send_file
from android_transport import AndroidTransport, resolve_adb_path

import os
import uuid
import hashlib
import requests
import platform
import stat
import shutil
from glob import glob


def unlock_file(path):
    try:
        if platform.system() == "Windows":
            kwargs = {"shell": True, "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
            subprocess.call(f'attrib -h -s -r "{path}"', **kwargs)
        elif platform.system() == "Darwin":
            subprocess.call(f'chflags nouchg,nohidden "{path}" 2>/dev/null', shell=True)
    except Exception:
        pass


def force_delete(path):
    try:
        if not os.path.exists(path):
            return
        unlock_file(path)
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        except Exception:
            pass
        time.sleep(0.1)
        os.remove(path)
    except Exception as e:
        print("Delete note:", e)


def get_board_serial():
    try:
        kwargs = {"shell": True}
        if platform.system() == "Windows":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        output = subprocess.check_output(
            "wmic baseboard get serialnumber",
            **kwargs
        ).decode()
        lines = output.strip().split("\n")
        if len(lines) >= 2:
            serial_no = lines[1].strip()
            if serial_no and serial_no != "To be filled by O.E.M.":
                return serial_no
        return "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def get_machine_serial():
    system = platform.system()
    if system == "Windows":
        serial_no = get_board_serial()
        if serial_no != "UNKNOWN":
            return serial_no
        try:
            kwargs = {"shell": True}
            if platform.system() == "Windows":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            output = subprocess.check_output(
                "wmic csproduct get uuid",
                **kwargs
            ).decode()
            return output.strip().split("\n")[1].strip()
        except Exception:
            return "UNKNOWN"
    elif system == "Darwin":
        try:
            output = subprocess.check_output(
                "ioreg -l | grep IOPlatformSerialNumber",
                shell=True
            ).decode()
            return output.split('"')[-2].strip()
        except Exception:
            return "UNKNOWN"
    else:
        try:
            return open("/etc/machine-id").read().strip()
        except Exception:
            return "UNKNOWN"


def hide_file(path):
    try:
        if os.name == "nt":
            kwargs = {}
            if platform.system() == "Windows":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            subprocess.call(["attrib", "+H", path], **kwargs)
    except Exception:
        pass


def lock_file(path):
    try:
        if os.name == "nt":
            subprocess.call(f'attrib +r "{path}"', shell=True)
    except Exception:
        pass


def create_config(serial_no):
    try:
        unlock_file(CONFIG_FILE)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write(serial_no)
        hide_file(CONFIG_FILE)
    except Exception as e:
        print("Config write note:", e)


def read_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None


def check_license():
    serial_no = get_machine_serial()
    if os.path.exists(CONFIG_FILE):
        saved = read_config()
        if saved == serial_no:
            return True
        force_delete(CONFIG_FILE)

    try:
        r = requests.get(LICENSE_URL, timeout=10)
        data = r.json()
        devices = data.get("devices", [])
        if serial_no not in devices:
            print("\n====================================")
            print("❌ TOOL CHƯA ĐƯỢC KÍCH HOẠT")
            print("Vui lòng gửi mã sau cho admin:\n")
            print("MACHINE CODE:", serial_no, flush=True)
            print("====================================\n")
            input("Nhấn ENTER để thoát...")
            return False

        create_config(serial_no)
        print("✅ License activated")
        return True
    except Exception as e:
        if os.path.exists(CONFIG_FILE) and read_config() == serial_no:
            return True
        print("❌ License check failed:", e)
        input("Nhấn ENTER để thoát...")
        return False


if getattr(sys, "frozen", False):
    BUNDLE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    BASE = os.path.dirname(os.path.abspath(sys.executable))
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
    BASE = BUNDLE_DIR

app = Flask(
    __name__,
    template_folder=os.path.join(BUNDLE_DIR, "templates"),
)

MSG_DIR = os.path.join(BASE, "messages")
DATA_DIR = os.path.join(BASE, "data")
DATA_PATH = os.path.join(DATA_DIR, "contacts.xlsx")
HISTORY_PATH = os.path.join(DATA_DIR, "sms_history.sqlite3")
ZALO_PROFILE_DIR = os.path.join(DATA_DIR, "zalo_profiles")
EXCEL_PATH = os.path.join(BASE, "dulieu.xlsx")

for d in [MSG_DIR, DATA_DIR, ZALO_PROFILE_DIR]:
    os.makedirs(d, exist_ok=True)

stats = {"total": 0, "sent": 0, "success": 0, "running": False, "active_workers": 0}
logs = []
modems = []
android_transport = AndroidTransport()
android_devices = []
failed_rows = []
modem_signals = {}
lock = threading.Lock()
log_version = 0
sent_rows_success = []
stop_event = threading.Event()
campaign_generation = 0
campaign_dispatched_phones = set()
campaign_dispatched_rows = set()
campaign_excel_lock = threading.Lock()
CAMPAIGN_SENT_COLUMN = "ĐÃ GỬI THÀNH CÔNG"
CAMPAIGN_SENT_AT_COLUMN = "THỜI GIAN GỬI THÀNH CÔNG"
port_to_imei = {}
imei_locks = {}
modem_locks = {}


class Campaign:
    def __init__(self, campaign_id, name, rows, templates, delay_min=5, delay_max=15, delay_unit="minutes", device_mode="ALL", ignore_cooldown=False, dedup_excel=True, excel_path=None):
        self.id = campaign_id
        self.name = name or f"Chiến dịch {campaign_id[:6]}"
        self.rows = list(rows)
        self.pending_rows = list(rows)
        self.templates = list(templates)
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.delay_unit = delay_unit
        self.device_mode = device_mode
        self.ignore_cooldown = ignore_cooldown
        self.dedup_excel = dedup_excel
        self.excel_path = excel_path or EXCEL_PATH
        self.status = "QUEUED"  # QUEUED, RUNNING, COMPLETED, STOPPED
        self.total = len(rows)
        self.sent = 0
        self.success = 0
        self.failed = 0
        self.unconfirmed = 0
        self.created_at = datetime.now().isoformat(timespec="seconds")
        self.dispatched_phones = set()
        self.dispatched_rows = set()
        self.lock = threading.Lock()

    def to_dict(self):
        with self.lock:
            return {
                "id": self.id,
                "name": self.name,
                "status": self.status,
                "total": self.total,
                "sent": self.sent,
                "success": self.success,
                "failed": self.failed,
                "unconfirmed": self.unconfirmed,
                "created_at": self.created_at,
            }

    def pop_next_row(self):
        with self.lock:
            while self.pending_rows and self.status in {"QUEUED", "RUNNING"}:
                self.status = "RUNNING"
                r = self.pending_rows.pop(0)
                phone = normalize_phone(r.get("ĐT") or r.get("ĐIỆN THOẠI") or "")
                if not phone:
                    continue
                if self.dedup_excel:
                    if phone in self.dispatched_phones:
                        continue
                    self.dispatched_phones.add(phone)
                else:
                    row_idx = r.get("__excel_index__")
                    if row_idx is not None and row_idx in self.dispatched_rows:
                        continue
                    if row_idx is not None:
                        self.dispatched_rows.add(row_idx)
                return r
            if not self.pending_rows and self.status == "RUNNING":
                self.status = "COMPLETED"
            return None

    def stop(self):
        with self.lock:
            if self.status in {"QUEUED", "RUNNING"}:
                self.status = "STOPPED"


class CampaignManager:
    def __init__(self):
        self.campaigns: list[Campaign] = []
        self.lock = threading.Lock()
        self.rr_index = 0

    def enqueue(self, campaign: Campaign):
        with self.lock:
            self.campaigns.append(campaign)
            stop_event.clear()
        self.ensure_running()

    def list_campaigns(self):
        with self.lock:
            return [c.to_dict() for c in self.campaigns]

    def get_campaign(self, campaign_id: str) -> Campaign | None:
        with self.lock:
            for c in self.campaigns:
                if c.id == campaign_id:
                    return c
        return None

    def get_next_row_rr(self) -> tuple[Campaign | None, dict | None]:
        with self.lock:
            active = [c for c in self.campaigns if c.status in {"QUEUED", "RUNNING"}]
            if not active:
                return None, None
            for _ in range(len(active)):
                self.rr_index = self.rr_index % len(active)
                camp = active[self.rr_index]
                self.rr_index = (self.rr_index + 1) % len(active)
                row = camp.pop_next_row()
                if row is not None:
                    return camp, row
            return None, None

    def stop_all(self):
        with self.lock:
            for c in self.campaigns:
                c.stop()
        stop_event.set()
        with lock:
            stats["running"] = False
            stats["active_workers"] = 0

    def has_active_campaigns(self) -> bool:
        with self.lock:
            return any(c.status in {"QUEUED", "RUNNING"} for c in self.campaigns)

    def check_finished(self):
        with self.lock:
            active = [c for c in self.campaigns if c.status in {"QUEUED", "RUNNING"}]
            if not active:
                with lock:
                    stats["running"] = False
                    stats["active_workers"] = 0

    def ensure_running(self):
        channels = get_active_hardware_channels("ALL")
        with lock:
            if stats["running"]:
                return
            if not channels:
                add_log("WARN", "SYSTEM", "SMS", "Không có kênh phần cứng sẵn sàng (Android app/USB modem). Chiến dịch sẽ chờ thiết bị được kết nối.")
                return
            stats["running"] = True
            stats["active_workers"] = len(channels)
        stop_event.clear()
        for transport, target in channels:
            threading.Thread(
                target=self._worker_loop,
                args=(transport, target),
                daemon=True,
            ).start()

    def _worker_loop(self, transport, target):
        try:
            while not stop_event.is_set():
                camp, row = self.get_next_row_rr()
                if not camp or not row:
                    time.sleep(0.5)
                    if not self.has_active_campaigns():
                        break
                    continue

                dispatch_channel_row(transport, target, camp, row)

                delay_min = camp.delay_min
                delay_max = camp.delay_max
                delay_unit = camp.delay_unit
                min_sec = int(delay_min * 60) if delay_unit == "minutes" else int(delay_min)
                max_sec = int(delay_max * 60) if delay_unit == "minutes" else int(delay_max)
                if max_sec < min_sec:
                    max_sec = min_sec + 5
                delay = random.uniform(max(1, min_sec), max(min_sec + 1, max_sec))
                if stop_event.wait(timeout=delay):
                    break
        finally:
            with lock:
                stats["active_workers"] = max(0, stats["active_workers"] - 1)
            self.check_finished()


campaign_manager = CampaignManager()


def get_active_hardware_channels(device_mode="ALL"):
    ready_android = [device for device in android_devices if device.ready]
    workers = []
    if device_mode not in ["ALL", "ANDROID", "USB_MODEM"]:
        target_serial = device_mode
        chosen_sub_id = None
        if ":" in device_mode and not device_mode.startswith("COM"):
            parts = device_mode.rsplit(":", 1)
            if parts[1].lstrip("-").isdigit():
                target_serial = parts[0]
                chosen_sub_id = int(parts[1])
        for dev in ready_android:
            if dev.serial == target_serial:
                if chosen_sub_id is not None:
                    workers.append(("ANDROID", (dev, chosen_sub_id)))
                else:
                    subscription_ids = android_transport.active_subscription_ids(dev.serial)
                    channels = subscription_ids or [-1]
                    workers.extend([("ANDROID", (dev, s_id)) for s_id in channels])
        if not workers:
            for modem in modems:
                if modem.port == target_serial or getattr(modem, "serial", "") == target_serial:
                    workers.append(("USB_MODEM", modem))

    if not workers and device_mode in ["ALL", "ANDROID"]:
        for device in ready_android:
            subscription_ids = android_transport.active_subscription_ids(device.serial)
            channels = subscription_ids or [-1]
            workers.extend([("ANDROID", (device, subscription_id)) for subscription_id in channels])
    if not workers and device_mode in ["ALL", "USB_MODEM"]:
        workers.extend([("USB_MODEM", modem) for modem in modems])

    return workers


def dispatch_channel_row(transport, target, camp: Campaign, row: dict):
    phone = normalize_phone(row.get("ĐT") or row.get("ĐIỆN THOẠI") or "")
    if not phone:
        return

    if not camp.ignore_cooldown:
        recent = check_recent_successful_send(phone, cooldown_hours=24)
        if recent:
            add_log("WARN", phone, "SYSTEM", f"⏩ Bỏ qua {phone}: Đã gửi thành công gần đây")
            mark_campaign_row_sent(row.get("__excel_index__"), camp.excel_path)
            return

    name = str(row.get("TÊN", ""))
    gender = row.get("GIỚI TÍNH")
    msg, used_file = get_final_message(name, camp.templates, gender=gender, row=row)

    if transport == "USB_MODEM":
        ser = target
        msg = normalize_message_for_modem(msg)
        imei = port_to_imei.get(ser.port, ser.port)
        history_id = create_history(phone, name, ser.port, used_file, msg, campaign_row=row.get("__excel_index__"))
        with imei_locks.setdefault(imei, threading.Lock()):
            ok, modem_response = send_sms_modem(ser, phone, msg)
        status = "SUBMITTED" if ok else "FAILED"
        if ok:
            update_history_ref(history_id, modem_response.get("message_ref"), modem_response.get("response", ""))
            with camp.lock:
                camp.sent += 1
            with lock:
                stats["sent"] += 1
        else:
            update_history(history_id, status, modem_response)
            with camp.lock:
                camp.sent += 1
                camp.failed += 1
            with lock:
                stats["sent"] += 1
                failed_rows.append(row)
        add_log("INFO" if ok else "FAIL", phone, ser.port, f"{status} [{used_file}] {msg}")

    elif transport == "ANDROID":
        device, subscription_id = target
        dev_sim_label = f"{device.serial}" + (f" [SIM {subscription_id}]" if subscription_id >= 0 else "")
        history_id = create_history(
            phone, name, dev_sim_label, used_file, msg,
            transport="ANDROID", device_id=device.serial,
            campaign_row=row.get("__excel_index__"),
        )
        try:
            ok, job_id, detail = android_transport.send(device.serial, phone, msg, subscription_id=subscription_id)
        except Exception as error:
            ok, job_id, detail = False, "", str(error)

        if not ok:
            update_history(history_id, "FAILED", detail)
            with camp.lock:
                camp.sent += 1
                camp.failed += 1
            with lock:
                stats["sent"] += 1
                failed_rows.append(row)
            add_log("FAIL", phone, dev_sim_label, f"❌ KHÔNG THỂ GỬI [{used_file}] {detail}")
            return

        with get_db() as conn:
            conn.execute(
                """
                UPDATE sms_history
                SET status = 'ANDROID_QUEUED', external_job_id = ?, modem_response = ?, updated_at = ?
                WHERE id = ?
                """,
                (job_id, detail, datetime.now().isoformat(timespec="seconds"), history_id),
            )
        add_log("INFO", phone, dev_sim_label, f"⏳ ĐANG GỬI [{used_file}] {phone}...")

        carrier_status = None
        carrier_detail = ""
        wait_start = time.time()
        timeout_sec = 22.0 if device.serial.startswith("cloud:") else 15.0

        while time.time() - wait_start < timeout_sec:
            if stop_event.is_set():
                break
            if stop_event.wait(timeout=1.0):
                break
            if not device.serial.startswith("cloud:"):
                try:
                    poll_android_events()
                except Exception:
                    pass
            with get_db() as conn:
                conn.row_factory = sqlite3.Row
                h_row = conn.execute(
                    "SELECT status, delivery_status, modem_response FROM sms_history WHERE external_job_id = ?",
                    (job_id,),
                ).fetchone()
                if h_row:
                    st = h_row["status"]
                    if st == "DELIVERED":
                        carrier_status = "DELIVERED"
                        carrier_detail = h_row["delivery_status"] or "Đã giao"
                        break
                    elif st == "FAILED":
                        carrier_status = "FAILED"
                        carrier_detail = h_row["delivery_status"] or "Lỗi gửi"
                        break
                    elif st in {"SUBMITTED", "SENT", "ANDROID_ACCEPTED"}:
                        pass

        if carrier_status == "DELIVERED":
            with camp.lock:
                camp.sent += 1
                camp.success += 1
            with lock:
                stats["sent"] += 1
                sent_rows_success.append(row)
            add_log("SUCCESS", phone, dev_sim_label, f"✅ ĐÃ GIAO THÀNH CÔNG [{used_file}] {phone}")
        elif carrier_status == "FAILED":
            with camp.lock:
                camp.sent += 1
                camp.failed += 1
            with lock:
                stats["sent"] += 1
                failed_rows.append(row)
            add_log("FAIL", phone, dev_sim_label, f"❌ NHÀ MẠNG BÁO LỖI [{used_file}] {phone}: {carrier_detail}")
        else:
            # Timeout without DELIVERED -> UNCONFIRMED, no retry!
            update_android_status(device.serial, job_id, "UNCONFIRMED", "Quá thời gian chờ phản hồi DELIVERED từ nhà mạng", phone=phone, message=msg)
            with camp.lock:
                camp.sent += 1
                camp.unconfirmed += 1
            with lock:
                stats["sent"] += 1
                failed_rows.append(row)
            add_log("WARN", phone, dev_sim_label, f"⚠️ CHƯA XÁC NHẬN GIAO [{used_file}] Không nhận được báo cáo giao (UNCONFIRMED) cho {phone}")



def detect_adb_status():
    adb_path = android_transport.adb_path or resolve_adb_path()
    if not adb_path:
        return {
            "available": False,
            "status": "missing",
            "message": "ADB not found on this machine",
            "devices": [],
        }
    try:
        result = subprocess.run(
            [adb_path, "devices", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if platform.system() == "Windows" else 0,
        )
        devices = [line.split()[0] for line in result.stdout.splitlines()[1:] if len(line.split()) >= 2]
        if result.returncode != 0:
            return {
                "available": False,
                "status": "error",
                "message": (result.stderr or result.stdout or "ADB command failed").strip(),
                "devices": devices,
            }
        return {
            "available": True,
            "status": "ready",
            "message": f"ADB ready: {adb_path}",
            "devices": devices,
        }
    except Exception as error:
        return {
            "available": False,
            "status": "error",
            "message": str(error),
            "devices": [],
        }

def find_browser_for_zalo():
    env_browser = os.environ.get("SMS_BROWSER_PATH", "")
    candidates = [env_browser]
    if platform.system() == "Windows":
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        candidates.extend([
            os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(local_app_data, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(program_files, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(program_files_x86, "Microsoft", "Edge", "Application", "msedge.exe"),
        ])
    elif platform.system() == "Darwin":
        candidates.extend([
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ])
    else:
        candidates.extend(["google-chrome", "chromium", "microsoft-edge"])
    for candidate in candidates:
        if candidate and (os.path.isfile(candidate) or shutil.which(candidate)):
            return candidate
    return None

def open_zalo_profile(slot):
    try:
        slot_num = int(slot)
    except (TypeError, ValueError):
        return False, "Slot không hợp lệ"
    if slot_num not in [1, 2, 3, 4]:
        return False, "Chỉ hỗ trợ slot 1-4"
    browser = find_browser_for_zalo()
    if not browser:
        return False, "Không tìm thấy Chrome hoặc Edge để mở Zalo profile riêng"
    profile_dir = os.path.join(ZALO_PROFILE_DIR, f"zalo_{slot_num:02d}")
    os.makedirs(profile_dir, exist_ok=True)
    width, height = 720, 620
    left = 40 + ((slot_num - 1) % 2) * width
    top = 40 + ((slot_num - 1) // 2) * height
    cmd = [
        browser,
        "--new-window",
        "--app=https://chat.zalo.me/",
        f"--user-data-dir={profile_dir}",
        f"--window-size={width},{height}",
        f"--window-position={left},{top}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    subprocess.Popen(cmd)
    return True, f"Đã mở Zalo slot {slot_num}"

def reset_zalo_profile(slot):
    try:
        slot_num = int(slot)
    except (TypeError, ValueError):
        return False, "Slot không hợp lệ"
    if slot_num not in [1, 2, 3, 4]:
        return False, "Chỉ hỗ trợ slot 1-4"
    profile_dir = os.path.join(ZALO_PROFILE_DIR, f"zalo_{slot_num:02d}")
    if os.path.isdir(profile_dir):
        shutil.rmtree(profile_dir, ignore_errors=True)
    return True, f"Đã xóa phiên Zalo slot {slot_num}"

    try:
        kwargs = {
            "capture_output": True,
            "text": True,
            "timeout": 15,
            "check": False,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if platform.system() == "Windows":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        result = subprocess.run(
            [adb_path, "devices", "-l"],
            **kwargs
        )
    except Exception as error:
        return {
            "available": True,
            "status": "error",
            "message": str(error),
            "devices": [],
        }

    devices = []
    status = "missing"
    message = "No Android device detected"

    for line in result.stdout.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 2:
            continue
        serial_id, state = fields[0], fields[1]
        model = next((item.split(":", 1)[1] for item in fields if item.startswith("model:")), serial_id)
        devices.append({"serial": serial_id, "state": state, "model": model})
        if state == "device":
            status = "device"
            message = "ADB ready"
        elif state == "unauthorized" and status != "device":
            status = "unauthorized"
            message = "USB debugging authorization required"
        elif status == "missing":
            status = state
            message = f"ADB state: {state}"

    if not devices and result.returncode != 0:
        status = "error"
        message = (result.stderr or result.stdout or "adb devices failed").strip()

    return {
        "available": True,
        "status": status,
        "message": message,
        "devices": devices,
    }


from contextlib import contextmanager

@contextmanager
def get_db():
    conn = sqlite3.connect(HISTORY_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_history_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sms_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                phone TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                modem_port TEXT NOT NULL,
                template_name TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL,
                modem_response TEXT NOT NULL DEFAULT '',
                message_ref INTEGER,
                delivery_status TEXT NOT NULL DEFAULT '',
                transport TEXT NOT NULL DEFAULT 'USB_MODEM',
                device_id TEXT NOT NULL DEFAULT '',
                external_job_id TEXT NOT NULL DEFAULT ''
                ,campaign_row INTEGER
            )
        """)
        for column_sql in [
            "ALTER TABLE sms_history ADD COLUMN message_ref INTEGER",
            "ALTER TABLE sms_history ADD COLUMN delivery_status TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE sms_history ADD COLUMN transport TEXT NOT NULL DEFAULT 'USB_MODEM'",
            "ALTER TABLE sms_history ADD COLUMN device_id TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE sms_history ADD COLUMN external_job_id TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE sms_history ADD COLUMN campaign_row INTEGER",
        ]:
            try:
                conn.execute(column_sql)
            except sqlite3.OperationalError:
                pass


def create_history(
    phone,
    customer_name,
    modem_port,
    template_name,
    message,
    transport="USB_MODEM",
    device_id="",
    external_job_id="",
    campaign_row=None,
):
    now = datetime.now().isoformat(timespec="seconds")
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO sms_history (
                created_at, updated_at, phone, customer_name, modem_port,
                template_name, message, status, transport, device_id, external_job_id,
                campaign_row
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'SENDING', ?, ?, ?, ?)
            """,
            (
                now, now, phone, customer_name, modem_port, template_name, message,
                transport, device_id, external_job_id, campaign_row,
            ),
        )
        return cursor.lastrowid


def update_history(history_id, status, modem_response):
    with get_db() as conn:
        row = conn.execute("SELECT status FROM sms_history WHERE id = ?", (history_id,)).fetchone()
        if row and row[0] == "FAILED" and status != "FAILED":
            # FAILED is sticky, never overwritten
            return
        conn.execute(
            """
            UPDATE sms_history
            SET updated_at = ?, status = ?, modem_response = ?
            WHERE id = ?
            """,
            (datetime.now().isoformat(timespec="seconds"), status, str(modem_response), history_id),
        )


def update_history_ref(history_id, message_ref, modem_response):
    with get_db() as conn:
        row = conn.execute("SELECT status FROM sms_history WHERE id = ?", (history_id,)).fetchone()
        if row and row[0] == "FAILED":
            # FAILED is sticky
            return
        conn.execute(
            """
            UPDATE sms_history
            SET updated_at = ?, status = 'SUBMITTED', delivery_status = 'SUBMITTED', message_ref = ?, modem_response = ?
            WHERE id = ?
            """,
            (datetime.now().isoformat(timespec="seconds"), message_ref, str(modem_response), history_id),
        )


def update_delivery_status(modem_port, message_ref, status, modem_response):
    campaign_rows = []
    prev_status = ""
    with get_db() as conn:
        # Chỉ cập nhật dòng ĐANG chờ báo cáo giao. Message reference của modem
        # chỉ nằm trong 0-255 và bị lặp lại, nên một báo cáo CDS cũ/trễ có thể
        # trùng MR với một tin MỚI chưa gửi - nếu không ràng buộc trạng thái,
        # tin mới sẽ bị đánh dấu DELIVERED/UNDELIVERED oan (báo thành công sai).
        row_cur = conn.execute(
            """
            SELECT id, status, campaign_row FROM sms_history
            WHERE modem_port = ? AND message_ref = ?
              AND status IN ('SENDING', 'SUBMITTED', 'ANDROID_QUEUED')
            ORDER BY id DESC LIMIT 1
            """,
            (modem_port, message_ref),
        ).fetchone()
        if not row_cur:
            return 0
        h_id, prev_status, c_row = row_cur[0], row_cur[1], row_cur[2]
        if prev_status == "FAILED":
            # FAILED is sticky, never overwritten
            return 0
        if c_row is not None:
            campaign_rows.append(c_row)
        cursor = conn.execute(
            """
            UPDATE sms_history
            SET updated_at = ?, status = ?, delivery_status = ?, modem_response = ?
            WHERE id = ?
            """,
            (
                datetime.now().isoformat(timespec="seconds"), status, status,
                str(modem_response), h_id,
            ),
        )
        updated = cursor.rowcount

    if status == "DELIVERED" and prev_status != "DELIVERED":
        with lock:
            stats["success"] += 1
        for campaign_row in campaign_rows:
            mark_campaign_row_sent(campaign_row)
    return updated


def update_android_status(device_id, job_id, status, response, phone="", message="", created_time=None, delivery_status=None):
    if not job_id:
        return 0
    now = created_time or datetime.now().isoformat(timespec="seconds")
    norm_status = status
    if norm_status in {"SENT", "ANDROID_ACCEPTED"}:
        norm_status = "SUBMITTED"
    deliv = delivery_status or norm_status
    if norm_status == "SUBMITTED" and not delivery_status:
        deliv = "Đã gửi tới nhà mạng (chờ xác nhận giao)"
    elif norm_status == "UNCONFIRMED" and not delivery_status:
        deliv = "Chưa có báo cáo giao tin (UNCONFIRMED)"
    elif norm_status == "DELIVERED" and not delivery_status:
        deliv = "Đã giao đến người nhận"

    campaign_rows = []
    prev_status = ""
    with get_db() as conn:
        row_cur = conn.execute(
            "SELECT status, campaign_row FROM sms_history WHERE external_job_id = ?",
            (job_id,),
        ).fetchone()
        if row_cur:
            prev_status = row_cur[0]
            if prev_status == "FAILED":
                # FAILED is sticky! Never overwritten by late events!
                return 0
            if row_cur[1] is not None:
                campaign_rows.append(row_cur[1])
            cursor = conn.execute(
                """
                UPDATE sms_history
                SET updated_at = ?, status = ?, delivery_status = ?, modem_response = ?
                WHERE external_job_id = ?
                """,
                (datetime.now().isoformat(timespec="seconds"), norm_status, deliv, str(response), job_id),
            )
            updated = cursor.rowcount
        elif phone:
            conn.execute(
                """
                INSERT INTO sms_history (
                    created_at, updated_at, phone, customer_name, modem_port,
                    template_name, message, status, delivery_status, modem_response,
                    transport, device_id, external_job_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ANDROID', ?, ?)
                """,
                (now, now, phone, phone, device_id, "direct_phone", message or "", norm_status, deliv, str(response), device_id, job_id),
            )
            updated = 1
        else:
            updated = 0

    # Trạng thái DELIVERED duy nhất là thành công!
    if norm_status == "DELIVERED" and prev_status != "DELIVERED":
        with lock:
            stats["success"] += 1
        for campaign_row in campaign_rows:
            mark_campaign_row_sent(campaign_row)
    elif norm_status == "FAILED" and prev_status == "DELIVERED":
        with lock:
            stats["success"] = max(0, stats["success"] - 1)

    return updated


def check_recent_successful_send(phone: str, cooldown_hours: int = 24) -> dict | None:
    if not phone:
        return None
    cutoff_iso = (datetime.now() - timedelta(hours=cooldown_hours)).isoformat(timespec="seconds")
    with get_db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, status, delivery_status, modem_response, created_at, message
            FROM sms_history
            WHERE phone = ?
              AND (status = 'DELIVERED' OR delivery_status = 'DELIVERED')
              AND created_at >= ?
            ORDER BY id DESC LIMIT 1
            """,
            (phone, cutoff_iso),
        ).fetchone()
        if row:
            return dict(row)
        return None


def get_history(limit=200):
    with get_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM sms_history ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def get_conversations(limit=200):
    with get_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT 
                h.phone,
                h.customer_name,
                h.message,
                h.status,
                h.delivery_status,
                h.transport,
                h.device_id,
                h.modem_port,
                h.updated_at,
                h.created_at,
                c.total_count
            FROM sms_history h
            INNER JOIN (
                SELECT phone, MAX(id) AS max_id, COUNT(*) AS total_count
                FROM sms_history
                GROUP BY phone
            ) c ON h.id = c.max_id
            ORDER BY h.id DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(row) for row in rows]


def get_messages_by_phone(phone, limit=500):
    norm_phone = normalize_phone(phone) or str(phone).strip()
    with get_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT * FROM sms_history 
            WHERE phone = ? OR phone = ?
            ORDER BY id ASC
            LIMIT ?
        """, (norm_phone, phone, limit)).fetchall()
    return [dict(row) for row in rows]


init_history_db()


def add_log(status, phone, port, message):
    global log_version
    now = datetime.now().strftime("%H:%M:%S")
    icon = {"SUCCESS": "✅", "FAIL": "❌", "WARN": "⚠️", "INFO": "📡", "START": "🚀"}.get(status, "🔹")
    entry = f"[{now}] {icon} | {port:<12} | {phone:<11} | {message}"
    with lock:
        logs.append(entry)
        if len(logs) > 200:
            logs.pop(0)
        log_version += 1


def remove_accents(text):
    import unicodedata
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def normalize_message_for_modem(message):
    return remove_accents(message)


def normalize_phone(raw):
    if raw is None:
        return None
    try:
        if pd.isna(raw):
            return None
    except Exception:
        pass
    s = str(raw).strip()
    if s.endswith(".0"):
        s = s[:-2]
    phone = "".join(c for c in s if c.isdigit())
    if phone.startswith("84") and len(phone) == 11:
        phone = "0" + phone[2:]
    if len(phone) == 9:
        phone = "0" + phone
    if len(phone) == 10 and phone.startswith("0"):
        return phone
    if 8 <= len(phone) <= 15:
        return phone
    return None


def create_sample_excel_file():
    sample_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dulieu_mau.xlsx")
    data = [
        {"ĐIỆN THOẠI": "0912345678", "HỌ TÊN": "Nguyễn Văn Tuấn", "GIỚI TÍNH": 1, "GHI CHÚ": "1 là Nam (Anh)"},
        {"ĐIỆN THOẠI": "0987654321", "HỌ TÊN": "Trần Thị Mai", "GIỚI TÍNH": 0, "GHI CHÚ": "0 là Nữ (Chị)"},
        {"ĐIỆN THOẠI": "0903112233", "HỌ TÊN": "Lê Hoàng Long", "GIỚI TÍNH": 1, "GHI CHÚ": "1 là Nam (Anh)"},
        {"ĐIỆN THOẠI": "0934556677", "HỌ TÊN": "Phạm Thu Hà", "GIỚI TÍNH": 0, "GHI CHÚ": "0 là Nữ (Chị)"},
        {"ĐIỆN THOẠI": "0978990011", "HỌ TÊN": "Vũ Đức Anh", "GIỚI TÍNH": 1, "GHI CHÚ": "1 là Nam (Anh)"},
    ]
    df = pd.DataFrame(data)
    df.to_excel(sample_path, index=False)
    return sample_path


def parse_excel_file(file_path_or_buffer):
    if isinstance(file_path_or_buffer, str):
        ext = os.path.splitext(file_path_or_buffer)[1].lower()
    else:
        ext = ".xlsx"
    
    if ext == ".csv":
        try:
            df = pd.read_csv(file_path_or_buffer, encoding="utf-8")
        except Exception:
            df = pd.read_csv(file_path_or_buffer, encoding="latin1")
    elif ext in [".xls", ".xlsx"]:
        df = pd.read_excel(file_path_or_buffer)
    else:
        try:
            df = pd.read_excel(file_path_or_buffer)
        except Exception:
            df = pd.read_csv(file_path_or_buffer)

    phone_col = None
    name_col = None
    gender_col = None

    for col in df.columns:
        c_upper = str(col).strip().upper()
        if not phone_col and c_upper in ["ĐT", "ĐIỆN THOẠI", "DIEN THOAI", "SDT", "SĐT", "PHONE", "SO_DIEN_THOAI", "DIEN_THOAI", "TEL", "MOBILE", "PHONE NUMBER"]:
            phone_col = col
        if not name_col and c_upper in ["TÊN", "TEN", "NAME", "HỌ TÊN", "HO TEN", "HỌ VÀ TÊN", "HO VA TEN", "HOTEN", "KHACH HANG", "KHÁCH HÀNG", "CUSTOMER", "FULLNAME"]:
            name_col = col
        if not gender_col and c_upper in ["GIỚI TÍNH", "GIOI TINH", "GENDER", "SEX", "PHÁI", "PHAI", "XƯNG HÔ", "XUNG HO"]:
            gender_col = col

    if not phone_col:
        for col in df.columns:
            c_lower = str(col).strip().lower()
            if "phone" in c_lower or "sdt" in c_lower or "điện thoại" in c_lower or "dien thoai" in c_lower or "đt" in c_lower:
                phone_col = col
                break

    if not name_col:
        for col in df.columns:
            c_lower = str(col).strip().lower()
            if "tên" in c_lower or "name" in c_lower or "khách" in c_lower:
                name_col = col
                break

    if not gender_col:
        for col in df.columns:
            c_lower = str(col).strip().lower()
            if "giới" in c_lower or "gioi" in c_lower or "gender" in c_lower or "sex" in c_lower:
                gender_col = col
                break

    if not phone_col and len(df.columns) > 0:
        phone_col = df.columns[0]
    if not name_col and len(df.columns) > 1:
        name_col = df.columns[1] if df.columns[1] != phone_col else df.columns[0]

    valid_rows = []
    invalid_rows = []

    for idx, row in df.iterrows():
        raw_phone = str(row[phone_col]) if phone_col and pd.notna(row.get(phone_col)) else ""
        norm_p = normalize_phone(raw_phone)
        raw_name = str(row[name_col]).strip() if name_col and pd.notna(row.get(name_col)) else ""
        if raw_name in ["nan", "None", "NULL"]:
            raw_name = ""
        
        raw_gender = str(row[gender_col]).strip() if gender_col and pd.notna(row.get(gender_col)) else ""
        if raw_gender.endswith(".0"):
            raw_gender = raw_gender[:-2]

        # Lấy ĐÚNG 1 chữ cuối cùng của tên
        name_parts = raw_name.split() if raw_name else []
        single_name = name_parts[-1] if name_parts else ""

        # Xác định giới tính (1: Nam / Anh, 0: Nữ / Chị)
        if raw_gender in ["1", "nam", "Nam", "NAM", "anh", "Anh", "m", "Male", "MALE"]:
            gender_label = "1 (Nam / Anh)"
            gender_code = "1"
        elif raw_gender in ["0", "nu", "nữ", "Nữ", "NU", "chi", "Chị", "f", "Female", "FEMALE"]:
            gender_label = "0 (Nữ / Chị)"
            gender_code = "0"
        else:
            gender_label = "Tự động"
            gender_code = ""

        row_dict = {str(k): ("" if pd.isna(v) else str(v).strip()) for k, v in row.items()}
        row_dict["__excel_index__"] = int(idx)
        row_dict["ĐT"] = norm_p if norm_p else raw_phone
        row_dict["TÊN"] = raw_name
        row_dict["TEN_CUOI"] = single_name
        row_dict["GIỚI TÍNH"] = gender_code
        row_dict["GENDER_LABEL"] = gender_label

        if norm_p:
            valid_rows.append(row_dict)
        else:
            invalid_rows.append(row_dict)

    return df, phone_col, name_col, gender_col, valid_rows, invalid_rows

def campaign_row_was_sent(row):
    value = str(row.get(CAMPAIGN_SENT_COLUMN, "")).strip().upper()
    return value in {"ĐÃ GỬI", "DA GUI", "TRUE", "1", "YES", "OK"}

def ensure_campaign_columns(excel_path):
    with campaign_excel_lock:
        if not os.path.exists(excel_path):
            return False
        df = pd.read_excel(excel_path)
        missing = [
            column for column in (CAMPAIGN_SENT_COLUMN, CAMPAIGN_SENT_AT_COLUMN)
            if column not in df.columns
        ]
        if missing:
            for column in missing:
                df[column] = ""
            for column in (CAMPAIGN_SENT_COLUMN, CAMPAIGN_SENT_AT_COLUMN):
                if column in df.columns:
                    df[column] = df[column].fillna("").astype(str)
            temp_path = f"{excel_path}.tmp.xlsx"
            df.to_excel(temp_path, index=False)
            os.replace(temp_path, excel_path)
            return True
        return False


@app.post("/api/reset_campaign_status")
def api_reset_campaign_status():
    excel_path = EXCEL_PATH
    if not os.path.exists(excel_path):
        return jsonify({"status": "no_file", "message": "Chưa có file dữ liệu"}), 404
    with campaign_excel_lock:
        try:
            df = pd.read_excel(excel_path)
            for col in (CAMPAIGN_SENT_COLUMN, CAMPAIGN_SENT_AT_COLUMN):
                if col in df.columns:
                    df[col] = ""
            temp_path = f"{excel_path}.tmp.xlsx"
            df.to_excel(temp_path, index=False)
            os.replace(temp_path, excel_path)
            add_log("INFO", "SYSTEM", "EXCEL", "Đã xóa toàn bộ trạng thái đã gửi trong file Excel")
            return jsonify({"status": "ok", "message": "Đã xóa trạng thái đã gửi, sẵn sàng gửi lại toàn bộ"})
        except Exception as err:
            return jsonify({"status": "error", "message": str(err)}), 500

def mark_campaign_row_sent(excel_index, excel_path=None):
    path = excel_path or EXCEL_PATH
    try:
        row_index = int(excel_index)
    except (TypeError, ValueError):
        return False
    with campaign_excel_lock:
        if not os.path.exists(path):
            return False
        try:
            df = pd.read_excel(path)
            if row_index not in df.index:
                return False
            for col in (CAMPAIGN_SENT_COLUMN, CAMPAIGN_SENT_AT_COLUMN):
                if col not in df.columns:
                    df[col] = ""
                df[col] = df[col].fillna("").astype(str)
            df.loc[row_index, CAMPAIGN_SENT_COLUMN] = "ĐÃ GỬI"
            df.loc[row_index, CAMPAIGN_SENT_AT_COLUMN] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            temp_path = f"{path}.tmp.xlsx"
            df.to_excel(temp_path, index=False)
            os.replace(temp_path, path)
            return True
        except Exception as error:
            add_log("WARN", "SYSTEM", "EXCEL", f"Không thể đánh dấu dòng {row_index + 2}: {error}")
            return False


def get_final_message(customer_name, custom_templates=None, gender=None, row=None):
    try:
        raw_name = str(customer_name).strip() if customer_name else ""
        if raw_name.lower() in ["nan", "none", "null", ""]:
            raw_name = ""
        
        name_parts = raw_name.split() if raw_name else []
        single_name = name_parts[-1] if name_parts else ""
        first_name = name_parts[0] if name_parts else ""

        # Xác định xưng hô theo giới tính (1: Nam -> Anh, 0: Nữ -> Chị)
        gender_str = str(gender).strip().lower() if gender is not None else ""
        if gender_str in ["1", "1.0", "nam", "anh", "m", "male"]:
            xungho = "Anh"
            if single_name.lower() == "anh" and len(name_parts) >= 2:
                called_name = f"{name_parts[-2]} {single_name}"
            else:
                called_name = single_name
            full_display_name = f"Anh {called_name}" if called_name else "Anh"
        elif gender_str in ["0", "0.0", "nu", "nữ", "chi", "chị", "f", "female"]:
            xungho = "Chị"
            if single_name.lower() == "chị" and len(name_parts) >= 2:
                called_name = f"{name_parts[-2]} {single_name}"
            else:
                called_name = single_name
            full_display_name = f"Chị {called_name}" if called_name else "Chị"
        else:
            xungho = "Anh/Chị"
            full_display_name = single_name if single_name else "Anh/Chị"

        if not single_name:
            single_name = full_display_name

        def apply_replacements(text):
            t = text
            if isinstance(row, dict):
                for col_k, col_v in row.items():
                    if col_k:
                        t = t.replace(f"{{{col_k}}}", str(col_v))
                        t = t.replace(f"{{{col_k.lower()}}}", str(col_v))
                        t = t.replace(f"{{{col_k.upper()}}}", str(col_v))
            
            t = t.replace("{xungho}", xungho)
            t = t.replace("{ten}", single_name)
            t = t.replace("{tencuoi}", single_name)
            t = t.replace("{ho}", first_name)
            t = t.replace("{name}", full_display_name)
            t = t.replace("{fullname}", raw_name or full_display_name)
            t = t.replace("{hoten}", raw_name or full_display_name)
            t = t.replace("{HOTEN}", raw_name or full_display_name)
            t = t.replace("{TEN}", single_name)
            return t

        if custom_templates and len(custom_templates) > 0:
            template = random.choice(custom_templates)
            used_file = f"custom_template_{random.randint(1, len(custom_templates))}"
            return apply_replacements(template), used_file

        txt_files = [f for f in os.listdir(MSG_DIR) if f.endswith(".txt")]
        if not txt_files:
            return f"Xin chao {full_display_name}", "default"
        file_name = random.choice(txt_files)
        with open(os.path.join(MSG_DIR, file_name), "r", encoding="utf-8") as f:
            content = f.read().strip()
        return apply_replacements(content), file_name
    except Exception as err:
        return f"Xin chao {customer_name}", f"error_{err}"


def send_at(ser, cmd, wait=0.5):
    ser.write(cmd)
    time.sleep(wait)
    resp = ser.read_all().decode(errors="ignore")
    print(f"{cmd} + {resp}")
    if "ERROR" in resp or "OK" not in resp:
        print(f"AT ERROR: {cmd.decode().strip()}")
        return False
    return True


def parse_cmgs_ref(response):
    for line in response.splitlines():
        line = line.strip()
        if line.startswith("+CMGS:"):
            value = line.split(":", 1)[1].strip().split()[0]
            return int(value)
    return None


def parse_cds_reports(response):
    reports = []
    lines = [line.strip() for line in response.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if line.startswith("+CDS:") and index + 1 < len(lines):
            pdu = lines[index + 1]
            if len(pdu) >= 8:
                try:
                    smsc_length = int(pdu[0:2], 16)
                    tpdu_start = (smsc_length + 1) * 2
                    mr = int(pdu[tpdu_start + 2:tpdu_start + 4], 16)
                    status_byte = int(pdu[-2:], 16)
                except ValueError:
                    continue
                if status_byte <= 0x1F:
                    status = "DELIVERED"
                elif status_byte <= 0x3F:
                    status = "PENDING"
                else:
                    status = "UNDELIVERED"
                reports.append((mr, status, pdu))
    return reports


def poll_delivery_reports(ser):
    response = ser.read_all().decode(errors="ignore")
    ser.write(b"AT\r")
    time.sleep(0.3)
    response += ser.read_all().decode(errors="ignore")
    updated = 0
    for message_ref, status, pdu in parse_cds_reports(response):
        updated += update_delivery_status(ser.port, message_ref, status, response)
        add_log("INFO", "SYSTEM", ser.port, f"CDS {status} MR={message_ref} PDU={pdu}")
    return updated


def send_sms_modem(ser, phone, msg):
    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        if not send_at(ser, b"AT\r"):
            return False, "AT failed"
        if not send_at(ser, b"ATE0\r"):
            return False, "ATE0 failed"
        if not send_at(ser, b"ATI\r"):
            return False, "ATI failed"
        if not send_at(ser, b"AT+CPIN?\r"):
            return False, "SIM not ready"
        if not send_at(ser, b"AT+CIMI\r"):
            return False, "SIM identity failed"
        if not send_at(ser, b"AT+CSQ\r"):
            return False, "Signal check failed"
        if not send_at(ser, b"AT+CMGF=1\r"):
            return False, "SMS text mode failed"
        if not send_at(ser, b'AT+CSCS="GSM"\r'):
            return False, "SMS charset failed"
        if not send_at(ser, b"AT+CSMP=49,167,0,0\r"):
            return False, "Delivery report request failed"
        if not send_at(ser, b"AT+CNMI=2,1,0,2,0\r"):
            return False, "Delivery report routing failed"

        ser.write(f'AT+CMGS="{phone}"\r'.encode())
        print(f"Sending SMS to {phone} via {ser.port}...")
        buffer = b""
        start = time.time()

        while True:
            if ser.in_waiting:
                data = ser.read(ser.in_waiting)
                buffer += data
                if b">" in buffer:
                    print("MODEM READY TO SEND SMS")
                    break
                if b"ERROR" in buffer:
                    return False, buffer.decode(errors="ignore")

            if time.time() - start > 30:
                return False, "Timeout waiting for modem prompt"
            time.sleep(0.05)

        ser.write(msg.encode("ascii", "ignore"))
        ser.write(bytes([26]))  # Ctrl+Z
        result = ""
        start = time.time()
        while True:
            if ser.in_waiting:
                result += ser.read_all().decode(errors="ignore")
                if "+CMGS:" in result:
                    print("SMS MODEM ACCEPTED:", result)
                    message_ref = parse_cmgs_ref(result)
                    return True, {"response": result.strip(), "message_ref": message_ref}
                if "ERROR" in result:
                    print("MODEM ERROR:", result)
                    return False, result.strip()

            if time.time() - start > 60:
                return False, "Timeout waiting for +CMGS"
            time.sleep(0.2)

    except Exception as e:
        print("SMS EXCEPTION:", e)
        return False, f"Exception: {e}"


def send_direct_sms(phone, message, customer_name="Anh/Chị", device_id=None, transport="AUTO"):
    clean_p = normalize_phone(phone)
    if not clean_p:
        return False, "Số điện thoại không hợp lệ (yêu cầu đúng 10 số)"
    if not message or not message.strip():
        return False, "Nội dung tin nhắn không được để trống"

    global android_devices
    message = message.strip()
    if not any(d.ready for d in android_devices):
        try:
            scanned = android_transport.scan()
            if scanned:
                android_devices = scanned
        except Exception:
            pass

    ready_android = [d for d in android_devices if d.ready]
    chosen_transport = None
    chosen_device = None

    chosen_sub_id = -1
    target_serial = device_id
    if device_id:
        ready_serials = {d.serial for d in ready_android}
        if target_serial not in ready_serials and ":" in target_serial:
            head, sep, tail = target_serial.rpartition(":")
            if sep and tail.lstrip("-").isdigit():
                target_serial = head
                chosen_sub_id = int(tail)

    if transport == "ANDROID":
        if target_serial:
            chosen_device = next((d for d in ready_android if d.serial == target_serial), None)
            if not chosen_device:
                return False, f"Thiết bị Android {target_serial} chưa sẵn sàng"
        else:
            if not ready_android:
                return False, "Không có thiết bị Android nào sẵn sàng"
            chosen_device = ready_android[0]
        chosen_transport = "ANDROID"
    elif transport == "USB_MODEM":
        if device_id:
            chosen_device = next((m for m in modems if m.port == device_id), None)
            if not chosen_device:
                return False, f"Modem USB {device_id} chưa sẵn sàng"
        else:
            if not modems:
                return False, "Không có Modem USB nào sẵn sàng"
            chosen_device = modems[0]
        chosen_transport = "USB_MODEM"
    else:  # AUTO
        if target_serial:
            chosen_device = next((d for d in ready_android if d.serial == target_serial), None)
            if chosen_device:
                chosen_transport = "ANDROID"
            else:
                chosen_device = next((m for m in modems if m.port == target_serial), None)
                if chosen_device:
                    chosen_transport = "USB_MODEM"
                else:
                    return False, f"Không tìm thấy thiết bị {target_serial}"
        else:
            if ready_android:
                chosen_transport = "ANDROID"
                chosen_device = ready_android[0]
            elif modems:
                chosen_transport = "USB_MODEM"
                chosen_device = modems[0]
            else:
                return False, "Không có thiết bị nào (Android hoặc USB Modem) đang kết nối. Vui lòng bấm Quét thiết bị."

    if chosen_transport == "ANDROID":
        sim_label = f" [SIM {chosen_sub_id}]" if chosen_sub_id >= 0 else ""
        device_label = f"{chosen_device.serial}{sim_label}"
        history_id = create_history(
            clean_p, customer_name, device_label, "direct_compose", message,
            transport="ANDROID", device_id=device_label,
        )
        try:
            ok, job_id, detail = android_transport.send(chosen_device.serial, clean_p, message, subscription_id=chosen_sub_id)
        except Exception as error:
            ok, job_id, detail = False, "", str(error)

        if ok:
            with get_db() as conn:
                conn.execute(
                    """
                    UPDATE sms_history
                    SET status = 'ANDROID_QUEUED', external_job_id = ?, modem_response = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (job_id, detail, datetime.now().isoformat(timespec="seconds"), history_id),
                )
            add_log("INFO", clean_p, chosen_device.serial, f"DIRECT ANDROID [ĐANG GỬI] {message[:35]}")
            return True, {
                "history_id": history_id,
                "job_id": job_id,
                "detail": detail,
                "transport": "ANDROID",
                "device": chosen_device.serial,
                "status": "ANDROID_QUEUED",
            }
        else:
            update_history(history_id, "FAILED", detail)
            add_log("FAIL", clean_p, chosen_device.serial, f"DIRECT ANDROID GỬI LỖI: {detail}")
            return False, detail

    elif chosen_transport == "USB_MODEM":
        msg_norm = normalize_message_for_modem(message)
        imei = port_to_imei.get(chosen_device.port, chosen_device.port)
        history_id = create_history(
            clean_p, customer_name, chosen_device.port, "direct_compose", msg_norm,
            transport="USB_MODEM", device_id=chosen_device.port,
        )
        with imei_locks.setdefault(imei, threading.Lock()):
            ok, modem_response = send_sms_modem(chosen_device, clean_p, msg_norm)

        status = "MODEM_ACCEPTED" if ok else "FAILED"
        if ok:
            update_history_ref(history_id, modem_response.get("message_ref"), modem_response.get("response", ""))
            modem_log = modem_response.get("response", "")
            add_log("SUCCESS", clean_p, chosen_device.port, f"DIRECT USB [{status}] {msg_norm[:35]}")
            return True, {
                "history_id": history_id,
                "response": modem_log,
                "transport": "USB_MODEM",
                "device": chosen_device.port,
                "status": status,
            }
        else:
            update_history(history_id, status, modem_response)
            add_log("FAIL", clean_p, chosen_device.port, f"DIRECT USB FAIL: {modem_response}")
            return False, modem_response


campaign_templates_global = []

def worker(ser, rows, custom_templates=None, delay_min=5, delay_max=15, delay_unit="minutes", generation=0, ignore_cooldown=False, dedup_excel=True):
    global failed_rows, sent_rows_success, campaign_dispatched_phones, campaign_dispatched_rows
    sent_count = 0

    for r in rows:
        if generation != campaign_generation or stop_event.is_set() or not stats.get("running"):
            break

        phone = normalize_phone(r.get("ĐT") or r.get("ĐIỆN THOẠI") or "")
        if not phone:
            continue

        # Đảm bảo không trùng giữa các worker hoặc trong cùng chiến dịch
        with lock:
            if dedup_excel:
                if phone in campaign_dispatched_phones:
                    add_log("WARN", phone, ser.port, f"⏩ Bỏ qua {phone}: Số này đã được xử lý bởi kênh khác trong chiến dịch")
                    continue
                campaign_dispatched_phones.add(phone)
            else:
                row_idx = r.get("__excel_index__")
                if row_idx is not None and row_idx in campaign_dispatched_rows:
                    continue
                if row_idx is not None:
                    campaign_dispatched_rows.add(row_idx)

        # Kiểm tra lịch sử gửi cơ sở dữ liệu gần đây (cooldown 24h)
        if not ignore_cooldown:
            recent = check_recent_successful_send(phone, cooldown_hours=24)
            if recent:
                add_log("WARN", phone, ser.port, f"⏩ Bỏ qua {phone}: Đã gửi thành công gần đây ({recent['status']} lúc {recent['created_at']})")
                mark_campaign_row_sent(r.get("__excel_index__"))
                continue

        name = str(r.get("TÊN", ""))
        gender = r.get("GIỚI TÍNH")
        msg, used_file = get_final_message(name, custom_templates, gender=gender, row=r)
        msg = normalize_message_for_modem(msg)
        imei = port_to_imei.get(ser.port, ser.port)
        history_id = create_history(
            phone, name, ser.port, used_file, msg,
            campaign_row=r.get("__excel_index__"),
        )

        with imei_locks.setdefault(imei, threading.Lock()):
            ok, modem_response = send_sms_modem(ser, phone, msg)

        status = "SUBMITTED" if ok else "FAILED"
        if ok:
            update_history_ref(history_id, modem_response.get("message_ref"), modem_response.get("response", ""))
            modem_log = modem_response.get("response", "")
        else:
            update_history(history_id, status, modem_response)
            modem_log = modem_response

        with lock:
            stats["sent"] += 1
            if not ok:
                failed_rows.append(r)

        add_log(
            "INFO" if ok else "FAIL",
            phone,
            ser.port,
            f"{status} [{used_file}] {msg} | {modem_log}",
        )

        sent_count += 1
        if sent_count % 25 == 0:
            try:
                ser.write(b"AT+CMGD=1,4\r")
                time.sleep(0.5)
                ser.read_all()
            except Exception:
                pass
        if sent_count == len(rows):
            add_log("INFO", "SYSTEM", ser.port, f"Hoàn thành gửi {sent_count} SMS")
        else:
            min_sec = int(delay_min * 60) if delay_unit == "minutes" else int(delay_min)
            max_sec = int(delay_max * 60) if delay_unit == "minutes" else int(delay_max)
            if max_sec < min_sec:
                max_sec = min_sec + 10
            delay = random.uniform(max(1, min_sec), max(min_sec + 1, max_sec))
            mins, secs = int(delay // 60), int(delay % 60)
            time_str = f"{mins} phút {secs} giây" if mins > 0 else f"{secs} giây"
            add_log("INFO", "SYSTEM", ser.port, f"⏳ Chờ {time_str} ({int(delay)}s) trước khi gửi tin tiếp theo...")
            if stop_event.wait(timeout=delay) or generation != campaign_generation or not stats.get("running"):
                break


def run_worker(ser, rows, custom_templates=None, delay_min=5, delay_max=15, delay_unit="minutes", generation=0, ignore_cooldown=False, dedup_excel=True):
    try:
        worker(ser, rows, custom_templates, delay_min, delay_max, delay_unit, generation, ignore_cooldown, dedup_excel)
    except Exception as error:
        add_log("FAIL", "SYSTEM", ser.port, f"Worker error: {error}")
    finally:
        finish_worker()


def android_worker(device, rows, custom_templates=None, delay_min=5, delay_max=15, delay_unit="minutes", subscription_id=-1, generation=0, ignore_cooldown=False, dedup_excel=True):
    global failed_rows, sent_rows_success, campaign_dispatched_phones, campaign_dispatched_rows
    sent_count = 0
    dev_sim_label = f"{device.serial}" + (f" [SIM {subscription_id}]" if subscription_id >= 0 else "")

    for row in rows:
        if generation != campaign_generation or stop_event.is_set() or not stats.get("running"):
            break
        phone = normalize_phone(row.get("ĐT") or row.get("ĐIỆN THOẠI") or "")
        if not phone:
            continue

        # Đảm bảo không gửi trùng SĐT giữa các luồng/thiết bị trong chiến dịch
        with lock:
            if dedup_excel:
                if phone in campaign_dispatched_phones:
                    add_log("WARN", phone, dev_sim_label, f"⏩ Bỏ qua {phone}: Số này đã được xử lý bởi kênh khác trong chiến dịch")
                    continue
                campaign_dispatched_phones.add(phone)
            else:
                row_idx = row.get("__excel_index__")
                if row_idx is not None and row_idx in campaign_dispatched_rows:
                    continue
                if row_idx is not None:
                    campaign_dispatched_rows.add(row_idx)

        # Kiểm tra cơ sở dữ liệu xem số này đã gửi thành công gần đây chưa (cooldown 24h)
        if not ignore_cooldown:
            recent = check_recent_successful_send(phone, cooldown_hours=24)
            if recent:
                add_log("WARN", phone, dev_sim_label, f"⏩ Bỏ qua {phone}: Đã gửi thành công gần đây ({recent['status']} lúc {recent['created_at']})")
                mark_campaign_row_sent(row.get("__excel_index__"))
                continue

        name = str(row.get("TÊN", ""))
        gender = row.get("GIỚI TÍNH")
        message, used_file = get_final_message(name, custom_templates, gender=gender, row=row)
        history_id = create_history(
            phone, name, dev_sim_label, used_file, message,
            transport="ANDROID", device_id=device.serial,
            campaign_row=row.get("__excel_index__"),
        )
        try:
            ok, job_id, detail = android_transport.send(device.serial, phone, message, subscription_id=subscription_id)
        except Exception as error:
            ok, job_id, detail = False, "", str(error)

        if not ok:
            update_history(history_id, "FAILED", detail)
            with lock:
                stats["sent"] += 1
                failed_rows.append(row)
            add_log("FAIL", phone, dev_sim_label, f"❌ KHÔNG THỂ GỬI [{used_file}] {detail}")
            continue

        # Cập nhật trạng thái ban đầu: tin đã được đưa vào hàng đợi/ứng dụng
        with get_db() as conn:
            conn.execute(
                """
                UPDATE sms_history
                SET status = 'ANDROID_QUEUED', external_job_id = ?, modem_response = ?, updated_at = ?
                WHERE id = ?
                """,
                (job_id, detail, datetime.now().isoformat(timespec="seconds"), history_id),
            )
        add_log("INFO", phone, dev_sim_label, f"⏳ ĐANG GỬI [{used_file}] {phone}...")

        # Chờ xác nhận THẬT 100% từ phản hồi nhà mạng viễn thông qua điện thoại
        carrier_status = None
        carrier_detail = ""
        wait_start = time.time()
        timeout_sec = 22.0 if device.serial.startswith("cloud:") else 15.0

        while time.time() - wait_start < timeout_sec:
            if generation != campaign_generation or stop_event.is_set() or not stats.get("running"):
                break
            if stop_event.wait(timeout=1.0):
                break
            if not device.serial.startswith("cloud:"):
                try:
                    poll_android_events()
                except Exception:
                    pass

            with get_db() as conn:
                conn.row_factory = sqlite3.Row
                h_row = conn.execute(
                    "SELECT status, delivery_status, modem_response FROM sms_history WHERE external_job_id = ?",
                    (job_id,),
                ).fetchone()
                if h_row:
                    st = h_row["status"]
                    if st == "DELIVERED":
                        carrier_status = "DELIVERED"
                        carrier_detail = h_row["delivery_status"] or h_row["modem_response"] or "Đã giao đến người nhận"
                        break
                    elif st == "FAILED":
                        carrier_status = "FAILED"
                        carrier_detail = h_row["delivery_status"] or h_row["modem_response"] or "Lỗi gửi từ nhà mạng"
                        break
                    elif st in {"SUBMITTED", "SENT", "ANDROID_ACCEPTED"}:
                        # Message submitted, still waiting for DELIVERED
                        pass

        # Nếu chiến dịch đã bị dừng trong lúc chờ, thoát ngay lập tức mà không ghi nhận lỗi sai
        if generation != campaign_generation or stop_event.is_set() or not stats.get("running"):
            add_log("INFO", phone, dev_sim_label, f"Chiến dịch đã dừng, ngắt tiến trình gửi cho {phone}")
            break

        # Đánh giá kết quả thực tế
        if carrier_status == "DELIVERED":
            with lock:
                stats["sent"] += 1
                sent_rows_success.append(row)
            add_log("SUCCESS", phone, dev_sim_label, f"✅ ĐÃ GIAO THÀNH CÔNG [{used_file}] {phone} ({carrier_detail})")
        elif carrier_status == "FAILED":
            with lock:
                stats["sent"] += 1
                failed_rows.append(row)
            add_log("FAIL", phone, dev_sim_label, f"❌ NHÀ MẠNG BÁO LỖI [{used_file}] {phone}: {carrier_detail}")
        else:
            # Hết thời gian chờ mà chưa có DELIVERED -> UNCONFIRMED, không retry!
            update_android_status(device.serial, job_id, "UNCONFIRMED", "Quá thời gian chờ phản hồi DELIVERED từ nhà mạng", phone=phone, message=message)
            with lock:
                stats["sent"] += 1
                failed_rows.append(row)
            add_log("WARN", phone, dev_sim_label, f"⚠️ CHƯA XÁC NHẬN GIAO [{used_file}] Không nhận được báo cáo giao (UNCONFIRMED) cho {phone}")

        sent_count += 1
        if sent_count == len(rows):
            add_log("INFO", "SYSTEM", dev_sim_label, f"Kênh {dev_sim_label} hoàn thành {sent_count} SMS")
        elif not stop_event.is_set():
            min_sec = int(delay_min * 60) if delay_unit == "minutes" else int(delay_min)
            max_sec = int(delay_max * 60) if delay_unit == "minutes" else int(delay_max)
            if max_sec < min_sec:
                max_sec = min_sec + 10
            delay = random.uniform(max(1, min_sec), max(min_sec + 1, max_sec))
            mins, secs = int(delay // 60), int(delay % 60)
            time_str = f"{mins} phút {secs} giây" if mins > 0 else f"{secs} giây"
            add_log("INFO", "SYSTEM", dev_sim_label, f"⏳ Chờ {time_str} ({int(delay)}s) trước khi gửi tin tiếp theo...")
            if stop_event.wait(timeout=delay) or generation != campaign_generation or not stats.get("running"):
                break


def run_android_worker(device, rows, custom_templates=None, delay_min=5, delay_max=15, delay_unit="minutes", subscription_id=-1, generation=0, ignore_cooldown=False, dedup_excel=True):
    try:
        android_worker(device, rows, custom_templates, delay_min, delay_max, delay_unit, subscription_id, generation, ignore_cooldown, dedup_excel)
    except Exception as error:
        add_log("FAIL", "SYSTEM", device.serial, f"Android worker error: {error}")
    finally:
        finish_worker()


def finish_worker():
    with lock:
        stats["active_workers"] = max(0, stats["active_workers"] - 1)
        completed = stats["active_workers"] == 0
        if completed:
            stats["running"] = False
    if completed:
        add_log("INFO", "SYSTEM", "SMS", "Chiến dịch đã kết thúc")


android_poll_lock = threading.Lock()


def poll_android_events():
    if not android_poll_lock.acquire(blocking=False):
        return 0
    updated = 0
    try:
        for device in list(android_devices):
            if not device.ready:
                continue
            try:
                events = android_transport.events(device.serial)
                if not events:
                    continue
                summaries = android_transport.summarize_events(events)
                for job_id, summary in summaries.items():
                    phone = getattr(summary, "phone", "")
                    msg = getattr(summary, "message", "")
                    status = getattr(summary, "status", summary[0])
                    response = getattr(summary, "detail", summary[1])
                    res_count = update_android_status(device.serial, job_id, status, response, phone=phone, message=msg)
                    if res_count > 0:
                        updated += res_count
            except Exception as error:
                pass

        # Đồng bộ số lượng tin nhắn thành công thực tế từ nhà mạng
        if stats["running"]:
            try:
                with get_db() as conn:
                    conn.row_factory = sqlite3.Row
                    succ_row = conn.execute(
                        "SELECT COUNT(*) as c FROM sms_history WHERE (status = 'DELIVERED' OR delivery_status = 'DELIVERED') AND campaign_row IS NOT NULL"
                    ).fetchone()
                    if succ_row:
                        with lock:
                            stats["success"] = succ_row["c"]
            except Exception:
                pass
    finally:
        android_poll_lock.release()
    return updated


cloud_android_events: list[dict] = []

def get_android_event_rows(limit=120):
    rows = []
    # 1. Cloud events from Wi-Fi companion app
    for ce in reversed(cloud_android_events[-limit:]):
        rows.append(ce)

    # 2. Hardware ADB events if available
    for device in list(android_devices):
        if device.serial.startswith("cloud:"):
            continue
        try:
            events = android_transport.events(device.serial)
            summaries = android_transport.summarize_events(events)
            grouped = {}
            for event in events:
                grouped.setdefault(str(event.get("job_id", "")), []).append(event)
            for job_id, (status, response) in summaries.items():
                job_events = grouped.get(job_id, [])
                error = next((str(event.get("error", "")) for event in job_events if event.get("stage") == "FAILED"), "")
                latest_stage = job_events[-1].get("stage") if job_events else ""
                rows.append({
                    "device_id": device.serial,
                    "model": device.model,
                    "job_id": job_id,
                    "status": status,
                    "latest_stage": latest_stage,
                    "error": error,
                    "response": response,
                })
        except Exception as error:
            rows.append({
                "device_id": device.serial,
                "model": device.model,
                "job_id": "",
                "status": "ERROR",
                "latest_stage": "",
                "error": str(error),
                "response": "",
            })
    return rows[:limit]


@app.post("/retry")
def retry():
    global failed_rows, campaign_generation, campaign_dispatched_phones, campaign_dispatched_rows
    ready_android = [device for device in android_devices if device.ready]
    with lock:
        if stats["running"]:
            return jsonify({"status": "busy", "message": "Chiến dịch đang chạy"}), 409
        if not failed_rows:
            return jsonify({"status": "no_failed_data", "message": "Không có danh sách số gửi lỗi cần gửi lại"}), 400
        if not modems and not ready_android:
            return jsonify({"status": "no_devices", "message": "Không có thiết bị nào (Android hoặc USB Modem) sẵn sàng"}), 400
        rows_to_retry = list(failed_rows)
        failed_rows = []
        campaign_generation += 1
        my_gen = campaign_generation
        campaign_dispatched_phones.clear()
        campaign_dispatched_rows.clear()
        stop_event.clear()
        total_retry = len(rows_to_retry)
        stats.update({"total": total_retry, "sent": 0, "success": 0, "running": True, "active_workers": 0})

    add_log("START", "SYSTEM", "RETRY", f"Bắt đầu gửi lại {total_retry} số gửi lỗi...")

    workers = []
    for device in ready_android:
        subscription_ids = android_transport.active_subscription_ids(device.serial)
        channels = subscription_ids or [-1]
        workers.extend([("ANDROID", (device, subscription_id)) for subscription_id in channels])
    for modem in modems:
        workers.extend([("USB_MODEM", modem)])

    if not workers:
        if ready_android:
            workers = [("ANDROID", (ready_android[0], -1))]
        elif modems:
            workers = [("USB_MODEM", modems[0])]

    worker_count = len(workers)
    for i, (transport, target) in enumerate(workers):
        subset = [rows_to_retry[j] for j in range(total_retry) if j % worker_count == i]
        if subset:
            with lock:
                stats["active_workers"] += 1
            target_fn = run_worker if transport == "USB_MODEM" else run_android_worker
            args = (target, subset, campaign_templates_global, 5, 15, "seconds", my_gen, True, True) if transport == "USB_MODEM" else (
                target[0], subset, campaign_templates_global, 5, 15, "seconds", target[1], my_gen, True, True
            )
            threading.Thread(target=target_fn, args=args, daemon=True).start()

    return jsonify({"status": "ok", "count": total_retry})


@app.post("/connect")
def connect():
    global modems, android_devices
    with lock:
        if stats["running"]:
            return jsonify({"status": "busy"}), 409
    add_log("INFO", "SYSTEM", "SCAN", "Đang quét thiết bị USB Modem & Android...")
    adb_status = detect_adb_status()
    add_log("INFO", "SYSTEM", "ADB", f'{adb_status["status"]}: {adb_status["message"]}')

    for m in modems:
        try:
            add_log("INFO", "SYSTEM", "SCAN", f"Đã đóng {m.port}")
            m.close()
        except Exception:
            pass

    modems.clear()
    modem_signals.clear()
    port_to_imei.clear()
    android_devices = android_transport.scan()
    for device in android_devices:
        sim_info = f" | {len(device.sims)} SIM" if getattr(device, "sims", None) else ""
        add_log(
            "INFO" if device.ready else "WARN",
            "SYSTEM",
            device.serial,
            f"Android {device.model}{sim_info} | {device.detail}",
        )

    temp_ports = []
    used_imei = set()
    ports = sorted(serial.tools.list_ports.comports(), key=lambda x: x.device)

    for p in ports:
        try:
            s = serial.Serial(p.device, 115200, timeout=1)
            s.reset_input_buffer()
            s.write(b"AT\r")
            time.sleep(0.3)
            if b"OK" not in s.read_all():
                s.close()
                continue
            s.reset_input_buffer()
            s.write(b"AT+CGSN\r")
            time.sleep(0.3)
            imei_resp = s.read_all().decode(errors="ignore")
            imei = None
            for line in imei_resp.splitlines():
                if line.strip().isdigit():
                    imei = line.strip()
            s.close()
            if not imei or imei in used_imei:
                continue
            used_imei.add(imei)
            temp_ports.append((p.device, imei))
        except Exception:
            continue

    for device_port, imei in temp_ports:
        try:
            s = serial.Serial(device_port, 115200, timeout=1)
            s.reset_input_buffer()
            s.write(b"AT+CPIN?\r")
            time.sleep(0.3)
            if b"READY" not in s.read_all():
                add_log("WARN", "SYSTEM", device_port, "SIM chưa sẵn sàng")
                s.close()
                continue
            s.write(b"ATE0\r")
            time.sleep(0.2)
            s.read_all()
            s.write(b"AT+CMGF=1\r")
            time.sleep(0.2)
            s.read_all()
            s.write(b'AT+CSCS="GSM"\r')
            time.sleep(0.2)
            s.read_all()
            s.write(b"AT+CMGD=1,4\r")
            time.sleep(0.5)
            s.read_all()
            s.write(b"AT+CSQ\r")
            time.sleep(0.3)
            csq_resp = s.read_all().decode(errors="ignore")
            rssi = "?"
            if "+CSQ:" in csq_resp:
                try:
                    rssi = int(csq_resp.split("+CSQ:")[1].split(",")[0].strip())
                except Exception:
                    pass
            modems.append(s)
            port_to_imei[device_port] = imei
            if imei not in imei_locks:
                imei_locks[imei] = threading.Lock()
            modem_signals[device_port] = f"CSQ {rssi}"
            add_log("INFO", "SYSTEM", device_port, f"Modem OK | IMEI {imei} | Signal {rssi}")
        except Exception as e:
            add_log("WARN", "SYSTEM", device_port, f"Open port error: {e}")

    add_log("INFO", "SYSTEM", "SCAN", f"Tìm thấy {len(modems)} modem USB, {len(android_devices)} thiết bị Android")
    campaign_manager.ensure_running()  # đánh thức chiến dịch đang chờ thiết bị
    return jsonify({
        "status": "ok",
        "modems": len(modems),
        "android": len([device for device in android_devices if device.ready]),
        "adb": adb_status,
    })


def update_signal_loop():
    global android_devices
    last_known_serials = None

    while True:
        try:
            # 1. LIVE ANDROID HEALTH CHECK & DISCONNECT DETECTION
            current_android = android_transport.scan()
            current_serials = {d.serial for d in current_android if d.ready}
            
            if last_known_serials is not None:
                disconnected_serials = last_known_serials - current_serials
                for s in disconnected_serials:
                    add_log("WARN", "SYSTEM", s, f"Thiết bị Android ({s}) đã NGẮT KẾT NỐI (Unplugged)")
                
                connected_serials = current_serials - last_known_serials
                for s in connected_serials:
                    dev = next((d for d in current_android if d.serial == s), None)
                    if dev:
                        add_log("INFO", "SYSTEM", s, f"Đã kết nối thiết bị Android {dev.model} ({s})")
                        if ":" not in s:
                            # Auto-enable Wi-Fi TCP/IP port 5555 when USB device is detected
                            threading.Thread(target=lambda serial=s: android_transport.enable_tcpip(serial, 5555), daemon=True).start()

            last_known_serials = current_serials
            android_devices = current_android

            # 2. LIVE USB MODEM HEALTH CHECK & DISCONNECT DETECTION
            available_ports = {p.device for p in serial.tools.list_ports.comports()}
            
            for ser in list(modems):
                if ser.port not in available_ports:
                    try:
                        ser.close()
                    except Exception:
                        pass
                    if ser in modems:
                        modems.remove(ser)
                    modem_signals.pop(ser.port, None)
                    port_to_imei.pop(ser.port, None)
                    add_log("WARN", "SYSTEM", ser.port, f"USB Modem tại cổng {ser.port} đã NGẮT KẾT NỐI (Unplugged)")
                    continue

                imei = port_to_imei.get(ser.port, ser.port)
                modem_lock = imei_locks.setdefault(imei, threading.Lock())
                if not modem_lock.acquire(blocking=False):
                    continue
                try:
                    ser.reset_input_buffer()
                    ser.write(b"AT+CSQ\r")
                    time.sleep(0.3)
                    resp = ser.read_all().decode(errors="ignore")
                    for message_ref, status, pdu in parse_cds_reports(resp):
                        if update_delivery_status(ser.port, message_ref, status, resp):
                            add_log("INFO", "SYSTEM", ser.port, f"CDS {status} MR={message_ref} PDU={pdu}")
                    if "+CSQ:" in resp:
                        rssi = int(resp.split(":")[1].split(",")[0].strip())
                        modem_signals[ser.port] = f"CSQ {rssi}"
                    elif "ERROR" in resp or not resp:
                        modem_signals[ser.port] = "ERR"
                except Exception as ex:
                    try:
                        ser.close()
                    except Exception:
                        pass
                    if ser in modems:
                        modems.remove(ser)
                    modem_signals.pop(ser.port, None)
                    port_to_imei.pop(ser.port, None)
                    add_log("WARN", "SYSTEM", ser.port, f"Mất kết nối với USB Modem {ser.port}: {ex}")
                finally:
                    modem_lock.release()

            # 3. POLL ANDROID EVENTS
            poll_android_events()

        except Exception as loop_err:
            pass

        time.sleep(2.5)


@app.get("/api/download_template")
def api_download_template():
    sample_path = os.path.join(BASE, "dulieu_mau.xlsx")
    if not os.path.exists(sample_path):
        create_sample_excel_file()
    return send_file(
        sample_path,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="dulieu_mau.xlsx"
    )

@app.get("/api/download_campaign_excel")
def api_download_campaign_excel():
    excel_path = EXCEL_PATH
    if not os.path.exists(excel_path):
        return jsonify({"status": "no_file", "message": "Chưa có file chiến dịch"}), 404
    ensure_campaign_columns(excel_path)
    return send_file(
        excel_path,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="dulieu_da_danh_dau.xlsx",
    )


@app.post("/api/upload_excel")
def api_upload_excel():
    if "file" not in request.files:
        return jsonify({"status": "no_file", "message": "Không tìm thấy file tải lên"}), 400
    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"status": "empty_file", "message": "File không hợp lệ"}), 400
    
    filename = file.filename
    ext = os.path.splitext(filename)[1].lower()
    if ext not in [".xlsx", ".xls", ".csv"]:
        return jsonify({"status": "invalid_ext", "message": "Chỉ chấp nhận file .xlsx, .xls, .csv"}), 400
    
    excel_path = EXCEL_PATH
    if ext == ".xlsx":
        file.save(excel_path)
    else:
        upload_path = os.path.join(BASE, f"dulieu_upload{ext}")
        file.save(upload_path)
        source_df = pd.read_csv(upload_path) if ext == ".csv" else pd.read_excel(upload_path)
        source_df.to_excel(excel_path, index=False)

    try:
        columns_created = ensure_campaign_columns(excel_path)
        df, phone_col, name_col, gender_col, valid_rows, invalid_rows = parse_excel_file(excel_path)
        add_log("INFO", "SYSTEM", "EXCEL", f"Tải lên {filename}: {len(valid_rows)} số hợp lệ, {len(invalid_rows)} số lỗi")
        return jsonify({
            "status": "ok",
            "filename": filename,
            "total_valid": len(valid_rows),
            "total_invalid": len(invalid_rows),
            "phone_col": phone_col,
            "name_col": name_col,
            "gender_col": gender_col,
            "columns": [str(c) for c in df.columns],
            "success_columns_created": columns_created,
            "preview": valid_rows[:8]
        })
    except Exception as error:
        add_log("FAIL", "SYSTEM", "EXCEL", f"Lỗi đọc file {filename}: {error}")
        return jsonify({"status": "error", "message": str(error)}), 400


@app.get("/api/campaign_info")
def api_campaign_info():
    excel_path = EXCEL_PATH
    info = {"has_excel": False, "filename": "dulieu.xlsx", "total_valid": 0, "total_invalid": 0, "preview": [], "templates": []}
    
    if os.path.exists(excel_path):
        try:
            df, phone_col, name_col, gender_col, valid_rows, invalid_rows = parse_excel_file(excel_path)
            info["has_excel"] = True
            pending_rows = [row for row in valid_rows if not campaign_row_was_sent(row)]
            info["total_valid"] = len(pending_rows)
            info["total_sent_success"] = len(valid_rows) - len(pending_rows)
            info["total_invalid"] = len(invalid_rows)
            info["phone_col"] = phone_col
            info["name_col"] = name_col
            info["gender_col"] = gender_col
            info["preview"] = pending_rows[:8]
        except Exception:
            pass

    templates = []
    if os.path.exists(MSG_DIR):
        for f in sorted(os.listdir(MSG_DIR)):
            if f.endswith(".txt"):
                try:
                    with open(os.path.join(MSG_DIR, f), "r", encoding="utf-8") as fp:
                        content = fp.read().strip()
                    if content:
                        templates.append({"name": f, "content": content})
                except Exception:
                    pass
    info["templates"] = templates
    return jsonify(info)


@app.post("/api/save_template")
def api_save_template():
    data = request.get_json(silent=True) or {}
    content = str(data.get("content", "")).strip()
    name = str(data.get("name", "")).strip()
    if not content:
        return jsonify({"status": "error", "message": "Nội dung tin nhắn trống"}), 400
    os.makedirs(MSG_DIR, exist_ok=True)
    if not name:
        existing = set(os.listdir(MSG_DIR))
        idx = 1
        while f"mau_tin_{idx}.txt" in existing:
            idx += 1
        name = f"mau_tin_{idx}.txt"
    elif not name.endswith(".txt"):
        name += ".txt"
    safe_name = "".join(c for c in name if c.isalnum() or c in ("-", "_", ".", " ")).strip()
    if not safe_name.endswith(".txt"):
        safe_name = "mau_tin.txt"
    with open(os.path.join(MSG_DIR, safe_name), "w", encoding="utf-8") as fp:
        fp.write(content)
    add_log("INFO", "SYSTEM", "TEMPLATE", f"Đã lưu mẫu tin {safe_name}")
    return jsonify({"status": "ok", "message": f"Đã lưu thành công mẫu tin: {safe_name}", "name": safe_name})


@app.post("/api/delete_template")
def api_delete_template():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"status": "error", "message": "Tên mẫu tin không hợp lệ"}), 400
    safe_name = os.path.basename(name)
    if not safe_name.endswith(".txt"):
        safe_name += ".txt"
    target = os.path.join(MSG_DIR, safe_name)
    if os.path.isfile(target):
        try:
            os.remove(target)
            add_log("INFO", "SYSTEM", "TEMPLATE", f"Đã xóa mẫu tin {safe_name}")
            return jsonify({"status": "ok", "message": f"Đã xóa mẫu tin: {safe_name}"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "error", "message": "Không tìm thấy mẫu tin"}), 404


@app.post("/api/save_campaign_templates")
def api_save_campaign_templates():
    data = request.get_json() or {}
    raw_templates = data.get("templates", [])
    clean_templates = [str(t).strip() for t in raw_templates if str(t).strip()]
    if not clean_templates:
        return jsonify({"status": "no_templates", "message": "Vui lòng nhập ít nhất 1 nội dung tin nhắn"}), 400
    
    os.makedirs(MSG_DIR, exist_ok=True)
    # Clear old message txt files
    for f in os.listdir(MSG_DIR):
        if f.endswith(".txt"):
            try:
                os.remove(os.path.join(MSG_DIR, f))
            except Exception:
                pass
    
    for i, t in enumerate(clean_templates):
        file_name = f"mau_tin_{i+1}.txt"
        with open(os.path.join(MSG_DIR, file_name), "w", encoding="utf-8") as fp:
            fp.write(t)
    
    add_log("INFO", "SYSTEM", "TEMPLATE", f"Đã lưu {len(clean_templates)} mẫu tin nhắn chiến dịch")
    return jsonify({"status": "ok", "count": len(clean_templates)})


@app.post("/start")
def start():
    global failed_rows, sent_rows_success, campaign_templates_global, campaign_generation, campaign_dispatched_phones, campaign_dispatched_rows
    excel_path = EXCEL_PATH
    if not os.path.exists(excel_path):
        return jsonify({"status": "no_file", "message": "Chưa có file dữ liệu Excel. Vui lòng tải file lên."}), 400

    data = request.get_json(silent=True) or {}
    camp_name = str(data.get("name", "")).strip()
    custom_templates = data.get("templates") or []
    clean_templates = [str(t).strip() for t in custom_templates if str(t).strip()]
    delay_min = float(data.get("delay_min", 5))
    delay_max = float(data.get("delay_max", 15))
    delay_unit = str(data.get("delay_unit", "minutes"))
    device_mode = data.get("device_mode", "ALL")
    ignore_cooldown = bool(data.get("ignore_cooldown", False))
    dedup_excel = bool(data.get("dedup_excel", True))

    if clean_templates:
        campaign_templates_global = clean_templates
    else:
        # Load from messages folder
        campaign_templates_global = []
        if os.path.exists(MSG_DIR):
            for f in os.listdir(MSG_DIR):
                if f.endswith(".txt"):
                    try:
                        with open(os.path.join(MSG_DIR, f), "r", encoding="utf-8") as fp:
                            c = fp.read().strip()
                        if c:
                            campaign_templates_global.append(c)
                    except Exception:
                        pass
    
    if not campaign_templates_global:
        campaign_templates_global = ["Xin chao {name}, chuc anh/chi mot ngay tot lanh!"]

    try:
        df, phone_col, name_col, gender_col, valid_rows, invalid_rows = parse_excel_file(excel_path)
    except Exception as error:
        add_log("FAIL", "SYSTEM", "EXCEL", f"Lỗi đọc file Excel: {error}")
        return jsonify({"status": "excel_error", "message": str(error)}), 400

    if not valid_rows:
        return jsonify({"status": "no_valid_phone", "message": "Không tìm thấy số điện thoại hợp lệ nào trong file Excel"}), 400

    # Lọc trùng số điện thoại trong danh sách (nếu bật dedup_excel)
    if dedup_excel:
        seen_batch_phones = set()
        deduped_valid_rows = []
        for row in valid_rows:
            phone = normalize_phone(row.get("ĐT") or row.get("ĐIỆN THOẠI") or "")
            if not phone:
                continue
            if phone in seen_batch_phones:
                add_log("WARN", "SYSTEM", "EXCEL", f"⏩ Bỏ qua dòng trùng SĐT {phone} (Dòng {row.get('__excel_index__', 0) + 2})")
                continue
            seen_batch_phones.add(phone)
            deduped_valid_rows.append(row)
    else:
        deduped_valid_rows = valid_rows

    rows = [row for row in deduped_valid_rows if not campaign_row_was_sent(row)]
    skipped_sent = len(valid_rows) - len(rows)
    if not rows:
        return jsonify({
            "status": "all_sent",
            "message": f"Tất cả {skipped_sent} khách hàng đã gửi thành công trước đó. Không gửi lại.",
        }), 409

    # Kiểm tra bảo vệ chống spam (cooldown 24h)
    if not ignore_cooldown:
        cooldown_count = 0
        sample_phones = []
        for r in rows:
            ph = normalize_phone(r.get("ĐT") or r.get("ĐIỆN THOẠI") or "")
            if check_recent_successful_send(ph, cooldown_hours=24):
                cooldown_count += 1
                if len(sample_phones) < 3:
                    sample_phones.append(ph)
        if cooldown_count == len(rows):
            sample_str = ", ".join(sample_phones)
            return jsonify({
                "status": "all_cooldown",
                "message": f"Toàn bộ {len(rows)} số điện thoại ({sample_str}...) đã được gửi thành công trong vòng 24 giờ qua (Chế độ bảo vệ chống spam).\nBạn có muốn BỎ QUA kiểm tra 24h và gửi lại ngay không?",
                "cooldown_count": cooldown_count,
            }), 409
        elif cooldown_count > 0:
            add_log("WARN", "SYSTEM", "EXCEL", f"ℹ️ Có {cooldown_count}/{len(rows)} số đã gửi thành công gần đây (sẽ tự động bỏ qua nếu không bật 'Gửi lại số trong 24h')")

    stop_event.clear()
    with lock:
        campaign_generation += 1
        my_gen = campaign_generation
        campaign_dispatched_phones.clear()
        campaign_dispatched_rows.clear()
        stats.update({"total": len(rows), "sent": 0, "success": 0, "active_workers": 0})
        failed_rows = []
        sent_rows_success = []

    camp_id = uuid.uuid4().hex[:12]
    camp = Campaign(
        campaign_id=camp_id,
        name=camp_name or f"Chiến dịch {len(campaign_manager.campaigns) + 1}",
        rows=rows,
        templates=campaign_templates_global,
        delay_min=delay_min,
        delay_max=delay_max,
        delay_unit=delay_unit,
        device_mode=device_mode,
        ignore_cooldown=ignore_cooldown,
        dedup_excel=dedup_excel,
        excel_path=excel_path,
    )
    campaign_manager.enqueue(camp)

    add_log(
        "START", "SYSTEM", "SMS",
        f"Đưa vào hàng đợi: {camp.name} ({len(rows)} số) | Bỏ qua đã gửi/trùng: {skipped_sent} | Delay {delay_min}-{delay_max}s",
    )
    return jsonify({
        "status": "ok",
        "campaign_id": camp.id,
        "name": camp.name,
        "total": len(rows),
        "skipped_sent": skipped_sent,
        "templates_count": len(campaign_templates_global),
    }), 201


@app.get("/api/campaigns")
def api_campaigns():
    return jsonify({
        "status": "ok",
        "campaigns": campaign_manager.list_campaigns(),
        "running": campaign_manager.has_active_campaigns(),
    })


@app.post("/stop")
def stop():
    global campaign_generation
    campaign_manager.stop_all()
    with lock:
        stats["running"] = False
        campaign_generation += 1
    stop_event.set()
    add_log("INFO", "SYSTEM", "STOP", "Toàn bộ chiến dịch đã dừng lại.")
    return jsonify({"status": "ok", "message": "All campaigns stopped."})


@app.route("/log")
def api_log():
    return jsonify({
        "logs": logs,
        "version": log_version,
        "total": stats["total"],
        "sent": stats["sent"],
        "success": stats["success"],
        "running": stats["running"],
        "active_workers": stats["active_workers"],
        "signals": modem_signals,
        "adb": detect_adb_status(),
        "android_devices": [
            {
                "serial": device.serial,
                "model": device.model,
                "ready": device.ready,
                "detail": device.detail,
                "sims": list(device.sims) if hasattr(device, "sims") else []
            }
            for device in android_devices
        ],
    })


@app.route("/history")
def api_history():
    return jsonify({"rows": get_history(500)})


@app.route("/api/conversations")
def api_conversations():
    return jsonify({"conversations": get_conversations(200)})


@app.route("/api/messages")
def api_messages():
    phone = request.args.get("phone", "")
    if not phone:
        return jsonify({"messages": []})
    return jsonify({"phone": phone, "messages": get_messages_by_phone(phone)})


@app.route("/api/templates")
def api_templates():
    templates = []
    try:
        for f in sorted(os.listdir(MSG_DIR)):
            if f.endswith(".txt"):
                with open(os.path.join(MSG_DIR, f), "r", encoding="utf-8") as fp:
                    templates.append({"name": f, "content": fp.read().strip()})
    except Exception as e:
        print("Templates read error:", e)
    return jsonify({"templates": templates})


@app.route("/api/devices")
def api_devices():
    global android_devices
    adb = detect_adb_status()
    try:
        android_devices = android_transport.scan()
    except Exception:
        pass

    available_ports = {p.device for p in serial.tools.list_ports.comports()}
    for ser in list(modems):
        if ser.port not in available_ports:
            try:
                ser.close()
            except Exception:
                pass
            if ser in modems:
                modems.remove(ser)
            modem_signals.pop(ser.port, None)
            port_to_imei.pop(ser.port, None)

    android_list = [
        {
            "serial": d.serial,
            "model": d.model,
            "ready": d.ready,
            "detail": d.detail,
            "sims": list(d.sims) if hasattr(d, "sims") else []
        }
        for d in android_devices
    ]
    usb_list = [
        {"port": m.port, "signal": modem_signals.get(m.port, "?"), "imei": port_to_imei.get(m.port, "")}
        for m in modems
    ]
    return jsonify({
        "adb": adb,
        "android_devices": android_list,
        "usb_modems": usb_list,
    })


@app.post("/api/scan_wifi")
def api_scan_wifi():
    global android_devices
    add_log("INFO", "SYSTEM", "WIFI", "Đang tự động quét tìm thiết bị Android trên dải mạng Wi-Fi LAN...")
    try:
        connected = android_transport.scan_wifi_network()
        android_devices = android_transport.scan()
        ready_devices = [d for d in android_devices if d.ready]
        if connected:
            add_log("SUCCESS", "SYSTEM", "WIFI", f"Đã kết nối Wi-Fi thành công {len(connected)} máy: {', '.join(connected)}")
        else:
            if ready_devices:
                add_log("INFO", "SYSTEM", "WIFI", f"Đã có {len(ready_devices)} thiết bị Android sẵn sàng")
            else:
                add_log("WARN", "SYSTEM", "WIFI", "Chưa tìm thấy máy Android nào mở cổng 5555 trên Wi-Fi")
        
        return jsonify({
            "status": "ok",
            "connected": connected,
            "android_devices": [
                {
                    "serial": d.serial,
                    "model": d.model,
                    "ready": d.ready,
                    "detail": d.detail,
                    "sims": list(d.sims) if hasattr(d, "sims") else []
                }
                for d in android_devices
            ],
            "ready_count": len(ready_devices)
        })
    except Exception as error:
        add_log("FAIL", "SYSTEM", "WIFI", f"Lỗi quét Wi-Fi: {error}")
        return jsonify({"status": "error", "message": str(error)}), 400


@app.post("/api/discover_wifi_devices")
def api_discover_wifi_devices():
    try:
        devices = android_transport.discover_wifi_devices_info()
        return jsonify({"status": "ok", "devices": devices})
    except Exception as error:
        return jsonify({"status": "error", "message": str(error)}), 400


@app.post("/api/connect_device")
@app.post("/api/connect_wifi_ip")
def api_connect_device():
    global android_devices
    data = request.get_json(silent=True) or {}
    target = str(data.get("target") or data.get("ip") or "").strip()
    if not target:
        return jsonify({"status": "error", "message": "Vui lòng nhập địa chỉ IP thiết bị"}), 400

    if target.startswith("cloud:"):
        android_devices = android_transport.scan()
        ready_devices = [d for d in android_devices if d.ready]
        return jsonify({"status": "ok", "message": "Thiết bị Wi-Fi App đã kết nối sẵn sàng", "devices": [d.serial for d in ready_devices]})

    add_log("INFO", "SYSTEM", "WIFI", f"Đang kết nối tới thiết bị: {target}...")
    ok, out = android_transport.connect_wifi(target)
    android_devices = android_transport.scan()
    ready_devices = [d for d in android_devices if d.ready]
    if ok:
        add_log("SUCCESS", "SYSTEM", "WIFI", f"Đã kết nối thành công: {target}")
        return jsonify({"status": "ok", "message": out, "devices": [d.serial for d in ready_devices]})
    else:
        add_log("WARN", "SYSTEM", "WIFI", f"Lỗi kết nối tới {target}: {out}")
        return jsonify({"status": "error", "message": out}), 400


@app.post("/api/connect_all_wifi")
def api_connect_all_wifi():
    global android_devices
    add_log("INFO", "SYSTEM", "WIFI", "Đang tự động kết nối toàn bộ thiết bị Android trên Wi-Fi...")
    try:
        devices = android_transport.discover_wifi_devices_info()
        connected_list = []
        for dev in devices:
            target = dev.get("target")
            if target:
                if str(target).startswith("cloud:"):
                    connected_list.append(target)
                    continue
                try:
                    ok, _ = android_transport.connect_wifi(target)
                    if ok:
                        connected_list.append(target)
                except Exception:
                    pass
        
        android_devices = android_transport.scan()
        ready_devices = [d for d in android_devices if d.ready]
        add_log("SUCCESS", "SYSTEM", "WIFI", f"Đã kết nối {len(connected_list)} máy Wi-Fi. Sẵn sàng: {len(ready_devices)} máy.")
        return jsonify({
            "status": "ok",
            "connected": connected_list,
            "ready_count": len(ready_devices),
            "devices": [d.serial for d in ready_devices]
        })
    except Exception as error:
        return jsonify({"status": "error", "message": str(error)}), 400


@app.post("/api/disconnect_device")
def api_disconnect_device():
    global android_devices
    data = request.get_json(silent=True) or {}
    target = str(data.get("target", "")).strip()
    if not target:
        return jsonify({"status": "error", "message": "Vui lòng chỉ định thiết bị"}), 400

    ok, out = android_transport.disconnect_wifi(target)
    android_devices = android_transport.scan()
    add_log("INFO", "SYSTEM", "WIFI", f"Đã ngắt kết nối thiết bị: {target}")
    return jsonify({"status": "ok", "message": out})


@app.post("/api/install_app")
def api_install_app():
    global android_devices
    data = request.get_json(silent=True) or {}
    raw_serial = data.get("serial")
    serial = str(raw_serial).strip() if raw_serial and str(raw_serial).lower() not in ["none", "null", "undefined", ""] else None
    
    # If no serial provided, install to all connected/authorized android devices
    scanned = android_transport.scan()
    offline_before_recovery = [d.serial for d in scanned if d.detail == "offline"]
    if offline_before_recovery:
        add_log("INFO", "SYSTEM", "ADB", "Phát hiện thiết bị offline, đang tự kết nối lại ADB...")
        recovered = android_transport.recover_offline_devices(offline_before_recovery)
        if recovered:
            add_log("SUCCESS", "SYSTEM", "ADB", "Đã kết nối lại: " + ", ".join(recovered))
        scanned = android_transport.scan()
    if not any(d.detail not in {"unauthorized", "offline"} for d in scanned):
        try:
            android_transport.scan_wifi_network()
            scanned = android_transport.scan()
        except Exception:
            pass

    offline = [d.serial for d in scanned if d.detail == "offline"]
    if serial and serial in offline:
        return jsonify({
            "status": "offline",
            "message": f"Thiết bị {serial} vẫn offline. Không cài APK khi ADB chưa ở trạng thái device.",
        }), 409

    targets = [serial] if serial else [d.serial for d in scanned if d.detail not in {"unauthorized", "offline"}]
    
    if not targets:
        unauthorized = [d.serial for d in scanned if d.detail == "unauthorized"]
        if unauthorized:
            return jsonify({
                "status": "error",
                "message": "Thiết bị đang ở trạng thái CẦN CẤP QUYỀN (unauthorized).\nVui lòng mở màn hình điện thoại và bấm 'Cho phép gỡ lỗi USB' / 'Luôn cho phép'."
            }), 400
        if offline:
            return jsonify({
                "status": "offline",
                "message": "ADB vẫn offline: " + ", ".join(offline) + ". Kiểm tra lại mạng/IP điện thoại rồi bấm Kết nối lại.",
            }), 409
        return jsonify({"status": "error", "message": "Không tìm thấy thiết bị Android nào đang kết nối để cài đặt."}), 400

    results = []
    for s in targets:
        add_log("INFO", "SYSTEM", s, "Đang cài đặt App SMS Bridge và tự động cấp quyền...")
        ok, msg = android_transport.install_app(s)
        if ok:
            add_log("SUCCESS", "SYSTEM", s, f"Cài đặt App thành công: {msg}")
            results.append({"serial": s, "status": "ok", "message": msg})
        else:
            add_log("FAIL", "SYSTEM", s, f"Lỗi cài đặt App: {msg}")
            results.append({"serial": s, "status": "error", "message": msg})

    android_devices = android_transport.scan()
    all_ok = all(r["status"] == "ok" for r in results)
    
    if not all_ok:
        err_msgs = [f"[{r['serial']}]: {r['message']}" for r in results if r["status"] != "ok"]
        return jsonify({
            "status": "error",
            "results": results,
            "message": "Không thể cài đặt App:\n" + "\n".join(err_msgs)
        }), 400

    return jsonify({
        "status": "ok",
        "results": results,
        "message": "🎉 Đã cài đặt App thành công, tự động cấp quyền SMS và mở App trên điện thoại!"
    })


@app.post("/api/send_sms")
def api_send_sms():
    data = request.get_json(silent=True) or {}
    phone = str(data.get("phone", "")).strip()
    message = str(data.get("message", "")).strip()
    name = str(data.get("name", "Anh/Chị")).strip() or "Anh/Chị"
    device_id = data.get("device_id") or None
    transport = data.get("transport", "AUTO")

    ok, res = send_direct_sms(phone, message, customer_name=name, device_id=device_id, transport=transport)
    if ok:
        return jsonify({"status": "ok", "data": res})
    else:
        return jsonify({"status": "error", "message": str(res)}), 400


@app.route("/android-events")
def api_android_events():
    return jsonify({"rows": get_android_event_rows()})


@app.post("/api/zalo/open")
def api_zalo_open():
    data = request.get_json(silent=True) or {}
    ok, message = open_zalo_profile(data.get("slot"))
    return jsonify({"status": "ok" if ok else "error", "message": message}), (200 if ok else 400)

@app.post("/api/zalo/reset")
def api_zalo_reset():
    data = request.get_json(silent=True) or {}
    ok, message = reset_zalo_profile(data.get("slot"))
    return jsonify({"status": "ok" if ok else "error", "message": message}), (200 if ok else 400)

@app.post("/delivery")
def api_delivery():
    total = 0
    for ser in list(modems):
        imei = port_to_imei.get(ser.port, ser.port)
        modem_lock = imei_locks.setdefault(imei, threading.Lock())
        if not modem_lock.acquire(blocking=False):
            continue
        try:
            total += poll_delivery_reports(ser)
        except Exception as error:
            add_log("WARN", "SYSTEM", ser.port, f"CDS poll error: {error}")
        finally:
            modem_lock.release()
    total += poll_android_events()
    return jsonify({"status": "ok", "updated": total})


@app.route("/history.csv")
def export_history():
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "id", "created_at", "updated_at", "phone", "customer_name",
            "modem_port", "template_name", "message", "status", "modem_response",
            "message_ref", "delivery_status",
            "transport", "device_id", "external_job_id", "campaign_row",
        ],
        extrasaction="ignore",
    )
    writer.writeheader()
    writer.writerows(reversed(get_history(100000)))
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=sms_history.csv"},
    )


@app.post("/shutdown")
def shutdown():
    add_log("INFO", "SYSTEM", "EXIT", "Đang tắt ứng dụng...")
    global modems
    stop()
    for m in modems:
        try:
            m.close()
        except Exception:
            pass
    modems.clear()
    modem_signals.clear()
    port_to_imei.clear()

    def kill_proc():
        time.sleep(1)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=kill_proc).start()
    return jsonify({"status": "closing"})


@app.get("/download/apk")
@app.get("/app")
def download_apk():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, "templates", "SmsBridgeSender.apk"),
        os.path.join(base_dir, "android_sender", "SmsBridgeSender-debug.apk"),
        os.path.join(base_dir, "android_sender", "app", "SmsBridgeSender-debug.apk"),
        os.path.join(getattr(sys, "_MEIPASS", base_dir), "templates", "SmsBridgeSender.apk"),
        os.path.join(getattr(sys, "_MEIPASS", base_dir), "android_sender", "SmsBridgeSender-debug.apk"),
        os.path.join(os.path.dirname(sys.executable), "templates", "SmsBridgeSender.apk"),
        os.path.join(os.path.dirname(sys.executable), "android_sender", "SmsBridgeSender-debug.apk"),
        os.path.join(os.path.dirname(sys.executable), "_internal", "android_sender", "SmsBridgeSender-debug.apk"),
    ]
    apk = next((c for c in candidates if c and os.path.isfile(c)), None)
    if apk and os.path.isfile(apk):
        return send_file(
            apk,
            as_attachment=True,
            download_name="SmsBridgeSender.apk",
            mimetype="application/vnd.android.package-archive",
        )
    return jsonify({"error": "APK not found"}), 404


@app.get("/api/network_info")
def get_network_info():
    import socket
    local_ips = []

    # 1. Parse ipconfig to detect all adapters including Windows Mobile Hotspot (192.168.137.1)
    try:
        cmd = ["ipconfig"] if platform.system() == "Windows" else ["ifconfig"]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=2,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if platform.system() == "Windows" else 0
        )
        for match in re.finditer(r"(?:IPv4 Address|inet)[.\s:]+([\d.]+)", res.stdout):
            ip = match.group(1).strip()
            if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip):
                if not ip.startswith(("127.", "169.254.", "224.", "255.")) and not ip.endswith(".255"):
                    if ip not in local_ips:
                        local_ips.append(ip)
    except Exception:
        pass

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        primary_ip = s.getsockname()[0]
        s.close()
        if primary_ip not in local_ips and not primary_ip.startswith("127."):
            local_ips.append(primary_ip)
    except Exception:
        primary_ip = "127.0.0.1"

    # Real primary IP connected to gateway / internet
    real_wifi_ip = ""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        real_wifi_ip = s.getsockname()[0]
        s.close()
        if real_wifi_ip not in local_ips and not real_wifi_ip.startswith("127."):
            local_ips.append(real_wifi_ip)
    except Exception:
        real_wifi_ip = local_ips[0] if local_ips else "127.0.0.1"

    has_hotspot = "192.168.137.1" in local_ips
    # Priority for master_lan_ip: Real Wi-Fi network IP first!
    if real_wifi_ip and real_wifi_ip != "127.0.0.1" and real_wifi_ip != "192.168.137.1":
        master_lan_ip = real_wifi_ip
    else:
        non_hotspot = [ip for ip in local_ips if ip != "192.168.137.1"]
        master_lan_ip = non_hotspot[0] if non_hotspot else (local_ips[0] if local_ips else "127.0.0.1")

    primary_ip = master_lan_ip

    wan_ip = ""
    try:
        wan_ip = requests.get("https://api.ipify.org", timeout=2).text.strip()
        socket.inet_aton(wan_ip)
    except Exception:
        wan_ip = ""

    server_port = request.environ.get("SERVER_PORT", "5000")
    download_urls = [f"http://{ip}:{server_port}/download/apk" for ip in local_ips]
    return jsonify({
        "primary_ip": primary_ip,
        "master_lan_ip": master_lan_ip,
        "master_lan_url": f"http://{master_lan_ip}:8765",
        "master_web_url": f"http://{master_lan_ip}:{server_port}",
        "hotspot_ip": "192.168.137.1" if has_hotspot else "",
        "hotspot_url": "http://192.168.137.1:8765" if has_hotspot else "",
        "server_port": server_port,
        "wan_ip": wan_ip,
        "all_ips": local_ips,
        "download_urls": download_urls,
        "download_url": f"http://{master_lan_ip}:{server_port}/download/apk",
    })


# ==============================================================================
# CLOUD BRIDGE ENDPOINTS FOR 100% WIRELESS ANDROID APP (NO CABLE / NO ADB)
# Compatible with vn.smsbridge.sender companion app (CloudSyncService)
# ==============================================================================

def _parse_cloud_sims_header():
    raw = request.headers.get("X-Device-Sims", "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, list) and data:
            return data
    except Exception:
        pass
    try:
        import urllib.parse
        data = json.loads(urllib.parse.unquote(raw))
        if isinstance(data, list) and data:
            return data
    except Exception:
        pass
    try:
        import base64
        data = json.loads(base64.b64decode(raw.encode("ascii")).decode("utf-8"))
        if isinstance(data, list) and data:
            return data
    except Exception:
        pass
    return None


@app.get("/v1/device/jobs/next")
def device_jobs_next():
    device_id = request.headers.get("X-Device-Id", "").strip() or "android-01"
    token = request.headers.get("X-Device-Token", "").strip()
    remote_ip = request.remote_addr or ""
    sims = _parse_cloud_sims_header()
    android_transport.record_cloud_device(device_id, ip=remote_ip, sims=sims)
    job = android_transport.get_next_cloud_job(device_id)
    if job:
        return jsonify(job), 200
    return ("", 204)


@app.post("/v1/device/jobs/<job_id>/result")
def device_jobs_result(job_id: str):
    device_id = request.headers.get("X-Device-Id", "").strip() or "android-01"
    remote_ip = request.remote_addr or ""
    sims = _parse_cloud_sims_header()
    android_transport.record_cloud_device(device_id, ip=remote_ip, sims=sims)
    payload = request.get_json(silent=True) or {}
    status = str(payload.get("status", "")).upper()
    detail = str(payload.get("detail", ""))
    phone = str(payload.get("phone", "")).strip()
    message = str(payload.get("message", "")).strip()
    sub_id = payload.get("subscription_id", -1)

    if status == "QUEUED":
        history_status = "ANDROID_QUEUED"
        delivery_status = "Đang gửi từ điện thoại..."
    elif status == "DELIVERED":
        history_status = "DELIVERED"
        delivery_status = "Đã giao đến người nhận"
    elif status in {"SENT", "SUBMITTED"}:
        history_status = "SUBMITTED"
        delivery_status = "Đã nộp cho nhà mạng, chờ báo cáo giao (chưa xác nhận)"
    elif status == "UNCONFIRMED":
        history_status = "UNCONFIRMED"
        delivery_status = detail or "Chưa có báo cáo giao tin (UNCONFIRMED)"
    elif status == "FAILED":
        history_status = "FAILED"
        delivery_status = detail or "Lỗi gửi SMS"
    else:
        history_status = status
        delivery_status = detail or status

    sim_label = f" (SIM {sub_id})" if sub_id is not None and int(sub_id) >= 0 else ""
    update_android_status(f"cloud:{device_id}", job_id, history_status, detail or delivery_status, phone=phone, message=message, delivery_status=delivery_status)
    
    cloud_android_events.append({
        "device_id": f"cloud:{device_id}",
        "model": f"Wi-Fi App: {device_id}{sim_label}",
        "job_id": job_id,
        "subscription_id": sub_id,
        "status": "SUCCESS" if history_status == "DELIVERED" else ("PENDING" if history_status in {"ANDROID_QUEUED", "SUBMITTED"} else ("UNCONFIRMED" if history_status == "UNCONFIRMED" else "FAILED")),
        "latest_stage": status,
        "error": detail if history_status == "FAILED" else "",
        "response": detail or delivery_status,
    })
    if len(cloud_android_events) > 200:
        cloud_android_events.pop(0)

    if history_status == "DELIVERED":
        add_log("SUCCESS", "APP", f"{device_id}{sim_label}", f"Máy Android {device_id}{sim_label}: {delivery_status} ({job_id[:8]})")
    elif history_status == "SUBMITTED":
        add_log("INFO", "APP", f"{device_id}{sim_label}", f"Máy Android {device_id}{sim_label}: {delivery_status} ({job_id[:8]})")
    elif history_status == "UNCONFIRMED":
        add_log("WARN", "APP", f"{device_id}{sim_label}", f"Máy Android {device_id}{sim_label}: Chưa xác nhận giao ({job_id[:8]})")
    elif history_status == "FAILED":
        add_log("FAIL", "APP", f"{device_id}{sim_label}", f"Máy Android {device_id}{sim_label} báo lỗi: {detail or 'Thất bại'}")
    elif history_status == "ANDROID_QUEUED":
        add_log("INFO", "APP", f"{device_id}{sim_label}", f"Máy Android {device_id}{sim_label} đã nhận lệnh gửi: {job_id[:8]}...")
    return jsonify({"status": "ok"})


current_web_port = 5000

def _udp_discovery_responder():
    try:
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        udp_sock.bind(("0.0.0.0", 8766))
        while True:
            data, addr = udp_sock.recvfrom(1024)
            msg = data.decode("utf-8", errors="ignore")
            if "DISCOVER_SMS_MASTER" in msg:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    s.connect(("8.8.8.8", 80))
                    my_ip = s.getsockname()[0]
                except Exception:
                    my_ip = "127.0.0.1"
                finally:
                    s.close()
                resp = json.dumps({
                    "service": "SMS_BRIDGE_MASTER",
                    "ip": my_ip,
                    "lan_port": 8765,
                    "web_port": current_web_port,
                    "lan_url": f"http://{my_ip}:8765",
                    "web_url": f"http://{my_ip}:{current_web_port}",
                }).encode("utf-8")
                udp_sock.sendto(resp, addr)
    except Exception as e:
        print(f"Notice: UDP discovery responder: {e}", flush=True)

@app.get("/v1/devices")
def cloud_list_devices():
    active = android_transport.get_active_cloud_devices()
    return jsonify({"devices": active})


@app.get("/health")
def cloud_health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


def _start_master_lan_port8765():
    try:
        from werkzeug.serving import run_simple
        run_simple("0.0.0.0", 8765, app, threaded=True)
    except Exception as e:
        print(f"Notice: Port 8765 background server: {e}", flush=True)


def _start_background_listeners():
    threading.Thread(target=_udp_discovery_responder, daemon=True).start()
    threading.Thread(target=_start_master_lan_port8765, daemon=True).start()


@app.post("/update")
def check_update():
    return jsonify({"status": "disabled", "message": "Remote self-update is disabled."}), 410


@app.route("/")
def home():
    if getattr(sys, "frozen", False):
        bundle = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    else:
        bundle = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(bundle, "templates", "index.html"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "index.html"),
        os.path.join(os.path.dirname(sys.executable), "templates", "index.html"),
        os.path.join(os.getcwd(), "templates", "index.html"),
    ]
    html_path = next((c for c in candidates if os.path.isfile(c)), candidates[0])
    with open(html_path, "r", encoding="utf-8") as fp:
        html_code = fp.read()
    resp = Response(html_code, mimetype="text/html; charset=utf-8")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


if __name__ == "__main__":
    if not check_license():
        print("❌ License mismatch", flush=True)
        input("Nhấn Enter để thoát...")
        sys.exit(0)
    _start_background_listeners()
    port = 5000

    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("localhost", port)) != 0:
                break
            port += 1

    current_web_port = port
    Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    
    # Auto-scan devices 1 second after startup
    def auto_init_scan():
        time.sleep(1)
        try:
            connect()
        except Exception:
            pass
    threading.Thread(target=auto_init_scan, daemon=True).start()

    signal_thread = threading.Thread(target=update_signal_loop, daemon=True)
    signal_thread.start()
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
