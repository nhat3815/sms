import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import launcher
from android_transport import AndroidDevice


class FakeSerial:
    port = "COM_TEST"

    def __init__(self, final_response):
        self.final_response = final_response
        self.pending = b""

    def reset_input_buffer(self):
        pass

    def reset_output_buffer(self):
        pass

    @property
    def in_waiting(self):
        return len(self.pending)

    def write(self, data):
        if data.startswith(b"AT+CMGS"):
            self.pending = b">"
        elif data == bytes([26]):
            self.pending = self.final_response

    def read(self, size):
        data, self.pending = self.pending[:size], self.pending[size:]
        return data

    def read_all(self):
        data, self.pending = self.pending, b""
        return data


class FakeDeliverySerial:
    port = "COM_TEST"

    def __init__(self, response):
        self.response = response

    def write(self, _data):
        return None

    def read_all(self):
        response, self.response = self.response, b""
        return response


class SmsSenderSelfCheck(unittest.TestCase):
    @patch.object(launcher, "send_at", return_value=True)
    def test_modem_acceptance_requires_cmgs(self, _send_at):
        ok, response = launcher.send_sms_modem(
            FakeSerial(b"\r\n+CMGS: 42\r\nOK\r\n"), "0900000000", "test"
        )
        self.assertTrue(ok)
        self.assertIn("+CMGS: 42", response["response"])
        self.assertEqual(42, response["message_ref"])

    @patch.object(launcher, "send_at", return_value=True)
    def test_modem_error_is_failed(self, _send_at):
        ok, response = launcher.send_sms_modem(
            FakeSerial(b"\r\n+CMS ERROR: 500\r\n"), "0900000000", "test"
        )
        self.assertFalse(ok)
        self.assertIn("ERROR", response)

    def test_history_persists_status(self):
        with tempfile.TemporaryDirectory() as directory:
            history_path = os.path.join(directory, "history.sqlite3")
            with patch.object(launcher, "HISTORY_PATH", history_path):
                launcher.init_history_db()
                history_id = launcher.create_history(
                    "0900000000", "Test User", "COM_TEST", "msg1.txt", "hello"
                )
                launcher.update_history(history_id, "MODEM_ACCEPTED", "+CMGS: 42")
                row = launcher.get_history(1)[0]

        self.assertEqual("MODEM_ACCEPTED", row["status"])
        self.assertEqual("+CMGS: 42", row["modem_response"])

    def test_history_api_and_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            history_path = os.path.join(directory, "history.sqlite3")
            with patch.object(launcher, "HISTORY_PATH", history_path):
                launcher.init_history_db()
                history_id = launcher.create_history(
                    "0900000000", "Test User", "COM_TEST", "msg1.txt", "hello"
                )
                launcher.update_history(history_id, "FAILED", "+CMS ERROR: 500")
                client = launcher.app.test_client()
                history_response = client.get("/history")
                csv_response = client.get("/history.csv")

        self.assertEqual(200, history_response.status_code)
        self.assertEqual("FAILED", history_response.get_json()["rows"][0]["status"])
        self.assertEqual(200, csv_response.status_code)
        self.assertIn(b"+CMS ERROR: 500", csv_response.data)

    def test_parse_cmgs_ref(self):
        self.assertEqual(42, launcher.parse_cmgs_ref("\r\n+CMGS: 42\r\nOK\r\n"))

    def test_campaign_success_marker_persists_in_excel(self):
        with tempfile.TemporaryDirectory() as directory:
            excel_path = os.path.join(directory, "campaign.xlsx")
            launcher.pd.DataFrame([
                {"ĐIỆN THOẠI": "0912345678", "HỌ TÊN": "Khách A"},
                {"ĐIỆN THOẠI": "0987654321", "HỌ TÊN": "Khách B"},
            ]).to_excel(excel_path, index=False)

            self.assertTrue(launcher.mark_campaign_row_sent(0, excel_path))
            _, _, _, _, rows, _ = launcher.parse_excel_file(excel_path)

        self.assertTrue(launcher.campaign_row_was_sent(rows[0]))
        self.assertFalse(launcher.campaign_row_was_sent(rows[1]))

    def test_campaign_import_adds_success_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            excel_path = os.path.join(directory, "campaign.xlsx")
            launcher.pd.DataFrame([{"ĐIỆN THOẠI": "0912345678"}]).to_excel(excel_path, index=False)

            self.assertTrue(launcher.ensure_campaign_columns(excel_path))
            self.assertFalse(launcher.ensure_campaign_columns(excel_path))
            columns = launcher.pd.read_excel(excel_path).columns

        self.assertIn(launcher.CAMPAIGN_SENT_COLUMN, columns)
        self.assertIn(launcher.CAMPAIGN_SENT_AT_COLUMN, columns)

    def test_campaign_download_exports_marked_excel(self):
        with tempfile.TemporaryDirectory() as directory:
            excel_path = os.path.join(directory, "dulieu.xlsx")
            launcher.pd.DataFrame([{"ĐIỆN THOẠI": "0912345678"}]).to_excel(excel_path, index=False)
            with patch.object(launcher, "__file__", os.path.join(directory, "launcher.py")):
                response = launcher.app.test_client().get("/api/download_campaign_excel")
                status_code = response.status_code
                content_disposition = response.headers["Content-Disposition"]
                response.close()

        self.assertEqual(200, status_code)
        self.assertIn("dulieu_da_danh_dau.xlsx", content_disposition)

    def test_zalo_profile_rejects_invalid_slot(self):
        ok, message = launcher.open_zalo_profile(5)
        self.assertFalse(ok)
        self.assertIn("1-4", message)

    def test_zalo_profiles_use_separate_persistent_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(launcher, "ZALO_PROFILE_DIR", directory), \
                 patch.object(launcher, "find_browser_for_zalo", return_value="/bin/echo"), \
                 patch.object(launcher.subprocess, "Popen") as popen:
                self.assertTrue(launcher.open_zalo_profile(1)[0])
                self.assertTrue(launcher.open_zalo_profile(2)[0])

        first_command = popen.call_args_list[0].args[0]
        second_command = popen.call_args_list[1].args[0]
        self.assertIn(f"--user-data-dir={directory}/zalo_01", first_command)
        self.assertIn(f"--user-data-dir={directory}/zalo_02", second_command)

    def test_delivery_report_updates_history(self):
        with tempfile.TemporaryDirectory() as directory:
            history_path = os.path.join(directory, "history.sqlite3")
            with patch.object(launcher, "HISTORY_PATH", history_path):
                launcher.init_history_db()
                history_id = launcher.create_history(
                    "0900000000", "Test User", "COM_TEST", "msg1.txt", "hello"
                )
                launcher.update_history_ref(history_id, 42, "+CMGS: 42")
                updated = launcher.poll_delivery_reports(
                    FakeDeliverySerial(b'\r\n+CDS: 25\r\n00022A00000000000000000000\r\n')
                )
                row = launcher.get_history(1)[0]

        self.assertEqual(1, updated)
        self.assertEqual("DELIVERED", row["status"])
        self.assertEqual("DELIVERED", row["delivery_status"])
        self.assertEqual(42, row["message_ref"])

    def test_conversations_and_messages_api(self):
        with tempfile.TemporaryDirectory() as directory:
            history_path = os.path.join(directory, "history.sqlite3")
            with patch.object(launcher, "HISTORY_PATH", history_path):
                launcher.init_history_db()
                launcher.create_history("0912345678", "Anh Nam", "COM1", "t1.txt", "Tin nhan 1")
                launcher.create_history("0912345678", "Anh Nam", "COM1", "t2.txt", "Tin nhan 2")
                launcher.create_history("0987654321", "Chi Hoa", "COM2", "t1.txt", "Chao chi Hoa")

                client = launcher.app.test_client()
                conv_resp = client.get("/api/conversations")
                self.assertEqual(200, conv_resp.status_code)
                convs = conv_resp.get_json()["conversations"]
                self.assertEqual(2, len(convs))
                
                # Verify conversation grouping
                nam_conv = next(c for c in convs if c["phone"] == "0912345678")
                self.assertEqual(2, nam_conv["total_count"])
                self.assertEqual("Tin nhan 2", nam_conv["message"])

                # Verify thread messages
                msg_resp = client.get("/api/messages?phone=0912345678")
                self.assertEqual(200, msg_resp.status_code)
                messages = msg_resp.get_json()["messages"]
                self.assertEqual(2, len(messages))
                self.assertEqual("Tin nhan 1", messages[0]["message"])
                self.assertEqual("Tin nhan 2", messages[1]["message"])

    def test_send_sms_api_validation(self):
        client = launcher.app.test_client()
        # Invalid phone
        resp = client.post("/api/send_sms", json={"phone": "123", "message": "hello"})
        self.assertEqual(400, resp.status_code)

        # Empty message
        resp = client.post("/api/send_sms", json={"phone": "0912345678", "message": ""})
        self.assertEqual(400, resp.status_code)

    def test_send_sms_api_android_direct(self):
        with tempfile.TemporaryDirectory() as directory:
            history_path = os.path.join(directory, "history.sqlite3")
            with patch.object(launcher, "HISTORY_PATH", history_path):
                launcher.init_history_db()
                device = AndroidDevice(serial="TEST_SERIAL", model="TestModel", ready=True, detail="ready")
                with patch.object(launcher, "android_devices", [device]):
                    with patch.object(launcher.android_transport, "send", return_value=(True, "job123", "Accepted")):
                        client = launcher.app.test_client()
                        resp = client.post("/api/send_sms", json={
                            "phone": "0912345678",
                            "name": "Nhat Minh",
                            "message": "Xin chao tat ca moi nguoi",
                            "transport": "ANDROID",
                            "device_id": "TEST_SERIAL"
                        })
                        self.assertEqual(200, resp.status_code)
                        data = resp.get_json()["data"]
                        self.assertEqual("job123", data["job_id"])
                        self.assertEqual("ANDROID", data["transport"])

                        # Check saved in database
                        history = launcher.get_history(1)[0]
                        self.assertEqual("0912345678", history["phone"])
                        self.assertEqual("Nhat Minh", history["customer_name"])
                        self.assertEqual("Xin chao tat ca moi nguoi", history["message"])
                        self.assertEqual("ANDROID_QUEUED", history["status"])

    def test_templates_api(self):
        client = launcher.app.test_client()
        resp = client.get("/api/templates")
        self.assertEqual(200, resp.status_code)
        self.assertIn("templates", resp.get_json())


class DeliveredOnlySuccessAndMultiCampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.history_path = os.path.join(self.temp_dir.name, "history.sqlite3")
        self.patcher = patch.object(launcher, "HISTORY_PATH", self.history_path)
        self.patcher.start()
        launcher.init_history_db()
        with launcher.lock:
            launcher.stats.update({"total": 0, "sent": 0, "success": 0, "running": False, "active_workers": 0})

    def tearDown(self):
        self.patcher.stop()
        self.temp_dir.cleanup()

    def test_sent_and_cmgs_mapped_to_submitted_not_success(self):
        # 1. Modem +CMGS maps to SUBMITTED
        hid = launcher.create_history("0911111111", "User A", "COM1", "t.txt", "msg", campaign_row=0)
        launcher.update_history_ref(hid, 101, "+CMGS: 101")
        row = launcher.get_history(1)[0]
        self.assertEqual("SUBMITTED", row["status"])
        self.assertEqual(0, launcher.stats["success"])

        # 2. Android SENT maps to SUBMITTED
        job_id = "job_sent_test"
        launcher.update_android_status("cloud:dev1", job_id, "SENT", "Sent via SIM", phone="0922222222", message="msg2")
        with launcher.get_db() as conn:
            h = conn.execute("SELECT status FROM sms_history WHERE external_job_id = ?", (job_id,)).fetchone()
        self.assertEqual("SUBMITTED", h[0])
        self.assertEqual(0, launcher.stats["success"])

    def test_delivered_is_the_only_success_and_updates_markers(self):
        excel_path = os.path.join(self.temp_dir.name, "camp.xlsx")
        launcher.pd.DataFrame([{"ĐIỆN THOẠI": "0933333333"}]).to_excel(excel_path, index=False)
        with patch.object(launcher, "EXCEL_PATH", excel_path):
            hid = launcher.create_history("0933333333", "User B", "cloud:dev1", "t.txt", "msg", campaign_row=0)
            job_id = "job_deliv_test"
            with launcher.get_db() as conn:
                conn.execute("UPDATE sms_history SET external_job_id = ? WHERE id = ?", (job_id, hid))

            # SENT -> SUBMITTED (not marked, not counted)
            launcher.update_android_status("cloud:dev1", job_id, "SENT", "Carrier sent", phone="0933333333")
            self.assertEqual(0, launcher.stats["success"])
            _, _, _, _, rows_check, _ = launcher.parse_excel_file(excel_path)
            self.assertFalse(launcher.campaign_row_was_sent(rows_check[0]))

            # DELIVERED -> SUCCESS (marked in Excel, counter incremented, cooldown set)
            launcher.update_android_status("cloud:dev1", job_id, "DELIVERED", "Delivered report", phone="0933333333")
            self.assertEqual(1, launcher.stats["success"])
            _, _, _, _, rows_check, _ = launcher.parse_excel_file(excel_path)
            self.assertTrue(launcher.campaign_row_was_sent(rows_check[0]))

            cooldown = launcher.check_recent_successful_send("0933333333", cooldown_hours=24)
            self.assertIsNotNone(cooldown)
            self.assertEqual("DELIVERED", cooldown["status"])

    def test_failed_is_sticky_and_never_overwritten(self):
        hid = launcher.create_history("0944444444", "User C", "cloud:dev1", "t.txt", "msg", campaign_row=0)
        job_id = "job_failed_test"
        with launcher.get_db() as conn:
            conn.execute("UPDATE sms_history SET external_job_id = ? WHERE id = ?", (job_id, hid))

        launcher.update_android_status("cloud:dev1", job_id, "FAILED", "Carrier error radio off")
        with launcher.get_db() as conn:
            h = conn.execute("SELECT status FROM sms_history WHERE external_job_id = ?", (job_id,)).fetchone()
        self.assertEqual("FAILED", h[0])

        # Attempt to overwrite with late DELIVERED
        launcher.update_android_status("cloud:dev1", job_id, "DELIVERED", "Late delivery report")
        with launcher.get_db() as conn:
            h = conn.execute("SELECT status FROM sms_history WHERE external_job_id = ?", (job_id,)).fetchone()
        self.assertEqual("FAILED", h[0])
        self.assertEqual(0, launcher.stats["success"])

    def test_timeout_becomes_unconfirmed_without_retry(self):
        hid = launcher.create_history("0955555555", "User D", "cloud:dev1", "t.txt", "msg", campaign_row=0)
        job_id = "job_timeout_test"
        with launcher.get_db() as conn:
            conn.execute("UPDATE sms_history SET external_job_id = ? WHERE id = ?", (job_id, hid))

        # Initial submit
        launcher.update_android_status("cloud:dev1", job_id, "SENT", "Sent")
        # On timeout
        launcher.update_android_status("cloud:dev1", job_id, "UNCONFIRMED", "Timeout waiting for delivery report")

        with launcher.get_db() as conn:
            h = conn.execute("SELECT status FROM sms_history WHERE external_job_id = ?", (job_id,)).fetchone()
        self.assertEqual("UNCONFIRMED", h[0])
        self.assertEqual(0, launcher.stats["success"])

        # Cooldown must be None
        self.assertIsNone(launcher.check_recent_successful_send("0955555555", cooldown_hours=24))

    def test_late_delivered_promotes_submitted_or_unconfirmed(self):
        excel_path = os.path.join(self.temp_dir.name, "camp.xlsx")
        launcher.pd.DataFrame([{"ĐIỆN THOẠI": "0966666666"}]).to_excel(excel_path, index=False)
        with patch.object(launcher, "EXCEL_PATH", excel_path):
            hid = launcher.create_history("0966666666", "User E", "cloud:dev1", "t.txt", "msg", campaign_row=0)
            job_id = "job_late_test"
            with launcher.get_db() as conn:
                conn.execute("UPDATE sms_history SET external_job_id = ? WHERE id = ?", (job_id, hid))

            # Transition to UNCONFIRMED
            launcher.update_android_status("cloud:dev1", job_id, "UNCONFIRMED", "Timeout")
            self.assertEqual(0, launcher.stats["success"])

            # Late DELIVERED arrives!
            launcher.update_android_status("cloud:dev1", job_id, "DELIVERED", "Late delivery report")
            with launcher.get_db() as conn:
                h = conn.execute("SELECT status FROM sms_history WHERE external_job_id = ?", (job_id,)).fetchone()
            self.assertEqual("DELIVERED", h[0])
            self.assertEqual(1, launcher.stats["success"])
            _, _, _, _, rows_check, _ = launcher.parse_excel_file(excel_path)
            self.assertTrue(launcher.campaign_row_was_sent(rows_check[0]))

    def test_multi_campaign_enqueue_and_api(self):
        excel_path = os.path.join(self.temp_dir.name, "camp.xlsx")
        launcher.pd.DataFrame([
            {"ĐIỆN THOẠI": "0977777771", "TÊN": "Khách 1"},
            {"ĐIỆN THOẠI": "0977777772", "TÊN": "Khách 2"},
        ]).to_excel(excel_path, index=False)

        client = launcher.app.test_client()
        with patch.object(launcher, "EXCEL_PATH", excel_path):
            # Enqueue Campaign 1
            resp1 = client.post("/start", json={"templates": ["Mẫu 1 {name}"], "name": "Chiến dịch A", "delay_min": 1, "delay_max": 2})
            self.assertIn(resp1.status_code, (200, 201))

            # Enqueue Campaign 2 (should NOT return 409 busy)
            resp2 = client.post("/start", json={"templates": ["Mẫu 2 {name}"], "name": "Chiến dịch B", "delay_min": 1, "delay_max": 2})
            self.assertIn(resp2.status_code, (200, 201))

            # Query /api/campaigns
            camp_resp = client.get("/api/campaigns")
            self.assertEqual(200, camp_resp.status_code)
            data = camp_resp.get_json()
            self.assertIn("campaigns", data)
            self.assertGreaterEqual(len(data["campaigns"]), 2)

            # Stop all
            stop_resp = client.post("/stop")
            self.assertEqual(200, stop_resp.status_code)

            # Check no RUNNING leftover
            camp_resp2 = client.get("/api/campaigns")
            camps = camp_resp2.get_json()["campaigns"]
            running_camps = [c for c in camps if c.get("status") == "RUNNING"]
            self.assertEqual(0, len(running_camps))
            self.assertFalse(launcher.stats.get("running", False))


if __name__ == "__main__":
    unittest.main()

