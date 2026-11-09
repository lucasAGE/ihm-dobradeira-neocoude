#!/usr/bin/env python3
"""Build the field kit after git pull, without copying local diagnostic evidence.

Creates a fresh output directory on every run. Does not publish, deploy, contact
the Raspberry, replace an existing archive or operate any service.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

try:
    from . import artifacts
    from .check_release import UPDATE_FILES, CONTEXT_FILES, check_release, load_manifest
except ImportError:
    import artifacts
    from check_release import UPDATE_FILES, CONTEXT_FILES, check_release, load_manifest

ARCHIVE_NAME = 'neocoude-campo-feedback-0.3.0-r1.zip'
CHECKSUM_NAME = 'SHA256SUMS-campo-0.3.0-r1.txt'


def build(root, output_parent=None):
    root = Path(root).resolve(strict=True)
    manifest = load_manifest(root / 'diagnostics/releases/feedback-0.3.0.json')
    compared = check_release(root / 'ihm_esp32', manifest, 'candidate')
    if not compared['matches_expected']:
        raise ValueError('Application differs from feedback-0.3.0; review the source before packaging')
    output_parent = Path(output_parent) if output_parent is not None else root / 'diagnostics/output'
    output_parent.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='campo-feedback-0.3.0-r1-', dir=output_parent)).resolve()
    archive = output / ARCHIVE_NAME
    includes = ['diagnostics', 'docs/diagnostico'] + ['ihm_esp32/' + name for name in UPDATE_FILES + CONTEXT_FILES]
    packed = artifacts.backup(root, includes, archive, 'neocoude-campo-feedback-0.3.0-r1')
    # Publish the three bootstrap scripts beside the ZIP so transfer does not
    # depend on files that might subsequently change in the working checkout.
    for name in ('artifacts.py', 'common.py', 'collect_linux.py'):
        with (output / name).open('xb') as stream:
            stream.write((root / 'diagnostics' / name).read_bytes())
    files = [ARCHIVE_NAME, 'artifacts.py', 'common.py', 'collect_linux.py']
    with (output / CHECKSUM_NAME).open('x', encoding='ascii', newline='\n') as stream:
        for name in files:
            stream.write(hashlib.sha256((output / name).read_bytes()).hexdigest() + '  ' + name + '\n')
    result = {'directory': str(output), 'archive': str(archive), 'checksums': str(output / CHECKSUM_NAME),
              'sha256': packed['sha256'], 'files': packed['files'], 'deployed': False}
    with (output / 'package.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.root), indent=2))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
