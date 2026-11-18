# Nika-Companion: project continuity context

Last updated: 2026-11-19
Purpose: this file is the authoritative handoff for continuing Nika-Companion after a conversation limit or in a new chat. Read this file first, then inspect the live GitHub branch and PR before editing code.

## 1. Project identity and goals

- Repository: https://github.com/Dharma2500/Nika-Companion
- Visibility: private. Do not make it public.
- Owner/developer: Vitaly (GitHub: Dharma2500).
- Product: a local-first AI companion called Nika for Minecraft and later desktop use.
- In-game avatar: vanilla Minecraft Allay ("Тихоня"), visually represented as Nika.
- Target Minecraft: Java 1.21.11, Fabric client-only mod, Java 21.
- Target loader: Fabric Loader 0.19.5+.
- Current Fabric API baseline: 0.141.6+1.21.11.
- The Python Core owns durable memory and dialogue. The Fabric mod is only a client adapter.
- Local state lives outside Git in NIKA_DATA (the user previously configured D:\NIKA_DATA). Never commit databases, runtime status, bridge tokens, logs, backups, API keys or model files.

## 2. Critical collaboration and delivery rules

1. Work on the existing feature branch and PR. Do not merge to `main` without Vitaly's explicit approval.
2. The repo must stay private.
3. Build the Fabric JAR through GitHub Actions. Do not ask Vitaly to build locally when CI artifact delivery is available.
4. **Never send or link a JAR before the relevant build has completed successfully and the artifact has been published.** Do not close the answer with "the JAR is not ready". Keep working/checking until the real artifact is available. Only then download it, extract the actual JAR, verify the exact file path, and provide the link.
5. Never substitute an older JAR for the requested build.
6. After every substantive assistant answer in the Nika project, update this file on the active GitHub feature branch with current state, decisions, commits, checks, artifacts and next steps. Add a short dated entry to `docs/continuity/CHAT_LOG.md`. This is a structured project handoff, not a promise to preserve unrelated personal conversation.
7. Be explicit about the distinction between CI success and in-game manual verification.
8. PowerShell commands, when needed, must be one line and lowercase only (per Vitaly's preference).
9. Keep answers concise and practical, in Russian, informal "ты". Avoid unnecessary clarifying questions.
10. Use the GitHub Actions build artifact, not a locally guessed path.

## 3. Current source-control state

- Active branch: `feature/companion-renderer-v0.4.0`
- Current PR: #1, https://github.com/Dharma2500/Nika-Companion/pull/1
- PR target: `main`
- PR state: open, draft. Do not merge without approval.
- Main branch has not been changed by the companion-renderer feature work.
- Latest known project commit before this continuity update: `1925276a1e6e1fa294d27f62faffe4a6b87ab3b6`
- Latest delivered mod: v0.4.5.
- v0.4.5 Fabric workflow: https://github.com/Dharma2500/Nika-Companion/actions/runs/44403839400
- v0.4.5 Python CI: https://github.com/Dharma2500/Nika-Companion/actions/runs/44403839669
- v0.4.5 artifact ID: 14472782965, artifact name `nika-companion-fabric-1.21.11`.
- v0.4.5 Fabric build and Python CI completed successfully; all checks passed.
- JAR delivered: `nika-companion-0.4.5.jar` from the Actions artifact.
- Vitaly manually tested v0.4.5 and confirmed the follow distance now varies and movement feels much better. This is the first positive in-game confirmation of inertial pace variation.

After this context file is committed, fetch the branch head again. Do not assume the above SHA remains the newest commit.

## 4. Minecraft companion behavior already implemented

Files:
- `minecraft-mod/src/client/java/ru/vitaly/nika/CompanionRenderer.java`
- `minecraft-mod/src/client/java/ru/vitaly/nika/NikaCompanionClient.java`
- `minecraft-mod/src/client/java/ru/vitaly/nika/BridgeClient.java`

The Allay is local render-only:
- Never inserted into `ClientLevel`.
- Never synchronized to server or visible to other players.
- AI and gravity disabled.
- No collision, item pickup or world interaction.
- Cleared when the player leaves the world or changes dimensions.

v0.4.2 renderer behavior:
- Filtered horizontal player travel direction, not camera yaw.
- Nika follows to the right and behind while moving.
- World-space idle anchor freezes when the player stops; camera turns do not orbit the target.
- Separate smoothed body yaw and head yaw.
- Periodic idle glances and small idle offsets around the anchor.
- `/nika` summons; `/nika dismiss` hides. Cyrillic alias was removed.

v0.4.3 attempted acceleration-limited velocity steering. Vitaly reported that the distance stayed too uniform and movement still appeared jerky.

v0.4.4 replaced that with critically damped follow integration using continuous blocks-per-second velocity and smooth braking. Vitaly still wanted more natural variable distance.

v0.4.5 added low-frequency random follow pace phases:
- Picks a new speed every 45–100 ticks while the player is moving.
- Target follow speed varies from 3.0 to 7.2 blocks/second.
- Actual speed eases toward the new target; it is not randomized every tick.
- When player movement stops, target pace returns smoothly to base speed.
- Vitaly confirmed: "Сейчас намного лучше, действительно меняется расстояние."

Outstanding visual acceptance checks remain: extended camera-turn while idle, dimension/world transition cleanup, and a final overall impression. Do not assume every visual acceptance check is complete merely because follow spacing improved.

## 5. Current Python Core and bridge

Python package:
- `agent/src/nika/database.py`
- `agent/src/nika/event_store.py`
- `agent/src/nika/runtime.py`
- `agent/src/nika/observation.py`
- `agent/src/nika/config.py`

Current persistence:
- SQLite schema version 1.
- Tables: `event_log`, `memories`, `skills`, `world_facts`.
- `EventStore` appends versioned events.
- `memories` table exists but there is not yet a full typed Memory API.
- There is no conversation/session/message table yet.
- There is no ContextBuilder or dialogue pipeline yet.

Runtime/bridge:
- Local HTTP runtime is bound to IPv4 loopback.
- Bridge protocol v1.
- HMAC-SHA256 authentication over method, path, timestamp, nonce and SHA-256 request body.
- Timestamp window and nonce/replay protection.
- Existing routes: signed `GET /bridge/v1/hello` and signed `POST /bridge/v1/observe`.
- Observation endpoint accepts strict bounded v1/v2/v3 schemas; current maximum observation payload is 8 KiB.
- Current capabilities are health/read and observation submit.
- Bridge token is stored locally in `NIKA_DATA/runtime/status.json`, never committed.
- No authenticated chat endpoint and no LLM provider integration have been implemented yet.
- Settings currently cover filesystem paths, not model/provider endpoint or credentials.

Observation:
- User-triggered only via `/nika observe`.
- v3 includes client versions; dimension; bounded loaded-only 5×3×5 block sample (max 32 non-air blocks, 12 properties per block); biome; time-of-day; rain/thunder; local light; game mode; one-shot on-ground/sprint/swim/crouch state.
- No automatic polling, chat capture, inventory dump, block entities, container contents, hidden server state or other-player data.
- Preserve manual-only observation and strict 8 KiB ceiling until the user explicitly approves a separately scoped feature.

## 6. New user requirements and product decisions (2026-11-19)

### Plain-text chat with Nika

Vitaly explicitly does NOT want `/nika ask` or any command/prefix to address Nika. He wants to type ordinary sentences in the Minecraft chat field.

Chat UX design baseline is documented in `docs/memory-dialogue-design.md`:
- When Nika is summoned, local Nika-chat mode activates.
- Ordinary text in the regular chat field is privately routed to the local Python bridge.
- A configurable key binding (initial default N) toggles between private Nika chat and normal server chat.
- In private mode, Nika-directed text is canceled before it can be sent to the multiplayer server.
- Slash commands remain on their separate command path and pass through normally.
- If Nika is hidden or the local bridge is unavailable, do not silently swallow ordinary messages; fall back to normal server chat and show local status.
- Display the current routing mode clearly.
- No prefix such as `!`, `@`, or `/ask` is required.

Fabric API evidence:
- `ClientSendMessageEvents.ALLOW_CHAT` can block an ordinary chat message before it reaches the server.
- Slash commands have their own `ALLOW_COMMAND` event path.
- Source checked: Fabric 1.21.11 message API source and 1.21.11 API index.
- This event is for outgoing client messages. Do not hook incoming player/server chat for the first dialogue milestone.

### Persistent context in GitHub

Vitaly wants a full project handoff saved in GitHub after every assistant answer so work can continue in a new chat after reaching the conversation size limit.
- This file is the primary handoff.
- Keep `docs/continuity/CHAT_LOG.md` as a concise append-only chronological record of decisions, completed work, delivered artifacts and next tasks.
- Update both after every substantive Nika project response.
- The handoff must contain enough context that a fresh assistant can continue without asking Vitaly to repeat requirements.


## 6.1 Nika Intelligence foundation implemented on 2026-11-19

Current implementation is in the same feature branch and PR #1 (still draft). Files:
- `agent/src/nika/database.py`: schema version 2; migration 1 is retained; migration 2 adds conversation tables and provenance/scope/tags columns to memories.
- `agent/src/nika/memory.py`: typed `MemoryStore` and `ConversationStore`.
- `agent/src/nika/context.py`: deterministic `ContextBuilder` with personality constitution, recent history, relevant memories and a 12 KiB UTF-8 byte budget.
- Tests: `agent/tests/test_database.py`, `agent/tests/test_memory.py`, `agent/tests/test_context.py`.
- Design: `docs/memory-dialogue-design.md`; implementation checklist: `docs/roadmap.md`; architecture: `docs/architecture.md`.

Schema v2 details:
- Adds `conversations` and `conversation_messages` with foreign keys, roles, content bounds, metadata and unique request_id.
- Extends `memories` with `provenance_type`, `scope`, `world_id`, `tags_json`.
- Legacy v1 memories are migrated with provenance `hypothesis`, not `user_taught` or `verified`.
- New MemoryInput also defaults to cautious `hypothesis`; explicit `user_taught` must be supplied when origin is known.
- Memory search is currently bounded keyword retrieval (up to 512 candidates) and Python Unicode casefolding; no embeddings yet.
- ConversationStore persists messages, returns chronological recent history, caps user input at 4,000 chars and supports request-id idempotency.
- ContextBuilder uses up to 12 recent messages and 6 relevant memories, drops oldest history/lowest-ranked memories first, and enforces a hard 12 KiB package budget. It explicitly returns `world_context: null` until a freshness/scope contract is implemented.

### Backup compatibility

- `agent/src/nika/backup.py` now accepts supported legacy backup schema v1 and migrates only a staged temporary copy to the current schema before the atomic restore swap.
- Schema v0 and unsupported future schemas are rejected.
- The original selected backup remains unchanged.
- Test `test_restore_migrates_v1_backup_without_modifying_source` creates a v1 SQLite backup with event and memory data, restores it into schema v2, verifies legacy memory provenance defaults to `hypothesis`, and confirms the original backup remains schema v1.

### Validation
- Current branch head before the final continuity refresh: `577d9450b7f1334959304f79fb2c78b57826fd09`.
- Python CI run 44408464677: **success**. All six matrix combinations (Python 3.11, 3.12 and 3.13 on Ubuntu and Windows) passed compile, Ruff lint and tests. Source overlay archive job also succeeded.
- Fabric build run 44408464712: **success**.
- Source overlay artifact ID 14475307885. No new Minecraft JAR was required because this milestone changed Python and documentation, not Fabric mod code. Continue delivering a new JAR only when a new mod build artifact exists.

## 6.2 Provider adapter implemented on 2026-11-19

Files:
- `agent/src/nika/provider.py`
- `agent/tests/test_provider.py`

Implemented:
- `ProviderConfig`, `load_provider_config`, `OpenAICompatibleProvider`, `ProviderManager`.
- Explicit configuration variables: `NIKA_LLM_BASE_URL`, `NIKA_LLM_MODEL`, optional `NIKA_LLM_API_KEY`. No endpoint, model ID or key is hard-coded.
- OpenAI-compatible `POST {base_url}/chat/completions` via Python standard library `urllib`; no additional HTTP package.
- Validates HTTP(S) base URL without embedded credentials, query or fragment.
- Bounds timeout (1–120 sec), model name (160 chars), request body (32 KiB), response body (64 KiB), assistant reply (12,000 chars), tokens (1–4096) and temperature (0–2).
- Sanitizes provider errors; does not include API key, user prompt or raw provider response in diagnostics.
- Adds explicit context instructions treating messages/memories/world observations as data, not instructions that can override Nika's rules.
- Provider tests use a fake local HTTP server; no real model endpoint has yet been configured or tested.
- `ProviderManager` currently wraps one optional provider. Budgets, failover/rotation and full degraded-mode orchestration are still pending.

Validation:
- Code commit introducing the adapter: `87fec3ecb9fd580b0f96e3c689962d6515a70c2e`.
- Python CI run 44409119993: success across Python 3.11, 3.12 and 3.13 on Ubuntu and Windows; compile, Ruff, tests and source overlay passed.
- Fabric build run 44409120014: success. No new JAR was required because this milestone changed only Python and documentation.
- Provider adapter is CI-verified, but a real LM Studio connection is NOT yet verified.

Next: verify the actual LM Studio host and model ID on the machine running Nika. Check the local `/v1/models` endpoint and use its exact model ID. Configure the three environment variables only locally, never in Git. Then implement authenticated `POST /bridge/v1/chat`, persist the user message before model work, assemble ContextBuilder output, persist the assistant reply and return it to the Fabric client. Finally implement ordinary private chat using Fabric's outgoing-chat allow event, a configurable key binding to toggle public server chat, local-only replies and slash-command passthrough.

## 7. Next development milestone: Nika Intelligence 0.5.x

Do not jump straight to voice. Build the deterministic foundation first.

### Step 1: database schema migration 2
- Keep all v1 data intact.
- Add `conversations` and `conversation_messages` tables.
- Add provenance and scope columns to existing `memories`: provenance type (`user_taught`, `observed`, `verified`, `inferred`, `hypothesis`), scope (`global` or `world`), optional world_id, bounded tags.
- Add constraints, indexes, foreign keys, safe migrations and tests.
- Never label old memories as verified by default.

### Step 2: typed storage APIs
- ConversationStore: create/get conversation, append message idempotently, fetch recent messages chronologically.
- MemoryStore: add/get/search/list memories with strict validation, confidence, provenance and world scope.
- Do not embed arbitrary SQL inside runtime handler code.

### Step 3: ContextBuilder
- Provider-independent, deterministic structured output.
- Sections: Nika personality constitution, last 12 turns, up to 6 relevant memories with provenance/confidence labels, and only fresh/scope-valid world context.
- Hard context budget and content truncation rules.
- Never claim current world knowledge from stale observations.

### Step 4: provider manager
- OpenAI-compatible adapter design, local LM Studio as first candidate only after verifying the endpoint/model on the actual Nika machine.
- No model endpoint or model name is assumed yet.
- Timeouts, bounded responses, offline diagnostics, no fake AI response.

### Step 5: authenticated dialogue route
- Add strict, versioned `POST /bridge/v1/chat` with HMAC/replay protection.
- Suggested body limit: 16 KiB, user text ceiling 4,000 Unicode characters.
- Persist user message before provider call, never hold a write transaction across a network call.
- Persist assistant answer after validation.
- Client-generated request ID provides idempotency in addition to nonce replay protection.
- Do not log chat bodies.

### Step 6: Fabric plain-chat routing
- Implement `ClientSendMessageEvents.ALLOW_CHAT` in Nika-chat mode.
- Intercept ordinary messages only, cancel network send, queue bridge call asynchronously.
- Keep slash commands untouched.
- Display local conversation and assistant reply in Minecraft chat.
- Configurable key binding toggles local Nika chat vs server chat.
- No ordinary text is sent to the multiplayer server while private routing mode is enabled.

### Step 7: manual acceptance
- Plain sentence reaches Nika without slash/prefix.
- Message is not visible to server/other players.
- Reply appears locally in chat.
- Keybind restores normal public chat.
- Slash commands still work.
- Bridge offline does not swallow text.
- Long/empty/repeated messages are handled safely.
- World transition resets only session context where appropriate.
- No chat text appears in diagnostics logs.

Voice input/output and proactive initiative follow only after text dialogue is reliable. No world-changing actions until capability validation, approval gates, emergency stop and disposable-world tests exist.

## 8. Known issue to address before next Fabric release

`NikaCompanionClient.java` currently appears to contain a hard-coded `MOD_VERSION = "0.4.2"` while Gradle's `mod_version` and delivered artifact are v0.4.5. Correct this before the next Fabric JAR, ideally derive the runtime version from generated Fabric metadata or keep the constant in sync with `mod_version`.

## 9. Immediate next actions

1. Check active branch head, PR #1 and Actions state before editing.
2. Verify LM Studio is reachable on the actual PC running the Nika Python runtime; request the exact model ID from the local `/v1/models` endpoint.
3. Configure `NIKA_LLM_BASE_URL`, `NIKA_LLM_MODEL`, and optional `NIKA_LLM_API_KEY` locally. Never commit the key.
4. Add a provider diagnostic command/report that does not expose credentials or chat content.
5. Implement authenticated `POST /bridge/v1/chat` with strict schema, 16 KiB payload bound, 4,000-char user message ceiling, HMAC/replay checks and request-id idempotency.
6. Persist the user message before provider work, call ContextBuilder and ProviderManager outside write transactions, then persist and return the assistant reply.
7. Implement Fabric ordinary chat interception: local private mode while Nika is summoned, configurable key binding (default N) for public server chat, slash commands untouched, visible routing status, local-only reply display and automatic fallback to server chat if bridge is unavailable.
8. Fix hard-coded `MOD_VERSION = "0.4.2"` in `NikaCompanionClient.java` before the next Fabric JAR; preferably derive it from Fabric metadata.
9. Update this file and `CHAT_LOG.md` after each substantive Nika project response.
