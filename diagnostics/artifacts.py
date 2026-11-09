#!/usr/bin/env python3
"""Layered inventory and verified backups. Restore only to a NEW staging directory.

No service restart, deployment, SD imaging or restore onto the machine is provided.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import zipfile

try:
    from .common import envelope, run, sha256_file, write_json_new
    from .collect_linux import APP_FILES
except ImportError:
    from common import envelope, run, sha256_file, write_json_new
    from collect_linux import APP_FILES

MAX_BYTES = 200 * 1024 * 1024
MAX_FILES = 5000
EXCLUDED = {".git", "venv", ".venv", "__pycache__", "node_modules", "output"}


def inventory(root, snapshot=None, ladder=None, image=None, label="unversioned"):
    root = Path(root).resolve()
    data = envelope("layer_manifest")
    data.update(label=label, root=str(root), git_commit=run(["git", "-C", str(root), "rev-parse", "HEAD"]),
                git_status=run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=normal"]))
    observed = {}
    if snapshot:
        if Path(snapshot).stat().st_size > 10 * 1024 * 1024:
            raise ValueError("Snapshot too large")
        observed = json.loads(Path(snapshot).read_text(encoding="utf-8-sig"))
        if observed.get("kind") != "linux_snapshot":
            raise ValueError("Expected a linux_snapshot")
        data["snapshot_sha256"] = sha256_file(snapshot)
    files = {name: {"sha256": sha256_file(root / name)} for name in APP_FILES if (root / name).is_file()}
    checks = observed.get("checks", {})
    layers = data["layers"] = {
        "1_os_firmware": {"status": "observed" if observed else "not_collected",
                          "os": checks.get("os_release"), "kernel": checks.get("kernel"), "firmware": checks.get("firmware")},
        "2_hardware_network_services": {"status": "observed" if observed else "not_collected",
                                        "model": observed.get("metrics", {}).get("model"),
                                        "services": checks.get("service_details"), "network": checks.get("network")},
        "3_python_environment": {"status": "observed" if observed else "not_collected",
                                 "packages": checks.get("python_packages"), "requirements": files.get("requirements.txt")},
        "4_application": {"status": "repository_observed", "files": files, "installed": observed.get("application")},
        "5_modbus_ladder": {"status": "compatibility_not_validated", "mapping": files.get("modbus_map.py"), "ladder": None},
        "6_sd_image": {"status": "not_supplied", "image": None},
    }
    for path, layer, field in ((ladder, "5_modbus_ladder", "ladder"), (image, "6_sd_image", "image")):
        if path:
            item = Path(path)
            if not item.is_file():
                raise ValueError("Supply a regular artifact file, never a device: " + str(item))
            layers[layer][field] = {"name": item.name, "bytes": item.stat().st_size, "sha256": sha256_file(item)}
            if field == "image":
                layers[layer]["status"] = "existing_image_hashed_not_boot_validated"
    comparison = {}
    for name, value in files.items():
        installed = observed.get("application", {}).get("files", {}).get(name, {}).get("sha256")
        comparison[name] = "not_collected" if not installed else ("identical_bytes" if installed == value["sha256"] else "different_bytes")
    data["repository_vs_installed"] = comparison
    data["limitations"] = ["Hashes compare exact bytes, including line endings. Commit alone does not identify dirty deployments.",
                           "Observed inventory does not prove OS/library/Ladder compatibility. Validate each layer separately."]
    return data


def safe_name(name):
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and all(part not in ("", ".", "..") for part in name.split("/")) and "\\" not in name and ":" not in name


def selected_files(root, includes):
    root = root.resolve()
    files = {}
    for relative in includes:
        if not safe_name(relative):
            raise ValueError("Include must be a relative POSIX path: " + relative)
        path = root / relative
        if path.is_symlink() or not path.exists() or not path.resolve().is_relative_to(root):
            raise ValueError("Missing, external or symbolic include: " + relative)
        candidates = [path]
        if path.is_dir():
            candidates = []
            for base, dirs, names in os.walk(path, followlinks=False):
                dirs[:] = [d for d in dirs if d not in EXCLUDED and not (Path(base) / d).is_symlink()]
                candidates.extend(Path(base) / name for name in names)
        for candidate in candidates:
            if candidate.is_symlink() or not candidate.is_file():
                raise ValueError("Only regular files are accepted: " + str(candidate))
            rel = candidate.relative_to(root).as_posix()
            if any(part in EXCLUDED for part in PurePosixPath(rel).parts):
                continue
            if rel == "MANIFEST.json" or not safe_name(rel):
                raise ValueError("Reserved or invalid path: " + rel)
            files[rel] = candidate
    if not files or len(files) > MAX_FILES or sum(p.stat().st_size for p in files.values()) > MAX_BYTES:
        raise ValueError("Backup must contain 1..5000 files, at most 200 MiB; SD images are not supported")
    return files


def backup(root, includes, output, label):
    files = selected_files(Path(root), includes)
    manifest = envelope("application_backup")
    manifest.update(label=label, source_root=str(Path(root).resolve()),
                    git_commit=run(["git", "-C", str(root), "rev-parse", "HEAD"]),
                    files={})
    # O_EXCL and mode 0600 protect existing artifacts and sensitive config backups.
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as stream, zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        remaining = MAX_BYTES
        for name, path in sorted(files.items()):
            # Hash exactly the bytes archived; refuse races rather than promise a live-consistent backup.
            with path.open("rb") as source:
                data = source.read(remaining + 1)
            if len(data) > remaining:
                raise ValueError("File changed beyond backup limit")
            remaining -= len(data)
            info = zipfile.ZipInfo.from_file(path, arcname=name)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
            manifest["files"][name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                                       "mode": stat.S_IMODE(path.stat().st_mode)}
        archive.writestr("MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    verify_backup(output)
    return {"archive": str(output), "sha256": sha256_file(output), "files": len(files),
            "note": "File backup only. Capture changing application data during an approved maintenance stop."}


def validate_archive(archive):
    infos = archive.infolist()
    names = [info.filename for info in infos]
    if len(infos) > MAX_FILES + 1 or len(set(names)) != len(names) or sum(info.file_size for info in infos) > MAX_BYTES + 2 * 1024 * 1024:
        raise ValueError("Invalid archive size/count/duplicate entries")
    for info in infos:
        if not safe_name(info.filename) or info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError("Unsafe archive path/type")
    if "MANIFEST.json" not in names or archive.getinfo("MANIFEST.json").file_size > 2 * 1024 * 1024:
        raise ValueError("Missing or oversized manifest")
    manifest = json.loads(archive.read("MANIFEST.json"))
    if manifest.get("kind") != "application_backup" or set(manifest.get("files", {})) != set(names) - {"MANIFEST.json"}:
        raise ValueError("Manifest does not match archive contents")
    for name, expected in manifest["files"].items():
        if not isinstance(expected, dict) or not isinstance(expected.get("bytes"), int) or not isinstance(expected.get("sha256"), str) or not isinstance(expected.get("mode", 0o600), int):
            raise ValueError("Invalid file metadata: " + name)
        data = archive.read(name)
        if len(data) != expected["bytes"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
            raise ValueError("Checksum mismatch: " + name)
    return manifest


def verify_backup(path):
    with zipfile.ZipFile(path) as archive:
        return validate_archive(archive)


def restore_staging(path, destination):
    destination = Path(destination)
    if destination.exists():
        raise ValueError("Staging destination must not exist; installed files are never overwritten")
    with zipfile.ZipFile(path) as archive:
        manifest = validate_archive(archive)  # validate everything before creating destination
        destination.mkdir(parents=True, exist_ok=False, mode=0o700)
        for name in archive.namelist():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(archive.read(name))
            # Never restore setuid/setgid or world-writable modes.
            original = manifest["files"].get(name, {}).get("mode", 0o600)
            os.chmod(target, original & 0o700)
    return {"staging": str(destination), "files": len(manifest["files"]), "deployed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inv = commands.add_parser("inventory")
    inv.add_argument("--root", type=Path, required=True)
    inv.add_argument("--output", type=Path, required=True)
    inv.add_argument("--label", default="unversioned")
    inv.add_argument("--snapshot", type=Path)
    inv.add_argument("--ladder", type=Path)
    inv.add_argument("--image", type=Path, help="Hash an existing image only, on the maintenance computer")
    pack = commands.add_parser("backup")
    pack.add_argument("--root", type=Path, required=True)
    pack.add_argument("--include", action="append", required=True)
    pack.add_argument("--output", type=Path, required=True)
    pack.add_argument("--label", required=True)
    check = commands.add_parser("verify")
    check.add_argument("archive", type=Path)
    restore = commands.add_parser("restore-staging")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "inventory":
            result = inventory(args.root, args.snapshot, args.ladder, args.image, args.label)
            write_json_new(args.output, result)
            print("Manifest saved: " + str(args.output))
        elif args.command == "backup":
            print(json.dumps(backup(args.root, args.include, args.output, args.label), indent=2))
        elif args.command == "verify":
            manifest = verify_backup(args.archive)
            print(json.dumps({"verified_files": len(manifest["files"]), "sha256": sha256_file(args.archive)}))
        else:
            print(json.dumps(restore_staging(args.archive, args.destination)))
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
