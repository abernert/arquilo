# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Finite model-call budget shared by a task tree and its Python workers.

Each call claims one exclusive numbered log file before execution. Exclusive
creation works across processes; no scheduler, polling lock or service is needed.
Claims are never refunded, including on provider or logging failures.
"""
from __future__ import annotations

from datetime import datetime, UTC
import json
from pathlib import Path

DEFAULT_MAX_CALLS = 100


def positive_limit(value: int) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("max_calls muss eine positive Ganzzahl sein.")
    return value


class BudgetExhausted(RuntimeError):
    def __init__(self, budget: "CallBudget", task_id: str, phase: str):
        self.details = {**budget.snapshot(), "blocked_task_id": task_id, "blocked_phase": phase}
        super().__init__(f"Gemeinsames Aufrufbudget für {budget.root_id} erschöpft "
                         f"({budget.limit}/{budget.limit}); nächster Aufruf: {task_id}/{phase}.")


class CallBudget:
    def __init__(self, directory: Path, limit: int, root_id: str):
        self.directory = Path(directory).resolve()
        self.limit = positive_limit(limit)
        if not isinstance(root_id, str) or not root_id.strip():
            raise ValueError("Budget root_id must be nonempty text")
        self.root_id = root_id
        self.directory.mkdir(parents=True, exist_ok=True)
        contract = {"schema_version": "dora.call_budget.v1", "root_id": root_id, "limit": limit}
        try:
            stream = (self.directory / "budget.json").open("x", encoding="utf-8")
        except FileExistsError:
            if json.loads((self.directory / "budget.json").read_text(encoding="utf-8")) != contract:
                raise ValueError("Shared call budget cannot change its root or limit")
        else:
            with stream:
                stream.write(json.dumps(contract, ensure_ascii=False, indent=2) + "\n")

    def consume(self, task_id: str, phase: str) -> dict:
        self.directory.mkdir(parents=True, exist_ok=True)
        for number in range(1, self.limit + 1):
            path = self.directory / f"call_{number:06d}.json"
            try:
                stream = path.open("x", encoding="utf-8")
            except FileExistsError:
                continue
            record = {"schema_version": "dora.call_claim.v1", "number": number,
                      "root_id": self.root_id, "task_id": task_id, "phase": phase,
                      "limit": self.limit, "claimed_at": datetime.now(UTC).isoformat()}
            with stream:
                stream.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
            return record
        raise BudgetExhausted(self, task_id, phase)

    def snapshot(self) -> dict:
        # A still-being-written claim also counts. Never parse a concurrent
        # worker's partial log and never reuse a claim after a failed write.
        used = sum((self.directory / f"call_{n:06d}.json").exists()
                   for n in range(1, self.limit + 1))
        return {"schema_version": "dora.call_budget.v1", "root_id": self.root_id,
                "directory": str(self.directory), "limit": self.limit,
                "used": used, "remaining": self.limit - used}
