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

## 2026-11-19: memory and context foundation implementation

- Added SQLite migration v2 with `conversations`, `conversation_messages`, memory provenance/scope/tags. Existing v1 memory rows migrate to cautious `hypothesis`.
- Added typed `MemoryStore` and `ConversationStore`; conversation messages support idempotent request IDs.
- Added deterministic `ContextBuilder` with Nika constitution, up to 12 recent turns, up to 6 relevant memories, a hard 12 KiB UTF-8 budget and no stale world context.
- Memory keyword retrieval is bounded and Unicode-casefolded, including Russian text.
- Updated architecture, roadmap, README and the project continuity handoff.
- Plain Minecraft dialogue still remains unimplemented: no local provider integration, no `/bridge/v1/chat`, no client chat interception yet. The user requirement remains ordinary unprefixed text, private routing by default while Nika is summoned, keybind toggle for server chat, and slash commands untouched.
- Current validation is running on the latest feature branch head. Check GitHub Actions before calling the milestone green.

## 2026-11-19: legacy backup compatibility and green CI

- Fixed schema-v1 backup restore after the SQLite database moved to schema v2. Restore validates the legacy backup, copies it to a temporary staging file, migrates that copy with the normal database migrations, checkpoints WAL and switches to DELETE journal mode before atomic replacement.
- The original selected backup file remains unchanged. Schema 0 and future unsupported versions are rejected.
- Added regression test covering legacy event and memory preservation, cautious `hypothesis` provenance on migrated memory, schema-v2 active database and unchanged schema-v1 source backup.
- Current validation at branch head `577d9450b7f1334959304f79fb2c78b57826fd09`: Python CI 44408464677 passed all six Python/OS matrix jobs and source overlay; Fabric build 44408464712 passed.
- No new JAR is produced for this milestone because the Fabric client code did not change.
- Next: provider-independent OpenAI-compatible adapter with explicit configuration and fake-server tests; then authenticated chat route; then Fabric private unprefixed text chat. Verify the actual LM Studio host/model on the Nika runtime PC before setting values.

## 2026-11-19: OpenAI-compatible provider adapter

- Added `agent/src/nika/provider.py` with `ProviderConfig`, `load_provider_config`, `OpenAICompatibleProvider` and `ProviderManager`.
- Configuration is explicit and local-only: `NIKA_LLM_BASE_URL`, `NIKA_LLM_MODEL`, optional `NIKA_LLM_API_KEY`. No endpoint/model/key is hard-coded.
- Uses Python standard library HTTP client and standard `/chat/completions`; no third-party runtime dependency.
- Enforces URL validation, 1–120 sec timeout, 32 KiB request, 64 KiB response, 12,000-character reply limit, token/temperature bounds and sanitized errors. No prompts, model responses or keys are logged.
- Added fake-local-server tests for config, request shape, successful response parsing, HTTP failure sanitization, oversized response and honest no-provider status.
- CI for code commit `87fec3ecb9fd580b0f96e3c689962d6515a70c2e`: Python CI 44409119993 successful across Python 3.11/3.12/3.13 on Ubuntu and Windows; lint/tests/source overlay successful. Fabric build 44409120014 successful.
- No new JAR was built or sent because Fabric client code did not change.
- Real LM Studio connection is not yet tested. Next: verify actual host and model ID on the PC running Nika, then configure local environment variables, implement authenticated `POST /bridge/v1/chat`, and finally route ordinary unprefixed Minecraft chat privately to Nika with a keybind back to public server chat. Slash commands must remain untouched.
