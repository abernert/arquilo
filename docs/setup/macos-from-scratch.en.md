# ARQUILO on macOS: from a fresh Mac to a safe first run

[Deutsch](macos-from-scratch.de.md) · [Optional tools](optional-tools.en.md) · [User Guide](../guides/user-guide.en.md) · [README](../../README.md)

This guide starts **before** ARQUILO: on a Mac that might not yet have Homebrew, Git, Python or an agent CLI installed. It covers Apple silicon and Intel Macs with the usual `zsh` Terminal shell. Check for existing tools before installing anything. Homebrew is the **convenient installation path** used here, not a hard ARQUILO dependency.

**Minimum:** Python **3.11+** (CI covers 3.11–3.13), a complete ARQUILO checkout/package, and **either** an authenticated Codex CLI (default) **or** Claude Code (with `--backend claude-code`). Git is needed for a Git checkout, but not if you use the complete release ZIP. `gh`, VS Code, Node.js and file-format helpers are **optional**.

## 0. Open Terminal and check macOS

Open **Terminal** (Applications → Utilities → Terminal) as an ordinary user, not root.

```sh
sw_vers -productVersion
uname -m             # arm64 = Apple silicon; x86_64 = Intel
echo "$SHELL"       # normally /bin/zsh
```

Let each installation finish before proceeding. Managed work Macs may need IT approval for software, proxy, certificates and authentication. Inspect official sources before running downloaded installer scripts.

## 1. Apple Command Line Tools and Git

First check whether developer tools and Git are already installed:

```sh
xcode-select -p
git --version
```

If `xcode-select -p` fails, request Apple's tools, complete the macOS dialog, and retry the checks:

```sh
xcode-select --install
```

Apple Command Line Tools often include a usable Git. If `git --version` still fails afterward, install Git with `brew install git` once Homebrew is ready. You do **not** need a GitHub account to clone the **public** ARQUILO repository.

## 2. Install Homebrew if missing

```sh
command -v brew
brew --version
```

If absent, use the [official Homebrew installer](https://brew.sh/). Its published installation command is:

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

**Follow the installer's printed `Next steps`.** It will often tell you to add `brew shellenv` to `~/.zprofile`. If `brew` is not yet available in the current Terminal, select **one** prefix:

```sh
# Apple silicon:
eval "$(/opt/homebrew/bin/brew shellenv)"
# OR Intel:
# eval "$(/usr/local/bin/brew shellenv)"
brew --version
```

For a **persistent** PATH, copy the correct `shellenv` line printed by the installer to `~/.zprofile`; avoid duplicate lines. See [Homebrew installation](https://docs.brew.sh/Installation).

## 3. Check Git; add GitHub CLI only if useful

```sh
git --version
# If Git is still unavailable after step 1:
# brew install git
```

The `gh` CLI is useful for issues, pull requests and private repositories, but **not required** for cloning public ARQUILO:

```sh
command -v gh || brew install gh
gh --version
```

Only authenticate if you need GitHub operations requiring a login:

```sh
gh auth login
gh auth status
```

GitHub authentication is **separate** from Codex/Claude authentication. Do not paste tokens into task files, shell scripts or committed files. See the [GitHub CLI manual](https://cli.github.com/manual/gh_auth_login).

## 4. Install a compatible Python

The `python3` shipped with macOS may be too old. Check the **version**, not just the command:

```sh
python3 --version
python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'
```

If `python3` is missing or the second check fails, install a CI-tested version:

```sh
brew install python@3.13
python3.13 --version
```

Choose an interpreter for **this Terminal session**. Prefer the versioned Homebrew Python when available, rather than an outdated macOS `python3`:

```sh
PYTHON="$(command -v python3.13 || command -v python3)"
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 11), sys.version; print(sys.version)'
```

All remaining commands use `"$PYTHON"`. In a new Terminal window, repeat the assignment or directly use `python3.13`. ARQUILO core uses only Python's standard library: do **not** install `requirements.txt` just to run core. Python versions newer than the current CI matrix (3.11–3.13) may be untested.

## 5. Install and authenticate one agent backend

**Option A – Codex (default):**

```sh
command -v codex || brew install --cask codex
codex --version
codex login status
```

If not yet authenticated, run `codex login` and follow the sign-in flow. The [official Codex installation instructions](https://github.com/openai/codex#installing-and-running-codex-cli) also offer a standalone installer. The command-line tool is **not** the same thing as the desktop application.

**Option B – Claude Code (no Codex needed):**

```sh
command -v claude || brew install --cask claude-code
claude --version
```

If necessary, launch `claude` interactively once to complete provider authentication. The [official Claude Code setup](https://docs.anthropic.com/en/docs/claude-code/getting-started) describes a native installer too. The Homebrew installation here does **not require Node.js**; Node is only relevant when you deliberately choose an npm-based launcher. Either backend still requires suitable provider/model access.

**Security boundary:** Install Git and the agent CLIs (including resolved executable targets) outside every workspace that ARQUILO tasks can write to. Keep ARQUILO itself, your project workspace, and private controller state separate. Do not place credentials in project files.

## 6. Install ARQUILO

The public repository can be cloned without `gh auth login`:

```sh
mkdir -p "$HOME/tools" "$HOME/projects"
cd "$HOME/tools"
git clone https://github.com/abernert/arquilo.git
cd arquilo
```

If `$HOME/tools/arquilo` already exists, **do not clone over it**; first inspect `git -C "$HOME/tools/arquilo" status` and the [update guidance](../guides/user-guide.en.md).

**Without Git:** Download a **complete versioned runtime ZIP** from [Releases](https://github.com/abernert/arquilo/releases), extract it into its own directory, and open the directory containing `arquilo.py` in Terminal. One Python file alone is not a complete install.

## 7. No-model, no-cost smoke test

Run from the ARQUILO installation directory (`cd "$HOME/tools/arquilo"` for a Git checkout). The first checks require neither authentication nor model calls:

```sh
"$PYTHON" -B arquilo.py --version
"$PYTHON" -B arquilo.py tasklist run --help
```

Create a **separate disposable project workspace** and generate a dry-run preview:

```sh
mkdir -p "$HOME/projects/arquilo-smoke"
cp examples/minimal_todo.md "$HOME/projects/arquilo-smoke/tasks.md"

"$PYTHON" -B arquilo.py tasklist run \
  --workdir "$HOME/projects/arquilo-smoke" \
  --todo-file "$HOME/projects/arquilo-smoke/tasks.md" \
  --dry-run \
  --dry-run-file "$HOME/projects/arquilo-smoke/preview.md" \
  --process-stop-policy controller-only \
  --max-calls 8 --mcp none --skills none
```

Read `$HOME/projects/arquilo-smoke/preview.md`. A `--dry-run` validates task planning, **not** provider/model access. For a metadata-only diagnostic:

```sh
# Codex:
"$PYTHON" -B arquilo.py doctor --workdir "$HOME/projects/arquilo-smoke"
# For Claude Code instead:
# "$PYTHON" -B arquilo.py doctor --backend claude-code --workdir "$HOME/projects/arquilo-smoke"
```

**Prefer not to launch a real agent yet?** You are done. The [first real run](../guides/user-guide.en.md#first-run) can call an external model and incur charges. Add `--backend claude-code` when using Claude; named ARQUILO MCP servers are not supported by that backend in v0.10.0.

## 8. Troubleshooting and updates

| Symptom | Check / action |
| --- | --- |
| `brew: command not found` | Homebrew `Next steps` and `~/.zprofile`; reopen Terminal. |
| Python reports `3.9`/`3.10` | Use `python3.13` or `"$PYTHON"` explicitly. |
| `codex`/`claude` not found | Inspect `command -v codex` / `command -v claude`, PATH and Terminal restart. |
| `git` fails | Complete Apple Command Line Tools install or `brew install git`. |
| Authentication fails | Check the chosen provider/account, permissions, proxy and certificates; `gh auth login` is not agent authentication. |
| Managed Mac blocks installation | Ask IT to approve the software; do not bypass platform protections. |

Before updating, stop active ARQUILO runs, back up task inputs/controller evidence, and inspect `git status`. Only on a clean checkout, use `git pull --ff-only`. Do not mix Python modules from different versions; repeat a disposable dry run afterward.

## Next steps

- [English User Guide: tasks, output and first real run](../guides/user-guide.en.md)
- [Optional helper tools: VS Code, Office, PDF/OCR, images, media and structured data](optional-tools.en.md)
- [Security boundaries and limitations](../../SECURITY.md)
