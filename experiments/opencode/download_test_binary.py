# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Explicit per-directory download of a pinned upstream test binary, no installation.

Requires HTTPS access to GitHub. Does not edit PATH or bypass OS execution policy.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import tarfile
import urllib.request
import zipfile

VERSION = '1.18.34'


def download(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'ARQUILO-OpenCode-spike'}), timeout=90) as response:
        data = response.read(256 * 1024 * 1024 + 1)
    if len(data) > 256 * 1024 * 1024:
        raise ValueError('Download exceeds the test asset size limit')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--destination', required=True, type=Path, help='New directory, must not exist')
    args = parser.parse_args()
    system = {'Linux': 'linux', 'Darwin': 'darwin', 'Windows': 'windows'}[platform.system()]
    arch = {'x86_64': 'x64', 'amd64': 'x64', 'arm64': 'arm64', 'aarch64': 'arm64'}[platform.machine().lower()]
    extension = 'tar.gz' if system == 'linux' else 'zip'
    name = f'opencode-{system}-{arch}.{extension}'
    url = f'https://api.github.com/repos/anomalyco/opencode/releases/tags/v{VERSION}'
    release = json.loads(download(url))
    if release['tag_name'] != 'v' + VERSION or release['draft'] or release['prerelease']:
        raise ValueError('Unexpected upstream release')
    asset = next(a for a in release['assets'] if a['name'] == name)
    expected_url = f'https://github.com/anomalyco/opencode/releases/download/v{VERSION}/{name}'
    if asset['browser_download_url'] != expected_url:
        raise ValueError('Unexpected upstream asset URL')
    digest = asset.get('digest', '')
    if not digest.startswith('sha256:') or len(digest) != 71:
        raise ValueError('Upstream release does not publish a SHA-256 digest')
    raw = download(expected_url)
    if hashlib.sha256(raw).hexdigest() != digest[7:]:
        raise ValueError('Downloaded asset does not match upstream SHA-256')
    root = args.destination.expanduser().absolute()
    root.mkdir(parents=True, exist_ok=False)
    executable = 'opencode.exe' if system == 'windows' else 'opencode'
    if extension == 'zip':
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            candidates = [p for p in archive.infolist() if not p.is_dir() and Path(p.filename).name == executable]
            if len(candidates) != 1:
                raise ValueError('Expected exactly one native executable')
            content = archive.read(candidates[0])
    else:
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
            candidates = [p for p in archive.getmembers() if p.isfile() and Path(p.name).name == executable]
            if len(candidates) != 1:
                raise ValueError('Expected exactly one native executable')
            content = archive.extractfile(candidates[0]).read()
    target = root / executable
    target.write_bytes(content); target.chmod(0o700)
    receipt = {'version': VERSION, 'release': url, 'asset': name, 'asset_sha256': digest[7:],
               'binary_sha256': hashlib.sha256(content).hexdigest(), 'executable': str(target)}
    (root / 'download.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
