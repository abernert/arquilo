# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Read-only project questions outside the task/review/completion workflow."""
from __future__ import annotations
import argparse, json, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
from autobuild import CodexExecutionError, run_codex_exec_json
from runtime_config import resolve_model, resolve_reasoning_effort

def build_prompt(question: str, depth: str="normal")->str:
    q=question.strip(); rules={"overview":"Prefer top-level documentation and obvious relevant files.","normal":"Start with overview documentation, then inspect only files needed.","deep":"Investigate as deeply as needed while remaining relevant."}
    if not q: raise ValueError("Question must not be empty")
    if depth not in rules: raise ValueError("Invalid depth")
    return f"""You are ARQUILO Ask, a read-only project analyst.
This is not an ARQUILO task. Do not modify files, Git state, task status, controller state, or configuration. Do not run tests, builds, package managers, generators, or project programs. You may inspect files and use read-only search/listing commands. Do not use network access. Distinguish documented facts, code-derived conclusions, and interpretation. Cite project-relative paths and line numbers when practical. Say when project evidence does not establish an answer.
Research depth: {depth}. {rules[depth]}
Question: {q}
Return a concise but sufficient Markdown answer."""

def ask(*,workdir:str|Path,question:str,depth="normal",model=None,reasoning_effort=None,log_root:str|Path|None=None)->dict:
    workspace=Path(workdir).expanduser().resolve()
    if not workspace.is_dir(): raise ValueError(f"Workdir is not a directory: {workspace}")
    model,effort=resolve_model(model),resolve_reasoning_effort(reasoning_effort)
    root=Path(log_root).expanduser().resolve() if log_root else Path(tempfile.gettempdir())/"arquilo-ask"
    archive=root/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ"); archive.mkdir(parents=True,exist_ok=False)
    response=archive/"response.md"
    result=run_codex_exec_json(build_prompt(question,depth),workspace,sandbox="read-only",output_last_message_path=response,raw_log=archive/"events.jsonl",pretty_log=archive/"pretty.log",extra_args=[],model=model,reasoning_effort=effort,network_access=False,phase="ask")
    answer=result.end_answer or (response.read_text(encoding="utf-8").strip() if response.exists() else "")
    if not answer: raise RuntimeError("Ask completed without an answer")
    data={"schema_version":"arquilo.ask.v1","answer":answer,"workspace":str(workspace),"archive":str(archive),"model":model,"reasoning_effort":effort}
    (archive/"ask.json").write_text(json.dumps({**data,"question":question,"depth":depth},indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return data

def main(argv:Sequence[str]|None=None)->int:
    p=argparse.ArgumentParser(description="Ask a read-only question about an ARQUILO workspace."); p.add_argument("question"); p.add_argument("--workdir",default="."); p.add_argument("--depth",choices=("overview","normal","deep"),default="normal"); p.add_argument("--model"); p.add_argument("--reasoning-effort",choices=("none","minimal","low","medium","high","xhigh","max")); p.add_argument("--log-root"); p.add_argument("--json",action="store_true"); a=p.parse_args(argv)
    try:d=ask(workdir=a.workdir,question=a.question,depth=a.depth,model=a.model,reasoning_effort=a.reasoning_effort,log_root=a.log_root)
    except (ValueError,OSError,RuntimeError,CodexExecutionError) as exc: print(f"ARQUILO Ask failed: {exc}",file=__import__("sys").stderr); return 7
    print(json.dumps(d,ensure_ascii=False,indent=2) if a.json else d["answer"]); return 0
if __name__=="__main__": raise SystemExit(main())
