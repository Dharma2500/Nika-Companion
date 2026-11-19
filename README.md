# Nika-Companion

Nika is a personal, evolving local-first AI companion designed to work alongside Vitaly in Minecraft and outside the game.

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
| Local dashboard | Loopback-only authenticated dashboard with primary/secondary OpenAI password fields, credential save/delete, model and daily-token settings, connection test, redacted key status and usage counters. |
| Persistent SQLite memory | Schema v3; provenance-aware memories, conversations, provider token usage and learning-candidate table. Explicit remember/correction commands are saved locally without API calls. |
| Model provider adapter | OpenAI Responses API is primary, with primary/secondary Windows Credential Manager keys and quota-aware failover. Generic Chat Completions/LM Studio remains optional and untested. |
| Local configuration | Environment-based, no secrets required |
| Automated Python checks | Python CI #439: all 6 Ubuntu/Windows × Python 3.11–3.13 jobs passed; 185 tests in each job; Ruff, compileall and source overlay passed. |
| Fabric 1.21.11 client mod | Client-only mod v0.5.1; `/nika` summons the local Allay companion, automatic Python bridge connection, separate smooth head/body rotation, small idle gestures, critically damped inertial following and private unprefixed chat with N toggle and fail-closed offline handling; current Fabric build #146 passed and produced the v0.5.1 JAR; v1/v2/v3 local persistence verified |
| Python ↔ Minecraft protocol | Authenticated handshake, one-shot `/nika observe` and private `POST /bridge/v1/chat`; HMAC/replay protection, idempotent message persistence and unprefixed private chat with fail-closed offline handling; integration tests passed in all six Python CI jobs; in-game privacy acceptance remains |



Latest verified workflows:
- [Fabric build #223](https://github.com/Dharma2500/Nika-Companion/actions/runs/44597701458) — successful. No Java source changed; the existing JAR remains current.
- [Python CI #439](https://github.com/Dharma2500/Nika-Companion/actions/runs/44597701786) — all six Ubuntu/Windows × Python 3.11–3.13 jobs and the source-overlay job successful; 185 tests passed in each job, Ruff and compileall passed. Source overlay artifact ID `14567210993`.

## Quick start

Requires Python 3.11 or newer.

~~~bash
python -m venv .venv
python -m pip install -e ".[dev]"
python -m pytest
python -m nika.cli doctor
python -m nika.cli dashboard
~~~

The first doctor run creates the local data directory and initializes SQLite. By default, data is stored in ~/NIKA_DATA. Set NIKA_DATA to choose another location.

Before initializing SQLite, `nika doctor` validates the configured paths and checks that the data, logs, backups, runtime and database locations are usable. Empty `NIKA_DATA` or `NIKA_DATABASE_PATH` variables are treated as configuration errors instead of silently falling back to defaults. A database deliberately stored outside `NIKA_DATA` is allowed, but doctor reports that logs, runtime state and backups remain under `NIKA_DATA`.

Learning assets use `NIKA_DATA/learning` by default. This is where future datasets, base models, adapters, checkpoints, experiments and model exports belong. Set `NIKA_LEARNING_DIR` only when you deliberately want those files on a different volume.

Operational logs are written as structured JSON Lines under `NIKA_DATA/logs/`: the CLI uses `cli.jsonl`, and the background service uses `runtime.jsonl`. Each file is limited to 2 MiB plus five rotated files. Known credential fields and common token formats are redacted before writing.

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


## Learning and API economy

Nika's durable memory belongs to the local Python Core and SQLite database, not the OpenAI provider. The target design stores conversations, corrections, user-taught facts and verified reusable skills locally. Explicit memory operations and local retrieval must not call the API. OpenAI is called only when a user request needs generation or reasoning that local memory and deterministic logic cannot provide. Two OpenAI key slots are implemented (primary and secondary failover); explicit remember/correction commands are stored locally without API calls. LM Studio remains an optional, untested alternative. API credentials must be stored in the Windows OS credential manager, never in Git, SQLite, logs or browser storage.

## Local dashboard

After installing the project, run:

~~~powershell
.\\.venv\\Scripts\\python.exe -m nika.cli dashboard
~~~

The command starts the local Python runtime if it is not already running, then opens the dashboard in your browser. The dashboard now accepts primary/secondary OpenAI keys via a native same-origin password form. Keys are stored in the Windows Credential Manager, not in provider.json or browser storage. Its explicit connection test consumes a small number of API tokens. It shows runtime uptime, SQLite health/schema/counts, whether a provider is configured and the capabilities currently advertised by the local bridge. It does not show chat contents, API keys, runtime control tokens or bridge tokens.

The HTTP server binds only to 127.0.0.1 on an ephemeral local port. Browser entry uses a single-use ticket with a 60-second lifetime, exchanged for a one-hour HttpOnly; SameSite=Strict session cookie. The page has a nonce-based Content Security Policy and loads no external assets. The ticket is carried in the URL fragment and removed by the page after exchange. The dashboard does not store credentials in localStorage.

The optional advanced LM Studio pathway can save a non-secret Base URL and Model ID to NIKA_DATA/config/provider.json. It is not the primary provider and is not tested in this milestone. Close the browser tab when finished; stop the runtime separately with python -m nika.cli stop when you no longer need it.

## Repository layout

~~~text
agent/                  Python agent package and tests
minecraft-mod/          Fabric client mod
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

## Backup and restore

Create a verified SQLite backup:

~~~powershell
.\.venv\scripts\python.exe -m nika.cli backup
~~~

Verify a backup before using it:

~~~powershell
.\.venv\scripts\python.exe -m nika.cli backup-verify "C:\path\to\nika-backup.sqlite3"
~~~

Restore is deliberately interactive and requires confirmation:

~~~powershell
.\.venv\scripts\python.exe -m nika.cli restore "C:\path\to\nika-backup.sqlite3"
~~~

The restore command validates SQLite integrity and the supported schema before
changing anything. It reserves the runtime startup lock, gracefully stops a
responsive Nika runtime, and refuses to proceed when the runtime state is
ambiguous or the process is still alive but unresponsive. The existing database
and any SQLite WAL/SHM/journal sidecars are copied to
`NIKA_DATA/backups/restore-safety/` before replacement. The new database is
staged and verified before an atomic swap; a failed post-swap check triggers
automatic rollback. Add `--yes` only when running an intentional non-interactive
restore.

## Moving Nika data to another disk

Use the built-in migration command instead of copying a live SQLite directory by hand:

~~~powershell
.\.venv\scripts\python.exe -m nika.cli migrate-data "D:\NIKA_DATA"
~~~

The command creates a fresh verified database backup, reserves the runtime
maintenance lock, gracefully stops a responsive runtime, copies the complete
data directory and learning assets, and uses SQLite's online backup API for
the active database. The copied database is checked before the destination is
published. Runtime status and lock files are deliberately recreated at the new
location. The original data directory is never deleted or modified.

After verifying the migration, set the persistent Windows user variable:

~~~powershell
[Environment]::SetEnvironmentVariable('NIKA_DATA', 'D:\NIKA_DATA', 'User')
$env:NIKA_DATA = 'D:\NIKA_DATA'
~~~

Open a new PowerShell window after setting the user variable. Keep the old
directory until the new location has been used and backed up successfully.

The `backup` command currently protects the SQLite database only. Large model
weights, datasets and learning runs live under `learning` and need their own
versioned/offline backup policy; they are copied during a full data-directory
migration but are not duplicated by every database backup.

## Security boundary

Never commit API keys, .env files, SQLite databases, chat logs, world snapshots, or backups. The local data directory is intentionally separate from the repository. See docs/security.md.

## Project handoff

The canonical development handoff is maintained in [docs/CHAT_CONTEXT.md](docs/CHAT_CONTEXT.md). It records current implementation state, privacy requirements, CI/artifact status and the exact next steps. The chronological project log is [docs/continuity/CHAT_LOG.md](docs/continuity/CHAT_LOG.md).

## Development

Read docs/architecture.md before adding cross-component behavior. Record protocol changes and migrations deliberately. A passing CI run is required for a change to be considered verified.


## Current OpenAI and local-learning implementation

- Primary provider: OpenAI Responses API, default model gpt-6-luna with reasoning effort disabled, no tools, store=false and a 320-token normal reply ceiling.
- Credentials: primary and secondary API keys live in the Windows Credential Manager. The local dashboard accepts both, can replace/remove each independently, and never returns key values to the page.
- Failover: second key is used for quota exhaustion, authentication or permission errors. Ordinary 429 rate limits and malformed requests do not consume the reserve key.
- Local economy: up to 8 recent messages, 4 relevant memories and an 8 KiB context; daily ceiling 60,000 total tokens by default; provider-reported input/output/cached/reasoning counts are recorded per key slot in SQLite schema v3.
- Local learning: explicit "Ника, запомни: ..." and "Поправка: ..." commands are recorded as user_taught facts without an API call. Repeated explicit facts are deduplicated. Every private user turn is stored locally before provider availability is checked.
- LM Studio remains an optional advanced OpenAI-compatible provider, not the primary provider. It is not configured or tested in this milestone.
- Manual Windows acceptance with Vitaly's actual Credential Manager and OpenAI account remains outstanding. No credentials should be pasted into GitHub or this conversation.
- Review/approve UI for inferred candidates, skill-learning/verification, monthly USD budget and emergency API disable are future work.
