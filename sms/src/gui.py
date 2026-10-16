import os
import time
import random
import re
import threading
import pandas as pd
import serial
import serial.tools.list_ports
from flask import Flask, jsonify
from datetime import datetime

app = Flask(__name__)

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE, "data", "contacts.xlsx")
MSG_DIR = os.path.join(BASE, "messages")

running = False
modems = []
logs = []
total_tasks = 0
sent_count = 0
success_count = 0
lock = threading.Lock()

def text_to_ucs2_hex(text):
    return text.encode('utf-16-be').hex().upper()

def phone_to_ucs2_hex(phone):
    return phone.encode('utf-16-be').hex().upper()

def clean_phone(phone_raw):
    """Xử lý SĐT: Bỏ .0, xóa rác, đổi 84 -> 0"""
    if pd.isna(phone_raw): return ""
    phone = str(phone_raw).split('.')[0].strip()
    phone = re.sub(r'\D', '', phone) # Xóa hết ký tự không phải số
    if phone.startswith('84'):
        phone = '0' + phone[2:]
    return phone

def add_log(status, phone, modem_port, message, detail=""):
    now = datetime.now().strftime("%H:%M:%S")
    short_msg = (message[:35] + '...') if len(message) > 35 else message
    icons = {"SUCCESS": "✅", "FAIL": "❌", "WARN": "⚠️", "INFO": "📡"}
    icon = icons.get(status, "🔹")
    
    log_entry = f"[{now}] {icon} | {modem_port:<8} | {phone:<11} | {status:<8} | {short_msg}"
    if detail: log_entry += f" ({detail})"
    
    with lock:
        logs.append(log_entry)
        if len(logs) > 400: logs.pop(0)
        print(log_entry)

def get_random_template():
    try:
        files = [x for x in os.listdir(MSG_DIR) if x.endswith(".txt")]
        if not files: return "Chao {name}, Shinhan Finance ho tro vay..."
        f = random.choice(files)
        with open(os.path.join(MSG_DIR, f), "r", encoding="utf8") as fp:
            return fp.read()
    except:
        return "Chao {name}, moi ban check uu dai vay..."

# --- GIAO TIẾP MODEM ---
def send_sms_ucs2(ser, phone, msg):
    ser.reset_input_buffer()
    ser.write(b"AT+CMGF=1\r")
    time.sleep(0.5)
    ser.write(b'AT+CSCS="UCS2"\r')
    time.sleep(0.5)
    
    hex_phone = phone_to_ucs2_hex(phone)
    hex_msg = text_to_ucs2_hex(msg)
    
    ser.write(f'AT+CMGS="{hex_phone}"\r'.encode())
    time.sleep(1.5) # Chờ dấu nhắc >
    ser.write(hex_msg.encode())
    ser.write(bytes([26])) # Gửi Ctrl+Z
    
    time.sleep(10) # ĐÃ TĂNG LÊN 10 GIÂY theo ý Hiền để modem xử lý Unicode
    resp = ser.read_all().decode(errors="ignore")
    
    if "ERROR" in resp:
        raise Exception(f"Modem Error: {resp.strip()}")
    return resp

# --- CÔNG NHÂN GỬI TIN (WORKER) ---
def worker(ser, rows):
    global sent_count, success_count, running
    port_name = ser.port

    for r in rows:
        if not running: break
        
        phone = clean_phone(r.get("ĐT", ""))
        if len(phone) < 9:
            add_log("WARN", "N/A", port_name, "N/A", "SĐT rỗng hoặc sai")
            continue
            
        name = str(r.get("TÊN", "Anh/Chị")).strip()
        raw_msg = get_random_template()
        try:
            msg = raw_msg.format(name=name)
        except:
            msg = raw_msg # Phòng trường hợp file txt không có chỗ điền {name}

        add_log("INFO", phone, port_name, msg, "Đang gửi...")
        
        ok = False
        error_detail = ""
        for attempt in range(2): # Thử lại tối đa 2 lần
            try:
                send_sms_ucs2(ser, phone, msg)
                ok = True
                break
            except Exception as e:
                error_detail = str(e)
                time.sleep(5)

        with lock:
            sent_count += 1
            if ok:
                success_count += 1
                add_log("SUCCESS", phone, port_name, msg)
            else:
                add_log("FAIL", phone, port_name, msg, error_detail)
        
        # Nghỉ giữa mỗi số để tránh bị nhà mạng khóa sim
        time.sleep(random.uniform(12, 25))

# --- WEB GIAO DIỆN ---
@app.route("/")
def home():
    return """
    <html>
    <head>
        <title>SMS MODEM SVFC</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #121212; color: #e0e0e0; padding: 30px; }
            .card { background: #1e1e1e; padding: 20px; border-radius: 10px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
            .btn-group { margin: 20px 0; }
            button { padding: 12px 25px; margin-right: 10px; cursor: pointer; border: none; border-radius: 5px; font-weight: bold; transition: 0.3s; }
            .btn-blue { background: #007bff; color: white; }
            .btn-green { background: #28a745; color: white; }
            .btn-red { background: #dc3545; color: white; }
            button:hover { opacity: 0.8; transform: translateY(-2px); }
            #log-box { background: #000; border: 1px solid #333; padding: 15px; height: 500px; overflow-y: scroll; font-family: 'Consolas', monospace; font-size: 13px; color: #00ff00; }
            .status-bar { display: flex; justify-content: space-between; margin-bottom: 15px; font-size: 18px; font-weight: bold; border-bottom: 1px solid #333; padding-bottom: 10px; }
        </style>
    </head>
    <body>
        <div class="card">
            <h2>🚀 SMS MODEM TOOL - HIỀN SVFC</h2>
            <div class="status-bar">
                <div id="stat-progress">Tiến độ: 0/0</div>
                <div id="stat-success" style="color: #28a745;">Thành công: 0</div>
                <div id="stat-fail" style="color: #dc3545;">Thất bại: 0</div>
            </div>
            <div class="btn-group">
                <button class="btn-blue" onclick="run('/connect')">1. Tìm Modem</button>
                <button class="btn-green" onclick="run('/start')">2. Bắt đầu gửi</button>
                <button class="btn-red" onclick="run('/stop')">3. Dừng</button>
            </div>
            <div id="log-box">Chưa có hoạt động...</div>
        </div>

        <script>
            function run(url) { fetch(url); }
            function update() {
                fetch('/log').then(r => r.json()).then(data => {
                    const box = document.getElementById('log-box');
                    box.innerHTML = data.logs.join('<br>');
                    box.scrollTop = box.scrollHeight;
                    document.getElementById('stat-progress').innerText = `Tiến độ: ${data.sent}/${data.total}`;
                    document.getElementById('stat-success').innerText = `Thành công: ${data.success}`;
                    document.getElementById('stat-fail').innerText = `Thất bại: ${data.sent - data.success}`;
                });
            }
            setInterval(update, 2000);
        </script>
    </body>
    </html>
    """

@app.route("/connect")
def api_connect():
    global modems
    ports = [p.device for p in serial.tools.list_ports.comports()]
    modems = []
    for p in ports:
        try:
            s = serial.Serial(p, 115200, timeout=1)
            s.write(b"AT\r")
            time.sleep(0.5)
            if b"OK" in s.read(64):
                modems.append(s)
                add_log("SUCCESS", "Hệ thống", p, "Modem đã sẵn sàng")
        except: pass
    return "OK"

@app.route("/start")
def api_start():
    global running, total_tasks, sent_count, success_count
    if not modems: return "No Modem"
    if running: return "Running"
    
    try:
        df = pd.read_excel(DATA_PATH)
        rows = df.to_dict("records")
        total_tasks = len(rows)
        sent_count = 0
        success_count = 0
        running = True
        
        chunk = (total_tasks // len(modems)) + 1
        for i, ser in enumerate(modems):
            subset = rows[i*chunk : (i+1)*chunk]
            if subset:
                threading.Thread(target=worker, args=(ser, subset), daemon=True).start()
        
        add_log("INFO", "Hệ thống", "ALL", "Bắt đầu chạy tiến trình")
        return "OK"
    except Exception as e:
        add_log("FAIL", "Excel", "N/A", str(e))
        return "Error"

@app.route("/stop")
def api_stop():
    global running
    running = False
    add_log("WARN", "Hệ thống", "ALL", "Dừng gửi tin")
    return "STOP"

@app.route("/log")
def api_log():
    return jsonify({
        "logs": logs,
        "total": total_tasks,
        "sent": sent_count,
        "success": success_count
    })

if __name__ == "__main__":
    os.makedirs(os.path.join(BASE, "data"), exist_ok=True)
    os.makedirs(os.path.join(BASE, "messages"), exist_ok=True)
    app.run(port=5000)
