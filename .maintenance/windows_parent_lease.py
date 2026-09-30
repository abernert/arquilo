# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Additional exact correction found by the native Windows race regression."""
from pathlib import Path
import hashlib
import subprocess
p = Path('safe_io.py')
text = p.read_text(encoding='utf-8')
old = '    handle = create(str(path), 0, 1 | 2, None, 3, 0x02000000 | 0x00200000, None)'
new = '    # Query-only handles do not hold delete sharing; request FILE_LIST_DIRECTORY.\n    handle = create(str(path), 0x0001, 1 | 2, None, 3, 0x02000000 | 0x00200000, None)'
assert text.count(old) == 1, 'Unexpected directory-open implementation'
p.write_bytes(text.replace(old, new).encode('utf-8'))
assert hashlib.sha256(p.read_bytes()).hexdigest() == '60a4d04f04d201b3db77d86fd29ca531169595bd1947cd6a8f73851a0e3002b6'
subprocess.run(['git', 'add', '--', 'safe_io.py'], check=True)
