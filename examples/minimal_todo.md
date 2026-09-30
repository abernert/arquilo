***SYNTAX marked-en***

# Minimal smoke test

Work only in the provided workspace. Preserve the task list's content and do not
mark tasks DONE; the controller owns completion. Document any blocker rather
than bypassing it. Do not create `process_stop`; report issues for the controller.

***CFG network_access=false web_search=disabled***
1. ***Task***: Create an empty file named `hello.txt` and document the actual result in `todo_result_1.md`.
    Acceptance: `hello.txt` exists as a regular file and has exactly 0 bytes. Verify this from the filesystem and state the result in the report. If it already exists, verify it without overwriting a nonempty file. No other deliverables are required.
