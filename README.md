# Nika-Companion

Nika is a private, evolving AI companion designed to work alongside Vitaly in Minecraft and outside the game.

The project is built in small, testable layers. The local agent and persistent memory must remain useful when an external AI API is unavailable. Minecraft integration is client-side and must respect the actual permissions and capabilities available in each world or server.

## Project principles

- **Local-first memory.** User data lives in a configurable NIKA_DATA directory outside this repository.
- **Graceful degradation.** An API outage must not erase memory or stop local features.
- **Honest capabilities.** Nika must never claim to observe or do something she cannot access or perform.
- **Permission-aware actions.** No anti-cheat bypasses, hidden server-state access, or unauthorized actions.
- **Small, verifiable changes.** Tests and CI accompany implementation.
- **Secrets stay local.** Runtime API keys, databases, logs, and private world data do not belong in Git.

## Current status

| Area | Status |
|---|---|
| Python package skeleton | Initial implementation |
| Persistent SQLite memory | Initial schema and event journal |
| Local configuration | Environment-based, no secrets required |
| Automated Python checks | GitHub Actions workflow added |
| Fabric 1.21.11 client mod | Not started |
| Python ↔ Minecraft protocol | To be designed and versioned |
| Dashboard, voice, external AI | Planned, not required for local core |

## Quick start

Requires Python 3.11 or newer.

~~~bash
python -m venv .venv
python -m pip install -e ".[dev]"
python -m pytest
python -m nika.cli doctor
~~~

The first doctor run creates the local data directory and initializes SQLite. By default, data is stored in ~/NIKA_DATA. Set NIKA_DATA to choose another location.

Operational logs are written as structured JSON Lines under `NIKA_DATA/logs/`: the CLI uses `cli.jsonl`, and the background service uses `runtime.jsonl`. Each log is limited to 2 MiB plus five rotated files. Known credential fields and common token formats are redacted before writing.

**Windows PowerShell**
~~~powershell
$env:NIKA_DATA = "D:\NIKA_DATA"
python -m nika.cli doctor
~~~

**Linux / macOS**
~~~bash
export NIKA_DATA="$HOME/NIKA_DATA"
python -m nika.cli doctor
~~~

## Repository layout

~~~text
agent/                  Python agent package and tests
minecraft-mod/          Fabric client mod (planned)
docs/                   Architecture, security and roadmap
.github/workflows/      Automated checks and future mod builds
pyproject.toml          Python project and tool configuration
~~~

## Windows desktop launch

After installing the project with the commands above, use the two batch files in the repository root:

- Double-click `start_nika.bat` to run Nika in a visible console window.
- Close that window with its X button to request a graceful shutdown. The console handler waits for runtime cleanup before Windows closes the process.
- Alternatively, double-click `stop_nika.bat` to stop Nika from another window.

Do not launch the foreground batch while a background runtime is already running. Stop the existing runtime first with `stop_nika.bat`.

## Security boundary

Never commit API keys, .env files, SQLite databases, chat logs, world snapshots, or backups. The local data directory is intentionally separate from the repository. See docs/security.md.

## Development

Read docs/architecture.md before adding cross-component behavior. Record protocol changes and migrations deliberately. A passing CI run is required for a change to be considered verified.
