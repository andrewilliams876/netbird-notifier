"""Read-only API polling, TLS SMTP delivery, and durable deduplication."""

import argparse
from contextlib import closing
from dataclasses import dataclass, field
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate
import hashlib
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import signal
import smtplib
import sqlite3
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

LOG = logging.getLogger("notifier")
MAX_RESPONSE = 5 * 1024 * 1024
VERSION = __version__

USER_PENDING = "user_pending_approval"
USER_JOINED = "user_joined"
SERVICE_USER_CREATED = "service_user_created"
PEER_ADDED = "peer_added"
CREATION_EVENTS = (USER_JOINED, SERVICE_USER_CREATED, PEER_ADDED)
EVENT_SETTINGS = (
    (USER_PENDING, "ALERT_USER_PENDING_APPROVAL", "true"),
    (USER_JOINED, "ALERT_USER_JOINED", "false"),
    (SERVICE_USER_CREATED, "ALERT_SERVICE_USER_CREATED", "false"),
    (PEER_ADDED, "ALERT_PEER_ADDED", "false"),
)


class ConfigError(ValueError):
    pass


class ProtocolError(ValueError):
    pass


def secret(env, name, required=True):
    value, filename = env.get(name, ""), env.get(name + "_FILE", "")
    if value and filename:
        raise ConfigError(f"Set only {name} or {name}_FILE")
    if filename:
        with open(filename, encoding="utf-8-sig") as stream:
            value = stream.read(16385).rstrip("\r\n")
    if len(value) > 16384 or (required and not value):
        raise ConfigError(f"Invalid or missing {name}")
    return value


def boolean(env, key, default):
    value = env.get(key, default).lower()
    if value not in ("true", "false"):
        raise ConfigError(f"{key} must be true or false")
    return value == "true"


def integer(env, key, default, low, high):
    try:
        value = int(env.get(key, str(default)))
    except ValueError:
        raise ConfigError(f"{key} must be an integer") from None
    if not low <= value <= high:
        raise ConfigError(f"{key} is outside its permitted range")
    return value


def address(value):
    # Deliberately accept bare ASCII addresses only, never header fragments.
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value):
        raise ConfigError("Use bare ASCII SMTP addresses, without display names")
    if len(value) > 254:
        raise ConfigError("SMTP address too long")
    return value


def display_name(value):
    value = value.strip()
    if len(value) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ConfigError("SMTP_FROM_NAME contains invalid characters or is too long")
    return value


@dataclass(frozen=True)
class Config:
    url: str
    token: str = field(repr=False)
    host: str
    port: int
    security: str
    auth: bool
    username: str = field(repr=False)
    password: str = field(repr=False)
    sender: str
    sender_name: str
    recipients: tuple
    state_dir: Path
    namespace: str
    interval: int
    timeout: int
    max_alerts: int
    enabled_events: tuple
    api_ca: str | None
    smtp_ca: str | None

    @classmethod
    def load(cls, env=None):
        env = os.environ if env is None else env
        url = env.get("NETBIRD_URL", "").rstrip("/")
        try:
            parsed = urllib.parse.urlsplit(url)
            port = parsed.port
        except ValueError:
            raise ConfigError("Invalid NETBIRD_URL port") from None
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ("", "/api")
                or any(ord(c) <= 32 or ord(c) >= 127 for c in url)):
            raise ConfigError("NETBIRD_URL must be an HTTPS origin, optionally ending in /api")
        host = parsed.hostname.lower()
        if host == "api.netbird.io" or host == "netbird.io" or host.endswith(".netbird.io"):
            raise ConfigError("This notifier is for self-hosted NetBird endpoints")
        # Normalize URL so trailing /api and hostname case don't reset deduplication.
        authority = f"[{host}]" if ":" in host else host
        url = "https://" + authority + (f":{port}" if port and port != 443 else "")
        token = secret(env, "NETBIRD_API_TOKEN")
        if any(ord(c) <= 32 or ord(c) >= 127 for c in token):
            raise ConfigError("NETBIRD_API_TOKEN must be a single ASCII token")
        security = env.get("SMTP_SECURITY", "starttls").lower()
        if security not in ("starttls", "ssl", "none"):
            raise ConfigError("SMTP_SECURITY must be starttls, ssl, or none")
        auth = boolean(env, "SMTP_AUTH", "true")
        if security == "none" and (auth or not boolean(env, "ALLOW_INSECURE_SMTP", "false")):
            raise ConfigError("Plain SMTP requires explicit opt-in and SMTP_AUTH=false")
        username = env.get("SMTP_USERNAME", "")
        password = secret(env, "SMTP_PASSWORD", required=auth)
        if auth and not username:
            raise ConfigError("SMTP_USERNAME is required for authentication")
        if not auth and (username or password):
            raise ConfigError("Remove SMTP credentials when SMTP_AUTH=false")
        smtp_host = env.get("SMTP_HOST", "")
        if not smtp_host or len(smtp_host) > 253 or any(c.isspace() or ord(c) < 32 for c in smtp_host) or "/" in smtp_host:
            raise ConfigError("Invalid SMTP_HOST")
        recipients = tuple(dict.fromkeys(address(v.strip()) for v in env.get("SMTP_TO", "").split(",")))
        if len(recipients) > 20:
            raise ConfigError("At most 20 recipients are supported")
        namespace = env.get("STATE_NAMESPACE", "default")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", namespace):
            raise ConfigError("Invalid STATE_NAMESPACE")
        enabled_events = tuple(event for event, setting, default in EVENT_SETTINGS
                               if boolean(env, setting, default))
        return cls(url, token, smtp_host,
                   integer(env, "SMTP_PORT", 465 if security == "ssl" else 587, 1, 65535),
                   security, auth, username, password, address(env.get("SMTP_FROM", "")),
                   display_name(env.get("SMTP_FROM_NAME", "")),
                   recipients, Path(env.get("STATE_DIR", "/data")), namespace,
                   integer(env, "POLL_INTERVAL_SECONDS", 60, 30, 86400),
                   integer(env, "NETWORK_TIMEOUT_SECONDS", 20, 1, 120),
                   integer(env, "MAX_ALERTS_PER_POLL", 20, 1, 1000),
                   enabled_events,
                   env.get("NETBIRD_CA_FILE") or None, env.get("SMTP_CA_FILE") or None)


def tls_context(cafile=None):
    context = ssl.create_default_context(cafile=cafile)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProtocolError("API redirects are refused")


def parse_users(payload):
    if not isinstance(payload, list):
        raise ProtocolError("API users response must be an array")
    users, seen = [], set()
    for user in payload:
        if (not isinstance(user, dict) or not isinstance(user.get("id"), str)
                or not 1 <= len(user["id"]) <= 1024
                or type(user.get("pending_approval")) is not bool
                or ("is_service_user" in user and type(user["is_service_user"]) is not bool)
                or ("status" in user and not isinstance(user["status"], str))
                or user["id"] in seen):
            raise ProtocolError("Invalid user schema; no alerts sent")
        seen.add(user["id"])
        users.append({"id": user["id"], "email": clean_text(user.get("email", "")),
                      "name": clean_text(user.get("name", "")),
                      "status": clean_text(user.get("status", "")).lower(),
                      "pending_approval": user["pending_approval"],
                      "is_service_user": user.get("is_service_user", False)})
    return users


def parse_peers(payload):
    if not isinstance(payload, list):
        raise ProtocolError("API peers response must be an array")
    peers, seen = [], set()
    for peer in payload:
        if (not isinstance(peer, dict) or not isinstance(peer.get("id"), str)
                or not 1 <= len(peer["id"]) <= 1024 or peer["id"] in seen):
            raise ProtocolError("Invalid peer schema; no alerts sent")
        connection_ip = ""
        raw_connection_ip = peer.get("connection_ip")
        if isinstance(raw_connection_ip, str) and raw_connection_ip:
            try:
                connection_ip = str(ipaddress.ip_address(raw_connection_ip))
            except ValueError:
                pass
        seen.add(peer["id"])
        peers.append({"id": peer["id"], "name": clean_text(peer.get("name", "")),
                      "hostname": clean_text(peer.get("hostname", "")),
                      "ip": clean_text(peer.get("ip", "")),
                      "connection_ip": connection_ip,
                      "created_at": clean_text(peer.get("created_at", ""))})
    return peers


def fetch_json(config, path):
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect(),
        urllib.request.HTTPSHandler(context=tls_context(config.api_ca)))
    request = urllib.request.Request(config.url + path, headers={
        "Authorization": "Token " + config.token,
        "Accept": "application/json", "Accept-Encoding": "identity",
        "User-Agent": f"netbird-notifier/{VERSION}"})
    with opener.open(request, timeout=config.timeout) as response:
        if response.status != 200 or response.headers.get_content_type() != "application/json":
            raise ProtocolError("Unexpected API status or content type")
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ProtocolError("API response exceeds size limit")
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProtocolError("API returned invalid JSON") from None


def fetch_users(config):
    return parse_users(fetch_json(config, "/api/users"))


def fetch_snapshot(config):
    snapshot = {}
    user_events = {USER_PENDING, USER_JOINED, SERVICE_USER_CREATED}.intersection(config.enabled_events)
    if user_events:
        users = fetch_users(config)
        if USER_PENDING in user_events:
            snapshot[USER_PENDING] = [
                {**user, "event": USER_PENDING} for user in users
                if user["pending_approval"] and not user["is_service_user"]
            ]
        if USER_JOINED in user_events:
            if any(not user["is_service_user"] and not user["pending_approval"]
                   and not user["status"] for user in users):
                raise ProtocolError("User status is required for joined-user alerts")
            snapshot[USER_JOINED] = [
                {**user, "event": USER_JOINED} for user in users
                if not user["is_service_user"] and not user["pending_approval"]
                and user["status"] == "active"
            ]
        if SERVICE_USER_CREATED in user_events:
            snapshot[SERVICE_USER_CREATED] = [
                {**user, "event": SERVICE_USER_CREATED} for user in users
                if user["is_service_user"]
            ]
    if PEER_ADDED in config.enabled_events:
        snapshot[PEER_ADDED] = [
            {**peer, "event": PEER_ADDED}
            for peer in parse_peers(fetch_json(config, "/api/peers"))
        ]
    return snapshot


def clean_text(value):
    if not isinstance(value, str):
        return ""
    return "".join(c for c in value[:512] if c.isprintable())


def digest(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=True).encode()).hexdigest()


def alert_content(config, item):
    event = item.get("event", USER_PENDING)
    if event == USER_PENDING:
        return "NetBird user awaiting approval", (
            "A user was pending approval at the last check.\n\n"
            f"Name (user supplied): {clean_text(item.get('name', ''))}\n"
            f"Email (user supplied): {clean_text(item.get('email', ''))}\n"
            f"User ID: {clean_text(item['id'])}\n\n"
            f"Review in your trusted NetBird dashboard: {config.url}\n"
            "Verify the request before approving it. This notifier cannot approve users.\n")
    if event == USER_JOINED:
        return "NetBird user joined", (
            "A user appeared as active in the NetBird account after the event baseline.\n\n"
            f"Name (user supplied): {clean_text(item.get('name', ''))}\n"
            f"Email (user supplied): {clean_text(item.get('email', ''))}\n"
            f"User ID: {clean_text(item['id'])}\n\n"
            f"Review in your trusted NetBird dashboard: {config.url}\n"
            "Verify that this account access is expected.\n")
    if event == SERVICE_USER_CREATED:
        return "NetBird service user created", (
            "A service user appeared in the NetBird account after the event baseline.\n\n"
            f"Name: {clean_text(item.get('name', ''))}\n"
            f"Service user ID: {clean_text(item['id'])}\n\n"
            f"Review in your trusted NetBird dashboard: {config.url}\n"
            "Verify the service user, its role, and its tokens.\n")
    if event == PEER_ADDED:
        public_ip = clean_text(item.get("connection_ip", ""))
        public_ip_line = f"Public IP (API supplied): {public_ip}\n" if public_ip else ""
        return "NetBird peer added", (
            "A peer appeared in the NetBird account after the event baseline.\n\n"
            f"Name (peer supplied): {clean_text(item.get('name', ''))}\n"
            f"Hostname (peer supplied): {clean_text(item.get('hostname', ''))}\n"
            f"NetBird IP: {clean_text(item.get('ip', ''))}\n"
            f"{public_ip_line}"
            f"Peer ID: {clean_text(item['id'])}\n"
            f"Created at (API supplied): {clean_text(item.get('created_at', ''))}\n\n"
            f"Review in your trusted NetBird dashboard: {config.url}\n"
            "Verify that this peer is expected.\n")
    raise ProtocolError("Unsupported alert event")


def send_alert(config, item, recipient, key, test=False):
    message = EmailMessage()
    message["From"] = Address(display_name=config.sender_name, addr_spec=config.sender)
    message["To"] = recipient
    subject, body = ("Notifier test email", "This is a notifier delivery test.\n") \
        if test else alert_content(config, item)
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=False, usegmt=True)
    message["Message-ID"] = f"<{key}@netbird-notifier.invalid>"
    message.set_content(body)
    context = tls_context(config.smtp_ca)
    if config.security == "ssl":
        server = smtplib.SMTP_SSL(config.host, config.port, timeout=config.timeout, context=context)
    else:
        server = smtplib.SMTP(config.host, config.port, timeout=config.timeout)
    try:
        server.ehlo_or_helo_if_needed()
        if config.security == "starttls":
            server.starttls(context=context)
            server.ehlo()
        if config.auth:
            server.login(config.username, config.password)
        refused = server.send_message(message, from_addr=config.sender, to_addrs=[recipient])
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
    finally:
        # QUIT failures after successful DATA must not turn acceptance into failure.
        server.close()


def open_state(config):
    config.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(config.state_dir / "state.sqlite3", timeout=1, isolation_level=None)
    try:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA trusted_schema=OFF")
        if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise sqlite3.DatabaseError("State integrity check failed")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2, 3):
            raise sqlite3.DatabaseError("Unsupported state version")
        db.execute("CREATE TABLE IF NOT EXISTS sent (key TEXT PRIMARY KEY, accepted_at INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS health (scope TEXT PRIMARY KEY, success_at INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS retries (key TEXT PRIMARY KEY, attempted_at INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS event_baselines ("
                   "scope TEXT NOT NULL, event TEXT NOT NULL, active INTEGER NOT NULL CHECK(active IN (0,1)), "
                   "initialized_at INTEGER NOT NULL, PRIMARY KEY(scope,event))")
        db.execute("CREATE TABLE IF NOT EXISTS observed ("
                   "scope TEXT NOT NULL, event TEXT NOT NULL, object_key TEXT NOT NULL, "
                   "PRIMARY KEY(scope,event,object_key))")
        db.execute("PRAGMA user_version=3")
        return db
    except Exception:
        db.close()
        raise


def event_key(config, event, object_id):
    return digest(config.url, config.namespace, event, object_id)


def delivery_key(config, event, object_id, recipient):
    # Preserve the v0.1.x pending-user key so existing delivery history migrates intact.
    if event == USER_PENDING:
        return digest(config.url, config.namespace, object_id, recipient)
    return digest(config.url, config.namespace, event, object_id, recipient)


def normalize_snapshot(config, value):
    if isinstance(value, list):
        value = {USER_PENDING: value}
    if not isinstance(value, dict):
        raise ProtocolError("Invalid notifier snapshot")
    expected = set(config.enabled_events)
    if set(value) != expected:
        raise ProtocolError("Notifier snapshot does not match enabled events")
    normalized = {}
    for event, items in value.items():
        if event not in {setting[0] for setting in EVENT_SETTINGS} or not isinstance(items, list):
            raise ProtocolError("Invalid notifier snapshot")
        seen = set()
        normalized[event] = []
        for item in items:
            if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                    or not 1 <= len(item["id"]) <= 1024 or item["id"] in seen):
                raise ProtocolError("Invalid notifier snapshot")
            normalized[event].append({**item, "event": event})
            seen.add(item["id"])
    return normalized


def prepare_creation_events(config, db, snapshot):
    scope = digest(config.url, config.namespace)
    baselines = {}
    db.execute("BEGIN IMMEDIATE")
    try:
        for event in CREATION_EVENTS:
            row = db.execute("SELECT active FROM event_baselines WHERE scope=? AND event=?",
                             (scope, event)).fetchone()
            if event not in config.enabled_events:
                if row:
                    db.execute("UPDATE event_baselines SET active=0 WHERE scope=? AND event=?",
                               (scope, event))
                continue
            items = snapshot[event]
            if row is None or row[0] == 0:
                db.execute("DELETE FROM observed WHERE scope=? AND event=?", (scope, event))
                db.executemany("INSERT INTO observed VALUES (?, ?, ?)",
                               ((scope, event, event_key(config, event, item["id"])) for item in items))
                db.execute("INSERT OR REPLACE INTO event_baselines VALUES (?, ?, 1, ?)",
                           (scope, event, int(time.time())))
                baselines[event] = len(items)
                snapshot[event] = []
            else:
                snapshot[event] = [item for item in items if not db.execute(
                    "SELECT 1 FROM observed WHERE scope=? AND event=? AND object_key=?",
                    (scope, event, event_key(config, event, item["id"]))).fetchone()]
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return baselines


def prepare_pending_episode(config, db, snapshot):
    """Rearm a user only after a successful poll observed it was no longer pending."""
    scope = digest(config.url, config.namespace)
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("SELECT active FROM event_baselines WHERE scope=? AND event=?",
                         (scope, USER_PENDING)).fetchone()
        if USER_PENDING not in config.enabled_events:
            if row:
                db.execute("UPDATE event_baselines SET active=0 WHERE scope=? AND event=?",
                           (scope, USER_PENDING))
            db.execute("COMMIT")
            return

        items = snapshot[USER_PENDING]
        current = {event_key(config, USER_PENDING, item["id"]): item for item in items}
        if row is None or row[0] == 0:
            # On upgrade or re-enable, establish presence without replaying delivery history.
            db.execute("DELETE FROM observed WHERE scope=? AND event=?", (scope, USER_PENDING))
            for object_key in current:
                db.execute("INSERT INTO observed VALUES (?, ?, ?)",
                           (scope, USER_PENDING, object_key))
            db.execute("INSERT OR REPLACE INTO event_baselines VALUES (?, ?, 1, ?)",
                       (scope, USER_PENDING, int(time.time())))
        else:
            previous = {record[0] for record in db.execute(
                "SELECT object_key FROM observed WHERE scope=? AND event=?",
                (scope, USER_PENDING))}
            for object_key, item in current.items():
                if object_key not in previous:
                    for recipient in config.recipients:
                        key = delivery_key(config, USER_PENDING, item["id"], recipient)
                        db.execute("DELETE FROM sent WHERE key=?", (key,))
                        db.execute("DELETE FROM retries WHERE key=?", (key,))
            db.execute("DELETE FROM observed WHERE scope=? AND event=?", (scope, USER_PENDING))
            for object_key in current:
                db.execute("INSERT INTO observed VALUES (?, ?, ?)",
                           (scope, USER_PENDING, object_key))
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def poll(config, db, fetch=fetch_snapshot, send=send_alert, stop=None):
    snapshot = normalize_snapshot(config, fetch(config))
    prepare_pending_episode(config, db, snapshot)
    baselines = prepare_creation_events(config, db, snapshot)
    if baselines:
        counts = " ".join(f"{event}={count}" for event, count in baselines.items())
        LOG.info("creation_baseline_initialized %s", counts)
    sent = attempts = 0
    failed = False
    candidates = []
    for event, items in snapshot.items():
        for item in items:
            for recipient in config.recipients:
                key = delivery_key(config, event, item["id"], recipient)
                last = db.execute("SELECT attempted_at FROM retries WHERE key=?", (key,)).fetchone()
                candidates.append((last[0] if last else 0, event, item, recipient, key))
    # Unattempted deliveries first, then oldest failures. Stable sort preserves
    # API/recipient order for new requests, while avoiding a poisoned head of queue.
    candidates.sort(key=lambda item: item[0])
    for _, event, item, recipient, key in candidates:
        if attempts >= config.max_alerts:
            break
        if stop is not None and stop.is_set():
            return sent
        # Reserve a writer lock BEFORE checking, across SMTP and durable commit.
        # A second process using this local volume cannot send the same key.
        db.execute("BEGIN IMMEDIATE")
        try:
            exists = db.execute("SELECT 1 FROM sent WHERE key=?", (key,)).fetchone()
            if not exists and attempts < config.max_alerts:
                attempts += 1
                try:
                    send(config, item, recipient, key)
                except (OSError, smtplib.SMTPException):
                    failed = True
                    db.execute("INSERT OR REPLACE INTO retries VALUES (?, ?)", (key, time.time_ns()))
                    LOG.error("smtp_delivery_failed; check credentials, TLS, relay policy, and connectivity")
                else:
                    db.execute("INSERT INTO sent VALUES (?, ?)", (key, int(time.time())))
                    db.execute("DELETE FROM retries WHERE key=?", (key,))
                    sent += 1
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    scope = digest(config.url, config.namespace)
    for event in CREATION_EVENTS:
        for item in snapshot.get(event, ()):
            keys = [delivery_key(config, event, item["id"], recipient)
                    for recipient in config.recipients]
            if all(db.execute("SELECT 1 FROM sent WHERE key=?", (key,)).fetchone() for key in keys):
                db.execute("INSERT OR IGNORE INTO observed VALUES (?, ?, ?)",
                           (scope, event, event_key(config, event, item["id"])))
    if failed:
        raise ProtocolError("One or more SMTP deliveries failed")
    db.execute("INSERT OR REPLACE INTO health VALUES (?, ?)", (scope, int(time.time())))
    counts = " ".join(f"{event}={len(snapshot.get(event, ()))}" for event in config.enabled_events)
    LOG.info("poll_success %s accepted=%d baselined=%d", counts, sent, sum(baselines.values()))
    return sent


def healthy(config):
    path = config.state_dir.resolve() / "state.sqlite3"
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute("SELECT success_at FROM health WHERE scope=?",
                         (digest(config.url, config.namespace),)).fetchone()
    return bool(row and 0 <= time.time() - row[0] < max(180, config.interval * 3))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    for flag in ("once", "dry-run", "check-config", "test-email", "healthcheck"):
        group.add_argument("--" + flag, action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.umask(0o077)
    try:
        config = Config.load()
        if args.healthcheck:
            return 0 if healthy(config) else 1
        # Validate CA files even when no network request is made.
        tls_context(config.api_ca)
        tls_context(config.smtp_ca)
        if args.check_config:
            LOG.info("configuration_valid; connectivity not tested")
            return 0
        if args.dry_run:
            snapshot = fetch_snapshot(config)
            counts = " ".join(f"{event}={len(snapshot.get(event, ()))}"
                              for event in config.enabled_events)
            LOG.info("dry_run %s; no email or state changes", counts)
            return 0
        if args.test_email:
            for recipient in config.recipients:
                send_alert(config, {}, recipient, digest(time.time_ns(), recipient), test=True)
            LOG.info("test_email_accepted; verify inbox delivery")
            return 0
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        with closing(open_state(config)) as db:
            failures = 0
            while not stop.is_set():
                try:
                    poll(config, db, stop=stop)
                    failures = 0
                except sqlite3.DatabaseError:
                    # Never delete or reset state automatically on storage failures.
                    LOG.error("state_failure; stop and inspect storage before restarting")
                    return 1
                except Exception as exc:
                    failures += 1
                    code = exc.code if isinstance(exc, urllib.error.HTTPError) else None
                    LOG.error("poll_failed category=%s http_status=%s; details suppressed",
                              type(exc).__name__, code)
                    if args.once:
                        return 1
                if args.once:
                    return 0
                delay = min(max(config.interval, 900), config.interval * (2 ** min(failures, 6)))
                stop.wait(delay)
        return 0
    except ConfigError as exc:
        LOG.error("configuration_error: %s", exc)
        return 2
    except Exception as exc:
        LOG.error("operation_failed category=%s; details suppressed", type(exc).__name__)
        return 1
