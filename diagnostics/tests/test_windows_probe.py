"""End-to-end test with local mock HTTP/WS servers; no machine is contacted."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import socketserver
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LocalServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class HttpHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(5)
        self.request.recv(8192)
        self.request.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 4\r\nConnection: close\r\n\r\ntest")


def ws_frame(body, opcode=1, final=True):
    data = body.encode()
    header = bytes([(0x80 if final else 0) | opcode])
    return header + (bytes([len(data)]) if len(data) < 126 else b"\x7e" + len(data).to_bytes(2, "big")) + data


class WsHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(5)
        headers = b""
        while b"\r\n\r\n" not in headers and len(headers) < 16384:
            chunk = self.request.recv(4096)
            if not chunk:
                return
            headers += chunk
        key = next(line.split(b":", 1)[1].strip() for line in headers.split(b"\r\n") if line.lower().startswith(b"sec-websocket-key:"))
        accept = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
        self.request.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n")
        message = json.dumps({"type": "full_state", "data": {"encoder_raw": 311, "encoder_degrees": 139.95, "poll_count": 1,
            "inputs": {"E0": False, "E6": True}, "outputs": {"S0": True}, "control_bits": {"ATINGIU_ANGULO": False},
            "states": {"ST_IDLE": True}, "velocidade_rpm": 5.0, "contador_pecas": 10,
            "poll_ok": False, "feedback_version": 1, "feedback_session": "fixture",
            "machine_state_name": "DESCONHECIDO", "machine_state_error": "read_failed",
            "read_quality": {"inputs.E6": {"status": "error", "success_count": 1, "error_count": 1}}}})
        self.request.sendall(ws_frame(message[:30], final=False) + ws_frame(message[30:], opcode=0))
        self.request.sendall(ws_frame('{"type":"state_update","data":{"poll_count":2}}') + ws_frame("invalid json"))
        try:
            while True:
                data = self.request.recv(4096)
                if not data:
                    break
                self.server.received.append(data)
        except (ConnectionError, TimeoutError, OSError):
            pass


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Requires Windows PowerShell 5.1")
class WindowsProbeTests(unittest.TestCase):
    def test_receive_only_probe_with_fragmented_websocket_and_closed_port(self):
        with LocalServer(("127.0.0.1", 0), HttpHandler) as http, LocalServer(("127.0.0.1", 0), WsHandler) as ws:
            ws.received = []
            workers = [threading.Thread(target=server.serve_forever, daemon=True) for server in (http, ws)]
            for worker in workers:
                worker.start()
            try:
                with socket.socket() as unavailable:
                    unavailable.bind(("127.0.0.1", 0))
                    closed_port = unavailable.getsockname()[1]
                with tempfile.TemporaryDirectory() as directory:
                    output = Path(directory) / "report.json"
                    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "Test-Neocoude.ps1"),
                        "-TargetAddress", "127.0.0.1", "-Ports", str(closed_port), "-TimeoutMs", "4000",
                        "-HttpPort", str(http.server_address[1]), "-WebSocketPort", str(ws.server_address[1]),
                        "-WebSocketSeconds", "1", "-OutputPath", str(output)], capture_output=True, timeout=25)
                    self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
                    report = json.loads(output.read_text(encoding="utf-8-sig"))
                    self.assertEqual(report["checks"]["tcp"][0]["status"], "refused")
                    self.assertEqual(report["checks"]["http"]["status_code"], 200)
                    observed = report["checks"]["websocket"]
                    self.assertTrue(observed["connected"], observed)
                    self.assertEqual(observed["status"], "observation_complete")
                    self.assertEqual(observed["malformed"], 1)
                    self.assertEqual(observed["frames"][0]["data"]["encoder_raw"], 311)
                    self.assertEqual(observed["frames"][0]["data"]["inputs"], {"E0": False, "E6": True})
                    self.assertEqual(observed["frames"][0]["data"]["outputs"], {"S0": True})
                    self.assertEqual(observed["frames"][0]["data"]["control_bits"], {"ATINGIU_ANGULO": False})
                    self.assertEqual(observed["frames"][0]["data"]["states"], {"ST_IDLE": True})
                    self.assertEqual(observed["frames"][0]["data"]["contador_pecas"], 10)
                    self.assertEqual(observed["frames"][0]["data"]["read_quality"]["inputs.E6"]["status"], "error")
                    self.assertEqual(observed["frames"][0]["data"]["machine_state_error"], "read_failed")
                    self.assertEqual(observed["frames"][0]["data"]["feedback_version"], 1)
                    self.assertFalse(observed["frames"][0]["data"]["poll_ok"])
                    self.assertEqual(observed["frames"][1]["data"]["poll_count"], 2)
                    self.assertIsNone(observed["successful_encoder_read_hz"])
                    self.assertEqual(ws.received, [])
            finally:
                http.shutdown(); ws.shutdown()
                for worker in workers:
                    worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
