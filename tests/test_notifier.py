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


USER = {"id": "user-123", "email": "pending@example.com", "name": "Pending",
        "status": "pending", "pending_approval": True, "is_service_user": False}
ACTIVE_USER = {"id": "active-123", "email": "active@example.com", "name": "Active",
               "status": "active", "pending_approval": False, "is_service_user": False}
SERVICE_USER = {"id": "service-123", "email": "", "name": "Automation",
                "status": "active", "pending_approval": False, "is_service_user": True}
PEER = {"id": "peer-123", "name": "workstation", "hostname": "workstation",
        "ip": "100.64.0.10", "connection_ip": "203.0.113.10",
        "created_at": "2026-09-12T08:00:00Z"}


def all_events(config):
    return replace(config, enabled_events=(app.USER_PENDING, app.USER_JOINED,
                                           app.SERVICE_USER_CREATED, app.PEER_ADDED))


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
        self.assertEqual(self.config.enabled_events, (app.USER_PENDING,))
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
                 ("SMTP_FROM_NAME", "NetBird\r\nBcc: x@y"),
                 ("SMTP_AUTH", "yes"), ("POLL_INTERVAL_SECONDS", "0"),
                 ("SMTP_PORT", "99999"), ("NETBIRD_API_TOKEN", "x\r\ny"),
                 ("ALERT_PEER_ADDED", "yes")]
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
        users = [USER, {**ACTIVE_USER, "id": "invited", "status": "invited"}, SERVICE_USER]
        parsed = app.parse_users(users)
        self.assertEqual([u["id"] for u in parsed], ["user-123", "invited", "service-123"])
        with patch.object(app, "fetch_users", return_value=parsed), \
                patch.object(app, "fetch_json", return_value=[PEER]):
            snapshot = app.fetch_snapshot(all_events(self.config))
        self.assertEqual([u["id"] for u in snapshot[app.USER_PENDING]], [USER["id"]])
        self.assertEqual(snapshot[app.USER_JOINED], [])
        self.assertEqual([u["id"] for u in snapshot[app.SERVICE_USER_CREATED]], [SERVICE_USER["id"]])

    def test_schema_fail_closed(self):
        for payload in ({"users": [USER]}, [{}], [{**USER, "pending_approval": "true"}],
                        [USER, USER], [{**USER, "pending_approval": 1}],
                        [{**USER, "status": 1}]):
            with self.subTest(payload=payload), self.assertRaises(app.ProtocolError):
                app.parse_users(payload)

    def test_peer_schema_fail_closed(self):
        self.assertEqual(app.parse_peers([PEER]), [PEER])
        for payload in ({"peers": [PEER]}, [{}], [PEER, PEER]):
            with self.subTest(payload=payload), self.assertRaises(app.ProtocolError):
                app.parse_peers(payload)

    def test_peer_connection_ip_is_optional_and_ipv6_is_normalized(self):
        without = {key: value for key, value in PEER.items() if key != "connection_ip"}
        self.assertEqual(app.parse_peers([without])[0]["connection_ip"], "")
        _, body = app.alert_content(self.config, {**without, "event": app.PEER_ADDED})
        self.assertNotIn("Public IP", body)
        ipv6 = app.parse_peers([{**PEER, "connection_ip": "2001:0db8::1"}])[0]
        self.assertEqual(ipv6["connection_ip"], "2001:db8::1")
        for unavailable in (None, 123, "not-an-ip"):
            with self.subTest(unavailable=unavailable):
                parsed = app.parse_peers([{**PEER, "connection_ip": unavailable}])[0]
                self.assertEqual(parsed["connection_ip"], "")

    def test_event_configuration_toggles(self):
        env = {**self.env, "ALERT_USER_PENDING_APPROVAL": "false",
               "ALERT_USER_JOINED": "true", "ALERT_SERVICE_USER_CREATED": "true",
               "ALERT_PEER_ADDED": "true"}
        self.assertEqual(app.Config.load(env).enabled_events,
                         (app.USER_JOINED, app.SERVICE_USER_CREATED, app.PEER_ADDED))

    def test_fetch_snapshot_uses_one_users_request_and_optional_peers_request(self):
        config = all_events(self.config)
        with patch.object(app, "fetch_json", side_effect=[[USER, ACTIVE_USER, SERVICE_USER], [PEER]]) as fetch:
            snapshot = app.fetch_snapshot(config)
        self.assertEqual([call.args[1] for call in fetch.call_args_list], ["/api/users", "/api/peers"])
        self.assertEqual([item["id"] for item in snapshot[app.USER_PENDING]], [USER["id"]])
        self.assertEqual([item["id"] for item in snapshot[app.USER_JOINED]], [ACTIVE_USER["id"]])
        self.assertEqual([item["id"] for item in snapshot[app.SERVICE_USER_CREATED]], [SERVICE_USER["id"]])
        self.assertEqual([item["id"] for item in snapshot[app.PEER_ADDED]], [PEER["id"]])

    def test_joined_user_requires_active_status(self):
        config = replace(self.config, enabled_events=(app.USER_JOINED,))
        with patch.object(app, "fetch_users", return_value=[{**ACTIVE_USER, "status": ""}]):
            with self.assertRaises(app.ProtocolError):
                app.fetch_snapshot(config)

    def test_creation_events_baseline_then_alert_once(self):
        config, db, send = all_events(self.config), self.db(), MagicMock()
        initial = {app.USER_PENDING: [], app.USER_JOINED: [ACTIVE_USER],
                   app.SERVICE_USER_CREATED: [SERVICE_USER], app.PEER_ADDED: [PEER]}
        self.assertEqual(app.poll(config, db, lambda _: initial, send), 0)
        send.assert_not_called()
        newer = {event: list(items) for event, items in initial.items()}
        newer[app.USER_JOINED].append({**ACTIVE_USER, "id": "active-new"})
        newer[app.SERVICE_USER_CREATED].append({**SERVICE_USER, "id": "service-new"})
        newer[app.PEER_ADDED].append({**PEER, "id": "peer-new"})
        self.assertEqual(app.poll(config, db, lambda _: newer, send), 3)
        self.assertEqual([call.args[1]["event"] for call in send.call_args_list],
                         [app.USER_JOINED, app.SERVICE_USER_CREATED, app.PEER_ADDED])
        self.assertEqual(app.poll(config, db, lambda _: newer, send), 0)
        self.assertEqual(send.call_count, 3)

    def test_creation_baseline_survives_restart_without_storing_identifiers(self):
        config = replace(self.config, enabled_events=(app.PEER_ADDED,))
        with closing(app.open_state(config)) as db:
            self.assertEqual(app.poll(config, db, lambda _: {app.PEER_ADDED: [PEER]}, MagicMock()), 0)
        new_peer = {**PEER, "id": "peer-new"}
        send = MagicMock()
        with closing(app.open_state(config)) as db:
            self.assertEqual(app.poll(config, db,
                                      lambda _: {app.PEER_ADDED: [PEER, new_peer]}, send), 1)
            rows = str(db.execute("SELECT * FROM observed").fetchall())
        self.assertNotIn(PEER["id"], rows)
        self.assertNotIn(new_peer["id"], rows)

    def test_disabled_creation_event_rebaselines_when_reenabled(self):
        enabled = replace(self.config, enabled_events=(app.PEER_ADDED,))
        disabled = replace(self.config, enabled_events=())
        db, send = self.db(), MagicMock()
        self.assertEqual(app.poll(enabled, db, lambda _: {app.PEER_ADDED: [PEER]}, send), 0)
        self.assertEqual(app.poll(disabled, db, lambda _: {}, send), 0)
        peers = [PEER, {**PEER, "id": "added-while-disabled"}]
        self.assertEqual(app.poll(enabled, db, lambda _: {app.PEER_ADDED: peers}, send), 0)
        send.assert_not_called()
        peers.append({**PEER, "id": "added-after-reenable"})
        self.assertEqual(app.poll(enabled, db, lambda _: {app.PEER_ADDED: peers}, send), 1)

    def test_failed_creation_delivery_is_retried_before_observed(self):
        config = replace(self.config, enabled_events=(app.PEER_ADDED,))
        db = self.db()
        app.poll(config, db, lambda _: {app.PEER_ADDED: [PEER]}, MagicMock())
        peers = [PEER, {**PEER, "id": "peer-new"}]
        with self.assertRaises(app.ProtocolError):
            app.poll(config, db, lambda _: {app.PEER_ADDED: peers},
                     MagicMock(side_effect=OSError("failure")))
        self.assertEqual(db.execute("SELECT count(*) FROM observed").fetchone()[0], 1)
        send = MagicMock()
        self.assertEqual(app.poll(config, db, lambda _: {app.PEER_ADDED: peers}, send), 1)
        self.assertEqual(db.execute("SELECT count(*) FROM observed").fetchone()[0], 2)

    def test_pending_user_becomes_joined_after_approval(self):
        config = replace(self.config, enabled_events=(app.USER_PENDING, app.USER_JOINED))
        db, send = self.db(), MagicMock()
        initial = {app.USER_PENDING: [USER], app.USER_JOINED: []}
        self.assertEqual(app.poll(config, db, lambda _: initial, send), 1)
        approved = {**ACTIVE_USER, "id": USER["id"]}
        current = {app.USER_PENDING: [], app.USER_JOINED: [approved]}
        self.assertEqual(app.poll(config, db, lambda _: current, send), 1)
        self.assertEqual([call.args[1]["event"] for call in send.call_args_list],
                         [app.USER_PENDING, app.USER_JOINED])

    def test_creation_event_waits_for_every_recipient(self):
        config = replace(self.config, enabled_events=(app.PEER_ADDED,),
                         recipients=("first@example.com", "second@example.com"))
        db = self.db()
        app.poll(config, db, lambda _: {app.PEER_ADDED: [PEER]}, MagicMock())
        peers = [PEER, {**PEER, "id": "peer-new"}]
        send = MagicMock(side_effect=[None, smtplib.SMTPDataError(451, b"temporary")])
        with self.assertRaises(app.ProtocolError):
            app.poll(config, db, lambda _: {app.PEER_ADDED: peers}, send)
        self.assertEqual(db.execute("SELECT count(*) FROM observed").fetchone()[0], 1)
        retry = MagicMock()
        self.assertEqual(app.poll(config, db, lambda _: {app.PEER_ADDED: peers}, retry), 1)
        self.assertEqual(retry.call_args.args[2], "second@example.com")
        self.assertEqual(db.execute("SELECT count(*) FROM observed").fetchone()[0], 2)

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
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(app.poll(self.config, db, lambda _: [USER], MagicMock()), 0)

    def test_schema_two_upgrade_retains_pending_delivery_key(self):
        key = app.delivery_key(self.config, app.USER_PENDING, USER["id"],
                               self.config.recipients[0])
        with closing(app.open_state(self.config)) as db:
            db.execute("INSERT INTO sent VALUES (?, ?)", (key, int(time.time())))
            db.execute("DROP TABLE event_baselines")
            db.execute("DROP TABLE observed")
            db.execute("PRAGMA user_version=2")
        send = MagicMock()
        with closing(app.open_state(self.config)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(app.poll(self.config, db, lambda _: [USER], send), 0)
        send.assert_not_called()

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
            self.assertEqual(str(message["From"]), "sender@example.com")
            server.close.assert_called_once()

    def test_sender_display_name(self):
        config = app.Config.load({**self.env, "SMTP_FROM_NAME": "NetBird"})
        with patch.object(app.smtplib, "SMTP") as factory:
            factory.return_value.send_message.return_value = {}
            app.send_alert(config, USER, config.recipients[0], "key")
            message = factory.return_value.send_message.call_args.args[0]
            self.assertEqual(str(message["From"]), "NetBird <sender@example.com>")
            self.assertEqual(factory.return_value.send_message.call_args.kwargs["from_addr"],
                             "sender@example.com")

    def test_event_specific_email_subjects_and_safe_fields(self):
        cases = ((app.USER_JOINED, ACTIVE_USER, "NetBird user joined"),
                 (app.SERVICE_USER_CREATED, SERVICE_USER, "NetBird service user created"),
                 (app.PEER_ADDED, PEER, "NetBird peer added"))
        with patch.object(app.smtplib, "SMTP") as factory:
            factory.return_value.send_message.return_value = {}
            for event, item, subject in cases:
                with self.subTest(event=event):
                    app.send_alert(self.config, {**item, "event": event, "name": "Bad\r\nBcc: x@y"},
                                   self.config.recipients[0], "key")
                    message = factory.return_value.send_message.call_args.args[0]
                    self.assertEqual(message["Subject"], subject)
                    self.assertIsNone(message["Bcc"])
                    self.assertNotIn("\r\nBcc:", message.get_content())
                    if event == app.PEER_ADDED:
                        self.assertIn("Public IP (API supplied): 203.0.113.10",
                                      message.get_content())

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
            response.headers.get_content_type.return_value = "application/json"
            response.read.return_value = b"not-json"
            with self.assertRaises(app.ProtocolError):
                app.fetch_users(self.config)

    def test_dry_run_has_no_delivery_or_state(self):
        with patch.dict(app.os.environ, self.env), \
                patch.object(app, "fetch_snapshot", return_value={app.USER_PENDING: [USER]}), \
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
