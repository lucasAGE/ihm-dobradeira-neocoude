#!/usr/bin/env python3
"""Compare installed files with an audited release, without importing the app.

Reads regular source files only. Never stops services, opens serial, installs,
changes permissions or updates the application. A match is a source comparison,
not hardware, dependency-version, safety or deployment approval.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import stat

try:
    from .common import envelope, write_json_new
except ImportError:
    from common import envelope, write_json_new

UPDATE_FILES = ('main_server.py', 'state_manager.py', 'static/index.html')
CONTEXT_FILES = ('modbus_client.py', 'modbus_map.py', 'bend_logger.py',
                 'wifi_manager.py', 'requirements.txt')
MAX_FILE_BYTES = 2 * 1024 * 1024


def fingerprints(data):
    return {'sha256': hashlib.sha256(data).hexdigest(),
            'lf_sha256': hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()}


def load_manifest(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 65536:
        raise ValueError('Release manifest must be a regular file of at most 64 KiB')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or manifest.get('schema_version') != 1 or not isinstance(manifest.get('files'), dict):
        raise ValueError('Unknown release manifest format')
    if set(manifest['files']) != set(UPDATE_FILES + CONTEXT_FILES):
        raise ValueError('Manifest must list exactly the three updates and five context files')
    for name, item in manifest['files'].items():
        if not isinstance(item, dict):
            raise ValueError('Invalid file entry')
        for version in ('base', 'candidate'):
            if not isinstance(item.get(version), dict):
                raise ValueError('Missing version hashes: ' + name)
            for key in ('sha256', 'lf_sha256'):
                if not isinstance(item[version].get(key), str) or not re.fullmatch(r'[0-9a-f]{64}', item[version][key]):
                    raise ValueError('Invalid hash: ' + name)
        if name in CONTEXT_FILES and item['base']['lf_sha256'] != item['candidate']['lf_sha256']:
            raise ValueError('This update cannot change context files: ' + name)
    return manifest


def inspect_file(root, name, expected):
    path = root
    try:
        for component in Path(name).parts:
            path = path / component
            if path.is_symlink():
                return {'status': 'symlink_requires_review', 'versions': []}
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
            return {'status': 'not_regular_or_too_large', 'versions': []}
        with path.open('rb') as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            return {'status': 'too_large', 'versions': []}
        actual = fingerprints(data)
        matches = {}
        for version in ('base', 'candidate'):
            if actual['sha256'] == expected[version]['sha256']:
                matches[version] = 'exact_bytes'
            elif actual['lf_sha256'] == expected[version]['lf_sha256']:
                matches[version] = 'crlf_lf_only'
        return {'status': 'matched' if matches else 'different', 'versions': list(matches),
                'matches': matches, **actual, 'bytes': len(data), 'mode': oct(stat.S_IMODE(info.st_mode)),
                'uid': info.st_uid, 'gid': info.st_gid}
    except FileNotFoundError:
        return {'status': 'missing', 'versions': []}
    except OSError as exc:
        return {'status': 'unreadable', 'error_type': type(exc).__name__, 'versions': []}


def check_release(root, manifest, expect='either'):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Installed root must be an existing directory')
    report = envelope('release_check')
    report.update(installed_root=str(root), release=manifest.get('release'),
                  base_commit=manifest.get('base_commit'), expected=expect)
    files = report['files'] = {name: inspect_file(root, name, item) for name, item in manifest['files'].items()}
    if any(item['status'] != 'matched' for item in files.values()):
        result = 'different_or_unavailable'
    elif all('base' in files[name]['versions'] for name in UPDATE_FILES):
        result = 'audited_base'
    elif all('candidate' in files[name]['versions'] for name in UPDATE_FILES):
        result = 'candidate'
    else:
        result = 'mixed_versions'
    report['source_state'] = result
    report['matches_expected'] = result in ({'audited_base', 'candidate'} if expect == 'either' else
                                         {'audited_base'} if expect == 'base' else {'candidate'})
    report['deployment_performed'] = False
    report['limitations'] = [
        'Source-file comparison only; no import, serial access or service operation.',
        'Only CRLF to LF normalization is allowed; no whitespace, encoding or code changes are ignored.',
        'Interpreter, installed packages, service, hardware and resident Ladder require separate checks.',
        'A matching source tree does not prove that the running process loaded these files.']
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installed-root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, default=Path(__file__).parent / 'releases' / 'feedback-0.3.0.json')
    parser.add_argument('--expect', choices=('base', 'candidate', 'either'), default='either')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        report = check_release(args.installed_root, load_manifest(args.manifest), args.expect)
        if args.output:
            write_json_new(args.output, report)
        print(json.dumps(report, indent=2, ensure_ascii=True))
        return 0 if report['matches_expected'] else 2
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
