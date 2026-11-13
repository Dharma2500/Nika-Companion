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

## Persistence

- SQLite is the initial source of truth for structured local data.
- Schema changes are numbered migrations. Unknown future schema versions must never be downgraded automatically.
- SQLite uses foreign keys, a busy timeout and WAL mode for local concurrency.
- Backups and restore verification will be implemented before memory is considered production-safe.
- NIKA_DATA is outside the Git repository by default.

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

## Minecraft integration

The target is a Fabric 1.21.11 client-side mod. Nika's companion rendering is local to Vitaly's client. The mod reports only data legitimately exposed to the client and forwards requests through a versioned localhost protocol. The Python agent independently validates every incoming message and action request.

Protocol versioning, authentication of the local bridge, replay protection, payload limits and safe shutdown are required before enabling world-changing actions.
