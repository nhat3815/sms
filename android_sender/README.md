# SMS Bridge Sender

1. Mở thư mục `android_sender` bằng Android Studio.
2. Sync project với JDK 17, Android SDK 36.
3. Build/install bản debug vào điện thoại.
4. Mở app, bấm **Cấp quyền SMS**.
5. Bật Developer options + USB debugging, chấp nhận khóa RSA của máy Windows.
6. Desktop tool tự phát hiện thiết bị bằng `adb devices -l`.

Build CLI khi đã có Gradle 9.4.1:

```bat
gradle :app:assembleDebug
adb install -r app\build\outputs\apk\debug\app-debug.apk
```
