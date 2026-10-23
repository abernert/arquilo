# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""Explicit synthetic review acceptance for low-level local Git tests only.

This fixture is not a model review and is not installed in the runtime package.
Controller integration tests separately exercise the mandatory review gate.
"""
import git_snapshot


def reviewed_candidate(selection):
    request = selection.begin_review(run='offline-test', task='1', attempt='fixture')
    token, _ = git_snapshot.capture(request, selection.workspace, 1)
    return selection.accept_review(request, token, review_index=1)


def publish(selection, message):
    return selection.commit(message, candidate=reviewed_candidate(selection))
