import re

with open("launcher.py", "r", encoding="utf-8") as f:
    code = f.read()

# 1. Update imports to include send_file
if "send_file" not in code:
    code = code.replace("from flask import Flask, Response, jsonify, request", "from flask import Flask, Response, jsonify, request, send_file")

# 2. Add sample excel creation and enhanced parser & get_final_message
sample_gen_code = """def create_sample_excel_file():
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


def get_final_message(customer_name, custom_templates=None, gender=None):
    try:
        raw_name = str(customer_name).strip() if customer_name else ""
        if raw_name.lower() in ["nan", "none", "null", ""]:
            raw_name = ""
        
        # Lấy ĐÚNG 1 chữ cuối cùng của tên (Ví dụ: Nguyễn Văn Tuấn -> Tuấn)
        name_parts = raw_name.split() if raw_name else []
        single_name = name_parts[-1] if name_parts else ""

        # Xác định xưng hô theo giới tính (1: Nam -> Anh, 0: Nữ -> Chị)
        gender_str = str(gender).strip().lower() if gender is not None else ""
        if gender_str in ["1", "1.0", "nam", "anh", "m", "male"]:
            xungho = "Anh"
            full_display_name = f"Anh {single_name}" if single_name else "Anh"
        elif gender_str in ["0", "0.0", "nu", "nữ", "chi", "chị", "f", "female"]:
            xungho = "Chị"
            full_display_name = f"Chị {single_name}" if single_name else "Chị"
        else:
            xungho = "Anh/Chị"
            full_display_name = single_name if single_name else "Anh/Chị"

        if not single_name:
            single_name = full_display_name

        def apply_replacements(text):
            t = text
            t = t.replace("{xungho}", xungho)
            t = t.replace("{ten}", single_name)
            t = t.replace("{name}", full_display_name)
            t = t.replace("{fullname}", raw_name or full_display_name)
            t = t.replace("{hoten}", raw_name or full_display_name)
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
"""

# Replace parse_excel_file and get_final_message
pattern_helpers = r"def parse_excel_file\(file_path_or_buffer\):[\s\S]*?return f\"Xin chao \{customer_name\}\", f\"error_\{err\}\""
code = re.sub(pattern_helpers, sample_gen_code.strip(), code, count=1)

# Now update worker and android_worker to pass gender
pattern_worker = r"name = str\(r\.get\(\"TÊN\", \"Anh/Chị\"\)\)\s+msg, used_file = get_final_message\(name, custom_templates\)"
code = re.sub(
    pattern_worker,
    'name = str(r.get("TÊN", ""))\n        gender = r.get("GIỚI TÍNH")\n        msg, used_file = get_final_message(name, custom_templates, gender=gender)',
    code
)

pattern_android_worker = r"name = str\(row\.get\(\"TÊN\", \"Anh/Chị\"\)\)\s+message, used_file = get_final_message\(name, custom_templates\)"
code = re.sub(
    pattern_android_worker,
    'name = str(row.get("TÊN", ""))\n        gender = row.get("GIỚI TÍNH")\n        message, used_file = get_final_message(name, custom_templates, gender=gender)',
    code
)

# Now add @app.get("/api/download_template") and update /api/upload_excel and /api/campaign_info
new_routes = """@app.get("/api/download_template")
def api_download_template():
    sample_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dulieu_mau.xlsx")
    if not os.path.exists(sample_path):
        create_sample_excel_file()
    return send_file(
        sample_path,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="dulieu_mau.xlsx"
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
        df, phone_col, name_col, gender_col, valid_rows, invalid_rows = parse_excel_file(save_path)
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
            df, phone_col, name_col, gender_col, valid_rows, invalid_rows = parse_excel_file(excel_path)
            info["has_excel"] = True
            info["total_valid"] = len(valid_rows)
            info["total_invalid"] = len(invalid_rows)
            info["phone_col"] = phone_col
            info["name_col"] = name_col
            info["gender_col"] = gender_col
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
    return jsonify(info)"""

pattern_old_routes = r"@app\.post\(\"/api/upload_excel\"\)[\s\S]*?info\[\"templates\"\] = templates\s+return jsonify\(info\)"
code = re.sub(pattern_old_routes, new_routes.strip(), code, count=1)

# Also update start() to handle df, phone_col, name_col, gender_col, valid_rows, invalid_rows
pattern_parse_in_start = r"df, phone_col, name_col, valid_rows, invalid_rows = parse_excel_file\(excel_path\)"
code = re.sub(pattern_parse_in_start, "df, phone_col, name_col, gender_col, valid_rows, invalid_rows = parse_excel_file(excel_path)", code)

with open("launcher.py", "w", encoding="utf-8") as f:
    f.write(code)

print("launcher.py updated with Gender 0/1, Single-word name extraction, and Template Download!")
