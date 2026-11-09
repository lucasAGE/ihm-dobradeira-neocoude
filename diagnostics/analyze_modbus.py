#!/usr/bin/env python3
"""Analyze an OFFLINE JSONL transaction capture. Never opens a serial device.

Each line: {"request_at":"...+00:00", "response_at":"...+00:00",
"request_hex":"01 03 ... CRC", "response_hex":"01 03 ... CRC"}.
For a missing response use error="timeout" and omit response_at/response_hex.
Frames must come from an existing logger or an isolated passive analyzer.
"""
import argparse
from collections import Counter
import datetime as dt
import json
from pathlib import Path
import statistics

try:
    from .common import envelope, sha256_file, write_json_new
except ImportError:
    from common import envelope, sha256_file, write_json_new


def crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def valid_crc(frame):
    return len(frame) >= 4 and crc16(frame[:-2]) == int.from_bytes(frame[-2:], "little")


def timestamp(value):
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return parsed.timestamp()


def inspect_transaction(item):
    start = timestamp(item["request_at"])
    request = bytes.fromhex(item["request_hex"])
    result = {"request_at": item["request_at"], "epoch": start, "status": "invalid_request", "latency_ms": None}
    if len(request) != 8 or not valid_crc(request):
        result["reason"] = "request_length_or_crc"
        return result
    slave, function = request[:2]
    address = int.from_bytes(request[2:4], "big")
    count = int.from_bytes(request[4:6], "big")
    result.update(slave=slave, function=function, address=address, count=count)
    if not 1 <= slave <= 247:
        result["reason"] = "non_unicast_address"
        return result
    if function not in (1, 2, 3, 4):
        result.update(status="unsupported_function", reason="Only captured FC01/02/03/04 reads are analyzed")
        return result
    if not 1 <= count <= (2000 if function in (1, 2) else 125) or address + count > 65536:
        result["reason"] = "invalid_register_range"
        return result
    if item.get("error"):
        result.update(status="timeout" if item["error"] == "timeout" else "capture_error", reason=str(item["error"])[:200])
        return result
    response_time = timestamp(item["response_at"])
    result["latency_ms"] = round((response_time - start) * 1000, 3)
    if response_time < start:
        result.update(status="invalid_timestamps", latency_ms=None)
        return result
    response = bytes.fromhex(item["response_hex"])
    if not valid_crc(response):
        result["status"] = "crc_error"
    elif response[0] != slave:
        result["status"] = "slave_mismatch"
    elif response[1] == function | 0x80 and len(response) == 5:
        result.update(status="modbus_exception", exception_code=response[2])
    elif response[1] != function:
        result["status"] = "function_mismatch"
    elif len(response) != 5 + ((count + 7) // 8 if function in (1, 2) else count * 2) or response[2] != ((count + 7) // 8 if function in (1, 2) else count * 2):
        result["status"] = "length_mismatch"
    elif function in (1, 2) and count % 8 and response[-3] >> (count % 8):
        result["status"] = "padding_error"
    elif function in (1, 2):
        result.update(status="ok", bits=[bool(response[3 + i // 8] & (1 << (i % 8))) for i in range(count)])
    else:
        result.update(status="ok", values=[int.from_bytes(response[i:i+2], "big") for i in range(3, len(response)-2, 2)])
    return result


def analyze(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Capture must be a regular file of at most 32 MiB; devices are never opened")
    report = envelope("modbus_capture")
    report["source"] = {"path": str(path), "sha256": sha256_file(path), "mode": "offline_capture"}
    rows, counts, latencies, starts, read_starts = [], Counter(), [], [], []
    # Bounded input and output: retain 500 events; aggregate at most 20,000 lines.
    with open(path, encoding="utf-8-sig") as stream:
        for number in range(1, 20002):
            line = stream.readline(65537)
            if not line:
                break
            if number > 20000 or len(line) > 65536:
                raise ValueError("Capture exceeds 20,000 lines or 64 KiB per line; split offline first")
            try:
                row = inspect_transaction(json.loads(line))
                starts.append(row["epoch"])
                if row["status"] == "ok":
                    latencies.append(row["latency_ms"])
                    read_starts.append(row["epoch"])
            except (ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
                row = {"status": "invalid_capture", "reason": str(exc)[:200]}
            counts[row["status"]] += 1
            if len(rows) < 500:
                rows.append(dict(row, line=number))
    span = max(starts) - min(starts) if len(starts) > 1 else 0
    sorted_latency = sorted(latencies)
    report["statistics"] = {"transactions": sum(counts.values()), "by_status": dict(counts),
        "capture_span_seconds": round(span, 6),
        "observed_request_hz": (len(starts)-1)/span if span > 0 else None,
        "successful_read_hz": (len(read_starts)-1)/(max(read_starts)-min(read_starts)) if len(read_starts) > 1 and max(read_starts) > min(read_starts) else None,
        "latency_median_ms": statistics.median(latencies) if latencies else None,
        "latency_p95_ms": sorted_latency[max(0, (95*len(latencies)+99)//100-1)] if latencies else None,
        "latency_max_ms": max(latencies) if latencies else None}
    report["events"] = rows
    report["events_truncated"] = sum(counts.values()) > len(rows)
    report["limitations"] = ["Metrics describe captured FC01/02/03/04 transactions only; gaps or logger clock corrections affect them.",
                              "RTU has no transaction ID: request/response pairing is supplied by the capture source, not proven here.",
                              "No capture is fabricated from WebSocket data. No automatic angle conversion or Ladder compatibility claim."]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        write_json_new(args.output, analyze(args.capture))
    except (OSError, ValueError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
