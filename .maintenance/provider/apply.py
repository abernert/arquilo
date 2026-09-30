from pathlib import Path
import hashlib
import os
import subprocess
import sys

BASE = '45efd35fabea5aea00a20b373cf70339d5747c0c'
EXPECTED_PATCH = '71d63b7cca5a82eaf4c35fc2c1dc95e13aab183ab8ca02568cf9538aabf0fa95'
EXPECTED_TREE = '894afd6bc918ae4fe6b0c66a9884711ef587a713'
parts = sorted(Path('.maintenance/provider').glob('part*.txt'))
assert len(parts) == 6, 'Incomplete change set'
data = b''.join(p.read_bytes().replace(b'\r\n', b'\n') for p in parts)
assert hashlib.sha256(data).hexdigest() == EXPECTED_PATCH, 'Patch content changed'
subprocess.run(['git', 'checkout', '--detach', BASE], check=True)
subprocess.run(['git', 'apply', '--unidiff-zero', '--index', '--whitespace=error', '-'], input=data, check=True)
tree = subprocess.check_output(['git','write-tree'], text=True).strip()
assert tree == EXPECTED_TREE, 'Result differs from locally tested source'
print('Verified exact provider configuration candidate:', tree)
if '--publish-candidate' in sys.argv:
    live = subprocess.check_output(['gh','api','repos/abernert/arquilo/git/ref/heads/main','--jq','.object.sha'], text=True).strip()
    assert live == BASE, 'main changed; rebase and retest'
    env = dict(os.environ, GIT_AUTHOR_NAME='github-actions[bot]', GIT_COMMITTER_NAME='github-actions[bot]',
               GIT_AUTHOR_EMAIL='41898282+github-actions[bot]@users.noreply.github.com',
               GIT_COMMITTER_EMAIL='41898282+github-actions[bot]@users.noreply.github.com')
    sha = subprocess.check_output(['git','commit-tree',tree,'-p',BASE,'-m',
        'Use configured Codex model/provider for Decide without routing overrides (0.3.2)'],env=env,text=True).strip()
    subprocess.run(['gh','api','--method','POST','repos/abernert/arquilo/git/refs',
        '-f','ref=refs/heads/fix/decide-provider-config-032','-f','sha='+sha],check=True)
    print('Clean candidate SHA:', sha)
