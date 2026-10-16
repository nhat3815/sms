# Android Master + Agent LAN

Build two APKs: `:master` and `:app`.

1. Cài `SMS Bridge Master` lên một Android, mở app để Master service chạy.
2. Ghi `Server` và `Token` trên màn Master.
3. Cài `SMS Bridge Sender` lên mọi Android Agent. Chọn `Cloud`, nhập Server, Agent ID riêng, Token rồi lưu.
4. Master gửi job đến Agent ID đã nhập.

## Master tự gửi SMS

Cài cả hai APK trên Master Android. Trong `SMS Bridge Sender > Cloud`, dùng:

```text
Server: http://127.0.0.1:8765
Agent ID: master
Token: token hiển thị trong SMS Bridge Master
```

Master service phải chạy foreground, các máy phải cùng Wi-Fi/hotspot, và tắt battery optimization cho cả hai app.
