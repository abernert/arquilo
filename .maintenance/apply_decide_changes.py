"""Temporary validation helper; not included in the final branch or package."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess

ROOT = Path(__file__).resolve().parents[1]
NEW = {
    'docs/decide-configuration.md': 'eb0182f2928b6a0ce45000966a2b8bd0193ed16955c0297fbdd7830682b06dc0',
    'scripts/check_codex_configuration.py': 'c8ddc905a64b8e2d67e1dcdccf632f6e63579348570ebeb59c6f821f1289e8f6',
    'tests/test_decide_configuration.py': 'e62c40d69d4b106f5ddb16553edcfaea49331f78b6729d34bb970ee9b9860ef8',
}


def tracked(path):
    return subprocess.check_output(['git', 'show', 'HEAD:' + path], cwd=ROOT)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked_path(name):
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0] in ('.git', '.maintenance'):
        raise ValueError('Invalid candidate path')
    return ROOT.joinpath(*p.parts)


ops = []
for n in range(1, 4):
    ops.extend(json.loads((ROOT/'.maintenance'/f'decide-edits-{n}.json').read_text(encoding='utf-8')))
assert len(ops) == 24 and len({op['path'] for op in ops}) == 24
prepared = {}
for op in ops:
    name = op['path']; checked_path(name)
    before = tracked(name)
    assert digest(before) == op['sha256_before'], f'Before hash mismatch: {name}'
    if op.get('delete'):
        assert name in ('scripts/check_codex_features.py', 'tests/test_codex_features.py')
        prepared[name] = None
        continue
    lines = before.decode('utf-8').splitlines(keepends=True)
    previous = len(lines) + 1
    for edit in reversed(op['edits']):
        a, b = edit['start'], edit['end']
        assert 0 <= a <= b < previous, f'Invalid/overlapping edit: {name}'
        # JSON may represent the Python NUL-test literal as U+0000. Render it
        # as a Python escape; the full expected file digest must still match.
        replacement = edit['text'].replace('\0', r'\0')
        lines[a:b] = [replacement]
        previous = a + 1
    after = ''.join(lines).encode('utf-8')
    assert digest(after) == op['sha256_after'], f'After hash mismatch: {name}'
    prepared[name] = after
for name, expected in NEW.items():
    checked_path(name)
    data = tracked(name)
    assert digest(data) == expected, f'New-file hash mismatch: {name}'
    prepared[name] = data
# No working-tree writes until ALL source/output hashes have been checked.
for name, data in prepared.items():
    path = checked_path(name)
    if data is None:
        path.unlink()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
(ROOT/'.maintenance'/'candidate-paths.json').write_text(json.dumps(sorted(prepared)), encoding='utf-8')
print(f'Verified and applied {len(prepared)} exact candidate files; no credentials/model calls.')
