import base64
import subprocess
import unittest
from unittest.mock import patch

from android_transport import AndroidTransport, resolve_adb_path


class AndroidTransportSelfCheck(unittest.TestCase):
    def test_scan_marks_bridge_ready(self):
        def runner(command, **_kwargs):
            if command[1:3] == ["devices", "-l"]:
                return subprocess.CompletedProcess(command, 0, "List of devices attached\nABC123 device model:Pixel_7\n", "")
            return subprocess.CompletedProcess(command, 0, "package:vn.smsbridge.sender\n", "")

        devices = AndroidTransport(adb_path="adb", runner=runner).scan()
        self.assertEqual(1, len(devices))
        self.assertTrue(devices[0].ready)
        self.assertEqual("ABC123", devices[0].serial)

    def test_send_encodes_message_base64_and_preserves_full_text(self):
        captured_commands = []

        def runner(command, **_kwargs):
            captured_commands.append(command)
            if "run-as" in command:
                return subprocess.CompletedProcess(command, 0, "dummy-token\n", "")
            return subprocess.CompletedProcess(command, 0, "Broadcast completed: result=0\n", "")

        transport = AndroidTransport(adb_path="adb", runner=runner)
        multi_word_message = "Xin chào Nguyễn Văn A! Gói vay 50tr lãi suất 0.8%."
        ok, job_id, detail = transport.send("DEVICE123", "0912345678", multi_word_message)

        self.assertTrue(ok)
        self.assertTrue(len(job_id) > 0)
        self.assertIn("Broadcast completed", detail)

        # Verify am broadcast call arguments
        broadcast_cmd = captured_commands[-1]
        self.assertIn("--es", broadcast_cmd)
        
        # Check message_b64
        b64_idx = broadcast_cmd.index("message_b64") + 1
        b64_val = broadcast_cmd[b64_idx]
        decoded_b64 = base64.b64decode(b64_val.encode("ascii")).decode("utf-8")
        self.assertEqual(multi_word_message, decoded_b64)

        # Verify message_b64 is present and decoded properly
        self.assertIn("message_b64", broadcast_cmd)

    def test_summarize_events_requires_all_parts(self):
        events = [
            {"job_id": "job", "stage": "SENT", "part_index": 0, "part_count": 2, "result_code": -1},
            {"job_id": "job", "stage": "SENT", "part_index": 1, "part_count": 2, "result_code": -1},
            {"job_id": "job", "stage": "DELIVERED", "part_index": 0, "part_count": 2, "result_code": -1},
            {"job_id": "job", "stage": "DELIVERED", "part_index": 1, "part_count": 2, "result_code": -1},
        ]
        status, _ = AndroidTransport.summarize_events(events)["job"]
        self.assertEqual("DELIVERED", status)

    def test_summarize_events_marks_send_failure(self):
        events = [{"job_id": "job", "stage": "SENT", "part_index": 0, "part_count": 1, "result_code": 1}]
        status, _ = AndroidTransport.summarize_events(events)["job"]
        self.assertEqual("FAILED", status)

    def test_token_fallback_when_run_as_fails(self):
        def runner(command, **_kwargs):
            return subprocess.CompletedProcess(command, 1, "", "Permission denied")

        transport = AndroidTransport(adb_path="adb", runner=runner)
        token = transport._token("DEVICE123")
        self.assertEqual("SmsBridge_2026_Direct_Token", token)

    def test_reconnect_offline_runs_adb_reconnect(self):
        captured_commands = []

        def runner(command, **_kwargs):
            captured_commands.append(command)
            return subprocess.CompletedProcess(command, 0, "reconnecting", "")

        self.assertTrue(AndroidTransport(adb_path="adb", runner=runner).reconnect_offline())
        self.assertEqual(["adb", "reconnect", "offline"], captured_commands[0])

    def test_recover_offline_reconnects_wifi_serial(self):
        captured_commands = []

        def runner(command, **_kwargs):
            captured_commands.append(command)
            return subprocess.CompletedProcess(command, 0, "connected to 192.168.1.20:5555", "")

        with patch("socket.socket") as mock_sock:
            mock_sock.return_value.connect_ex.return_value = 0
            recovered = AndroidTransport(adb_path="adb", runner=runner).recover_offline_devices([
                "192.168.1.20:5555", "USB123",
            ])
        self.assertEqual(["192.168.1.20:5555"], recovered)
        self.assertIn(["adb", "disconnect", "192.168.1.20:5555"], captured_commands)
        self.assertIn(["adb", "connect", "192.168.1.20:5555"], captured_commands)

    def test_active_subscription_ids_uses_only_in_service_sims(self):
        def runner(command, **_kwargs):
            if any("bridge_token" in item for item in command):
                return subprocess.CompletedProcess(command, 0, "token\n", "")
            if any("sim_status.json" in item for item in command):
                return subprocess.CompletedProcess(command, 0, '{"subscriptions":[{"subscription_id":1,"in_service":true},{"subscription_id":2,"in_service":false}]}', "")
            return subprocess.CompletedProcess(command, 0, "Broadcast completed: result=0\n", "")

        subscriptions = AndroidTransport(adb_path="adb", runner=runner).active_subscription_ids("DEVICE123")
        self.assertEqual([1], subscriptions)

    def test_summarize_events_with_carrier_error_description(self):
        events = [{
            "job_id": "job123",
            "stage": "FAILED",
            "part_index": 0,
            "part_count": 1,
            "result_code": 1,
            "error": "GENERIC_FAILURE (Tài khoản không đủ tiền / Bị chặn / Lỗi SIM)"
        }]
        status, detail = AndroidTransport.summarize_events(events)["job123"]
        self.assertEqual("FAILED", status)
        self.assertIn("Tài khoản không đủ tiền", detail)


if __name__ == "__main__":
    unittest.main()
