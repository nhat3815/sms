# SMS Cloud Controller

## 1. Chạy backend

```bash
export SMS_ADMIN_TOKEN="$(openssl rand -hex 32)"
export SMS_OPERATOR_TOKEN="$(openssl rand -hex 32)"
python cloud_server.py
```

Production phải đặt sau HTTPS reverse proxy và giữ hai token trong secret manager.

## 2. Tạo thông tin cho từng Android

```bash
curl -X POST https://sms.example.com/v1/admin/devices \
  -H "X-Admin-Token: $SMS_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Android 01"}'
```

Mở `Cloud` trong app Android, nhập URL HTTPS, `id`, `token` từ response rồi bật service.

## 3. Tạo app iOS

Tạo project SwiftUI iOS 16+ trong Xcode, thay file app mặc định bằng
`ios_controller/SmsControllerApp.swift`. Nhập URL backend và `SMS_OPERATOR_TOKEN`.

## Giới hạn

- iOS chỉ điều khiển; Android mới có quyền gửi SMS bằng SIM.
- Android hiện báo `QUEUED` ngay khi chuyển lệnh cho `SmsManager`. Đồng bộ chính xác
  `SENT/DELIVERED/FAILED` lên cloud cần uploader đọc `events.jsonl`.
- Foreground service hiện polling mỗi 5 giây. FCM nên dùng khi số thiết bị lớn.
