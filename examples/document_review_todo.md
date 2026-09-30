***SYNTAX marked-en***

# Document task example

Use only the supplied `brief.md`, which contains synthetic facts. Do not use web
search or invent missing information. The controller owns DONE; do not create a
`process_stop` file. Record blockers in the result report.

***CFG network_access=false web_search=disabled***
1. ***Task***: Write a concise `summary.md` of `brief.md`, with a section titled `Open questions`, and document checks in `todo_result_1.md`.
    Acceptance: The summary includes all three stated milestones, preserves their dates, and identifies the unassigned acceptance owner as an open question. Do not resolve that question by guessing. Keep the summary under 250 words. A faithfully documented open question is not itself a blocker for this task.
