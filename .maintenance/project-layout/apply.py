from pathlib import Path
import hashlib
import os
import subprocess
import sys

BASE = '8ba3375dd82f2b6c8eda1a40a5de490ec2116281'
PATCH_SHA256 = 'f24d594cf2cd4c7fe0fcdc723c5c9cfda869e2cf49821bde8dd9c96c81d73e46'
TREE = 'b68456caecab6e278aeb31ca39cc1cf3ac5487a5'
BRANCH = 'feat/project-logs-050'
parts = [Path('.maintenance/project-layout') / f'chunk{i}.patch' for i in range(1, 6)]
data = b''.join(p.read_bytes().replace(b'\r\n', b'\n') for p in parts)
followup = Path('.maintenance/project-layout/followup.patch').read_bytes().replace(b'\r\n', b'\n')
assert hashlib.sha256(data).hexdigest() == PATCH_SHA256, 'Patch transfer differs from tested source'
assert hashlib.sha256(followup).hexdigest() == 'c356bde7598d8178957d187576b6c29b47ac4197b56aff6febb54224f4a45550'
subprocess.run(['git', 'checkout', '--detach', BASE], check=True)
for patch_data in (data, followup):
    subprocess.run(['git', 'apply', '--unidiff-zero', '--index', '--whitespace=error', '-'], input=patch_data, check=True)
actual = subprocess.check_output(['git', 'write-tree'], text=True).strip()
assert actual == TREE, 'Applied source tree differs from locally tested tree'
print('Verified exact project-log source:', actual, flush=True)
if '--publish-candidate' in sys.argv:
    subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-v'], check=True)
    subprocess.run([sys.executable, '-B', 'scripts/check_release.py'], check=True)
    live = subprocess.check_output(['gh', 'api', 'repos/abernert/arquilo/git/ref/heads/main', '--jq', '.object.sha'], text=True).strip()
    assert live == BASE, 'main changed; rebase and retest before publishing'
    env = dict(os.environ, GIT_AUTHOR_NAME='github-actions[bot]', GIT_COMMITTER_NAME='github-actions[bot]',
               GIT_AUTHOR_EMAIL='41898282+github-actions[bot]@users.noreply.github.com',
               GIT_COMMITTER_EMAIL='41898282+github-actions[bot]@users.noreply.github.com')
    sha = subprocess.check_output(['git', 'commit-tree', TREE, '-p', BASE, '-m',
        'Add project IDs and readable timestamped run logs (0.5.0)'], env=env, text=True).strip()
    subprocess.run(['git', '-c', 'credential.helper=!gh auth git-credential', 'push', 'origin',
                    sha + ':refs/heads/' + BRANCH], check=True)
    print('Clean candidate branch:', BRANCH, 'commit:', sha, flush=True)
