import re

with open("launcher.py", "r", encoding="utf-8") as f:
    code = f.read()

# Let's inspect get_final_message and replace it with enhanced version
old_get_final_msg = """def get_final_message(customer_name):
    try:
        name_parts = str(customer_name).strip().split()
        short_name = " ".join(name_parts[-2:]) if len(name_parts) >= 2 else customer_name
        txt_files = [f for f in os.listdir(MSG_DIR) if f.endswith(".txt")]
        if not txt_files:
            return "Xin chao", "default"
        file_name = random.choice(txt_files)
        with open(os.path.join(MSG_DIR, file_name), "r", encoding="utf-8") as f:
            content = f.read().strip()
        return content.replace("{name}", short_name), file_name
    except Exception:
        return "Xin chao", "error" """

new_helpers = """def parse_excel_file(file_path_or_buffer):
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

    for col in df.columns:
        c_upper = str(col).strip().upper()
        if not phone_col and c_upper in ["ĐT", "ĐIỆN THOẠI", "DIEN THOAI", "SDT", "SĐT", "PHONE", "SO_DIEN_THOAI", "DIEN_THOAI", "TEL", "MOBILE", "PHONE NUMBER"]:
            phone_col = col
        if not name_col and c_upper in ["TÊN", "TEN", "NAME", "HỌ TÊN", "HO TEN", "HỌ VÀ TÊN", "HO VA TEN", "HOTEN", "KHACH HANG", "KHÁCH HÀNG", "CUSTOMER", "FULLNAME"]:
            name_col = col

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
            raw_name = "Anh/Chị"
        
        row_dict = {str(k): ("" if pd.isna(v) else str(v).strip()) for k, v in row.items()}
        row_dict["ĐT"] = norm_p if norm_p else raw_phone
        row_dict["TÊN"] = raw_name if raw_name else "Anh/Chị"

        if norm_p:
            valid_rows.append(row_dict)
        else:
            invalid_rows.append(row_dict)

    return df, phone_col, name_col, valid_rows, invalid_rows


def get_final_message(customer_name, custom_templates=None):
    try:
        name_str = str(customer_name).strip() if customer_name else "Anh/Chị"
        if not name_str or name_str.lower() in ["nan", "none", "null", ""]:
            name_str = "Anh/Chị"
        
        name_parts = name_str.split()
        short_name = " ".join(name_parts[-2:]) if len(name_parts) >= 2 else name_str

        if custom_templates and len(custom_templates) > 0:
            template = random.choice(custom_templates)
            used_file = f"custom_template_{random.randint(1, len(custom_templates))}"
            content = template.replace("{name}", short_name)
            return content, used_file

        txt_files = [f for f in os.listdir(MSG_DIR) if f.endswith(".txt")]
        if not txt_files:
            return f"Xin chao {short_name}", "default"
        file_name = random.choice(txt_files)
        with open(os.path.join(MSG_DIR, file_name), "r", encoding="utf-8") as f:
            content = f.read().strip()
        return content.replace("{name}", short_name), file_name
    except Exception as err:
        return f"Xin chao {customer_name}", f"error_{err}"
"""

# Replace get_final_message
pattern_get_msg = r"def get_final_message\(customer_name\):[\s\S]*?return \"Xin chao\", \"error\""
code = re.sub(pattern_get_msg, new_helpers.strip(), code, count=1)

# Now update worker and android_worker
pattern_workers = r"def worker\(ser, rows\):[\s\S]*?def run_android_worker\(device, rows\):[\s\S]*?finish_worker\(\)"

new_workers = """campaign_templates_global = []

def worker(ser, rows, custom_templates=None, delay_min=5, delay_max=15):
    global failed_rows, sent_rows_success
    sent_count = 0

    for r in rows:
        if stop_event.is_set() or not stats["running"]:
            break

        phone = normalize_phone(r.get("ĐT") or r.get("ĐIỆN THOẠI") or "")
        if not phone:
            continue

        name = str(r.get("TÊN", "Anh/Chị"))
        msg, used_file = get_final_message(name, custom_templates)
        msg = normalize_message_for_modem(msg)
        imei = port_to_imei.get(ser.port, ser.port)
        history_id = create_history(phone, name, ser.port, used_file, msg)

        with imei_locks.setdefault(imei, threading.Lock()):
            ok, modem_response = send_sms_modem(ser, phone, msg)

        status = "MODEM_ACCEPTED" if ok else "FAILED"
        if ok:
            update_history_ref(history_id, modem_response.get("message_ref"), modem_response.get("response", ""))
            modem_log = modem_response.get("response", "")
        else:
            update_history(history_id, status, modem_response)
            modem_log = modem_response

        with lock:
            stats["sent"] += 1
            if ok:
                stats["success"] += 1
                sent_rows_success.append(r)
            else:
                failed_rows.append(r)

        add_log(
            "SUCCESS" if ok else "FAIL",
            phone,
            ser.port,
            f"{status} [{used_file}] {msg} | {modem_log}",
        )

        sent_count += 1
        if sent_count % 25 == 0:
            try:
                ser.write(b"AT+CMGD=1,4\\r")
                time.sleep(0.5)
                ser.read_all()
            except Exception:
                pass
        if sent_count == len(rows):
            add_log("INFO", "SYSTEM", ser.port, f"Worker finished sending {sent_count} SMS")
        else:
            delay = random.uniform(max(1, delay_min), max(delay_min + 1, delay_max))
            add_log("INFO", "SYSTEM", ser.port, f"Sleep {int(delay)}s before next SMS")
            time.sleep(delay)


def run_worker(ser, rows, custom_templates=None, delay_min=5, delay_max=15):
    try:
        worker(ser, rows, custom_templates, delay_min, delay_max)
    except Exception as error:
        add_log("FAIL", "SYSTEM", ser.port, f"Worker error: {error}")
    finally:
        finish_worker()


def android_worker(device, rows, custom_templates=None, delay_min=5, delay_max=15):
    global failed_rows, sent_rows_success
    for row in rows:
        if stop_event.is_set() or not stats["running"]:
            break
        phone = normalize_phone(row.get("ĐT") or row.get("ĐIỆN THOẠI") or "")
        if not phone:
            continue
        name = str(row.get("TÊN", "Anh/Chị"))
        message, used_file = get_final_message(name, custom_templates)
        history_id = create_history(
            phone, name, device.serial, used_file, message,
            transport="ANDROID", device_id=device.serial,
        )
        try:
            ok, job_id, detail = android_transport.send(device.serial, phone, message)
        except Exception as error:
            ok, job_id, detail = False, "", str(error)
        if ok:
            with get_db() as conn:
                conn.execute(
                    \"\"\"
                    UPDATE sms_history
                    SET status = 'ANDROID_QUEUED', external_job_id = ?, modem_response = ?, updated_at = ?
                    WHERE id = ?
                    \"\"\",
                    (job_id, detail, datetime.now().isoformat(timespec="seconds"), history_id),
                )
        else:
            update_history(history_id, "FAILED", detail)
        with lock:
            stats["sent"] += 1
            if ok:
                stats["success"] += 1
                sent_rows_success.append(row)
            else:
                failed_rows.append(row)
        add_log("SUCCESS" if ok else "FAIL", phone, device.serial, f"ANDROID {'QUEUED' if ok else 'FAILED'} [{used_file}] {detail}")
        if not stop_event.is_set():
            delay = random.uniform(max(1, delay_min), max(delay_min + 1, delay_max))
            time.sleep(delay)


def run_android_worker(device, rows, custom_templates=None, delay_min=5, delay_max=15):
    try:
        android_worker(device, rows, custom_templates, delay_min, delay_max)
    except Exception as error:
        add_log("FAIL", "SYSTEM", device.serial, f"Android worker error: {error}")
    finally:
        finish_worker()"""

code = re.sub(pattern_workers, new_workers.strip(), code, count=1)

# Now update start() and add /api/upload_excel, /api/campaign_info, /api/save_campaign_templates
pattern_start = r"@app\.post\(\"/start\"\)[\s\S]*?return jsonify\(\{\"status\": \"ok\"\}\)"

new_campaign_routes = """@app.post("/api/upload_excel")
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
    
    save_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dulieu.xlsx") if ext != ".csv" else os.path.join(os.path.dirname(os.path.abspath(__file__)), "dulieu.csv")
    file.save(save_path)
    if ext == ".csv":
        try:
            df_csv = pd.read_csv(save_path)
            excel_save = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dulieu.xlsx")
            df_csv.to_excel(excel_save, index=False)
        except Exception:
            pass

    try:
        df, phone_col, name_col, valid_rows, invalid_rows = parse_excel_file(save_path)
        add_log("INFO", "SYSTEM", "EXCEL", f"Tải lên {filename}: {len(valid_rows)} số hợp lệ, {len(invalid_rows)} số lỗi")
        return jsonify({
            "status": "ok",
            "filename": filename,
            "total_valid": len(valid_rows),
            "total_invalid": len(invalid_rows),
            "phone_col": phone_col,
            "name_col": name_col,
            "columns": [str(c) for c in df.columns],
            "preview": valid_rows[:8]
        })
    except Exception as error:
        add_log("FAIL", "SYSTEM", "EXCEL", f"Lỗi đọc file {filename}: {error}")
        return jsonify({"status": "error", "message": str(error)}), 400


@app.get("/api/campaign_info")
def api_campaign_info():
    excel_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dulieu.xlsx")
    info = {"has_excel": False, "filename": "dulieu.xlsx", "total_valid": 0, "total_invalid": 0, "preview": [], "templates": []}
    
    if os.path.exists(excel_path):
        try:
            df, phone_col, name_col, valid_rows, invalid_rows = parse_excel_file(excel_path)
            info["has_excel"] = True
            info["total_valid"] = len(valid_rows)
            info["total_invalid"] = len(invalid_rows)
            info["phone_col"] = phone_col
            info["name_col"] = name_col
            info["preview"] = valid_rows[:8]
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
    global failed_rows, sent_rows_success, campaign_templates_global
    excel_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dulieu.xlsx")
    if not os.path.exists(excel_path):
        return jsonify({"status": "no_file", "message": "Chưa có file dữ liệu Excel. Vui lòng tải file lên."}), 400

    ready_android = [device for device in android_devices if device.ready]
    if not modems and not ready_android:
        return jsonify({"status": "no_devices", "message": "Chưa có thiết bị nào (Android hoặc USB Modem) sẵn sàng."}), 400

    with lock:
        if stats["running"]:
            return jsonify({"status": "busy", "message": "Chiến dịch đang chạy."}), 409

    data = request.get_json(silent=True) or {}
    custom_templates = data.get("templates") or []
    clean_templates = [str(t).strip() for t in custom_templates if str(t).strip()]
    delay_min = int(data.get("delay_min", 5))
    delay_max = int(data.get("delay_max", 15))
    device_mode = data.get("device_mode", "ALL")

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
        df, phone_col, name_col, valid_rows, invalid_rows = parse_excel_file(excel_path)
    except Exception as error:
        add_log("FAIL", "SYSTEM", "EXCEL", f"Lỗi đọc file Excel: {error}")
        return jsonify({"status": "excel_error", "message": str(error)}), 400

    if not valid_rows:
        return jsonify({"status": "no_valid_phone", "message": "Không tìm thấy số điện thoại hợp lệ nào trong file Excel"}), 400

    rows = valid_rows
    stop_event.clear()
    with lock:
        stats.update({"total": len(rows), "sent": 0, "success": 0, "running": True, "active_workers": 0})
        failed_rows = []
        sent_rows_success = []

    workers = []
    if device_mode in ["ALL", "ANDROID"]:
        workers.extend([("ANDROID", device) for device in ready_android])
    if device_mode in ["ALL", "USB_MODEM"]:
        workers.extend([("USB_MODEM", modem) for modem in modems])

    if not workers:
        if ready_android:
            workers = [("ANDROID", device) for device in ready_android]
        elif modems:
            workers = [("USB_MODEM", modem) for modem in modems]
        else:
            return jsonify({"status": "no_devices", "message": "Không có thiết bị phù hợp sẵn sàng"}), 400

    worker_count = len(workers)
    for i, (transport, device) in enumerate(workers):
        subset = [rows[j] for j in range(len(rows)) if j % worker_count == i]
        if subset:
            with lock:
                stats["active_workers"] += 1
            target = run_worker if transport == "USB_MODEM" else run_android_worker
            threading.Thread(
                target=target,
                args=(device, subset, campaign_templates_global, delay_min, delay_max),
                daemon=True,
            ).start()

    add_log(
        "START", "SYSTEM", "SMS",
        f"Bắt đầu chiến dịch: {len(rows)} số | {len(campaign_templates_global)} mẫu tin cá nhân hóa | {len(workers)} thiết bị | Delay {delay_min}-{delay_max}s",
    )
    return jsonify({"status": "ok", "total": len(rows), "templates_count": len(campaign_templates_global)})"""

code = re.sub(pattern_start, new_campaign_routes.strip(), code, count=1)

with open("launcher.py", "w", encoding="utf-8") as f:
    f.write(code)

print("launcher.py successfully updated with Excel Import & Multi-template Personalized SMS!")
