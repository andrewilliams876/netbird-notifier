from contextlib import closing
from dataclasses import replace
import io
import json
from pathlib import Path
import smtplib
import sqlite3
import ssl
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from notifier import app


def environment(path):
    return dict(NETBIRD_URL="https://netbird.example.com", NETBIRD_API_TOKEN="test-only-token",
                SMTP_HOST="smtp.example.com", SMTP_USERNAME="sender@example.com",
                SMTP_PASSWORD="test-only-password", SMTP_FROM="sender@example.com",
                SMTP_TO="admin@example.com", STATE_DIR=str(path))


USER = {"id": "user-123", "email": "pending@example.com", "name": "Pending", "pending_approval": True}


class NotifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = environment(Path(self.temp.name))
        self.config = app.Config.load(self.env)

    def db(self):
        db = app.open_state(self.config)
        self.addCleanup(db.close)
        return db

    def test_secure_defaults_and_secret_repr(self):
        self.assertEqual(self.config.security, "starttls")
        self.assertEqual(self.config.interval, 60)
        self.assertNotIn("test-only-token", repr(self.config))
        self.assertNotIn("test-only-password", repr(self.config))
        context = app.tls_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_invalid_config(self):
        cases = [("NETBIRD_URL", "http://example.com"), ("NETBIRD_URL", "https://a:b@example.com"),
                 ("NETBIRD_URL", "https://api.netbird.io"), ("NETBIRD_URL", "https://example.com?x=1"),
                 ("NETBIRD_URL", "https://example.com/other"), ("SMTP_TO", "a@b\r\nBcc:c@d"),
                 ("SMTP_FROM", "Sender <a@b>"), ("SMTP_SECURITY", "auto"),
                 ("SMTP_AUTH", "yes"), ("POLL_INTERVAL_SECONDS", "0"),
                 ("SMTP_PORT", "99999"), ("NETBIRD_API_TOKEN", "x\r\ny")]
        for key, value in cases:
            with self.subTest(key=key, value=value), self.assertRaises(app.ConfigError):
                app.Config.load({**self.env, key: value})

    def test_url_normalized(self):
        self.assertEqual(app.Config.load({**self.env, "NETBIRD_URL": "https://NETBIRD.example.com:443/api/"}).url,
                         self.config.url)

    def test_secret_file_and_conflict(self):
        path = Path(self.temp.name) / "token.txt"
        path.write_text("file-test-token\n", encoding="utf-8")
        env = {**self.env, "NETBIRD_API_TOKEN_FILE": str(path)}
        with self.assertRaises(app.ConfigError):
            app.Config.load(env)
        del env["NETBIRD_API_TOKEN"]
        self.assertEqual(app.Config.load(env).token, "file-test-token")

    def test_plaintext_requires_opt_in_and_no_credentials(self):
        env = {**self.env, "SMTP_SECURITY": "none"}
        with self.assertRaises(app.ConfigError):
            app.Config.load(env)
        env.update(SMTP_AUTH="false", ALLOW_INSECURE_SMTP="true", SMTP_USERNAME="", SMTP_PASSWORD="")
        self.assertFalse(app.Config.load(env).auth)
        with self.assertRaises(app.ConfigError):
            app.Config.load({**env, "SMTP_PASSWORD": "test"})

    def test_pending_boolean_not_status_or_invite(self):
        users = [USER, {**USER, "id": "active", "pending_approval": False, "status": "invited"},
                 {**USER, "id": "service", "is_service_user": True}]
        self.assertEqual([u["id"] for u in app.parse_users(users)], [USER["id"]])

    def test_schema_fail_closed(self):
        for payload in ({"users": [USER]}, [{}], [{**USER, "pending_approval": "true"}],
                        [USER, USER], [{**USER, "pending_approval": 1}]):
            with self.subTest(payload=payload), self.assertRaises(app.ProtocolError):
                app.parse_users(payload)

    def test_dedup_survives_restart_and_reapproval(self):
        send = MagicMock()
        with closing(app.open_state(self.config)) as db:
            self.assertEqual(app.poll(self.config, db, lambda _: [USER], send), 1)
        with closing(app.open_state(self.config)) as db:
            self.assertEqual(app.poll(self.config, db, lambda _: [], send), 0)
            self.assertEqual(app.poll(self.config, db, lambda _: [USER], send), 0)
        send.assert_called_once()

    def test_recipient_failure_retries_only_failed_recipient(self):
        config = replace(self.config, recipients=("first@example.com", "second@example.com"))
        send = MagicMock(side_effect=[None, smtplib.SMTPDataError(451, b"temporary")])
        db = self.db()
        with self.assertRaises(app.ProtocolError):
            app.poll(config, db, lambda _: [USER], send)
        send = MagicMock()
        self.assertEqual(app.poll(config, db, lambda _: [USER], send), 1)
        self.assertEqual(send.call_args.args[2], "second@example.com")

    def test_api_failure_does_not_touch_state(self):
        db, send = self.db(), MagicMock()
        fetch = MagicMock(side_effect=app.ProtocolError("bad schema"))
        with self.assertRaises(app.ProtocolError):
            app.poll(self.config, db, fetch, send)
        self.assertEqual(db.execute("SELECT count(*) FROM sent").fetchone()[0], 0)
        send.assert_not_called()

    def test_state_contains_no_profile_or_recipient(self):
        db = self.db()
        app.poll(self.config, db, lambda _: [USER], MagicMock())
        rows = str(db.execute("SELECT * FROM sent").fetchall())
        self.assertNotIn(USER["id"], rows)
        self.assertNotIn("@", rows)

    def test_alert_cap_and_backlog(self):
        config, db, send = replace(self.config, max_alerts=1), self.db(), MagicMock()
        users = [USER, {**USER, "id": "second"}]
        self.assertEqual(app.poll(config, db, lambda _: users, send), 1)
        self.assertEqual(app.poll(config, db, lambda _: users, send), 1)
        self.assertEqual(send.call_count, 2)

    def test_namespace_isolation(self):
        db, send = self.db(), MagicMock()
        app.poll(self.config, db, lambda _: [USER], send)
        app.poll(replace(self.config, namespace="another"), db, lambda _: [USER], send)
        self.assertEqual(send.call_count, 2)

    def test_failed_head_does_not_starve_other_users(self):
        config, db = replace(self.config, max_alerts=1), self.db()
        users = [USER, {**USER, "id": "second"}]
        with self.assertRaises(app.ProtocolError):
            app.poll(config, db, lambda _: users, MagicMock(side_effect=OSError("failure")))
        send = MagicMock()
        self.assertEqual(app.poll(config, db, lambda _: users, send), 1)
        self.assertEqual(send.call_args.args[1]["id"], "second")
        app.poll(config, db, lambda _: users, send)
        self.assertEqual(send.call_args.args[1]["id"], USER["id"])
        self.assertEqual(db.execute("SELECT count(*) FROM retries").fetchone()[0], 0)

    def test_health_expires_and_readonly_missing_database(self):
        with self.assertRaises(sqlite3.OperationalError):
            app.healthy(self.config)
        db = self.db()
        app.poll(self.config, db, lambda _: [], MagicMock())
        self.assertTrue(app.healthy(self.config))
        db.execute("UPDATE health SET success_at=0")
        self.assertFalse(app.healthy(self.config))

    def test_corrupt_state_is_not_recreated(self):
        path = Path(self.temp.name) / "state.sqlite3"
        path.write_bytes(b"corrupt-state")
        with self.assertRaises(sqlite3.DatabaseError):
            app.open_state(self.config)
        self.assertEqual(path.read_bytes(), b"corrupt-state")

    def test_schema_one_upgrade_retains_history(self):
        with closing(app.open_state(self.config)) as db:
            app.poll(self.config, db, lambda _: [USER], MagicMock())
            db.execute("DROP TABLE retries")
            db.execute("PRAGMA user_version=1")
        with closing(app.open_state(self.config)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(app.poll(self.config, db, lambda _: [USER], MagicMock()), 0)

    def test_storage_failure_after_smtp_acceptance_rolls_back(self):
        db, send = self.db(), MagicMock()
        class DiskFailure:
            def execute(self, sql, parameters=()):
                if sql.startswith("INSERT INTO sent"):
                    raise sqlite3.OperationalError("database or disk is full")
                return db.execute(sql, parameters)
        with self.assertRaises(sqlite3.OperationalError):
            app.poll(self.config, DiskFailure(), lambda _: [USER], send)
        send.assert_called_once()
        self.assertFalse(db.in_transaction)
        self.assertEqual(db.execute("SELECT count(*) FROM sent").fetchone()[0], 0)
        self.assertFalse(app.healthy(self.config))

    def test_writer_lock_prevents_second_sender(self):
        db = self.db()
        with closing(app.open_state(self.config)) as other:
            other.execute("PRAGMA busy_timeout=1")
            def send(*_):
                second = MagicMock()
                with self.assertRaises(sqlite3.OperationalError):
                    app.poll(self.config, other, lambda _: [USER], second)
                second.assert_not_called()
            app.poll(self.config, db, lambda _: [USER], send)

    def test_rollback_if_interrupted_during_send(self):
        db = self.db()
        with self.assertRaises(KeyboardInterrupt):
            app.poll(self.config, db, lambda _: [USER], MagicMock(side_effect=KeyboardInterrupt))
        self.assertEqual(db.execute("SELECT count(*) FROM sent").fetchone()[0], 0)

    def test_starttls_before_auth_and_static_headers(self):
        with patch.object(app.smtplib, "SMTP") as factory:
            server = factory.return_value
            server.send_message.return_value = {}
            app.send_alert(self.config, {**USER, "name": "Bad\r\nBcc: x@y"}, self.config.recipients[0], "key")
            names = [c[0] for c in server.method_calls]
            self.assertLess(names.index("starttls"), names.index("login"))
            message = server.send_message.call_args.args[0]
            self.assertIsNone(message["Bcc"])
            self.assertEqual(message["Subject"], "NetBird user awaiting approval")
            server.close.assert_called_once()

    def test_missing_starttls_never_authenticates(self):
        with patch.object(app.smtplib, "SMTP") as factory:
            server = factory.return_value
            server.starttls.side_effect = smtplib.SMTPNotSupportedError("not available")
            with self.assertRaises(smtplib.SMTPNotSupportedError):
                app.send_alert(self.config, USER, "a@b", "key")
            server.login.assert_not_called()
            server.send_message.assert_not_called()

    def test_implicit_tls_and_unauthenticated_relay(self):
        with patch.object(app.smtplib, "SMTP_SSL") as factory:
            factory.return_value.send_message.return_value = {}
            app.send_alert(replace(self.config, security="ssl", auth=False), USER, "a@b", "key")
            factory.assert_called_once()
            factory.return_value.starttls.assert_not_called()
            factory.return_value.login.assert_not_called()

    def test_redirect_refused(self):
        with self.assertRaises(app.ProtocolError):
            app.NoRedirect().redirect_request(None, None, 302, "", {}, "https://attacker.example")

    def test_fetch_request_size_and_content_type(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers.get_content_type.return_value = "application/json"
        response.read.return_value = json.dumps([USER]).encode()
        with patch.object(app.urllib.request, "build_opener") as build:
            build.return_value.open.return_value = response
            self.assertEqual(len(app.fetch_users(self.config)), 1)
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.full_url, self.config.url + "/api/users")
            self.assertEqual(request.get_header("Authorization"), "Token test-only-token")
            response.read.return_value = b"x" * (app.MAX_RESPONSE + 1)
            with self.assertRaises(app.ProtocolError):
                app.fetch_users(self.config)
            response.headers.get_content_type.return_value = "text/html"
            with self.assertRaises(app.ProtocolError):
                app.fetch_users(self.config)

    def test_dry_run_has_no_delivery_or_state(self):
        with patch.dict(app.os.environ, self.env), patch.object(app, "fetch_users", return_value=[USER]), \
                patch.object(app, "send_alert") as send, patch.object(app, "open_state") as state:
            self.assertEqual(app.main(["--dry-run"]), 0)
            send.assert_not_called()
            state.assert_not_called()

    def test_errors_do_not_log_secrets(self):
        with patch.dict(app.os.environ, self.env), \
                patch.object(app, "fetch_users", side_effect=RuntimeError("test-only-token test-only-password")), \
                self.assertLogs("notifier", level="ERROR") as logs:
            self.assertEqual(app.main(["--dry-run"]), 1)
        self.assertNotIn("test-only-token", str(logs.output))
        self.assertNotIn("test-only-password", str(logs.output))


if __name__ == "__main__":
    unittest.main()
