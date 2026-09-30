# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Monotonic call claims in a controller-owned directory, shared across workers.

Counter reservations precede diagnostic claim writes. Crashes and missing claim
files never refund calls. This is a call limit, not a provider spending cap.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, UTC
import json
import os
from pathlib import Path
from legacy_naming import schema_matches
import safe_io

DEFAULT_MAX_CALLS = 100


def positive_limit(value: int) -> int:
    if type(value) is not int or value < 1:
        raise ValueError('max_calls muss eine positive Ganzzahl sein.')
    return value


class BudgetExhausted(RuntimeError):
    def __init__(self, budget: 'CallBudget', task_id: str, phase: str):
        self.details = {**budget.snapshot(), 'blocked_task_id': task_id, 'blocked_phase': phase}
        super().__init__(f'Gemeinsames Aufrufbudget für {budget.root_id} erschöpft '
                         f'({budget.limit}/{budget.limit}); nächster Aufruf: {task_id}/{phase}.')


class CallBudget:
    def __init__(self, directory: Path, limit: int, root_id: str):
        self.directory = safe_io.lexical_path(directory)
        self.limit = positive_limit(limit)
        if not isinstance(root_id, str) or not root_id.strip():
            raise ValueError('Budget root_id must be nonempty text')
        self.root_id = root_id
        safe_io.mkdir(self.directory)
        with self._lock():
            path = self.directory / 'budget.json'
            contract = {'schema_version': 'arquilo.call_budget.v1', 'root_id': root_id, 'limit': limit}
            try:
                saved = json.loads(safe_io.read_text(path))
            except FileNotFoundError:
                safe_io.write_text(path, json.dumps(contract) + '\n', exclusive=True)
            else:
                if isinstance(saved, dict) and schema_matches(saved.get('schema_version'), contract['schema_version']):
                    saved = saved | {'schema_version': contract['schema_version']}
                if saved != contract:
                    raise ValueError('Shared call budget cannot change its root or limit')
            # Migration from numbered-claim budgets retains every reservation,
            # including partial/failed claim writes. Never renumber old evidence.
            try:
                self._used()
            except FileNotFoundError:
                used = max((n for n in range(1, self.limit + 1)
                            if (self.directory / f'call_{n:06d}.json').exists()), default=0)
                self._save_used(used)

    @contextmanager
    def _lock(self):
        with safe_io.open_file(self.directory / 'budget.lock', 'a+b', shared=True) as stream:
            if os.name == 'nt':
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == 'nt':
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)

    def _used(self):
        value = json.loads(safe_io.read_text(self.directory / 'reservations.json'))
        if type(value) is not int or not 0 <= value <= self.limit:
            raise ValueError('Invalid call reservation counter; refusing to reset it')
        return value

    def _save_used(self, used):
        safe_io.atomic_write(self.directory / 'reservations.json', (str(used) + '\n').encode())

    def consume(self, task_id: str, phase: str) -> dict:
        with self._lock():
            used = self._used()
            if used < self.limit:
                number = used + 1
                self._save_used(number)  # Commit authority before creating diagnostic evidence.
                record = {'schema_version': 'arquilo.call_claim.v1', 'number': number,
                          'root_id': self.root_id, 'task_id': task_id, 'phase': phase,
                          'limit': self.limit, 'claimed_at': datetime.now(UTC).isoformat()}
                safe_io.write_text(self.directory / f'call_{number:06d}.json',
                                   json.dumps(record, ensure_ascii=False, indent=2) + '\n', exclusive=True)
                return record
        raise BudgetExhausted(self, task_id, phase)

    def snapshot(self) -> dict:
        with self._lock():
            used = self._used()
        return {'schema_version': 'arquilo.call_budget.v1', 'root_id': self.root_id,
                'directory': str(self.directory), 'limit': self.limit,
                'used': used, 'remaining': self.limit - used}
