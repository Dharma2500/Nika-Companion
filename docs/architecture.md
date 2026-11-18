# Architecture baseline

## Non-negotiable boundaries

1. The Python agent owns durable memory. The Minecraft mod is a client adapter, not the database.
2. Local memory and known skills remain available when external AI providers fail.
3. Every action is constrained by capabilities reported by the current Minecraft session.
4. Observations, user explanations, verified facts, and hypotheses remain distinguishable.
5. Irreversible or high-impact actions require explicit approval.
6. No anti-cheat bypass, hidden server-state access, or unauthorized server action.

## Planned components

| Component | Responsibility |
|---|---|
| Nika Core | Stable personality, dialogue policy and task orchestration |
| Memory Engine | SQLite records, event journal, retrieval and migrations |
| World Observer | Converts permitted client observations into bounded events |
| Capability Manager | Tracks what the current world/session allows |
| Skill Engine | Versioned procedures, prerequisites, confidence and validation |
| Planner | Breaks goals into steps with preconditions and postconditions |
| Action Engine | Executes only approved actions supported by current capabilities |
| Provider Manager | API selection, failover, budgets and degraded modes |
| Research Engine | Documentation lookup and evidence provenance |
| Initiative Engine | Context-aware suggestions with interruption limits |
| Agent Bridge | Versioned local protocol between mod and Python |
| Dashboard | Local status, chat, memory review, budgets and emergency stop |
| Voice Engine | Optional speech-to-text and text-to-speech |

## Initial data flow

~~~text
Minecraft client events
        |
        v
Capability checks -> World Observer
                         |
                         v
                 Local event journal
                         |
                         v
                 Memory / Skill Engine
                         |
              optional bounded context
                         |
                         v
                 Provider Manager
                         |
                         v
                 Nika Core / Planner
                         |
                  permission checks
                         |
                         v
                 Action Engine -> Minecraft client
~~~

The event journal is written locally before optional model analysis. Raw high-volume block updates must be aggregated locally; they must not become one API request per event.

## Memory provenance

Every durable knowledge record identifies its origin, timestamp, world/session where relevant, and confidence. Distinguish at minimum:

- user_taught: explicitly explained or demonstrated by Vitaly
- observed: directly seen through permitted client data
- verified: checked against a reliable source or successful controlled test
- inferred: reasoned from other records, not directly confirmed
- hypothesis: plausible but unverified

A fact about one world must not silently become a fact about every world. A reusable skill carries its Minecraft version, prerequisites, materials, procedure, validation steps, known failure modes and confidence.

## Configuration validation

The agent resolves `NIKA_DATA`, `NIKA_DATABASE_PATH` and `NIKA_LEARNING_DIR` once from the process environment. Unset values use the documented defaults; explicitly empty values are configuration errors. Paths are expanded and resolved before use.

The CLI checks that the data, logs, backups, runtime and database-parent locations are directories or can be created, and checks access to existing database files. A database outside `NIKA_DATA` is supported but reported as a warning because logs, runtime state and backups remain under `NIKA_DATA`. Invalid configuration fails before logging or database initialization can create or modify files.

Learning assets default to `NIKA_DATA/learning`; `NIKA_LEARNING_DIR` can place them on a deliberately separate volume. The learning tree separates datasets, base models, adapters, checkpoints, experiment runs, caches and exports. It is distinct from conversational SQLite memory: learning weights are not updated for every conversation.

The `migrate-data` operation must run under the runtime maintenance lock. It creates a fresh verified SQLite backup, copies ordinary data files and learning assets, excludes volatile runtime status/lock files, and snapshots the live SQLite database with the online backup API. The staged destination is integrity-checked before it is published. The original source directory is retained until the user verifies the new location.

## Persistence

- SQLite is the initial source of truth for structured local data.
- Schema changes are numbered migrations. Unknown future schema versions must never be downgraded automatically.
- SQLite uses foreign keys, a busy timeout and WAL mode for local concurrency.
- SQLite backups use the online backup API. Restore requires the caller to hold the runtime maintenance lock, validates integrity and exact schema compatibility, captures the previous database plus SQLite sidecars, stages the selected backup beside the target, and swaps it atomically. Failed post-install validation triggers rollback from the retained safety copy.
- NIKA_DATA is outside the Git repository by default.
- Runtime startup uses a Windows named mutex or a POSIX non-blocking file lock, held until its authenticated control endpoint is ready. The operating system releases the primitive automatically if the owning process exits. `start.lock` is only a diagnostic PID marker; it is not the lock authority. Stale status metadata is checked against both the authenticated endpoint and recorded PID; dead-process status is atomically replaced by the next runtime.

### Operational logs

The CLI and background runtime write separate structured JSONL files under
`NIKA_DATA/logs/`. Each file rotates at a bounded size, keeping a fixed
number of prior files.
The formatter redacts known sensitive field names and recognizable credential
formats. Logs are diagnostic records only; SQLite remains the source of truth
for durable events and memory.

## API degradation

External models are optional reasoning providers, not the storage layer or the agent process itself. The provider manager will later expose explicit modes:

- full: provider available within configured budget
- local: provider unavailable; use memory, known skills and deterministic local logic
- limited: insufficient knowledge for the requested task; observe, preserve state and explain the limitation

No component may claim that an unknown task can be solved offline without a matching skill or deterministic procedure.

## Companion visual identity

The in-game avatar for Nika is planned to use the Minecraft model/entity called
"Тихоня". This supersedes the earlier alt-style avatar concept. The renderer
and integration are not implemented yet; this is a recorded art-direction
decision for the future companion model.

## Minecraft integration

The target is a Fabric 1.21.11 client-side mod. Nika's companion rendering is local to Vitaly's client. The mod reports only data legitimately exposed to the client and forwards requests through a versioned localhost protocol. The Python agent independently validates every incoming message and action request.

Protocol versioning, authentication of the local bridge, replay protection, payload limits and safe shutdown are required before enabling world-changing actions.

### Protocol v1: read-only handshake

The first bridge endpoint is `GET /bridge/v1/hello`, bound to IPv4 loopback only.
It accepts an empty request and returns only the service identity, protocol version,
runtime PID/version and the `health.read` capability. It does not read or transmit
Minecraft world data and exposes no chat, memory, or action endpoint.

Each runtime start creates a separate random bridge token. The client reads the
token and ephemeral port from `NIKA_DATA/runtime/status.json`; it never receives
the runtime control token. Requests are authenticated with HMAC-SHA256 over the
uppercase method, exact path, Unix timestamp, random nonce and SHA-256 body hash.
The Python runtime checks a 60-second clock window and rejects each nonce after
its first valid use. The initial endpoint permits no request body. Future event
or action endpoints must define explicit versioned JSON schemas, strict size
limits and capability checks before they are added.

### Observation payload v1 contract

The JSON Schema is maintained at
`docs/schemas/observation-v1.schema.json`. The Python standard-library
validator in `nika.observation` mirrors that contract and rejects duplicate
JSON keys, non-standard numeric constants, non-finite numbers, unknown
properties, unsupported versions and out-of-range values. The encoded body is
limited to 8 KiB.

The payload contains only the client Minecraft/mod versions, current dimension,
player coordinates, health, food level and selected item identifier. It does
not include chat, inventory contents, server address, player identity or other
players. The schema and validator are implemented and tested; no observation
HTTP endpoint or automatic polling is enabled yet. The first live observation
will be an explicit user-triggered snapshot.
