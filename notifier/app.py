"""Read-only API polling, TLS SMTP delivery, and durable deduplication."""

import argparse
from contextlib import closing
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formatdate
import hashlib
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

LOG = logging.getLogger("notifier")
MAX_RESPONSE = 5 * 1024 * 1024


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
    recipients: tuple
    state_dir: Path
    namespace: str
    interval: int
    timeout: int
    max_alerts: int
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
        return cls(url, token, smtp_host,
                   integer(env, "SMTP_PORT", 465 if security == "ssl" else 587, 1, 65535),
                   security, auth, username, password, address(env.get("SMTP_FROM", "")),
                   recipients, Path(env.get("STATE_DIR", "/data")), namespace,
                   integer(env, "POLL_INTERVAL_SECONDS", 60, 30, 86400),
                   integer(env, "NETWORK_TIMEOUT_SECONDS", 20, 1, 120),
                   integer(env, "MAX_ALERTS_PER_POLL", 20, 1, 1000),
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
                or user["id"] in seen):
            raise ProtocolError("Invalid user schema; no alerts sent")
        seen.add(user["id"])
        if user["pending_approval"] and not user.get("is_service_user", False):
            users.append({"id": user["id"], "email": clean_text(user.get("email", "")),
                          "name": clean_text(user.get("name", ""))})
    return users


def fetch_users(config):
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect(),
        urllib.request.HTTPSHandler(context=tls_context(config.api_ca)))
    request = urllib.request.Request(config.url + "/api/users", headers={
        "Authorization": "Token " + config.token,
        "Accept": "application/json", "Accept-Encoding": "identity",
        "User-Agent": "netbird-notifier/0.1.0"})
    with opener.open(request, timeout=config.timeout) as response:
        if response.status != 200 or response.headers.get_content_type() != "application/json":
            raise ProtocolError("Unexpected API status or content type")
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ProtocolError("API response exceeds size limit")
    return parse_users(json.loads(raw))


def clean_text(value):
    if not isinstance(value, str):
        return ""
    return "".join(c for c in value[:512] if c.isprintable())


def digest(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=True).encode()).hexdigest()


def send_alert(config, user, recipient, key, test=False):
    message = EmailMessage()
    message["From"] = config.sender
    message["To"] = recipient
    message["Subject"] = "Notifier test email" if test else "NetBird user awaiting approval"
    message["Date"] = formatdate(localtime=False, usegmt=True)
    message["Message-ID"] = f"<{key}@netbird-notifier.invalid>"
    message.set_content("This is a notifier delivery test.\n" if test else (
        "A user was pending approval at the last check.\n\n"
        f"Name (user supplied): {clean_text(user.get('name', ''))}\n"
        f"Email (user supplied): {clean_text(user.get('email', ''))}\n"
        f"User ID: {clean_text(user['id'])}\n\n"
        f"Review in your trusted NetBird dashboard: {config.url}\n"
        "Verify the request before approving it. This notifier cannot approve users.\n"))
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
        if version not in (0, 1, 2):
            raise sqlite3.DatabaseError("Unsupported state version")
        db.execute("CREATE TABLE IF NOT EXISTS sent (key TEXT PRIMARY KEY, accepted_at INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS health (scope TEXT PRIMARY KEY, success_at INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS retries (key TEXT PRIMARY KEY, attempted_at INTEGER NOT NULL)")
        db.execute("PRAGMA user_version=2")
        return db
    except Exception:
        db.close()
        raise


def poll(config, db, fetch=fetch_users, send=send_alert, stop=None):
    users = fetch(config)
    sent = attempts = 0
    failed = False
    candidates = []
    for user in users:
        for recipient in config.recipients:
            key = digest(config.url, config.namespace, user["id"], recipient)
            last = db.execute("SELECT attempted_at FROM retries WHERE key=?", (key,)).fetchone()
            candidates.append((last[0] if last else 0, user, recipient, key))
    # Unattempted deliveries first, then oldest failures. Stable sort preserves
    # API/recipient order for new requests, while avoiding a poisoned head of queue.
    candidates.sort(key=lambda item: item[0])
    for _, user, recipient, key in candidates:
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
                    send(config, user, recipient, key)
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
    if failed:
        raise ProtocolError("One or more SMTP deliveries failed")
    scope = digest(config.url, config.namespace)
    db.execute("INSERT OR REPLACE INTO health VALUES (?, ?)", (scope, int(time.time())))
    LOG.info("poll_success pending=%d accepted=%d", len(users), sent)
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
            LOG.info("dry_run pending=%d; no email or state changes", len(fetch_users(config)))
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
