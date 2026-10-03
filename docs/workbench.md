# Workbench and Ask

ARQUILO includes two optional interaction surfaces without adding Python dependencies.

## Read-only questions

```sh
python3 -B arquilo.py ask --workdir /path/to/project "Why is this component structured this way?"
```

`ask` is deliberately outside the task lifecycle: it creates no task, performs no review, and changes no DONE state. Codex receives the project as a `read-only` workspace with shell network disabled. The prompt forbids tests, builds, generators and project execution; it asks for targeted inspection and project-relative citations.

Use `--depth overview|normal|deep` to control how broadly it should inspect the workspace. `--model` and `--reasoning-effort` use the normal ARQUILO configuration precedence. Ask archives are kept outside the workdir by default in the operating-system temporary directory.

Read-only is a write boundary, **not a confidentiality boundary**: the model provider can receive content Codex reads. Do not use this command on material that may not be sent to the configured provider.

## Local browser workbench

```sh
python3 -B arquilo.py workbench --workdir /path/to/project --todo-file tasks.md
```

The command prints a tokenized URL such as `http://127.0.0.1:8765/?token=...`. The server binds to loopback only. The initial implementation intentionally uses only the Python standard library.

The workbench can:

- display parsed task IDs, status and text;
- turn one-natural-language-task-per-line input into numbered `***Task***` syntax;
- edit the task Markdown directly;
- start the normal ARQUILO runner as a separate process;
- display bounded runner output;
- ask read-only project questions at overview, normal or deep research depth.

The workbench does **not** implement a second scheduler. A run is delegated to `arquilo.py run`, so controller authority, review, plan integrity and state storage remain unchanged.

### Security and operating limits

The URL token prevents an unrelated local page from casually invoking the workbench endpoints, and the server is not exposed beyond `127.0.0.1`. Treat the URL as sensitive while the server is running. This is a local convenience boundary, not hardened multi-user authentication.

The browser editor writes the selected task file because editing the plan is its purpose. ARQUILO's normal strict plan checks still apply when a run starts. Do not use `--accept-plan-changes` merely to suppress a controller integrity warning.

The first implementation supports one active run per workbench process. Closing the browser does not terminate that run; stopping the workbench process itself may leave the separately started runner to finish according to normal process behavior.

## Design boundary

The stable split is:

```text
browser workbench ─┬─ task-file editing / plan generation
                   ├─ normal ARQUILO runner subprocess
                   └─ Ask service ── read-only Codex transport
```

This keeps the UI replaceable. A future richer desktop or web frontend should call the same runner/Ask boundaries rather than duplicating controller logic.
