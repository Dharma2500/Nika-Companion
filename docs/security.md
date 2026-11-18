# Security and privacy baseline

## Never commit

- API keys, access tokens, passwords or private certificates
- .env files or local provider configuration
- SQLite databases, WAL/SHM files, backups or chat histories
- World snapshots, coordinates, inventories or private server data
- Local logs and crash dumps that may contain personal information

The repository ignore rules cover common cases, but .gitignore is not a security boundary. Review staged files before every commit.

## Local data

The default data directory is ~/NIKA_DATA. Set NIKA_DATA to a dedicated path on the machine that runs the agent. Backups must remain local or in a storage location explicitly chosen by Vitaly.

The CLI rejects empty path variables and checks the data, logs, backups, runtime and database locations before opening SQLite or creating logs. Existing database files must be readable and writable. A database outside NIKA_DATA is supported, but the CLI warns that its logs, runtime state and backups remain in NIKA_DATA.

## Local logs

Structured application logs are stored as JSON Lines in `NIKA_DATA/logs/`.
The CLI writes to `cli.jsonl` and the background service writes to
`runtime.jsonl`, avoiding cross-process rotation races. Each active file is
limited to 2 MiB and up to five rotated files are retained.
Known credential fields and common bearer/API-token formats are redacted before
records are written. Redaction is defense in depth, not permission to log secrets:
never place credentials, private chat content, or sensitive world data in log
messages. Treat logs as private local data and never commit or upload them.

## Runtime recovery

A stale runtime status file is not sufficient evidence that the process is still alive. Startup verifies both the authenticated control endpoint and the recorded PID. If the PID is still alive but the endpoint is unresponsive, startup fails closed rather than launching a second process. Invalid status files are preserved for inspection. Startup exclusion uses a Windows named mutex or a POSIX non-blocking file lock held until the control endpoint is ready; the operating system releases the lock if its owner exits. `start.lock` is only a diagnostic PID marker. Its presence or contents do not prove that a runtime is active.

## Database restore

Restore accepts only a readable SQLite file that passes `PRAGMA integrity_check`
and matches the currently supported schema version. Before replacing the live
database, the CLI reserves the runtime startup lock and requests graceful
shutdown. Ambiguous status files and live but unresponsive Runtime processes
cause a fail-closed refusal.

The current database and any `-wal`, `-shm` or `-journal` sidecars are copied
to `NIKA_DATA/backups/restore-safety/`. The selected backup is staged in the
database directory and checked before atomic replacement. A failed post-install
check triggers rollback from the safety copy. Safety snapshots are retained
separately from normal backup rotation and should be treated as private data.

## API credentials

Runtime API credentials will be loaded from a local secret store or environment variables in a later implementation. They must never be placed in the Fabric JAR, source files, dashboard frontend, Git history, logs or model prompts.

## Minecraft permissions

The mod must not bypass anti-cheat, access hidden server data, impersonate other players or execute actions outside the permissions available to the user. Capability checks are session-specific and fail closed.

## Local bridge

Before enabling actions, the bridge must bind to loopback only, authenticate its client, validate message schemas and size limits, reject replayed requests, and provide an emergency stop. No public network listener is required for the initial design.
