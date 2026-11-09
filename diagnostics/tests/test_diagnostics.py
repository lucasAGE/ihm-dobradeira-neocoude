import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from diagnostics import artifacts, collect_linux, common
from diagnostics.analyze_modbus import analyze, crc16, inspect_transaction


def frame(payload):
    body = bytes.fromhex(payload)
    return (body + crc16(body).to_bytes(2, "little")).hex()


def transaction(**overrides):
    item = {"request_at": "2026-11-09T12:00:00+00:00", "response_at": "2026-11-09T12:00:00.025+00:00",
            "request_hex": "010300000001840a", "response_hex": frame("0103020137")}
    item.update(overrides)
    return item


class CollectionTests(unittest.TestCase):
    def test_power_flags_distinguish_present_and_history(self):
        state = collect_linux.decode_throttled("throttled=0x50000")
        self.assertTrue(state["flags"]["undervoltage_occurred"])
        self.assertTrue(state["flags"]["throttling_occurred"])
        self.assertFalse(state["flags"]["undervoltage_now"])
        self.assertIsNone(collect_linux.decode_throttled("command unavailable"))

    def test_cpu_excludes_guest_double_counting(self):
        self.assertEqual(collect_linux.cpu_percent("cpu 100 0 50 850 0 0 0 0 90 0", "cpu 150 0 50 900 0 0 0 0 100 0"), 50)

    def test_passive_disk_activity_uses_512_byte_sectors(self):
        first = "179 0 mmcblk0 1 0 100 0 1 0 50 0 0 5 0"
        second = "179 0 mmcblk0 2 0 104 0 1 0 50 0 0 9 0"
        result = collect_linux.disk_rates(first, second, 2)["mmcblk0"]
        self.assertEqual(result["read_KiB_s"], 1)
        self.assertEqual(result["write_KiB_s"], 0)

    def test_command_output_bounded_and_timeout_reported(self):
        result = common.run([sys.executable, "-c", "print('a'*200000)"], max_output=128)
        self.assertEqual(len(result["output"]), 128)
        self.assertTrue(result["truncated"])
        result = common.run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.05)
        self.assertEqual(result["status"], "timeout")

    def test_unavailable_command_and_no_overwrite(self):
        self.assertEqual(common.run(["neocoude-no-such-executable"])["status"], "unavailable")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report.json"
            common.write_json_new(target, {"original": True})
            with self.assertRaises(FileExistsError):
                common.write_json_new(target, {})
            self.assertEqual(json.loads(target.read_text()), {"original": True})

    def test_redaction(self):
        result = common.redact('wpa_passphrase=secret-value\npassword: abc\nhttps://user:pass@example.org\nchannel=6')
        self.assertNotIn("secret-value", result)
        self.assertNotIn("abc", result)
        self.assertNotIn("user:pass", result)
        self.assertIn("channel=6", result)


class ModbusTests(unittest.TestCase):
    def test_coils_and_discrete_inputs_are_decoded_lsb_first(self):
        for function in (1, 2):
            item = transaction(request_hex=frame(f"01{function:02x}01000009"),
                               response_hex=frame(f"01{function:02x}024d01"))
            result = inspect_transaction(item)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["bits"], [True, False, True, True, False, False, True, False, True])

    def test_coil_padding_and_byte_count_are_validated(self):
        item = transaction(request_hex=frame("010101000009"), response_hex=frame("0101024d81"))
        self.assertEqual(inspect_transaction(item)["status"], "padding_error")
        item["response_hex"] = frame("0101014d")
        self.assertEqual(inspect_transaction(item)["status"], "length_mismatch")

    def test_invalid_requests_and_broadcast_never_become_readings(self):
        for payload in ("000301000001", "010301000000", "0103ffff0002", "0101010007d1"):
            self.assertEqual(inspect_transaction(transaction(request_hex=frame(payload)))["status"], "invalid_request")
        with self.assertRaises(ValueError):
            inspect_transaction(transaction(request_at="2026-11-09T12:00:00"))

    def test_every_single_bit_response_corruption_is_rejected(self):
        good = bytes.fromhex(transaction()["response_hex"])
        for position in range(len(good) * 8):
            changed = bytearray(good); changed[position // 8] ^= 1 << (position % 8)
            self.assertEqual(inspect_transaction(transaction(response_hex=changed.hex()))["status"], "crc_error")

    def test_non_file_capture_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                analyze(directory)

    def test_known_crc_and_read_response(self):
        self.assertEqual(crc16(bytes.fromhex("010300000001")), 0x0A84)
        result = inspect_transaction(transaction())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["values"], [311])
        self.assertAlmostEqual(result["latency_ms"], 25, places=2)

    def test_corruption_mismatch_exception_and_timeout(self):
        cases = [("01030201370000", "crc_error"), (frame("0203020137"), "slave_mismatch"),
                 (frame("0104020137"), "function_mismatch"), (frame("0103040137"), "length_mismatch"),
                 (frame("018302"), "modbus_exception")]
        for response, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(inspect_transaction(transaction(response_hex=response))["status"], expected)
        self.assertEqual(inspect_transaction(transaction(error="timeout"))["status"], "timeout")
        self.assertEqual(inspect_transaction(transaction(request_hex=frame("010600000001")))["status"], "unsupported_function")
        self.assertEqual(inspect_transaction(transaction(response_at="2026-11-09T11:00:00+00:00"))["status"], "invalid_timestamps")

    def test_statistics_do_not_count_timeouts_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            rows = [transaction(), transaction(request_at="2026-11-09T12:00:01+00:00", error="timeout"),
                    transaction(request_at="2026-11-09T12:00:02+00:00", response_at="2026-11-09T12:00:02.050+00:00")]
            path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            report = analyze(path)
            self.assertEqual(report["statistics"]["by_status"], {"ok": 2, "timeout": 1})
            self.assertEqual(report["statistics"]["successful_read_hz"], .5)
            self.assertEqual(report["statistics"]["observed_request_hz"], 1)


class ArtifactTests(unittest.TestCase):
    def test_backup_verify_restore_and_preserve_existing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "app"; source.mkdir()
            (source / "main.py").write_text("print('offline fixture')", encoding="utf-8")
            output = root / "backup.zip"
            artifacts.backup(source, ["main.py"], output, "test")
            self.assertEqual(len(artifacts.verify_backup(output)["files"]), 1)
            destination = root / "staging"
            result = artifacts.restore_staging(output, destination)
            self.assertFalse(result["deployed"])
            self.assertEqual((destination / "main.py").read_bytes(), (source / "main.py").read_bytes())
            with self.assertRaises(ValueError):
                artifacts.restore_staging(output, destination)
            with self.assertRaises(FileExistsError):
                artifacts.backup(source, ["main.py"], output, "test")

    def test_tampering_and_zip_traversal_rejected_before_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("../escape.txt", "C:/escape.txt", "a\\b", "ok.txt"):
                archive_path = root / (hashlib.sha256(name.encode()).hexdigest() + ".zip")
                manifest = {"kind": "application_backup", "files": {name: {"bytes": 3, "sha256": "incorrect"}}}
                with zipfile.ZipFile(archive_path, "w") as archive:
                    archive.writestr(name, b"bad")
                    archive.writestr("MANIFEST.json", json.dumps(manifest))
                with self.assertRaises(ValueError):
                    artifacts.restore_staging(archive_path, root / "staging")
                self.assertFalse((root / "staging").exists())

    def test_selection_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                artifacts.selected_files(Path(directory), ["../elsewhere"])


if __name__ == "__main__":
    unittest.main()
