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

- Repository: private Dharma2500/Nika-Companion. Keep it private.
- Active branch: feature/companion-renderer-v0.4.0.
- PR #1: https://github.com/Dharma2500/Nika-Companion/pull/1
- PR title: Nika Companion v0.5.0: private plain-text chat and intelligence foundation (draft).
- PR target main; open and draft. Do not merge without Vitaly's explicit approval.
- Main remains unchanged.
- Branch head before this continuity refresh: aee1198da156306bcb660528a40588f452fe299b.
- Minecraft mod version: v0.5.0. Gradle mod_version and runtime MOD_VERSION are both 0.5.0.
- Fabric build run 44413370724: success; artifact ID 14478771154, artifact name nika-companion-fabric-1.21.11.
- Python CI run 44413370413: success; all six Python 3.11/3.12/3.13 Windows/Ubuntu jobs, Ruff, tests and source overlay passed.
- Delivered JAR: nika-companion-0.5.0.jar. It was downloaded from the successful Actions artifact and verified to contain NikaChatClient.class, updated BridgeClient.class and Fabric metadata version 0.5.0.
- JAR SHA-256: 8fcc2912fa894cbeb8c85b49d81e57067191860331f6c8fc901ad3cb0707ef62.
- Verified local assistant-container path: /mnt/data/nika-companion-0.5.0.jar.
- Artifact expiry: 2026-12-02.
- Vitaly confirmed v0.4.5 follow spacing varies and movement feels much better.
- v0.5.0 has passed CI/build but still needs manual Minecraft privacy/input-flow acceptance and real LM Studio configuration. CI success does not prove live multiplayer privacy.

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

Main Python files:
- agent/src/nika/database.py
- agent/src/nika/event_store.py
- agent/src/nika/runtime.py
- agent/src/nika/observation.py
- agent/src/nika/config.py
- agent/src/nika/memory.py
- agent/src/nika/context.py
- agent/src/nika/provider.py
- agent/src/nika/dialogue.py

### Persistence, memory and context
- SQLite schema version 2.
- Tables: event_log, memories, skills, world_facts, conversations, conversation_messages.
- Migration v1 remains intact; migration v2 adds conversation history and memory provenance/scope/tags.
- Legacy v1 memories receive cautious provenance hypothesis, never automatically verified or user_taught.
- MemoryStore: add/get/recent/search, confidence/provenance/tags validation, global/world scope, bounded keyword candidates and Python Unicode casefold() for Russian case-insensitive matching.
- ConversationStore: create/get conversation, append user/assistant/system messages, recent chronological retrieval, request_id idempotency and bounded metadata/content.
- User message limit 4,000 characters; assistant/system 12,000. Metadata 4 KiB.
- ContextBuilder: stable Nika constitution, up to 12 recent turns, up to 6 relevant memories with provenance/confidence, hard 12 KiB UTF-8 budget. Old history and low-ranked memories are trimmed first.
- ContextBuilder returns world_context null until observation freshness/scope checks exist. Never claim stale observation is live world state.
- Legacy schema-v1 backups are migrated only on a staged temporary copy to schema v2 before atomic restore; original backup remains unchanged.

### Provider adapter
- agent/src/nika/provider.py: ProviderConfig, load_provider_config, OpenAICompatibleProvider, ProviderManager.
- Environment: NIKA_LLM_BASE_URL, NIKA_LLM_MODEL, optional NIKA_LLM_API_KEY. No endpoint, model or credential is committed or hard-coded.
- OpenAI-compatible POST {base_url}/chat/completions via Python standard library urllib; no third-party HTTP dependency.
- Bounds: HTTP(S) URL validation; timeout 1–120 sec; request 32 KiB; response 64 KiB; assistant reply 12,000 characters; max_tokens 1–4096; temperature 0–2.
- API key, prompts and provider response bodies are not logged. Provider failures are sanitized.
- Fake local HTTP-server tests cover config parsing, request body, response parsing, HTTP errors, oversized bodies and missing provider.
- ProviderManager currently wraps one optional provider. Budgets, failover/rotation and full degraded-mode orchestration are not implemented.
- Actual LM Studio endpoint and exact model ID on the PC running Nika have NOT been verified/configured. Do not assume localhost/model IDs until checked on that PC.

### Runtime and authenticated bridge
- Local HTTP runtime is bound to IPv4 loopback.
- Bridge protocol v1; HMAC-SHA256 over method, exact path, timestamp, nonce and SHA-256 request body, with timestamp window and nonce/replay protection.
- Routes: signed GET /bridge/v1/hello, signed POST /bridge/v1/observe, signed POST /bridge/v1/chat.
- Observation endpoint accepts strict bounded v1/v2/v3 schemas; maximum payload 8 KiB.
- Chat endpoint POST /bridge/v1/chat:
  - Strict schema v1, duplicate/unknown JSON field rejection, canonical UUIDs, UTF-8 checks.
  - Maximum request body 16 KiB, user text 4,000 characters.
  - Reuses HMAC/timestamp/nonce replay protection.
  - Persists user message first, calls ContextBuilder/ProviderManager outside SQLite write transactions, then persists assistant reply.
  - User and assistant request IDs are unique. Repeated request with same ID/content returns cached assistant reply without another model call; same ID with different content returns HTTP 409.
  - No provider configured returns HTTP 503 before persisting user message; provider failure returns sanitized 503.
  - Message text is never included in runtime diagnostics logs.
- Hello response advertises dialogue.chat only when provider settings loaded successfully at runtime startup.
- Bridge token lives in NIKA_DATA/runtime/status.json; never commit.
- Provider environment changes require restarting the Python runtime so capability state is recalculated.

### Minecraft client chat adapter
- NikaChatClient.java intercepts outgoing ordinary chat with Fabric ClientSendMessageEvents.ALLOW_CHAT.
- It cancels only when Nika private mode is active, Nika is summoned, and bridge handshake advertises dialogue.chat.
- User message echo and assistant reply are displayed locally only.
- Key binding default N toggles private Nika chat vs public server chat; configurable in Controls. Presses while another screen/chat input is open are discarded to avoid eating a typed N.
- /nika summons and enables private mode; /nika dismiss hides Nika and disables private mode. Slash commands remain on their separate command event path.
- If bridge/provider is unavailable before send, ordinary text falls back to server chat with a local warning. If a request fails after interception, local error says the message was not sent to server.
- Conversation UUID is local to the current client-world session and resets when client level changes.
- No incoming chat capture, player/server messages, inventory, block entities, containers, hidden state or other-player data are collected.

### Observation boundary
- User-triggered only via /nika observe.
- v3 includes client versions; dimension; bounded loaded-only 5×3×5 block sample (max 32 non-air blocks, 12 properties per block); biome; time-of-day; rain/thunder; local light; game mode; one-shot on-ground/sprint/swim/crouch state.
- No automatic polling. Keep manual-only observation and strict 8 KiB ceiling until separately approved.

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

Next: verify the actual LM Studio host/model ID on the PC running Nika, configure environment variables locally, restart runtime and confirm hello advertises dialogue.chat. Then test v0.5.0 private chat in Minecraft: no server leakage while capability is available, N toggles public server chat, slash commands pass through, and provider-offline mode falls back to server chat with a local warning.

## 6.3 Authenticated plain-text chat implemented in v0.5.0 (2026-11-19)

User requirement: Vitaly addresses Nika by writing ordinary text in the Minecraft chat field. No /nika ask, slash command or per-message prefix.

Files:
- Python: agent/src/nika/dialogue.py, agent/src/nika/runtime.py, agent/src/nika/memory.py.
- Tests: agent/tests/test_dialogue.py, agent/tests/test_chat_bridge.py, plus memory/context/provider tests.
- Fabric: minecraft-mod/src/client/java/ru/vitaly/nika/BridgeClient.java, NikaChatClient.java, NikaCompanionClient.java.
- Translations: minecraft-mod/src/main/resources/assets/nika_companion/lang/en_us.json and ru_ru.json.

Behavior:
- /nika summons Nika and activates private mode.
- Type normal text in Minecraft chat. Fabric intercepts ordinary outgoing chat only when bridge capability dialogue.chat is available. It cancels server transmission, forwards to the local Python bridge and displays the reply locally.
- Press N (configurable in Controls) to switch private Nika chat vs public server chat.
- /nika dismiss hides Nika and returns routing to public server chat.
- Slash commands remain untouched.
- If provider/bridge is unavailable before send, normal text falls back to server chat with a local warning. If a request fails after private interception, local error explicitly says it was not sent to server.
- Chat route is authenticated and idempotent; message text is not written to runtime logs.
- Private mode and provider availability are separate: a real LM Studio endpoint/model must still be configured on the target machine.

CI and delivery:
- Fabric build run 44413370724: success.
- Python CI run 44413370413: success. All six Python 3.11/3.12/3.13 Windows/Ubuntu jobs and source overlay passed.
- JAR artifact ID 14478771154.
- Delivered JAR v0.5.0 SHA-256 8fcc2912fa894cbeb8c85b49d81e57067191860331f6c8fc901ad3cb0707ef62.
- In-game private-routing/privacy behavior has NOT yet been manually tested.

## 7. Next development tasks after v0.5.0

Do not move to voice yet. First connect a real local model and verify privacy/input flow in Minecraft.

1. Verify the LM Studio base URL on the PC running the Nika Python runtime. Query its local /v1/models endpoint and use the exact model ID returned.
2. Configure NIKA_LLM_BASE_URL, NIKA_LLM_MODEL and optional NIKA_LLM_API_KEY locally only. Never commit credentials. Restart the Python runtime after changing values.
3. Run an end-to-end chat request and ensure hello advertises dialogue.chat.
4. Manual Minecraft 1.21.11 acceptance:
   - invoke /nika;
   - send ordinary text without prefix;
   - verify the text and answer are not visible to other players/server;
   - press N and verify messages go to public server chat;
   - verify slash commands still work;
   - stop provider/bridge and verify clear public fallback warning;
   - test long text, repeated send and world/dimension transition.
5. Improve provider manager budgets, failover/rotation and safe offline diagnostics.
6. Add explicit memory teaching/review UX. Do not silently promote model-generated statements to durable memories.
7. Only after text dialogue and memory are reliable, add voice input/output and context-aware initiative.
8. No autonomous world-changing actions until capability validation, explicit approval gates, emergency stop and disposable-world regression tests exist.

## 9. Immediate next actions

1. Verify the actual LM Studio endpoint and exact model ID on the PC running the Python runtime. Do not guess.
2. Configure NIKA_LLM_BASE_URL, NIKA_LLM_MODEL and optional NIKA_LLM_API_KEY locally; restart runtime and check hello capability dialogue.chat.
3. Install and manually test nika-companion-0.5.0.jar on Minecraft 1.21.11 using a disposable/private test world or trusted server.
4. Test no server leakage, N key toggle, slash commands, provider-offline fallback, duplicate messages and world transitions.
5. If issues are found, inspect them and fix on the feature branch.
6. Update this handoff and CHAT_LOG.md after every substantive Nika project response.

