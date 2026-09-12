"""Loopback-only HTTPS and SMTP integration tests; never contact real services."""

from contextlib import closing, contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socketserver
import ssl
import tempfile
import threading
import unittest
import urllib.error

from notifier import app
from test_notifier import ACTIVE_USER, PEER, SERVICE_USER, USER, all_events, environment

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
except ImportError:
    x509 = None


class APIHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        self.server.requests.append((self.path, self.headers.get("Authorization")))
        self.send_response(self.server.status)
        self.send_header("Content-Type", "application/json")
        if self.server.status == 302:
            self.send_header("Location", "https://localhost:1/do-not-follow")
        self.end_headers()
        payload = self.server.payload.get(self.path, []) if isinstance(self.server.payload, dict) \
            else self.server.payload
        self.wfile.write(json.dumps(payload).encode())


class MailHandler(socketserver.BaseRequestHandler):
    def handle(self):
        conn = self.request
        if self.server.implicit:
            try:
                conn = self.server.context.wrap_socket(conn, server_side=True)
            except ssl.SSLError:
                return
        stream = conn.makefile("rb")
        secure = self.server.implicit
        try:
            conn.sendall(b"220 localhost test SMTP\r\n")
            while True:
                line = stream.readline()
                if not line:
                    return
                verb = line.split(b" ", 1)[0].strip().upper()
                if verb in (b"EHLO", b"HELO"):
                    conn.sendall(b"250-localhost\r\n250-STARTTLS\r\n250 AUTH PLAIN\r\n")
                elif verb == b"STARTTLS":
                    conn.sendall(b"220 begin TLS\r\n")
                    stream.close()
                    conn = self.server.context.wrap_socket(conn, server_side=True)
                    stream = conn.makefile("rb")
                    secure = True
                elif verb == b"AUTH":
                    self.server.auth_secure.append(secure)
                    conn.sendall(b"235 authenticated\r\n")
                elif verb in (b"MAIL", b"RCPT", b"RSET"):
                    conn.sendall(b"250 accepted\r\n")
                elif verb == b"DATA":
                    conn.sendall(b"354 send data\r\n")
                    data = bytearray()
                    while True:
                        line = stream.readline()
                        if line in (b".\r\n", b""):
                            break
                        data.extend(line)
                    self.server.messages.append(bytes(data))
                    conn.sendall(b"250 queued\r\n")
                else:
                    conn.sendall(b"500 unsupported\r\n")
        finally:
            stream.close()
            conn.close()


class MailServer(socketserver.ThreadingTCPServer):
    daemon_threads = True


@contextmanager
def running(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@unittest.skipIf(x509 is None, "Install requirements-dev.txt to run TLS integration tests")
class IntegrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .sign(key, hashes.SHA256()))
        self.ca = self.path / "test-cert.pem"
        self.ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path = self.path / "test-key.pem"
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(self.ca, key_path)
        self.config = app.Config.load(environment(self.path / "state"))

    def api(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), APIHandler)
        server.socket = self.context.wrap_socket(server.socket, server_side=True)
        server.status, server.payload, server.requests = 200, [USER], []
        return server

    def mail(self, implicit=False):
        server = MailServer(("127.0.0.1", 0), MailHandler)
        server.context, server.implicit = self.context, implicit
        server.auth_secure, server.messages = [], []
        return server

    def test_https_starttls_end_to_end_restart(self):
        with running(self.api()) as api, running(self.mail()) as mail:
            config = replace(self.config, url=f"https://localhost:{api.server_port}",
                             api_ca=str(self.ca), host="localhost", port=mail.server_address[1],
                             smtp_ca=str(self.ca))
            with closing(app.open_state(config)) as db:
                self.assertEqual(app.poll(config, db), 1)
            with closing(app.open_state(config)) as db:
                self.assertEqual(app.poll(config, db), 0)
            self.assertEqual(len(mail.messages), 1)
            self.assertEqual(mail.auth_secure, [True])
            self.assertEqual(api.requests, [("/api/users", "Token test-only-token")] * 2)
            self.assertTrue(app.healthy(config))

    def test_all_v020_events_end_to_end(self):
        with running(self.api()) as api, running(self.mail()) as mail:
            api.payload = {"/api/users": [USER, ACTIVE_USER, SERVICE_USER], "/api/peers": [PEER]}
            config = all_events(replace(self.config, url=f"https://localhost:{api.server_port}",
                                        api_ca=str(self.ca), host="localhost",
                                        port=mail.server_address[1], smtp_ca=str(self.ca)))
            with closing(app.open_state(config)) as db:
                self.assertEqual(app.poll(config, db), 1)
                api.payload["/api/users"].extend([
                    {**ACTIVE_USER, "id": "active-new"},
                    {**SERVICE_USER, "id": "service-new"},
                ])
                api.payload["/api/peers"].append({**PEER, "id": "peer-new"})
                self.assertEqual(app.poll(config, db), 3)
                self.assertEqual(app.poll(config, db), 0)
            subjects = [line for message in mail.messages for line in message.split(b"\r\n")
                        if line.startswith(b"Subject:")]
            self.assertEqual(subjects, [b"Subject: NetBird user awaiting approval",
                                        b"Subject: NetBird user joined",
                                        b"Subject: NetBird service user created",
                                        b"Subject: NetBird peer added"])
            self.assertEqual(api.requests,
                             [item for _ in range(3) for item in
                              (("/api/users", "Token test-only-token"),
                               ("/api/peers", "Token test-only-token"))])

    def test_https_untrusted_and_wrong_hostname_rejected(self):
        with running(self.api()) as api:
            config = replace(self.config, url=f"https://localhost:{api.server_port}")
            with self.assertRaises(urllib.error.URLError):
                app.fetch_users(config)
            config = replace(config, url=f"https://127.0.0.1:{api.server_port}", api_ca=str(self.ca))
            with self.assertRaises(urllib.error.URLError):
                app.fetch_users(config)
            self.assertEqual(api.requests, [])

    def test_https_redirect_and_unauthorized_rejected(self):
        with running(self.api()) as api:
            config = replace(self.config, url=f"https://localhost:{api.server_port}", api_ca=str(self.ca))
            api.status = 302
            with self.assertRaises(app.ProtocolError):
                app.fetch_users(config)
            api.status = 401
            with self.assertRaises(urllib.error.HTTPError) as error:
                app.fetch_users(config)
            self.assertEqual(error.exception.code, 401)
            self.assertEqual(len(api.requests), 2)

    def test_implicit_tls_smtp_delivery(self):
        with running(self.mail(implicit=True)) as mail:
            config = replace(self.config, host="localhost", port=mail.server_address[1],
                             smtp_ca=str(self.ca), security="ssl")
            app.send_alert(config, USER, "admin@example.com", "test-key")
            self.assertEqual(len(mail.messages), 1)
            self.assertEqual(mail.auth_secure, [True])

    def test_smtp_untrusted_certificate_rejected(self):
        with running(self.mail(implicit=True)) as mail:
            config = replace(self.config, host="localhost", port=mail.server_address[1], security="ssl")
            with self.assertRaises(ssl.SSLCertVerificationError):
                app.send_alert(config, USER, "admin@example.com", "test-key")
            self.assertEqual(mail.messages, [])
            self.assertEqual(mail.auth_secure, [])
