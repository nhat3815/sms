from __future__ import annotations

import hmac
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request


PHONE_PATTERN = re.compile(r"^\+?[0-9]{8,15}$")
FINAL_STATUSES = {"DELIVERED", "UNCONFIRMED", "FAILED"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CloudStore:
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_database()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _init_database(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    token TEXT NOT NULL,
                    last_seen TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL REFERENCES devices(id),
                    phone TEXT NOT NULL,
                    message TEXT NOT NULL,
                    subscription_id INTEGER NOT NULL DEFAULT -1,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    claimed_at TEXT,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_device_status
                ON jobs(device_id, status, created_at);
                """
            )

    def create_device(self, name: str) -> dict[str, Any]:
        device = {
            "id": secrets.token_hex(8),
            "name": name,
            "token": secrets.token_urlsafe(32),
            "created_at": utc_now(),
        }
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO devices(id, name, token, created_at) VALUES (?, ?, ?, ?)",
                (device["id"], device["name"], device["token"], device["created_at"]),
            )
        return device

    def authenticate_device(self, device_id: str, token: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT token FROM devices WHERE id = ?", (device_id,)
            ).fetchone()
        return bool(row and hmac.compare_digest(row["token"], token))

    def list_devices(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, name, last_seen, created_at FROM devices ORDER BY name"
            ).fetchall()
        return [dict(row) for row in rows]

    def heartbeat(self, device_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE devices SET last_seen = ? WHERE id = ?", (utc_now(), device_id)
            )

    def create_job(
        self, device_id: str, phone: str, message: str, subscription_id: int
    ) -> dict[str, Any] | None:
        job = {
            "id": secrets.token_hex(16),
            "device_id": device_id,
            "phone": phone,
            "message": message,
            "subscription_id": subscription_id,
            "status": "QUEUED",
            "detail": "",
            "created_at": utc_now(),
        }
        try:
            with self.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO jobs(
                        id, device_id, phone, message, subscription_id,
                        status, detail, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    tuple(job[key] for key in (
                        "id", "device_id", "phone", "message", "subscription_id",
                        "status", "detail", "created_at"
                    )),
                )
        except sqlite3.IntegrityError:
            return None
        return job

    def claim_job(self, device_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM jobs
                WHERE device_id = ? AND status = 'QUEUED'
                ORDER BY created_at LIMIT 1
                """,
                (device_id,),
            ).fetchone()
            if row is None:
                return None
            claimed_at = utc_now()
            connection.execute(
                "UPDATE jobs SET status = 'CLAIMED', claimed_at = ? WHERE id = ?",
                (claimed_at, row["id"]),
            )
        job = dict(row)
        job["status"] = "CLAIMED"
        job["claimed_at"] = claimed_at
        return job

    def update_job(self, device_id: str, job_id: str, status: str, detail: str) -> bool:
        finished_at = utc_now() if status in FINAL_STATUSES else None
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs SET status = ?, detail = ?, finished_at = COALESCE(?, finished_at)
                WHERE id = ? AND device_id = ?
                """,
                (status, detail, finished_at, job_id, device_id),
            )
        return cursor.rowcount == 1

    def list_jobs(self, limit: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]


class CloudApi:
    def __init__(self, store: CloudStore, operator_token: str, admin_token: str) -> None:
        self.store = store
        self.operator_token = operator_token
        self.admin_token = admin_token

    @staticmethod
    def token_matches(actual: str | None, expected: str) -> bool:
        return bool(actual and expected and hmac.compare_digest(actual, expected))

    def require_operator(self) -> tuple[Any, int] | None:
        if self.token_matches(request.headers.get("X-Operator-Token"), self.operator_token):
            return None
        return jsonify({"error": "unauthorized"}), 401

    def require_admin(self) -> tuple[Any, int] | None:
        if self.token_matches(request.headers.get("X-Admin-Token"), self.admin_token):
            return None
        return jsonify({"error": "unauthorized"}), 401

    def require_device(self) -> tuple[str | None, tuple[Any, int] | None]:
        device_id = request.headers.get("X-Device-Id", "").strip()
        token = request.headers.get("X-Device-Token", "")
        if device_id and self.store.authenticate_device(device_id, token):
            return device_id, None
        return None, (jsonify({"error": "unauthorized"}), 401)


def create_app(
    database_path: str | None = None,
    operator_token: str | None = None,
    admin_token: str | None = None,
) -> Flask:
    app = Flask(__name__)
    store = CloudStore(database_path or os.environ.get("SMS_CLOUD_DB", "data/cloud.sqlite3"))
    api = CloudApi(
        store,
        operator_token if operator_token is not None else os.environ.get("SMS_OPERATOR_TOKEN", ""),
        admin_token if admin_token is not None else os.environ.get("SMS_ADMIN_TOKEN", ""),
    )

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "time": utc_now()})

    @app.post("/v1/admin/devices")
    def create_device():
        denied = api.require_admin()
        if denied:
            return denied
        name = str((request.get_json(silent=True) or {}).get("name", "")).strip()
        if not 1 <= len(name) <= 80:
            return jsonify({"error": "name must contain 1-80 characters"}), 400
        return jsonify(store.create_device(name)), 201

    @app.get("/v1/devices")
    def list_devices():
        denied = api.require_operator()
        if denied:
            return denied
        return jsonify({"devices": store.list_devices()})

    @app.post("/v1/jobs")
    def create_job():
        denied = api.require_operator()
        if denied:
            return denied
        payload = request.get_json(silent=True) or {}
        device_id = str(payload.get("device_id", "")).strip()
        phone = re.sub(r"[\s().-]", "", str(payload.get("phone", "")))
        message = str(payload.get("message", ""))
        try:
            subscription_id = int(payload.get("subscription_id", -1))
        except (TypeError, ValueError):
            return jsonify({"error": "subscription_id must be an integer"}), 400
        if not PHONE_PATTERN.fullmatch(phone):
            return jsonify({"error": "invalid phone"}), 400
        if not 1 <= len(message) <= 2000:
            return jsonify({"error": "message must contain 1-2000 characters"}), 400
        job = store.create_job(device_id, phone, message, subscription_id)
        if job is None:
            return jsonify({"error": "unknown device"}), 404
        return jsonify(job), 201

    @app.get("/v1/jobs")
    def list_jobs():
        denied = api.require_operator()
        if denied:
            return denied
        try:
            limit = min(max(int(request.args.get("limit", 100)), 1), 500)
        except ValueError:
            return jsonify({"error": "invalid limit"}), 400
        return jsonify({"jobs": store.list_jobs(limit)})

    @app.get("/v1/device/jobs/next")
    def next_device_job():
        device_id, denied = api.require_device()
        if denied:
            return denied
        assert device_id is not None
        store.heartbeat(device_id)
        job = store.claim_job(device_id)
        return ("", 204) if job is None else jsonify(job)

    @app.post("/v1/device/jobs/<job_id>/result")
    def update_device_job(job_id: str):
        device_id, denied = api.require_device()
        if denied:
            return denied
        payload = request.get_json(silent=True) or {}
        status = str(payload.get("status", "")).upper()
        detail = str(payload.get("detail", ""))[:2000]
        if status not in {"QUEUED", "SUBMITTED", "SENT", "DELIVERED", "UNCONFIRMED", "FAILED"}:
            return jsonify({"error": "invalid status"}), 400
        assert device_id is not None
        if not store.update_job(device_id, job_id, status, detail):
            return jsonify({"error": "job not found"}), 404
        store.heartbeat(device_id)
        return jsonify({"status": "ok"})

    return app


app = create_app()


if __name__ == "__main__":
    if not os.environ.get("SMS_OPERATOR_TOKEN") or not os.environ.get("SMS_ADMIN_TOKEN"):
        raise SystemExit("Set SMS_OPERATOR_TOKEN and SMS_ADMIN_TOKEN before starting server")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
