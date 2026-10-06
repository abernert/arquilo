# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Measure narrow result retrieval separately from full-history compatibility."""
from __future__ import annotations
import json
from pathlib import Path
import urllib.error


def read_structured_result(client, session, message, logs: Path):
    """Use documented result endpoints, recording a specific upstream history defect.

    This is not a retry of the model request. Every request here is a GET.
    Unexpected errors are still failures; no stale or uncorrelated result is accepted.
    """
    expected = message['info']
    message_id = expected['id']
    single = client.call(f'/session/{session}/message/{message_id}')
    info = single.get('info', {})
    if (info.get('id') != message_id or info.get('sessionID') != session
            or info.get('parentID') != expected.get('parentID')
            or info.get('error') or info.get('structured') != expected.get('structured')):
        raise AssertionError('Targeted structured result does not match the completed response')
    recent = client.call(f'/session/{session}/message?limit=1')
    if (not isinstance(recent, list) or len(recent) != 1
            or recent[0].get('info') != info):
        raise AssertionError('Latest-message result does not match the targeted structured response')
    (logs / 'structured-targeted-read.json').write_text(json.dumps(single, indent=2)+'\n', encoding='utf-8')
    (logs / 'structured-latest-read.json').write_text(json.dumps(recent, indent=2)+'\n', encoding='utf-8')
    limitation = None
    try:
        history = client.call(f'/session/{session}/message')
        if not any(m.get('info', {}).get('id') == message_id for m in history):
            raise AssertionError('Structured result missing from full history')
        observation = {'status': 'PASS', 'detail': 'Full structured history is readable'}
    except urllib.error.HTTPError as exc:
        # Measured in upstream 1.18.34: response encoding fails on the user's
        # persisted Format class, even though the structured assistant is valid.
        if exc.code != 400 or 'OutputFormatJsonSchema' not in str(exc):
            raise
        limitation = {'code': 'structured_history_http_400', 'session': session,
                      'message': message_id, 'error': str(exc),
                      'workaround': 'targeted assistant GET or latest-message GET; both verified'}
        observation = {'status': 'KNOWN_UPSTREAM_FAILURE', **limitation}
    (logs / 'structured-history-observation.json').write_text(
        json.dumps(observation, indent=2)+'\n', encoding='utf-8')
    return [single], limitation
