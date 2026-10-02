from pathlib import Path
import base64
import hashlib
import os
import subprocess
import sys
import zlib

BASE = 'b5e4ff92872791a635ee9f5d06a0f8dadeed7361'
TREE = 'ed2ef4752430dea5a07c4a7403f48864446839d6'
PATCH_SHA = '7520d785c345e17052e6c3775711683fd850b8eeb1875fc960fe739ae7e1700b'
BRANCH = 'feat/operator-controls-060'
PART_HASHES = [
    '82e51538b970464dd0a16e97c7b233d52bcbd6dc8b348303cb8b2ab5a8610167',
    'def5a9bcc56c2eb68b9b0ad066cba9188417dc7050e5fa650aa86b09acbc8040',
    '7ead458939663e497f3dab2082bbe8774fb3fb4f3afe681b2f361628bd68f163',
    '680f8ac52422103af452ea157122d29b8d353ffdbb2b11406494addd80230457',
]
parts = []
for i, expected in enumerate(PART_HASHES, 1):
    value = (Path('.maintenance/operator-controls') / f'patch-{i}.b64').read_text(encoding='ascii').strip().encode('ascii')
    actual = hashlib.sha256(value).hexdigest()
    assert actual == expected, f'Part {i} transfer mismatch: length={len(value)}, digest={actual}'
    parts.append(value)
data = zlib.decompress(base64.b64decode(b''.join(parts), validate=True))
assert hashlib.sha256(data).hexdigest() == PATCH_SHA, 'Full patch mismatch'
# This exact public-source patch is transported compressed only to avoid API text limits.
# No preparation files/workflows or private credentials enter the clean candidate tree.
subprocess.run(['git', 'checkout', '--detach', BASE], check=True)
subprocess.run(['git', 'apply', '--unidiff-zero', '--index', '--whitespace=error', '-'], input=data, check=True)
actual = subprocess.check_output(['git', 'write-tree'], text=True).strip()
assert actual == TREE, 'Applied tree differs from locally tested tree'
print('Verified exact operator-controls source tree:', actual, flush=True)
if '--publish-candidate' in sys.argv:
    subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-v'], check=True)
    subprocess.run([sys.executable, '-B', 'scripts/check_release.py'], check=True)
    live = subprocess.check_output(['gh', 'api', 'repos/abernert/arquilo/git/ref/heads/main', '--jq', '.object.sha'], text=True).strip()
    assert live == BASE, 'main changed; rebase and retest'
    env = dict(os.environ, GIT_AUTHOR_NAME='github-actions[bot]', GIT_COMMITTER_NAME='github-actions[bot]',
               GIT_AUTHOR_EMAIL='41898282+github-actions[bot]@users.noreply.github.com',
               GIT_COMMITTER_EMAIL='41898282+github-actions[bot]@users.noreply.github.com')
    sha = subprocess.check_output(['git', 'commit-tree', TREE, '-p', BASE, '-m',
        'Add unlimited default budgets and explicit operator workflow controls (0.6.0)'], env=env, text=True).strip()
    subprocess.run(['git', '-c', 'credential.helper=!gh auth git-credential', 'push', 'origin',
                    sha + ':refs/heads/' + BRANCH], check=True)
    print('Clean candidate:', BRANCH, sha, flush=True)
