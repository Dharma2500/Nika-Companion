# Nika-Companion project chat log

Chronological project decisions and delivery milestones. The authoritative current state is in [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md).

## 2026-11-18 to 2026-11-19: companion movement iterations

- v0.4.2 improved independent body/head rotation, idle glances, idle wander and filtered movement direction. The Cyrillic `/ника` alias was removed.
- v0.4.3 introduced acceleration-limited velocity steering. Vitaly reported that Nika still followed at a fixed-feeling distance and jerked.
- v0.4.4 replaced steering with a critically damped spring and continuous blocks-per-second velocity. The behavior still needed more natural distance variation.
- v0.4.5 added slow random pace phases: speed target changes every 45–100 ticks between 3.0 and 7.2 blocks/second, with gradual easing. Fabric build and Python CI passed.
- Artifact v0.4.5 was delivered from GitHub Actions artifact 14472782965.
- Vitaly manually confirmed that spacing now varies and the movement is much better.

## 2026-11-19: Nika Intelligence planning

- Vitaly wants ordinary unprefixed text in the Minecraft chat field to address Nika. Do not implement `/nika ask` or any required per-message prefix.
- Chat privacy matters: local Nika-chat mode consumes ordinary text before it reaches the multiplayer server. A configurable key binding switches to normal server chat. Slash commands remain untouched.
- Vitaly requests that this GitHub project handoff and concise chat log be updated after every assistant answer so a new chat can resume after context limits.
- Inspected current database/runtime: SQLite schema v1 already includes `memories`, `skills`, `world_facts`, and `event_log`; no conversation table, Memory API, ContextBuilder, LLM provider or chat endpoint exists yet.
- Created design baseline in `docs/memory-dialogue-design.md`.
- Next: schema migration v2, ConversationStore, MemoryStore, ContextBuilder, tests, then local provider and authenticated chat route. Voice remains deferred.
