#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

# 1. Tìm hoặc cài đặt Python môi trường ảo
PYTHON="${PYTHON:-python3}"
if [[ ! -x .venv/bin/python ]]; then
  echo "Đang tạo môi trường ảo Python .venv..."
  "$PYTHON" -m venv .venv
fi

.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt

# 2. Tự động tìm ADB trên Linux / macOS
find_adb() {
  if command -v adb >/dev/null 2>&1; then
    command -v adb
    return 0
  fi
  if [[ -n "${ADB_PATH:-}" && -x "$ADB_PATH" ]]; then
    echo "$ADB_PATH"
    return 0
  fi
  if [[ -n "${ANDROID_HOME:-}" && -x "$ANDROID_HOME/platform-tools/adb" ]]; then
    echo "$ANDROID_HOME/platform-tools/adb"
    return 0
  fi
  if [[ -n "${ANDROID_SDK_ROOT:-}" && -x "$ANDROID_SDK_ROOT/platform-tools/adb" ]]; then
    echo "$ANDROID_SDK_ROOT/platform-tools/adb"
    return 0
  fi

  local candidates=(
    "$HOME/Android/Sdk/platform-tools/adb"
    "$HOME/Library/Android/sdk/platform-tools/adb"
    "$HOME/.android-sdk/platform-tools/adb"
    "$HOME/platform-tools/adb"
    "/usr/bin/adb"
    "/usr/local/bin/adb"
    "/opt/android-sdk/platform-tools/adb"
    "/usr/lib/android-sdk/platform-tools/adb"
    "./platform-tools/adb"
    "./adb"
  )

  for c in "${candidates[@]}"; do
    if [[ -x "$c" ]]; then
      echo "$c"
      return 0
    fi
  done
  return 1
}

DETECTED_ADB=$(find_adb || true)
if [[ -n "$DETECTED_ADB" ]]; then
  echo "✅ Đã tìm thấy ADB: $DETECTED_ADB"
  export ADB_PATH="$DETECTED_ADB"
  export PATH="$(dirname "$DETECTED_ADB"):$PATH"
else
  echo "⚠️ Chưa tìm thấy ADB trên hệ thống (vẫn có thể dùng USB Modem)."
fi

echo "🚀 Đang khởi động SMS Messenger & Launcher..."
exec .venv/bin/python launcher.py
