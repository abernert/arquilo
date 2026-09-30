from pathlib import Path
import hashlib
import json
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
    prefix = 'repos/abernert/arquilo/'
    def api(endpoint, payload=None):
        command = ['gh','api',prefix+endpoint]
        if payload is not None:
            command += ['--method','POST','--input','-']
        result = subprocess.run(command, input=None if payload is None else json.dumps(payload),
                                text=True, stdout=subprocess.PIPE, check=True)
        return json.loads(result.stdout)
    assert api('git/ref/heads/main')['object']['sha'] == BASE, 'main changed; rebase and retest'
    paths = subprocess.check_output(['git','diff','--cached','--name-only','-z'], text=True).split('\0')
    entries = [{'path':p, 'mode':'100644', 'type':'blob', 'content':Path(p).read_text(encoding='utf-8')}
               for p in paths if p]
    base_tree = subprocess.check_output(['git','rev-parse',BASE+'^{tree}'], text=True).strip()
    uploaded = api('git/trees', {'base_tree':base_tree, 'tree':entries})
    assert uploaded['sha'] == EXPECTED_TREE, 'Uploaded tree mismatch'
    commit = api('git/commits', {'tree':uploaded['sha'], 'parents':[BASE],
        'message':'Use configured Codex model/provider for Decide without routing overrides (0.3.2)'})
    api('git/refs', {'ref':'refs/heads/fix/decide-provider-config-032','sha':commit['sha']})
    print('Clean candidate SHA:', commit['sha'])
