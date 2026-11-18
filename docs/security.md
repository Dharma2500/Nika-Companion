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

Learning assets default to `NIKA_DATA/learning`, with `NIKA_LEARNING_DIR` available for a deliberate separate-volume location. Data migration is copy-first: it holds the runtime maintenance lock, takes a fresh database backup, uses SQLite's online backup API, verifies the staged database, omits volatile runtime status and lock files, and never deletes the source directory. The source should remain untouched until the destination has been verified.

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

The current protocol-v1 endpoint is read-only: an empty signed `GET /bridge/v1/hello`
returns runtime identity and the `health.read` and `observation.submit` capabilities. It binds to
`127.0.0.1`; no public network listener is created. A dedicated random bridge
token is generated per runtime start and kept separate from the runtime
start/stop control token. HMAC-SHA256 signatures include the method, exact path,
timestamp, nonce and body hash. Requests outside a 60-second clock window or
with a previously accepted nonce are rejected. The handshake does not expose
Minecraft state, durable memory, chat history or world-changing actions.

Observation contracts are versioned in `docs/schemas/`:
`observation-v1.schema.json`, `observation-v2.schema.json` and
`observation-v3.schema.json`. The Python validator rejects duplicate JSON
keys, unknown properties, non-finite numbers, invalid identifiers,
out-of-range values and unsupported versions. Every observation body is
limited to 8 KiB. The versions are additive and remain backward compatible:
v1 contains basic client/world/player context, v2 adds bounded loaded-only
block-state sampling, and v3 adds the biome, time/weather, local light level,
game mode and one-shot movement flags described in the architecture document.

The signed `POST /bridge/v1/observe` endpoint accepts only UTF-8 JSON
bodies up to 8 KiB. HMAC verification covers the exact body hash, path, method,
timestamp and nonce. The runtime rejects replayed nonces, validates the
observation against its declared version, then persists the normalized payload
as `minecraft.observation.vN`. The client sends a snapshot only when the user
runs `/nika observe`; it does not poll automatically.

Inventory contents, armor stacks, ender chest contents, block-entity data,
containers, sign text, NBT, chat, server address, account identity, UUIDs,
other players and entity lists remain excluded. The observation endpoint does
not provide any world-changing operation. World-changing operations remain
disabled until capability checks, user approval, an emergency stop and
disposable-world regression tests are implemented.
