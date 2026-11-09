"""Bounded collection helpers; no shell, privilege escalation or device access."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time

TOOL_VERSION = "0.3.0"
MAX_OUTPUT = 65536


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def redact(text):
    # Best effort only: local reports still require review before sharing.
    text = re.sub(r"(?im)(\b(?:password|passwd|psk|wpa_passphrase|token|secret|api_key)\b\s*[=:]\s*)([^\r\n]+)",
                  r"\1[REDACTED]", text)
    return re.sub(r"(https?://)[^\s/@:]+:[^\s/@]+@", r"\1[REDACTED]@", text)


def run(argv, timeout=3, max_output=MAX_OUTPUT):
    """Keep bounded output while draining pipes; kill the process group on timeout."""
    started = time.monotonic()
    result = {"command": list(argv), "collected_at": utc_now()}
    captured = bytearray()
    total = [0]
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, shell=False,
                                start_new_session=(os.name == "posix"),
                                env=dict(os.environ, LC_ALL="C", PAGER="cat",
                                         SYSTEMD_PAGER="cat", PYTHONDONTWRITEBYTECODE="1"))
    except (OSError, ValueError) as exc:
        result.update(status="unavailable", error=str(exc))
        return result

    def drain():
        try:
            while True:
                data = proc.stdout.read(4096)
                if not data:
                    break
                total[0] += len(data)
                captured.extend(data[:max(0, max_output - len(captured))])
        finally:
            proc.stdout.close()

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        proc.wait(timeout=timeout)
        result["status"] = "ok" if proc.returncode == 0 else "error"
    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except ProcessLookupError:
            pass
        proc.wait()
    reader.join(timeout=1)
    output = redact(bytes(captured).decode("utf-8", "replace"))
    if result["status"] == "error" and re.search(r"permission denied|operation not permitted|access denied", output, re.I):
        result["status"] = "permission_denied"
    result.update(returncode=proc.returncode, output=output, truncated=total[0] > max_output,
                  duration_ms=round((time.monotonic() - started) * 1000, 2))
    return result


def read_text(path, limit=MAX_OUTPUT):
    try:
        with open(path, "rb") as stream:
            data = stream.read(limit + 1)
        return {"status": "ok", "path": str(path), "collected_at": utc_now(),
                "output": redact(data[:limit].decode("utf-8", "replace").replace("\x00", "")),
                "truncated": len(data) > limit}
    except OSError as exc:
        return {"status": "permission_denied" if isinstance(exc, PermissionError) else "unavailable",
                "path": str(path), "error": str(exc), "collected_at": utc_now()}


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_new(path, data):
    """Exclusive creation: never overwrite existing evidence."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def envelope(kind):
    return {"schema_version": 1, "kind": kind, "tool_version": TOOL_VERSION,
            "collected_at": utc_now(), "read_only": True}
