import json
from pathlib import Path
import tempfile
import unittest

from diagnostics.check_release import (UPDATE_FILES, CONTEXT_FILES, check_release,
                                       fingerprints, load_manifest)


class ReleaseCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'installation'
        self.root.mkdir()
        self.base, self.candidate = {}, {}
        self.manifest = {'schema_version': 1, 'release': 'fixture', 'base_commit': 'fixture', 'files': {}}
        for name in UPDATE_FILES + CONTEXT_FILES:
            base = ('original ' + name + '\n').encode()
            candidate = ('updated ' + name + '\n').encode() if name in UPDATE_FILES else base
            self.base[name], self.candidate[name] = base, candidate
            self.manifest['files'][name] = {'base': fingerprints(base), 'candidate': fingerprints(candidate)}
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base)

    def test_base_and_candidate_are_distinguished_and_expectation_is_enforced(self):
        self.assertEqual(check_release(self.root, self.manifest)['source_state'], 'audited_base')
        self.assertFalse(check_release(self.root, self.manifest, 'candidate')['matches_expected'])
        for name in UPDATE_FILES:
            (self.root / name).write_bytes(self.candidate[name])
        result = check_release(self.root, self.manifest, 'candidate')
        self.assertTrue(result['matches_expected'])
        self.assertFalse(result['deployment_performed'])

    def test_mixed_update_stops_even_when_each_file_is_known(self):
        (self.root / UPDATE_FILES[0]).write_bytes(self.candidate[UPDATE_FILES[0]])
        result = check_release(self.root, self.manifest)
        self.assertEqual(result['source_state'], 'mixed_versions')
        self.assertFalse(result['matches_expected'])

    def test_changed_dependency_is_not_approved_and_never_imported(self):
        path = self.root / 'modbus_map.py'
        data = b'raise RuntimeError("must never import application")\n'
        path.write_bytes(data)
        before = path.stat().st_mtime_ns
        result = check_release(self.root, self.manifest)
        self.assertFalse(result['matches_expected'])
        self.assertEqual(path.read_bytes(), data)
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_only_line_endings_are_normalized(self):
        for name, data in self.base.items():
            (self.root / name).write_bytes(data.replace(b'\n', b'\r\n'))
        result = check_release(self.root, self.manifest, 'base')
        self.assertTrue(result['matches_expected'])
        self.assertEqual(result['files']['main_server.py']['matches']['base'], 'crlf_lf_only')
        (self.root / 'main_server.py').write_bytes(self.base['main_server.py'] + b' ')
        self.assertFalse(check_release(self.root, self.manifest)['matches_expected'])

    def test_missing_file_and_directory_instead_of_source_are_rejected(self):
        path = self.root / 'state_manager.py'
        path.unlink()
        self.assertEqual(check_release(self.root, self.manifest)['files']['state_manager.py']['status'], 'missing')
        path.mkdir()
        self.assertFalse(check_release(self.root, self.manifest)['matches_expected'])

    def test_symlink_is_not_followed(self):
        path = self.root / 'state_manager.py'
        path.unlink()
        try:
            path.symlink_to(self.root / 'main_server.py')
        except OSError:
            self.skipTest('Creating symlinks is not supported for this user')
        self.assertEqual(check_release(self.root, self.manifest)['files']['state_manager.py']['status'], 'symlink_requires_review')

    def test_manifest_cannot_add_external_paths_or_changed_context(self):
        path = Path(self.temp.name) / 'release.json'
        path.write_text(json.dumps(self.manifest), encoding='utf-8')
        self.assertEqual(load_manifest(path)['release'], 'fixture')
        self.manifest['files']['../outside'] = self.manifest['files'].pop('state_manager.py')
        path.write_text(json.dumps(self.manifest), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_manifest(path)
        self.manifest['files']['state_manager.py'] = self.manifest['files'].pop('../outside')
        self.manifest['files']['modbus_map.py']['candidate'] = fingerprints(b'changed')
        path.write_text(json.dumps(self.manifest), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_manifest(path)

    def test_manifest_allows_context_crlf_without_allowing_code_changes(self):
        path = Path(self.temp.name) / 'release.json'
        name = 'modbus_client.py'
        self.manifest['files'][name]['candidate'] = fingerprints(self.base[name].replace(b'\n', b'\r\n'))
        path.write_text(json.dumps(self.manifest), encoding='utf-8')
        self.assertTrue(check_release(self.root, load_manifest(path))['matches_expected'])
