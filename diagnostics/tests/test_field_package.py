import json
from pathlib import Path
import tempfile
import unittest

from diagnostics import artifacts
from diagnostics.build_field_package import build, ARCHIVE_NAME, CHECKSUM_NAME
from diagnostics.check_release import UPDATE_FILES, CONTEXT_FILES, fingerprints


class FieldPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'diagnostics/releases').mkdir(parents=True)
        (self.root / 'docs/diagnostico').mkdir(parents=True)
        (self.root / 'docs/diagnostico/guide.md').write_text('Fixture guide')
        for name in ('artifacts.py', 'common.py', 'collect_linux.py'):
            (self.root / 'diagnostics' / name).write_text('# fixture ' + name)
        manifest = {'schema_version': 1, 'release': 'fixture', 'files': {}}
        for name in UPDATE_FILES + CONTEXT_FILES:
            path = self.root / 'ihm_esp32' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            data = ('fixture ' + name).encode()
            path.write_bytes(data)
            base = fingerprints(b'previous ' + data) if name in UPDATE_FILES else fingerprints(data)
            manifest['files'][name] = {'base': base, 'candidate': fingerprints(data)}
        (self.root / 'diagnostics/releases/feedback-0.3.0.json').write_text(json.dumps(manifest))

    def test_fresh_bundles_exclude_private_evidence_and_match_bootstrap_hashes(self):
        evidence = self.root / 'diagnostics/output/private-device-report.json'
        evidence.parent.mkdir()
        evidence.write_text('private local evidence')
        first, second = build(self.root), build(self.root)
        self.assertNotEqual(first['directory'], second['directory'])
        for result in (first, second):
            output = Path(result['directory'])
            manifest = artifacts.verify_backup(output / ARCHIVE_NAME)
            self.assertFalse(any('output/' in name for name in manifest['files']))
            self.assertEqual(len((output / CHECKSUM_NAME).read_text().splitlines()), 4)
            for line in (output / CHECKSUM_NAME).read_text().splitlines():
                expected, name = line.split('  ', 1)
                self.assertEqual(artifacts.sha256_file(output / name), expected)
            self.assertFalse(result['deployed'])
        self.assertEqual(evidence.read_text(), 'private local evidence')

    def test_changed_application_is_rejected_before_creating_output(self):
        (self.root / 'ihm_esp32/state_manager.py').write_text('unexpected version')
        with self.assertRaises(ValueError):
            build(self.root)
        self.assertFalse((self.root / 'diagnostics/output').exists())
