#!/usr/bin/env python3
"""Exercise the documented copy/rollback function on temporary Linux files.

systemctl and sudo are shell doubles. No service, SSH, application import or
serial access. Run in WSL/Linux from the repository root, never against a device.
"""
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from diagnostics import artifacts
from diagnostics.check_release import (UPDATE_FILES, CONTEXT_FILES, check_release,
                                       load_manifest)


def main():
    if os.name != 'posix' or not shutil.which('bash') or not shutil.which('install'):
        raise SystemExit('Run this isolated procedure check in Linux/WSL with bash and install')
    guide = (ROOT / 'docs/diagnostico/ATUALIZACAO_EM_CAMPO.md').read_text(encoding='utf-8')
    blocks = re.findall(r'```bash\n(.*?)\n```', guide, re.S)
    for block in blocks:
        subprocess.run(['bash', '-n'], input=block, text=True, check=True)
    function = next(block for block in blocks if block.startswith('neo_copy_three()'))
    manifest = load_manifest(ROOT / 'diagnostics/releases/feedback-0.3.0.json')
    with tempfile.TemporaryDirectory(prefix='neocoude-field-test-') as temporary:
        folder = Path(temporary)
        installed, candidate, case = (folder / name for name in ('installed', 'candidate', 'case'))
        case.mkdir()
        for name in UPDATE_FILES + CONTEXT_FILES:
            for base in (installed, candidate):
                (base / name).parent.mkdir(parents=True, exist_ok=True)
            (installed / name).write_bytes(subprocess.check_output(
                ['git', '-C', str(ROOT), 'show', manifest['base_commit'] + ':ihm_esp32/' + name]))
            (candidate / name).write_bytes((ROOT / 'ihm_esp32' / name).read_bytes())
            (installed / name).chmod(0o640)
        baseline = check_release(installed, manifest, 'base')
        assert baseline['matches_expected'], baseline
        (case / 'versao-parada.json').write_text(json.dumps(baseline), encoding='utf-8')
        originals = {name: (installed / name).read_bytes() for name in UPDATE_FILES}
        backup = case / 'backup-aplicacao.zip'
        artifacts.backup(installed, list(UPDATE_FILES + CONTEXT_FILES), backup, 'isolated-procedure-test')
        restored = case / 'rollback-conferido'
        artifacts.restore_staging(backup, restored)
        assert check_release(restored, manifest, 'base')['matches_expected']
        # A deliberate lower-permission staging restore is repaired from the
        # recorded source metadata, not from the staging file's 0600 mode.
        assert stat.S_IMODE((restored / 'state_manager.py').stat().st_mode) == 0o600
        environment = dict(os.environ, NEO_SERVICE='fixture.service', NEO_APP=str(installed),
                           NEO_CASE=str(case), NEO_PY=sys.executable,
                           FIELD_TEST_SOURCE=str(candidate), FIELD_TEST_ACTIVE='inactive')
        doubles = '''
systemctl() {
  test "$1" = show && test "$2" = fixture.service || return 90
  case "$4" in
    ActiveState) printf '%s\n' "$FIELD_TEST_ACTIVE" ;;
    MainPID) printf '0\n' ;;
    *) return 91 ;;
  esac
}
sudo() {
  test "$1" = install || return 92
  "$@"
}
'''
        program = doubles + function + '\nneo_copy_three "$FIELD_TEST_SOURCE"\n'
        active = dict(environment, FIELD_TEST_ACTIVE='active')
        denied = subprocess.run(['bash'], input=program, text=True, env=active, capture_output=True)
        assert denied.returncode != 0, 'Must refuse a running service'
        assert all((installed / name).read_bytes() == data for name, data in originals.items())
        subprocess.run(['bash'], input=program, text=True, env=environment, check=True)
        assert check_release(installed, manifest, 'candidate')['matches_expected']
        assert all(stat.S_IMODE((installed / name).stat().st_mode) == 0o640 for name in UPDATE_FILES)
        # Simulate an interrupted/rejected update and recover from the actual backup.
        (installed / 'state_manager.py').unlink()
        (installed / 'main_server.py').chmod(0o600)
        assert not check_release(installed, manifest)['matches_expected']
        environment['FIELD_TEST_SOURCE'] = str(restored)
        subprocess.run(['bash'], input=program, text=True, env=environment, check=True)
        assert check_release(installed, manifest, 'base')['matches_expected']
        assert all((installed / name).read_bytes() == data for name, data in originals.items())
        assert all(stat.S_IMODE((installed / name).stat().st_mode) == 0o640 for name in UPDATE_FILES)
        assert all((installed / name).stat().st_uid == baseline['files'][name]['uid'] and
                   (installed / name).stat().st_gid == baseline['files'][name]['gid'] for name in UPDATE_FILES)
    print(f'Passed: {len(blocks)} Bash blocks parsed; running-service refusal, backup, three-file update, interrupted update and rollback of bytes/owner/group/mode in temporary files only.')


if __name__ == '__main__':
    main()
