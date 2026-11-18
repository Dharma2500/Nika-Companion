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

### Minecraft observation v2

A user-triggered `/nika observe` request reads only a compact region around the local player: 5×3×5 positions, limited to already loaded client chunks. The sample records up to 32 non-air blocks, each with its namespaced block ID and at most 12 state properties. The payload also reports the scan count and whether block entries were truncated. The request remains capped at 8 KiB.

The observer reads `BlockState` only. It does not inspect block entities, container inventories, sign text, NBT, chat, other players or hidden server state. There is no automatic polling. The Python validator accepts observation schemas v1, v2 and v3; each event is persisted with its corresponding versioned event type. Future continuous observation must aggregate and deduplicate changes locally before persistence or model context assembly.

### Minecraft observation v3

A user-triggered `/nika observe` retains the v2 block sample and adds a compact environment object: biome at the player's current loaded position, time-of-day ticks, rain/thunder flags and local light level at that same position. It also adds the local player's game mode and one-shot on-ground, sprinting, swimming and crouching flags.

Spatial environment reads are guarded by a loaded-chunk check. Movement is represented as a handful of booleans, not a movement trace. Inventory contents, chat, server identity, other players, entities and block-entity data remain excluded. The payload stays within the same 8 KiB limit, and v1/v2 validation and persistence remain supported.


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

## Conversation and memory storage (schema v2)

SQLite schema v2 preserves the original event, memory, skill and world-fact data.
It adds `conversations` and `conversation_messages` with foreign keys, ordered
history and optional request IDs for idempotent message submission. Existing
memory rows receive a cautious `hypothesis` provenance default; new memory
records can explicitly distinguish `user_taught`, `observed`, `verified`,
`inferred` and `hypothesis`, and can be scoped globally or to an opaque local
world ID.

The typed `MemoryStore` and `ConversationStore` own validation and persistence.
Dialogue code must not issue ad-hoc SQL. Initial keyword retrieval is bounded
and Unicode-aware; semantic embeddings are a later improvement, not a current
capability.

The provider-independent `ContextBuilder` assembles the stable Nika
constitution, recent conversation turns and relevant memories with provenance
and confidence labels. It enforces a hard UTF-8 byte budget. Until a freshness
and world-scope contract is implemented, its `world_context` field is null.
It must never present stale observations as current world state.

The provider adapter in `nika.provider` speaks OpenAI-compatible
`/chat/completions` using only the Python standard library. It reads
`NIKA_LLM_BASE_URL`, `NIKA_LLM_MODEL` and optional `NIKA_LLM_API_KEY`; no
host or model is hard-coded. Requests and responses have strict size limits,
timeouts and sanitized error handling. Fake local-server tests verify the
protocol shape. This does not mean a real model is configured: the actual
LM Studio endpoint and model ID must be checked on the PC running the Nika
runtime before use.

The authenticated `POST /bridge/v1/chat` route is implemented. It
accepts strict schema v1 with a 16 KiB transport bound and a 4,000-character
user-message ceiling, reuses HMAC-SHA256/timestamp/nonce protection, and uses
request IDs for idempotency. User and assistant messages are stored in separate
transactions; provider calls do not hold SQLite write transactions. When no
provider is configured, the route returns a truthful error and does not pretend
that a model response was generated.

Fabric v0.5.1 intercepts ordinary outgoing chat through
`ClientSendMessageEvents.ALLOW_CHAT` only while Nika's private chat mode is
enabled and the local bridge advertises `dialogue.chat`. The message is
canceled before multiplayer server send, forwarded asynchronously to the
loopback bridge, and the reply is displayed locally. A configurable key binding
(default N) switches back to public server chat. Slash commands use their
separate event path and are not intercepted. If the provider is unavailable
before send, the client blocks the ordinary message locally and shows a warning.
The text is never sent to the server while private mode is active; the user must
explicitly press the N toggle to switch to public server chat.
Live Minecraft privacy and input-flow acceptance tests are still required.

## API degradation

External models are optional reasoning providers, not the storage layer or the agent process itself. The provider manager will later expose explicit modes:

- full: provider available within configured budget
- local: provider unavailable; use memory, known skills and deterministic local logic
- limited: insufficient knowledge for the requested task; observe, preserve state and explain the limitation

No component may claim that an unknown task can be solved offline without a matching skill or deterministic procedure.

## Companion visual identity

The in-game avatar for Nika uses the vanilla Minecraft entity called
"Тихоня" (Allay). This supersedes the earlier alt-style avatar concept.

The v0.4.x renderer (current mod v0.5.1) creates a client-side Allay object and submits its
vanilla render state through Fabric's world-render event and Minecraft's entity
render dispatcher. The object is never added to ClientLevel, never synchronized
with a server, and is not visible to other players. AI and gravity are disabled;
the object is a visual-only representation.

Summoning uses /nika and dismissal uses /nika dismiss. The local bridge performs
an authenticated handshake automatically and retries at a bounded five-second
interval, so manual /nika connect is only a diagnostic fallback.

The follow target uses filtered horizontal player displacement, never camera
yaw. While the player moves, Nika tracks to the right and behind the travel
direction. When horizontal movement stops, a world-space idle anchor prevents
her from circling the player when the camera turns. A critically damped integrator with smoothly randomized slow/fast pace phases
smooths position changes and varies follow spacing. Body yaw and head yaw are interpolated independently;
the head can look at the player or make occasional short glances. Small,
infrequent idle offsets keep her gently moving near the anchor without leaving
conversation range. The Allay instance is discarded when the player leaves the
world or changes dimensions.

No custom entity type, server registration, pathfinding, collision, item pickup,
or world interaction is part of this renderer. The milestone remains incomplete
until the Fabric build and live in-game rendering/follow/cleanup checks pass.

## Minecraft integration

The target is a Fabric 1.21.11 client-side mod. Nika's companion rendering is local to Vitaly's client. The mod reports only data legitimately exposed to the client and forwards requests through a versioned localhost protocol. The Python agent independently validates every incoming message and action request.

Protocol versioning, authentication of the local bridge, replay protection, payload limits and safe shutdown are required before enabling world-changing actions.

### Protocol v1: read-only handshake

The first bridge endpoint is `GET /bridge/v1/hello`, bound to IPv4 loopback only.
It accepts an empty request and returns service identity, protocol version,
runtime PID/version and the `health.read` plus `observation.submit` capabilities.
The handshake itself does not read or transmit Minecraft world data. A separate
signed observation endpoint accepts only the bounded v1 snapshot described below.

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
players. The signed `POST /bridge/v1/observe` endpoint accepts the payload only
after HMAC and nonce verification. Python validates the JSON before appending
a `minecraft.observation.v1` event to the local SQLite journal. The client
exposes this through the explicit `/nika observe` command. No automatic
polling, chat transfer or world-changing action is enabled.
