# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""CI-only, opt-in download of an upstream Codex test binary to a NEW directory.

No local installation/update, PATH mutation, authentication or model execution.
Verify the archive against the digest returned by the official release API.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import tarfile
import urllib.request
import zipfile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version', choices=('0.154.0', '0.159.1'))
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    system, machine = platform.system(), platform.machine().lower()
    triples = {('Linux', 'x86_64'): 'x86_64-unknown-linux-musl',
               ('Darwin', 'arm64'): 'aarch64-apple-darwin',
               ('Darwin', 'x86_64'): 'x86_64-apple-darwin',
               ('Windows', 'amd64'): 'x86_64-pc-windows-msvc'}
    triple = triples[(system, machine)]
    suffix = '.zip' if system == 'Windows' else '.tar.gz'
    filename = 'codex-' + triple + ('.exe' if system == 'Windows' else '') + suffix
    url = 'https://api.github.com/repos/openai/codex/releases/tags/rust-v' + args.version
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'arquilo-compatibility-ci'}
    if os.environ.get('GH_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        release = json.load(response)
    assets = [row for row in release['assets'] if row['name'] == filename]
    if len(assets) != 1:
        raise RuntimeError('Exact upstream test asset unavailable')
    asset = assets[0]
    if not re.fullmatch('sha256:[a-f0-9]{64}', asset.get('digest') or ''):
        raise RuntimeError('Upstream asset digest unavailable')
    expected_url = 'https://github.com/openai/codex/releases/download/rust-v' + args.version + '/' + filename
    if asset['browser_download_url'] != expected_url:
        raise RuntimeError('Unexpected upstream asset URL')
    # Do not forward an API token to storage redirects.
    with urllib.request.urlopen(expected_url, timeout=180) as response:
        data = response.read(256 * 1024 * 1024 + 1)
    if len(data) > 256 * 1024 * 1024 or 'sha256:' + hashlib.sha256(data).hexdigest() != asset['digest']:
        raise RuntimeError('Upstream test archive digest/size mismatch')
    names = {'codex', 'codex.exe', 'codex-' + triple, 'codex-' + triple + '.exe'}
    if suffix == '.zip':
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = [m for m in archive.infolist() if not m.is_dir() and Path(m.filename).name in names]
            if len(entries) != 1: raise RuntimeError('Ambiguous upstream binary')
            binary = archive.read(entries[0])
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            entries = [m for m in archive.getmembers() if m.isfile() and Path(m.name).name in names]
            if len(entries) != 1: raise RuntimeError('Ambiguous upstream binary')
            with archive.extractfile(entries[0]) as stream:
                binary = stream.read()
    # No extractall: archive paths never control where files are written.
    args.destination.mkdir(parents=True, exist_ok=False)
    target = args.destination / ('codex.exe' if system == 'Windows' else 'codex')
    target.write_bytes(binary); target.chmod(0o755)
    print(json.dumps({'version': args.version, 'asset': filename, 'digest': asset['digest']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
