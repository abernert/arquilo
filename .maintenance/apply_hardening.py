# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Temporary validation helper; excluded from the proposed runtime commit."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
PATCHES = {'hardening-01.patch': 'f6599e1774d18b831a19fd8bf761df4997fdeb191b2710251094d6dc61985c48', 'hardening-02.patch': '40a21c9f4ee12402086d81211caf607a2356207934737f9c37da8cefb066bd79', 'hardening-03.patch': '103060ea2aa66a067641c1c9e74f531b22644c20d34fe7daa1f2d9bfb70bbc55', 'hardening-04.patch': 'fbe12b2e8626300a891553953ba3380f4f473530b805d36d034bc38cf7aae63e', 'hardening-05.patch': '228c4a39f43a7ff335c3798642b4c9132a83fef27b19ff002616643b806936c6'}
EXPECTED = {'CHANGELOG.md': '375cd65ca7395490dbb501712c0404229db64844fe61ee0f5474cfa1881e3529', 'CITATION.cff': '6465869664cd00814d5b03be114c26ae92b30f3ce5578f468cd07b5286202e32', 'README.de.md': '167210d5b9e8212b03bb5d0b5321cb0a4581db52ace296ca0b294bb821ea924c', 'README.md': '818453c0a799a6fff96912708ae3c335ef9b26900fd86c982cfc68fb3f25d37a', 'RUNTIME_PROFILE_API.md': '77bbbacbe44e91dce5d8c4cfa350b3d7289e06ab9bffde1882aed6bd66492e40', 'SECURITY.md': '687d44507b300394645fd843ddf78527cceb7777f51f2635a8b881837c76766e', 'VERSION': 'd915cc95d6ca8f47ae297713ed46d4e5c5d99ddd29fc3c61e263bdf305f2b5b0', 'arquilo_doctor.py': '47fb5eb6327bcc017f5c0bb08b857f23292f1d57d8154691e044045459b55682', 'autobuild.py': '4988b1fcca8fee515179a22d45cdcb4f2f40d50005ec3a67a08beeda4d79f74c', 'codex_transport.py': 'ae6a8144d97a04aa8d93ea9a23481f8accdf997ebc56181567f11ffcab559527', 'controller_state.py': '13ad4c3612878642121ea7713ab565f5657bf70fed42de8ba7f531b8ce6218df', 'docs/compatibility.md': '488a4980aa4579b057cce5bd675b5adf8b85b824d2222ae2b62241b0475cd99c', 'docs/controller-safety.md': '53957d30674c6b84fb248695feb90b21533ba204e2a6ba9454752d0c31ad2d74', 'docs/quickstart.md': 'e2d5d63f946aab809065bb624e619079995a056fc2e3c055310340b147faf035', 'docs/testing.md': 'aef351e937f588561206b8508af16e735bd93d8a32ae6dbbc2660396c20120b5', 'docs/troubleshooting.md': '305cfb6bfe5f551a5439a26d5b4d07efce964d0ddd6edd59db17b3dd0dcb5cc0', 'documents/CONFIGURATION.md': 'c0f2cf8beb189a949aca1342e6d1bd119108a784ffb977ac7b6c0caf10ab39c8', 'documents/MIGRATION.md': '107f26988fe1d1e5aa0e4b522b02d2824e81a9599504c815ca3e8309474129b5', 'documents/REVIEW_CORE.md': '965f67c54d747d4fd23f4b2ad2be79cf263a7555a29b402b9f79264569919947', 'documents/WORKFLOW_LIMITS.md': '8c8dacbf2cbffdc8541e0366ff5c6157e6f32cf33e610925287829937d9c1f22', 'documents/lean_package.json': '784d94e968bb688e2f30d49880449373f76e973ea984346c2bf8fd337c5d1fb4', 'execution_budget.py': '0f36a31b92bd3e18dbae7afffb0bc9e288bb12e54051a7049d0eaf7cc41f2a38', 'reviewed_git.py': 'a0298d2a0b0525e0f3b9f72a778ab93cd7e3be81120b2f4b55465fef60fc49f3', 'run_todos.py': '4d16ca179b740c5fa4ffcddddaefad046a199ea5aefdee0c88c98b6ab6649c56', 'runtime_files.py': '7f48a97f8f093581f326bdea8f638fe17aba5f8cbab2ef4559e2e0548321a23f', 'runtime_logging.py': '41a5b7dcc92861400878d3292b0826751bc526f123c7863adb719e083e3f48b9', 'runtime_profile.py': '7a71346e396d6281c7c99e4ada045ed9a2c35ba00105879630a827addaaf2fba', 'safe_io.py': '92204f088f4c23dfb1ac6832c6f5513bd2f6536219a6bd5fe4f5cdf3639487e4', 'tests/test_controller_hardening.py': 'de89200e2e3804667a660352dcdee0ed2142887087b41c9d6b6c96ebe1cf28ca'}
for name, digest in PATCHES.items():
    path = '.maintenance/' + name
    data = subprocess.check_output(['git', 'show', 'HEAD:' + path])
    if hashlib.sha256(data).hexdigest() != digest:
        raise SystemExit('Unexpected patch bytes: ' + path)
    with tempfile.TemporaryDirectory() as d:
        patch = Path(d) / name
        patch.write_bytes(data)
        subprocess.run(['git', 'apply', '--index', str(patch)], check=True)
for name, digest in EXPECTED.items():
    if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest:
        raise SystemExit('Unexpected candidate content: ' + name)
subprocess.run(['git', 'diff', '--cached', '--check'], check=True)
print('Verified', len(EXPECTED), 'changed files and', len(PATCHES), 'plaintext patches.')
