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
import re
import threading
from pathlib import Path
from legacy_naming import schema_matches
import safe_io

DEFAULT_MAX_CALLS = 0
_BUDGET_THREAD_LOCK = threading.RLock()


def positive_limit(value: int) -> int:
    if type(value) is not int or value < 0:
        raise ValueError('max_calls muss eine nichtnegative Ganzzahl sein (0 = unbegrenzt).')
    return value


class BudgetExhausted(RuntimeError):
    def __init__(self, budget: 'CallBudget', task_id: str, phase: str):
        self.details = {**budget.snapshot(), 'blocked_task_id': task_id, 'blocked_phase': phase}
        super().__init__(f'Gemeinsames Aufrufbudget für {budget.root_id} erschöpft '
                         f'({budget.limit}/{budget.limit}); nächster Aufruf: {task_id}/{phase}.')


class CallBudget:
    def __init__(self, directory: Path, limit: int, root_id: str, *,
                 allow_limit_change: bool = False):
        """Workers may attach, but only the owning runner may change a limit.

        Zero is unlimited. Existing counters/claims are never reset when the
        owner changes a limit, including adoption of the unlimited default.
        """
        self.directory = safe_io.lexical_path(directory)
        self.limit = positive_limit(limit)
        if type(allow_limit_change) is not bool:
            raise ValueError('allow_limit_change must be bool')
        if not isinstance(root_id, str) or not root_id.strip():
            raise ValueError('Budget root_id must be nonempty text')
        self.root_id = root_id
        safe_io.mkdir(self.directory)
        with self._lock():
            path = self.directory / 'budget.json'
            contract = {'schema_version': 'arquilo.call_budget.v2', 'root_id': root_id, 'limit': limit}
            try:
                saved = self._contract()
            except FileNotFoundError:
                saved = contract
                safe_io.write_text(path, json.dumps(contract) + '\n', exclusive=True)
            if saved['root_id'] != root_id:
                raise ValueError('Shared call budget cannot change its root')
            previous_limit = saved['limit']
            # Include partial legacy claims. A missing diagnostic never refunds
            # the persistent reservation counter. No range(limit) scan for 0.
            try:
                used = self._used(limit=previous_limit)
            except FileNotFoundError:
                used = max((int(m.group(1)) for p in self.directory.iterdir()
                            if (m := re.fullmatch(r'call_(\d+)\.json', p.name))), default=0)
                if previous_limit and used > previous_limit:
                    raise ValueError('Legacy claims exceed the stored budget; refusing to reset it')
                self._save_used(used)
            if previous_limit != limit:
                if not allow_limit_change:
                    raise ValueError('Shared call budget limit differs; only the owning runner may change it')
                if limit and limit < used:
                    raise ValueError(f'max_calls {limit} is below {used} existing reservations; choose 0 or at least {used}')
                audit = safe_io.unique_directory(self.directory / 'limit_changes', 'change')
                safe_io.write_text(audit / 'change.json', json.dumps({
                    'schema_version': 'arquilo.budget_limit_change.v1',
                    'root_id': root_id, 'previous_limit': previous_limit,
                    'new_limit': limit, 'used': used,
                    'requested_at': datetime.now(UTC).isoformat(),
                }, indent=2) + '\n', exclusive=True)
                # The audit precedes the change. A crash cannot reset the count;
                # a retry may leave another recorded proposal, never a refund.
                safe_io.atomic_write(path, (json.dumps(contract) + '\n').encode())

    def _contract(self):
        saved = json.loads(safe_io.read_text(self.directory / 'budget.json'))
        if (not isinstance(saved, dict) or set(saved) != {'schema_version', 'root_id', 'limit'}
                or not (saved.get('schema_version') == 'arquilo.call_budget.v2'
                    or schema_matches(saved.get('schema_version'), 'arquilo.call_budget.v1'))
                or not isinstance(saved.get('root_id'), str) or not saved['root_id'].strip()):
            raise ValueError('Invalid call budget contract; refusing to reset it')
        positive_limit(saved['limit'])
        if saved['schema_version'] != 'arquilo.call_budget.v2' and saved['limit'] == 0:
            raise ValueError('Legacy budget v1 requires a finite positive limit')
        return saved

    def _check_current_limit(self):
        saved = self._contract()
        if saved['root_id'] != self.root_id or saved['limit'] != self.limit:
            raise ValueError('Call budget changed while this worker was active; restart with the owner-selected limit')

    @contextmanager
    def _lock(self):
        with _BUDGET_THREAD_LOCK, safe_io.open_file(self.directory / 'budget.lock', 'a+b', shared=True) as stream:
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

    def _used(self, *, limit=None):
        limit = self.limit if limit is None else limit
        value = json.loads(safe_io.read_text(self.directory / 'reservations.json'))
        if type(value) is not int or value < 0 or (limit and value > limit):
            raise ValueError('Invalid call reservation counter; refusing to reset it')
        return value

    def _save_used(self, used):
        safe_io.atomic_write(self.directory / 'reservations.json', (str(used) + '\n').encode())

    def consume(self, task_id: str, phase: str) -> dict:
        with self._lock():
            self._check_current_limit()
            used = self._used()
            if self.limit == 0 or used < self.limit:
                number = used + 1
                self._save_used(number)  # Commit authority before creating diagnostic evidence.
                record = {'schema_version': 'arquilo.call_claim.v2', 'number': number,
                          'root_id': self.root_id, 'task_id': task_id, 'phase': phase,
                          'limit': self.limit, 'claimed_at': datetime.now(UTC).isoformat()}
                safe_io.write_text(self.directory / f'call_{number:06d}.json',
                                   json.dumps(record, ensure_ascii=False, indent=2) + '\n', exclusive=True)
                return record
        raise BudgetExhausted(self, task_id, phase)

    def snapshot(self) -> dict:
        with self._lock():
            self._check_current_limit()
            used = self._used()
        return {'schema_version': 'arquilo.call_budget.v2', 'root_id': self.root_id,
                'directory': str(self.directory), 'limit': self.limit,
                'used': used, 'remaining': None if self.limit == 0 else self.limit - used,
                'unlimited': self.limit == 0}
