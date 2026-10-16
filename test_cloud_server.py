import tempfile
import unittest

from cloud_server import create_app


class CloudServerSelfCheck(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app(
            f"{self.temp_dir.name}/cloud.sqlite3",
            operator_token="operator-secret",
            admin_token="admin-secret",
        )
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_operator_to_android_job_round_trip(self) -> None:
        device_response = self.client.post(
            "/v1/admin/devices",
            headers={"X-Admin-Token": "admin-secret"},
            json={"name": "Android 01"},
        )
        self.assertEqual(201, device_response.status_code)
        device = device_response.get_json()

        job_response = self.client.post(
            "/v1/jobs",
            headers={"X-Operator-Token": "operator-secret"},
            json={"device_id": device["id"], "phone": "0912345678", "message": "Xin chao"},
        )
        self.assertEqual(201, job_response.status_code)
        job = job_response.get_json()

        device_headers = {
            "X-Device-Id": device["id"],
            "X-Device-Token": device["token"],
        }
        claimed = self.client.get("/v1/device/jobs/next", headers=device_headers)
        self.assertEqual(job["id"], claimed.get_json()["id"])

        result = self.client.post(
            f"/v1/device/jobs/{job['id']}/result",
            headers=device_headers,
            json={"status": "SENT", "detail": "Android accepted SMS"},
        )
        self.assertEqual(200, result.status_code)

        jobs = self.client.get(
            "/v1/jobs", headers={"X-Operator-Token": "operator-secret"}
        ).get_json()["jobs"]
        self.assertEqual("SENT", jobs[0]["status"])

    def test_rejects_missing_credentials_and_bad_phone(self) -> None:
        self.assertEqual(401, self.client.get("/v1/devices").status_code)
        response = self.client.post(
            "/v1/jobs",
            headers={"X-Operator-Token": "operator-secret"},
            json={"device_id": "missing", "phone": "123", "message": "x"},
        )
        self.assertEqual(400, response.status_code)
        unknown_device = self.client.post(
            "/v1/jobs",
            headers={"X-Operator-Token": "operator-secret"},
            json={"device_id": "missing", "phone": "0912345678", "message": "x"},
        )
        self.assertEqual(404, unknown_device.status_code)


if __name__ == "__main__":
    unittest.main()
