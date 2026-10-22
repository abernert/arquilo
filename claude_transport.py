# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Native Claude Code print/stream-json adapter. Never launches or probes Codex.

Fresh sessions, trusted user authentication/provider settings, no model default,
no CLI retry/fallback, strict terminal/session/protocol checks, retained raw I/O.
Native tool permissions are not a whole-process OS isolation guarantee.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
from types import MappingProxyType
from typing import Callable, Mapping
from uuid import uuid4

import safe_io
from agent_types import RunResult, TransportResult, TransportTimeouts, FileChange, CommandExec
from agent_process import _collect_process, AgentProcessError, observe_stop
from claude_launcher import resolve_launcher
from process_tree import ProcessTree, finish_cleanup
from project_logs import numbered_directory
from runtime_contracts import ExecutionResult, ExecutionStatus, Failure, FailureKind
from runtime_failure import execution_error
from runtime_files import atomic_write_text, native_path
from agent_backend import resolve_model, resolve_effort, validate_options, validate_resources

REQUIRED_FLAGS = ("--print", "--output-format", "--verbose", "--session-id", "--no-session-persistence",
                  "--permission-mode", "--tools", "--allowedTools", "--disallowedTools",
                  "--strict-mcp-config", "--mcp-config", "--setting-sources", "--settings",
                  "--disable-slash-commands", "--safe-mode")
READ_TOOLS = ("Read", "Glob", "Grep")
WRITE_TOOLS = (*READ_TOOLS, "Edit", "Write", "Bash")


def _strict_json(text):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate JSON key in native Claude event")
            result[key] = value
        return result
    def constant(value):
        raise ValueError("Non-finite JSON value in native Claude event")
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


@dataclass(frozen=True, slots=True, kw_only=True)
class ClaudeRequest:
    prompt: str
    cwd: Path
    env: Mapping[str, str]
    raw_log: Path
    pretty_log: Path
    phase: str = "execution"
    sandbox: str = "workspace-write"
    network_access: bool = False
    decision_only: bool = False
    output_schema: Path | None = None
    output_last_message: Path | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    session_id: str = field(default_factory=lambda: str(uuid4()))
    timeouts: TransportTimeouts = field(default_factory=TransportTimeouts)
    process_stop_path: Path | None = None
    cancel_requested: Callable[[], str | None] | None = None
    verbose: bool = False
    console_todo_id: str | None = None
    log_redactor: Callable[[str], str] | None = None

    def __post_init__(self):
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise ValueError("Claude prompt must be non-empty")
        if self.sandbox not in {"workspace-write", "read-only"}:
            raise ValueError("Claude backend supports workspace-write or read-only only")
        for key in ("network_access", "decision_only", "verbose"):
            if type(getattr(self, key)) is not bool:
                raise ValueError(f"{key} must be bool")
        if self.decision_only and (self.sandbox != "read-only" or self.network_access):
            raise ValueError("Decide requires read-only and no tool network")
        if not isinstance(self.timeouts, TransportTimeouts):
            raise ValueError("Invalid transport timeouts")
        from uuid import UUID
        if str(UUID(self.session_id)) != self.session_id:
            raise ValueError("Claude session must be a canonical UUID")
        env = dict(self.env)
        if any(not isinstance(k, str) or not isinstance(v, str) or not k or "=" in k or "\0" in k+v
               for k,v in env.items()):
            raise ValueError("Invalid trusted process environment")
        if os.name == "nt":
            seen = {}
            for k,v in env.items():
                if k.upper() in seen and seen[k.upper()] != v:
                    raise ValueError("Conflicting Windows environment aliases")
                seen[k.upper()] = v
        object.__setattr__(self, "env", MappingProxyType(env))
        cwd = native_path(self.cwd, label="Claude cwd")
        object.__setattr__(self, "cwd", cwd)
        outputs = []
        for name in ("raw_log", "pretty_log", "output_schema", "output_last_message", "process_stop_path"):
            value = getattr(self, name)
            if value is not None:
                path = safe_io.check_path(cwd / Path(value))
                object.__setattr__(self, name, path)
                if name != "process_stop_path":
                    outputs.append(path)
        if len(outputs) != len(set(outputs)):
            raise ValueError("Claude output paths must be distinct")
        if self.output_last_message is not None and self.output_last_message.exists():
            raise ValueError("Claude response path must initially be absent")


def selected_tools(request):
    return () if request.decision_only else READ_TOOLS if request.sandbox == "read-only" else WRITE_TOOLS


def policy_settings(request):
    # User/provider configuration stays native; repository settings/extensions
    # cannot select additional task tools or installed hooks. Bundled runtime
    # components still execute as part of the trusted native CLI.
    settings = {"disableAllHooks": True, "autoMemoryEnabled": False,
                "permissions": {"defaultMode": "dontAsk"}}
    if request.sandbox != "read-only":
        settings["sandbox"] = {"enabled": True, "failIfUnavailable": True,
            "allowUnsandboxedCommands": False, "autoAllowBashIfSandboxed": True,
            "filesystem": {"disabled": False},
            "network": {"deniedDomains": [] if request.network_access else ["*"],
                        "allowLocalBinding": False}}
    return settings


def build_command(request: ClaudeRequest) -> list[str]:
    tools = selected_tools(request)
    auto_allow = [name for name in tools if name not in {"Edit", "Write"}]
    auto_allow += [name + "(./**)" for name in tools if name in {"Edit", "Write"}]
    command = [request.env.get("ARQUILO_CLAUDE_CODE_COMMAND", "claude"), "--print",
        "--output-format", "stream-json", "--verbose", "--session-id", request.session_id,
        "--no-session-persistence", "--permission-mode", "dontAsk", "--tools", ",".join(tools),
        "--allowedTools", ",".join(auto_allow), "--disallowedTools", "mcp__*,Agent,Task,Skill,WebFetch,WebSearch",
        "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
        "--setting-sources", "user", "--disable-slash-commands", "--safe-mode",
        "--settings", json.dumps(policy_settings(request), separators=(",", ":"))]
    if request.model is not None:
        command += ["--model", request.model]
    if request.reasoning_effort is not None:
        command += ["--effort", request.reasoning_effort]
    if request.output_schema is not None:
        schema = _strict_json(safe_io.read_text(request.output_schema))
        if not isinstance(schema, dict):
            raise ValueError("Output schema must be a JSON object")
        command += ["--json-schema", json.dumps(schema, separators=(",", ":"))]
    return command


def _start(command, cwd, env):
    launcher = resolve_launcher(command[0], cwd=cwd, env=env)
    argv = [*launcher.argv, *command[1:]]
    tree, proc = ProcessTree(), None
    try:
        proc = subprocess.Popen(argv, cwd=str(cwd), env=dict(env), shell=False,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=False, bufsize=0, **tree.popen_options)
        proc.arquilo_process_tree, proc.arquilo_launcher, proc.arquilo_argv = tree, launcher.metadata(), argv
        tree.bind(proc)
        return proc
    except BaseException:
        tree.abort_start(proc)
        raise


def probe_cli(*, cwd: Path, env: Mapping[str,str], timeout=10.0, require_schema=False, require_effort=False):
    report = {"status":"FAIL", "backend":"claude-code", "version":None, "probes":[], "flags":{}, "model_calls":0}
    name = env.get("ARQUILO_CLAUDE_CODE_COMMAND", "claude")
    try:
        for kind, args in (("version", ["--version"]), ("help", ["--help"])):
            proc = _start([name, *args], cwd, env)
            try:
                out, err = proc.communicate(timeout=timeout)
                code = proc.returncode
            finally:
                cleanup = proc.arquilo_process_tree.terminate(reason="metadata_probe_exit", grace_seconds=.1)
                finish_cleanup(proc.arquilo_process_tree.close, cleanup)
            report["launcher"] = proc.arquilo_launcher
            report["probes"].append({"name":kind, "exit_code":code, "stderr_present":bool(err)})
            if code != 0 or cleanup.errors:
                raise ValueError("Claude CLI metadata probe failed")
            text = out.decode("utf-8")
            if kind == "version":
                if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][\w.-]+)?(?: \(Claude Code\))?\s*", text):
                    report["version"] = text.strip()
            else:
                flags = set(re.findall(r"--[A-Za-z][A-Za-z0-9-]*", text))
                required = (*REQUIRED_FLAGS, *(('--json-schema',) if require_schema else ()),
                            *(('--effort',) if require_effort else ()))
                report["flags"] = {f:f in flags for f in required}
                if not all(report["flags"].values()):
                    raise ValueError("Missing Claude CLI options: " + ", ".join(f for f,v in report["flags"].items() if not v))
        report["status"]="PASS"
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        report["detail"] = f"{type(exc).__name__}: {exc}"
    return report


class ClaudeProtocol:
    """Per-invocation native parser. Terminal text alone is never completion."""
    def __init__(self, request):
        self.request, self.initialized, self.terminal = request, False, False
        self.tools = set(selected_tools(request))
        self.structured = None

    def accept(self, line, trace):
        event = _strict_json(line)
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise ValueError("Malformed Claude event")
        kind = event["type"]
        if self.terminal:
            raise ValueError("Claude emitted data after its terminal result")
        if event.get("session_id") != self.request.session_id:
            raise ValueError("Claude event has missing or foreign session identity")
        if kind == "system" and event.get("subtype") == "ui_invalidate":
            # Measured native 2.1.303 pre-init UI notification, not a tool or
            # completion signal. Do not generalize this to arbitrary system data.
            if (set(event) != {"type", "subtype", "event", "uuid", "session_id"}
                    or event.get("event") != "ui.render"
                    or not isinstance(event.get("uuid"), str)):
                raise ValueError("Malformed Claude UI diagnostic")
            return False
        if kind == "result" and event.get("is_error") is True:
            # Startup failures (e.g. unavailable required sandbox) may precede
            # init. Retain their cause, but never establish completion or init.
            trace.capture["native_error"] = event
            raise ValueError("Claude native failure: " + json.dumps({
                "subtype": event.get("subtype"), "errors": event.get("errors"),
                "result": event.get("result")}, ensure_ascii=True)[:4096])
        if kind == "system" and event.get("subtype") == "init":
            if self.initialized:
                raise ValueError("Duplicate Claude init")
            if event.get("permissionMode") not in (None, "dontAsk"):
                raise ValueError("Claude did not apply dontAsk permission mode")
            permitted = self.tools | {"EndConversation"}
            if self.request.output_schema:
                permitted.add("StructuredOutput")
            actual = event.get("tools")
            if not isinstance(actual, list) or any(not isinstance(x,str) for x in actual) or set(actual)-permitted:
                raise ValueError("Unexpected native Claude tools in init")
            for field in ("mcp_servers", "plugin_errors", "mcp_server_errors", "skills", "slash_commands"):
                if event.get(field):
                    raise ValueError("Claude unexpectedly loaded or attempted an integration")
            # --safe-mode disables installed mods, not the CLI's own bundled
            # components. These two exact native 2.1.303 identities were measured
            # in a fresh home. Metadata validation is NOT pre-execution isolation.
            plugins = event.get("plugins", [])
            known = {"cc-plugin-agents-md", "cc-plugin-plugin-authoring"}
            if not isinstance(plugins, list):
                raise ValueError("Malformed Claude component metadata")
            seen = set()
            for plugin in plugins:
                if (not isinstance(plugin, dict) or set(plugin) != {"name", "path", "source"}
                        or plugin.get("name") not in known or plugin["name"] in seen
                        or plugin.get("path") != "builtin"
                        or plugin.get("source") != plugin["name"] + "@builtin"):
                    raise ValueError("Unqualified Claude runtime component")
                seen.add(plugin["name"])
            self.initialized = True
            trace.capture["verified_init"] = True
            trace.capture["runtime_components"] = plugins
            trace.capture["effective_model"] = event.get("model")
            trace.capture["effective_tools"] = actual
        elif not self.initialized:
            raise ValueError("Claude event arrived before verified init")
        elif kind == "result":
            if (event.get("subtype") != "success" or event.get("is_error") is not False
                    or event.get("permission_denials") or event.get("errors")
                    or event.get("safety_stops") or event.get("api_error_status")
                    or event.get("terminal_reason") not in (None, "completed")
                    or event.get("stop_reason") in {"max_tokens", "max_turns", "refusal", "length"}):
                raise ValueError("Claude result failed, was truncated, or contains permission denials")
            if self.request.output_schema is not None:
                self.structured = event.get("structured_output")
                if not isinstance(self.structured, dict):
                    raise ValueError("Claude structured result is missing")
                answer = json.dumps(self.structured, ensure_ascii=False, allow_nan=False)
            else:
                answer = event.get("result")
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("Claude terminal result has no usable answer")
            trace.assistant_messages.append(answer)
            trace.turn_completed = True
            trace.usage = {k:event[k] for k in ("usage", "modelUsage", "total_cost_usd", "num_turns") if k in event}
            self.terminal = True
            return True
        elif kind == "assistant":
            if event.get("error") or event.get("parent_tool_use_id") is not None:
                raise ValueError("Unexpected assistant error or subagent")
            message = event.get("message")
            if not isinstance(message, dict) or not isinstance(message.get("content"),list):
                raise ValueError("Malformed Claude assistant message")
            for block in message["content"]:
                if not isinstance(block, dict):
                    raise ValueError("Malformed Claude assistant block")
                if block.get("type") == "tool_use":
                    name = block.get("name")
                    internal_output = name == "StructuredOutput" and self.request.output_schema is not None
                    if name not in self.tools and name != "EndConversation" and not internal_output:
                        raise ValueError("Claude used a forbidden tool")
                    if name == "Bash":
                        trace.commands.append(CommandExec(str(block.get("input",{}).get("command","")),"requested"))
                    elif name in {"Write","Edit"}:
                        trace.file_changes.append(FileChange(raw={"tool":name,"input":block.get("input")}))
                elif block.get("type") not in {"text","thinking","redacted_thinking"}:
                    raise ValueError("Unknown assistant content type")
        elif kind == "system":
            if event.get("subtype") not in {"api_retry", "compact_boundary", "status"}:
                raise ValueError("Unexpected Claude system event (hooks and integration events are prohibited)")
        elif kind == "user":
            if event.get("parent_tool_use_id") is not None:
                raise ValueError("Unexpected subagent message")
        elif kind != "rate_limit_event":
            raise ValueError("Unknown Claude event type")
        return False


def execute(request: ClaudeRequest) -> TransportResult:
    request.__post_init__()
    command = build_command(request)
    trace, protocol = RunResult(), ClaudeProtocol(request)
    proc = None
    try:
        trace.capture_dir = numbered_directory(request.raw_log.parent, {"auftrag":"production"}.get(request.phase,request.phase))
        payload = request.prompt.encode("utf-8")
        trace.capture = {"schema_version":"arquilo.claude_code.io_capture.v1", "backend":"claude-code",
            "phase":request.phase, "cwd":str(request.cwd), "argv":command, "session_id":request.session_id,
            "started_at":datetime.now().astimezone().isoformat(), "diagnostics":[],
            "stdin":{"expected_bytes":len(payload), "archived_bytes":len(payload), "written_bytes":0,"closed":False},
            "stdout":{"received_bytes":0,"archived_bytes":0,"eof":False,"invalid_utf8_bytes":0},
            "stderr":{"received_bytes":0,"archived_bytes":0,"eof":False,"invalid_utf8_bytes":0},
            "raw_files":{"stdin":"prompt.utf8","stdout":"stdout.bin","stderr":"stderr.bin"},
            "answer_file":"response.txt", "answer_source":"correlated Claude native terminal result",
            "cli_answer_file":str(request.output_last_message) if request.output_last_message else None,
            "policy":"safe-mode, trusted user settings/bundled runtime; installed hooks/MCP/skills disabled; role-scoped tools"}
        safe_io.write_bytes(trace.capture_dir/"prompt.utf8",payload,exclusive=True)
        for name in ("stdout.bin","stderr.bin","response.txt"):
            safe_io.write_bytes(trace.capture_dir/name,b"",exclusive=True)
        for log in (request.raw_log, request.pretty_log):
            with safe_io.open_file(log,"a",encoding="utf-8"):
                pass
        reason = _cancel(request)
        if reason:
            observe_stop(trace,reason)
        else:
            compat = probe_cli(cwd=request.cwd,env=request.env,require_schema=request.output_schema is not None,
                               require_effort=request.reasoning_effort is not None)
            trace.capture["decision_cli_compatibility"] = compat
            trace.capture["decision_cli_version"] = compat["version"]
            reason = _cancel(request)
            if reason:
                observe_stop(trace,reason)
            elif compat["status"] != "PASS":
                raise ValueError(compat.get("detail","Claude CLI incompatible"))
            else:
                with safe_io.open_file(request.pretty_log,"a",encoding="utf-8") as f:
                    f.write(f"[claude-code] phase={request.phase} session={request.session_id} capture={trace.capture_dir}\n")
                proc = _start(command,request.cwd,request.env)
                _collect_process(request,trace,payload,proc,protocol=protocol)
                if trace.execution_error is None and not trace.process_stop_triggered and request.output_last_message:
                    # Only the correlated native structured result can become the
                    # adapter-owned response file. Existing/stale paths are refused.
                    safe_io.write_bytes(request.output_last_message,trace.end_answer.encode("utf-8"),exclusive=True)
    except AgentProcessError as exc:
        trace = exc.result
    except KeyboardInterrupt:
        observe_stop(trace,"KeyboardInterrupt")
    except (OSError, ValueError, RuntimeError, UnicodeError) as exc:
        trace.execution_error = execution_error(f"Claude Code execution failed: {exc}",code="claude_execution_failed",phase=request.phase)
    finally:
        if proc is not None:
            cleanup = proc.arquilo_process_tree.terminate(reason="transport_scope_exit",grace_seconds=request.timeouts.kill_grace)
            finish_cleanup(proc.arquilo_process_tree.close,cleanup)
            trace.process_exit_code = cleanup.parent_exit_after
            trace.capture["process_tree"] = cleanup.metadata()
            if cleanup.interrupted:
                observe_stop(trace,"KeyboardInterrupt")
            if cleanup.errors and trace.execution_error is None:
                trace.execution_error=execution_error("; ".join(cleanup.errors),code="claude_cleanup_failed",phase=request.phase)
        if trace.capture_dir:
            _finish_archive(request,trace)
    return TransportResult(_execution(trace,request.phase),trace)


def _cancel(request):
    if request.process_stop_path is not None and request.process_stop_path.exists():
        return safe_io.read_text(request.process_stop_path).strip() or "process_stop active"
    return request.cancel_requested() if request.cancel_requested else None


def _finish_archive(request, trace):
    try:
        atomic_write_text(trace.capture_dir/"response.txt", trace.end_answer)
        for name in ("stdout","stderr"):
            stats=trace.capture[name]
            stats["complete"] = stats["eof"] and stats["received_bytes"] == stats["archived_bytes"]
        stats=trace.capture["stdin"]
        stats["complete"] = stats["closed"] and stats["expected_bytes"] == stats["written_bytes"] == stats["archived_bytes"]
        trace.capture.update(finished_at=datetime.now().astimezone().isoformat(),process_exit_code=trace.process_exit_code,
            completion_seen=trace.turn_completed, process_stop_triggered=trace.process_stop_triggered,
            cancellation_reason=trace.process_stop_details, error=trace.execution_error, stream_errors=trace.stream_errors,
            status="failed" if trace.execution_error else "cancelled" if trace.process_stop_triggered else "succeeded")
        atomic_write_text(trace.capture_dir/"capture.json",json.dumps(trace.capture,ensure_ascii=True,indent=2)+"\n")
    except (OSError,ValueError) as exc:
        trace.stream_errors.append({"type":"log_error","message":str(exc)})
        trace.execution_error=execution_error("Claude archive incomplete: "+str(exc),code="claude_archive_failed",phase=request.phase)


def _execution(trace,phase):
    fields=dict(answer=trace.end_answer, process_exit_code=trace.process_exit_code,completion_seen=trace.turn_completed)
    if trace.execution_error:
        e=trace.execution_error
        return ExecutionResult(status=ExecutionStatus.FAILED,**fields,
            failure=Failure(kind=FailureKind.EXECUTION,code=e["code"],message=e["message"],phase=phase))
    if trace.process_stop_triggered:
        return ExecutionResult(status=ExecutionStatus.CANCELLED,**fields,cancellation_reason=trace.process_stop_details)
    return ExecutionResult(status=ExecutionStatus.SUCCEEDED,**fields)


def run_claude_exec_json(prompt,cwd,*,sandbox,output_last_message_path,raw_log,pretty_log,extra_args=(),
                        model=None,reasoning_effort=None,network_access=False,output_schema_path=None,
                        env=None,timeouts=None,config_profile=None,mcp_servers=None,**kwargs):
    validate_options("claude-code",config_profile=config_profile,extra_args=extra_args)
    validate_resources("claude-code", mcp=mcp_servers)
    environment=dict(os.environ if env is None else env)
    request=ClaudeRequest(prompt=prompt,cwd=cwd,sandbox=sandbox,env=environment,
        raw_log=raw_log,pretty_log=pretty_log,model=resolve_model(model,backend="claude-code",environ=environment),
        reasoning_effort=resolve_effort(reasoning_effort,backend="claude-code",environ=environment),
        network_access=network_access,output_schema=output_schema_path,output_last_message=output_last_message_path,
        timeouts=timeouts or TransportTimeouts(),**kwargs)
    return execute(request).trace
