from pathlib import Path
import json
import subprocess

BASE = '45efd35fabea5aea00a20b373cf70339d5747c0c'
FULL_TREE = '894afd6bc918ae4fe6b0c66a9884711ef587a713'
RUNTIME_TREE = 'a0208a3231b5bf3450cfab8d99f41eb89bc54907'
assert subprocess.check_output(['git','write-tree'], text=True).strip() == FULL_TREE
# GITHUB_TOKEN contents permission does not authorize workflow-file changes.
# Leave that file unchanged here; the owner's workflow-authorized connector
# applies that separately, without changing repository permissions.
subprocess.run(['git','checkout',BASE,'--','.github/workflows/codex-compatibility.yml'],check=True)
assert subprocess.check_output(['git','write-tree'],text=True).strip() == RUNTIME_TREE
prefix = 'repos/abernert/arquilo/'
def api(endpoint, payload=None):
    command = ['gh','api',prefix+endpoint]
    if payload is not None:
        command += ['--method','POST','--input','-']
    result = subprocess.run(command, input=None if payload is None else json.dumps(payload),
                            text=True, stdout=subprocess.PIPE, check=True)
    return json.loads(result.stdout)
assert api('git/ref/heads/main')['object']['sha'] == BASE, 'main changed'
paths = subprocess.check_output(['git','diff','--cached','--name-only','-z'],text=True).split('\0')
assert all(not p.startswith('.github/') for p in paths if p)
entries=[{'path':p,'mode':'100644','type':'blob','content':Path(p).read_bytes().decode('utf-8')}
         for p in paths if p]
base_tree=subprocess.check_output(['git','rev-parse',BASE+'^{tree}'],text=True).strip()
uploaded=api('git/trees',{'base_tree':base_tree,'tree':entries})
assert uploaded['sha']==RUNTIME_TREE
commit=api('git/commits',{'tree':uploaded['sha'],'parents':[BASE],
    'message':'Use configured Codex model/provider for Decide without routing overrides (0.3.2)'})
api('git/refs',{'ref':'refs/heads/fix/decide-provider-config-032','sha':commit['sha']})
print('Clean runtime candidate:',commit['sha'])
