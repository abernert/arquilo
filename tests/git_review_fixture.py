# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""Explicit synthetic review acceptance for low-level local Git tests only.

This fixture is not a model review and is not installed in the runtime package.
Controller integration tests separately exercise the mandatory review gate.
"""
import json
from pathlib import Path

import git_snapshot


def review_snapshot_root(prompt):
    """Read the explicit frozen-output location supplied to the fake reviewer."""
    for line in prompt.splitlines():
        try:
            value = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and {'snapshot_root', 'manifest_sha256',
                                        'paths_relative_to_snapshot_root'} <= value.keys():
            root = Path(value['snapshot_root'])
            if not root.is_absolute():
                raise AssertionError('Review snapshot root must be absolute')
            return root
    raise AssertionError('Reviewer was not given an explicit frozen output binding')


def reviewed_candidate(selection):
    request = selection.begin_review(run='offline-test', task='1', attempt='fixture')
    token, _ = git_snapshot.capture(request, selection.workspace, 1)
    return selection.accept_review(request, token, review_index=1)


def publish(selection, message):
    return selection.commit(message, candidate=reviewed_candidate(selection))
