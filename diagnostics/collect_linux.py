#!/usr/bin/env python3
"""One-shot Linux/Raspberry inventory. Stdlib only, Python >= 3.9.

Never opens a serial port, imports application modules, changes services,
installs packages, runs a benchmark or performs a filesystem repair.
"""
import argparse
import glob
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import stat
import sys
import time

try:
    from .common import envelope, read_text, run, sha256_file, write_json_new
except ImportError:
    from common import envelope, read_text, run, sha256_file, write_json_new

SERVICES = ("ihm.service", "ihm-web.service", "ssh.service", "sshd.service",
            "hostapd.service", "dnsmasq.service", "dhcpcd.service",
            "NetworkManager.service", "ihm-routing.service")
APP_FILES = ("main_server.py", "state_manager.py", "modbus_client.py", "modbus_map.py",
             "requirements.txt", "static/index.html", "config/ihm.service")


def decode_throttled(output):
    match = re.search(r"throttled=0x([0-9a-f]+)", output, re.I)
    if not match:
        return None
    value = int(match.group(1), 16)
    names = {0: "undervoltage_now", 1: "frequency_capped_now", 2: "throttled_now",
             3: "soft_temperature_limit_now", 16: "undervoltage_occurred",
             17: "frequency_capped_occurred", 18: "throttling_occurred",
             19: "soft_temperature_limit_occurred"}
    return {"raw": hex(value), "flags": {name: bool(value & (1 << bit)) for bit, name in names.items()},
            "scope": "Firmware historical flags are not a persistent incident log; absence does not prove power quality."}


def cpu_ticks(text):
    fields = next(line.split()[1:] for line in text.splitlines() if line.startswith("cpu "))
    values = [int(v) for v in fields[:8]]  # guest already included in user/nice
    return sum(values), values[3] + (values[4] if len(values) > 4 else 0)


def cpu_percent(before, after):
    total0, idle0 = cpu_ticks(before)
    total1, idle1 = cpu_ticks(after)
    return round(100 * (1 - (idle1 - idle0) / (total1 - total0)), 2) if total1 > total0 else None


def disk_ticks(text):
    records = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 14:
            records[fields[2]] = {"read_sectors": int(fields[5]), "write_sectors": int(fields[9]),
                                  "io_ms": int(fields[12])}
    return records


def disk_rates(before, after, elapsed):
    first, second = disk_ticks(before), disk_ticks(after)
    return {name: {"read_KiB_s": round((row["read_sectors"] - first[name]["read_sectors"]) / 2 / elapsed, 2),
                   "write_KiB_s": round((row["write_sectors"] - first[name]["write_sectors"]) / 2 / elapsed, 2),
                   "io_ms_delta": row["io_ms"] - first[name]["io_ms"]}
            for name, row in second.items() if name in first and not name.startswith(("loop", "ram"))}


def serial_metadata():
    # stat/readlink only: opening a tty can toggle control lines and steal bytes.
    paths = sorted(set(sum((glob.glob(p) for p in
                   ("/dev/ttyUSB*", "/dev/ttyACM*", "/dev/ttyAMA*", "/dev/serial*", "/dev/serial/by-id/*")), [])))
    records = []
    for path in paths:
        try:
            item = os.stat(path)
            records.append({"path": path, "target": os.path.realpath(path),
                            "mode": stat.filemode(item.st_mode), "uid": item.st_uid, "gid": item.st_gid})
        except OSError as exc:
            records.append({"path": path, "error": str(exc)})
    return records


def collect(app_root=None, interpreter=None, services=SERVICES, sample_seconds=1):
    if platform.system() != "Linux":
        raise RuntimeError("Execute este coletor no Linux alvo; para Windows use Test-Neocoude.ps1.")
    try:
        os.nice(10)
    except OSError:
        pass
    report = envelope("linux_snapshot")
    checks = report["checks"] = {}
    metrics = report["metrics"] = {}
    report["scope"] = {"hostname": socket.gethostname(), "architecture": platform.machine(),
                       "collector_python": sys.version, "uid": os.getuid(),
                       "is_raspberry_pi": False, "sample_seconds": sample_seconds}
    files = {"model": "/sys/firmware/devicetree/base/model", "os_release": "/etc/os-release",
             "memory": "/proc/meminfo", "uptime": "/proc/uptime", "load": "/proc/loadavg",
             "temperature": "/sys/class/thermal/thermal_zone0/temp",
             "cpu_frequency": "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq",
             "boot_id": "/proc/sys/kernel/random/boot_id", "resolv_conf": "/etc/resolv.conf",
             "dhcp_leases": "/var/lib/misc/dnsmasq.leases", "uart_cmdline": "/proc/cmdline"}
    for name, path in files.items():
        checks[name] = read_text(path)
    if checks["model"]["status"] != "ok":
        checks["model"] = read_text("/proc/device-tree/model")
    model = checks["model"].get("output", "").strip()
    report["scope"]["is_raspberry_pi"] = "Raspberry Pi" in model
    metrics["model"] = model or None
    for name, key, divisor in (("temperature", "cpu_temperature_c", 1000), ("cpu_frequency", "cpu_frequency_mhz", 1000)):
        try:
            metrics[key] = float(checks[name]["output"].strip()) / divisor
        except (KeyError, ValueError):
            metrics[key] = None
    memory = dict(re.findall(r"^(\w+):\s+(\d+)", checks["memory"].get("output", ""), re.M))
    metrics["memory_total_mib"] = round(int(memory["MemTotal"]) / 1024, 1) if "MemTotal" in memory else None
    metrics["memory_used_percent"] = round(100 * (1 - int(memory["MemAvailable"]) / int(memory["MemTotal"])), 2) if {"MemAvailable", "MemTotal"} <= memory.keys() else None
    stat0, disk0 = read_text("/proc/stat"), read_text("/proc/diskstats")
    began = time.monotonic()
    time.sleep(sample_seconds)
    stat1, disk1 = read_text("/proc/stat"), read_text("/proc/diskstats")
    elapsed = time.monotonic() - began
    try:
        metrics["cpu_used_percent"] = cpu_percent(stat0["output"], stat1["output"])
        metrics["disk_observed_activity"] = disk_rates(disk0["output"], disk1["output"], elapsed)
    except (KeyError, ValueError, StopIteration):
        metrics["cpu_used_percent"] = None
        metrics["disk_observed_activity"] = None
    checks["sample_counters"] = {"status": "ok" if all(c["status"] == "ok" for c in (stat0, stat1, disk0, disk1)) else "error",
                                 "before": {"cpu": stat0, "disk": disk0}, "after": {"cpu": stat1, "disk": disk1}, "elapsed_seconds": elapsed}
    usage = shutil.disk_usage("/")
    metrics["root_used_percent"] = round(100 * usage.used / usage.total, 2)
    metrics["root_free_gib"] = round(usage.free / (1024 ** 3), 2)
    commands = {
        "kernel": ["uname", "-a"], "cpu": ["lscpu"], "firmware": ["vcgencmd", "version"],
        "power_throttling": ["vcgencmd", "get_throttled"], "firmware_clock": ["vcgencmd", "measure_clock", "arm"],
        "storage": ["lsblk", "-o", "NAME,TYPE,SIZE,FSTYPE,MOUNTPOINT,RO,MODEL"],
        "filesystems": ["findmnt", "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"], "space": ["df", "-hT"], "inodes": ["df", "-i"],
        "usb": ["lsusb"], "usb_tree": ["lsusb", "-t"], "drivers": ["lsmod"],
        "services_enabled": ["systemctl", "list-unit-files", "--state=enabled", "--no-pager"],
        "services_failed": ["systemctl", "--failed", "--no-pager"],
        "service_details": ["systemctl", "show", *services, "--no-pager",
                            "--property=Id,LoadState,ActiveState,SubState,MainPID,NRestarts,Result,ExecMainStatus,User,Group,ExecStart,WorkingDirectory,FragmentPath"],
        "boot_history": ["journalctl", "--list-boots", "--no-pager", "-n", "12"],
        "kernel_log": ["journalctl", "-k", "-b", "0", "-n", "160", "-o", "short-iso", "--no-pager"],
        "previous_boot": ["journalctl", "-b", "-1", "-n", "100", "-o", "short-iso", "--no-pager"],
        "boot_errors": ["journalctl", "-b", "-p", "warning", "-n", "120", "-o", "short-iso", "--no-pager"],
        "service_logs": ["journalctl", *sum((["-u", s] for s in services), []), "-n", "200", "-o", "short-iso", "--no-pager"],
        "dmesg": ["dmesg", "--level=err,warn"], "shutdown_history": ["last", "-x", "-n", "20"],
        "network": ["ip", "-details", "address", "show"], "routes": ["ip", "route", "show", "table", "all"],
        "routing_policy": ["ip", "rule", "show"], "neighbors": ["ip", "neigh", "show"],
        "listeners": ["ss", "-lntup"], "wifi_interfaces": ["iw", "dev"], "rfkill": ["rfkill", "list"],
        "network_manager": ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"],
        "processes": ["ps", "-eo", "pid,ppid,user,comm,pcpu,pmem,etimes", "--sort=-pcpu"],
        "identity_groups": ["id"], "dialout_group": ["getent", "group", "dialout"], "tty_group": ["getent", "group", "tty"],
    }
    for interface in ("wlan0", "wlan1"):
        checks[interface + "_device"] = read_text("/sys/class/net/" + interface + "/device/uevent")
        commands[interface + "_driver"] = ["ethtool", "-i", interface]
        for suffix, args in (("info", ["info"]), ("link", ["link"]), ("stations", ["station", "dump"])):
            commands[interface + "_" + suffix] = ["iw", "dev", interface, *args]
    serial = serial_metadata()
    checks["serial_devices"] = {"status": "ok", "devices": serial, "note": "Metadata only; no tty opened."}
    ttys = [d["path"] for d in serial if d.get("mode", "").startswith("c")]
    if ttys:
        commands["serial_owners"] = ["fuser", "-v", *ttys]
    for name, argv in commands.items():
        checks[name] = run(argv)
    metrics["power_throttling"] = decode_throttled(checks["power_throttling"].get("output", ""))
    for path in ("/boot/config.txt", "/boot/firmware/config.txt", "/etc/hostapd/hostapd.conf", "/etc/dnsmasq.conf", "/etc/dhcpcd.conf"):
        item = read_text(path)
        if item["status"] == "ok":
            allowed = r"^\s*(?:\[|enable_uart=|dtoverlay=|dtparam=|core_freq=|interface[= ]|ssid=|driver=|country_code=|channel=|hw_mode=|dhcp-range=|dhcp-option=|static ip_address=|nohook |bind-interfaces|address=)"
            item["output"] = "\n".join(line for line in item["output"].splitlines() if re.match(allowed, line))
            item["filter"] = "allowlist; passwords and unrelated configuration omitted"
        checks[path] = item
    interpreter = interpreter or sys.executable
    checks["python_packages"] = run([interpreter, "-I", "-B", "-c",
        "import importlib.metadata as m,json,sys; print(json.dumps({'python':sys.version,'executable':sys.executable,'packages':sorted(({'name':d.metadata.get('Name','?'),'version':d.version} for d in m.distributions()),key=lambda d:d['name'].lower())}))"], timeout=5)
    checks["python_packages"]["scope"] = "Explicit --python interpreter, or collector interpreter; confirm it matches ExecStart."
    report["application"] = {"status": "not_collected", "files": {}}
    if app_root:
        root = Path(app_root).resolve()
        report["application"] = {"status": "observed", "root": str(root), "files": {},
                                 "git_commit": run(["git", "-C", str(root), "rev-parse", "HEAD"]),
                                 "git_status": run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"])}
        for name in APP_FILES:
            path = root / name
            try:
                if path.is_file() and not path.is_symlink() and path.stat().st_size <= 2 * 1024 * 1024:
                    report["application"]["files"][name] = {"sha256": sha256_file(path)}
                else:
                    report["application"]["files"][name] = {"status": "unavailable"}
            except OSError as exc:
                report["application"]["files"][name] = {"status": "error", "error": str(exc)}
    report["limitations"] = [
        "Command status ok means collected, never hardware approved. No stress, fsck, serial transactions or network scans.",
        "SD activity is an observation, not a benchmark or card integrity certification. Historical logs may be missing or truncated.",
        "No successful encoder read frequency, RTU latency/CRC, installed Ladder identity or stop-limit validation without additional evidence.",
        "Wi-Fi stations/driver logs and ARP neighbors are snapshots; they do not exclude intermittent faults or duplicate IPs.",
        "Review logs before sharing: redaction is best effort. No credentials files are copied."
    ]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New JSON file, preferably /tmp or a maintenance USB drive")
    parser.add_argument("--app-root", help="Directory actually used by ExecStart (not assumed from repository)")
    parser.add_argument("--python", dest="interpreter", help="Python interpreter actually used by ExecStart")
    parser.add_argument("--service", action="append", default=[], help="Additional systemd unit to inspect")
    args = parser.parse_args()
    if any(not re.fullmatch(r"[A-Za-z0-9_.@:-]+\.service", s) for s in args.service):
        parser.error("Invalid service name")
    if Path(args.output).exists():
        parser.error("Output already exists; use a new filename")
    try:
        report = collect(args.app_root, args.interpreter, tuple(dict.fromkeys((*SERVICES, *args.service))))
        write_json_new(args.output, report)
    except (OSError, RuntimeError) as exc:
        parser.exit(1, str(exc) + "\n")
    print("Snapshot saved: " + args.output)
    print("Machine approval: NOT PERFORMED")


if __name__ == "__main__":
    main()
