# Nika Companion — durable project context / handoff

Last updated: 2026-11-19
Repository: `Dharma2500/Nika-Companion` (private)
Active development branch: `feature/companion-renderer-v0.4.0`
Current draft PR: #1, targeting `main`
Current Fabric target: **0.5.1**
This file is the canonical handoff for a new ChatGPT conversation. Read it before changing code. Update it after every substantive project answer/implementation turn. Never store secrets, API keys, local databases, chat contents or private world snapshots here.

## 1. Product goal

Nika is Vitaly's local-first AI companion for Minecraft and outside the game. In Minecraft she appears as the vanilla Allay (Тихоня), rendered only on Vitaly's client. Long-term goal: a persistent companion with a stable personality, local memory, text/voice dialogue, relevant initiative and eventually carefully permissioned skills. The project must remain honest about what Nika can observe or do.

Core boundaries:
- Python Core owns durable memory, dialogue orchestration, provider access and policy.
- Fabric client mod is a client adapter for presentation, user chat routing and explicitly permitted observations.
- SQLite is the local source of truth. User data lives outside Git in `NIKA_DATA`.
- Python/AI must never execute arbitrary shell commands or modify Minecraft in this dialogue milestone.
- No anti-cheat bypass, hidden server-state reads, unauthorized server actions, automatic inventory/chat/player collection or world-changing actions.
- User messages intended for private Nika chat must not leak to multiplayer chat.

## 2. User decisions and workflow rules

- Communicate in Russian, casually using «ты». Be concise, technically rigorous and honest.
- The Minecraft dialogue UX is **ordinary unprefixed chat**. The user opens the normal chat input and writes a message naturally. No `/nika ask`, no slash command, no per-message prefix or keyword.
- `/nika` remains the summon utility command; `/nika dismiss`, `/nika status`, `/nika connect` and `/nika observe` remain utility/diagnostic commands.
- While Nika is summoned, private Nika chat mode starts enabled. Key binding **N** (configurable in Minecraft Controls) toggles between private Nika chat and public server chat. Slash commands must remain unaffected.
- **Fail-closed privacy:** while private Nika mode is active, ordinary messages must never be sent to the server. If the local Bridge/provider is unavailable, block the message locally and show a clear warning. The user must explicitly press N to switch to public server chat. Do not silently fall back to server chat.
- Voice is deferred until text dialogue and memory pass acceptance.
- After each substantive assistant answer about this project, update this file in GitHub with the latest decisions, branch/PR, code state, test state and exact next actions. This is the recovery point if the chat context reaches its limit. Do not merely paste a one-line summary.
- When a new JAR is requested or expected, provide it only after Fabric build succeeds and the artifact has been uploaded and verified. Do not send an old JAR in place of a new build.
- Never merge PR #1 without Vitaly's explicit approval and required manual checks.
- For PowerShell snippets, user prefers a single line, lowercase only. Avoid unnecessary PowerShell commands.

## 3. Technical architecture

### Python agent
Package root: `agent/src/nika/`
- `database.py`: SQLite migrations, currently schema v2.
- `event_store.py`: append-only local event journal.
- `memory.py`: typed `MemoryStore` and `ConversationStore`.
- `context.py`: deterministic, bounded `ContextBuilder`.
- `dialogue.py`: strict chat request schema/validation.
- `provider.py`: OpenAI-compatible provider adapter and minimal ProviderManager.
- `runtime.py`: local runtime, authenticated loopback HTTP bridge, observation and private chat routes.
- `backup.py`, `migration.py`, `config.py`, `logging_setup.py`: local data lifecycle, configuration and diagnostics.
- Tests: `agent/tests/`; GitHub Actions Python matrix uses Python 3.11/3.12/3.13 on Ubuntu and Windows plus Ruff.

### Persistence / memory
SQLite v2 preserves schema-v1 records and adds:
- `conversations`
- `conversation_messages` with FK, role, source, metadata and unique request ID for idempotency
- memory provenance: `user_taught`, `observed`, `verified`, `inferred`, `hypothesis`
- memory scope: `global` or `world`, plus opaque local world ID
Legacy memories use cautious `hypothesis` provenance. Do not falsely relabel old records as user-taught or verified.
MemoryStore supports add/get/list/search with validation, confidence, provenance, tags and world scope. Initial search is bounded keyword matching with Python Unicode casefolding; semantic/embedding retrieval is not implemented.
ConversationStore supports create/get/append and recent chronological history; request IDs provide idempotency.
ContextBuilder defaults to recent history (12 messages), relevant memories (up to 6) and a strict 12 KiB UTF-8 byte budget. It trims oldest history first, then low-ranked memories. `world_context` is intentionally null until a freshness and scope contract exists. Do not pretend it knows current Minecraft world state.

### Provider
- `NIKA_LLM_BASE_URL`
- `NIKA_LLM_MODEL`
- optional `NIKA_LLM_API_KEY`
The provider uses the Python standard library and OpenAI-compatible `/chat/completions`. It has strict timeouts and request/response/reply bounds and sanitized errors. The real LM Studio endpoint and exact model ID on the PC running Nika's Python runtime have **not** yet been verified/configured in this project. Do not hard-code a host/model or copy credentials into Git.
ProviderManager currently handles a single optional provider; budgets, rotation/failover and richer diagnostics remain future work.

### Local bridge / chat transport
- Runtime listens on IPv4 loopback only.
- Protocol v1 handshake and observation routes already use per-runtime bridge token, HMAC-SHA256, timestamp window and one-use nonce/replay protection.
- Authenticated chat endpoint: `POST /bridge/v1/chat`.
- Request schema v1: canonical UUID request_id and conversation_id, message text, max 4,000 Unicode characters, max 16 KiB JSON body, strict UTF-8, duplicate-key and unknown-field rejection.
- Chat request HMAC uses exact method/path/timestamp/nonce/body hash. Chat path is allowed by BridgeAuthenticator and replay protection.
- Runtime advertises `dialogue.chat` only when a provider was explicitly configured at startup.
- User turn is persisted before provider call; provider call is outside SQLite write transactions; assistant turn is persisted after valid provider reply. Request IDs provide idempotent retries. Chat bodies are not written to diagnostic logs.
- If no provider is configured, runtime returns 503 before recording a user turn.
- Fabric `BridgeClient` sends chat asynchronously via a single-thread executor, signs requests and validates bounded responses.

## 4. Minecraft client mod

Target: Minecraft Java 1.21.11, Fabric Loader 0.19.5+, Fabric API 0.141.6+1.21.11, Java 21.
Key files:
- `minecraft-mod/src/client/java/ru/vitaly/nika/NikaCompanionClient.java`
- `minecraft-mod/src/client/java/ru/vitaly/nika/CompanionRenderer.java`
- `minecraft-mod/src/client/java/ru/vitaly/nika/NikaChatClient.java`
- `minecraft-mod/src/client/java/ru/vitaly/nika/BridgeClient.java`
- language keys: `minecraft-mod/src/main/resources/assets/nika_companion/lang/en_us.json`, `ru_ru.json`
Version fields to keep in sync:
- `minecraft-mod/gradle.properties` `mod_version`
- `NikaCompanionClient.java` `MOD_VERSION`
- `.github/workflows/fabric-build.yml` artifact JAR path
- README build artifact path

### Visual companion baseline (v0.4.5)
- Allay instance is client-only render-only; never inserted into ClientLevel, never synchronized, no AI/gravity/collision/item pickup/world interactions.
- `/nika` summons; `/nika dismiss` hides.
- Head/body rotations independently smoothed; idle glances and small wander offsets.
- Follow uses critically damped position integrator, a filtered player travel direction and smooth randomized slow/fast pace phases (roughly 3.0–7.2 blocks/s, new target every few seconds with easing).
- Vitaly manually confirmed the follow spacing now varies and the movement is much better. Further manual acceptance remains for camera/idle/world transitions.

### Plain-text Nika chat (first shipped in v0.5.0; privacy fix in v0.5.1)
- `NikaChatClient.initialize()` registers Fabric `ClientSendMessageEvents.ALLOW_CHAT` and configurable key binding N.
- Summoning Nika enables private mode; dismiss disables it.
- Ordinary chat messages in private mode are intercepted without a slash prefix, echoed locally and submitted via BridgeClient. The AI reply is shown only in local client chat.
- Slash commands are separate and pass through.
- Public server chat is explicit: press N to toggle out of private mode.
- **v0.5.1 change:** if Bridge/provider is unavailable while private mode is active, ordinary chat is canceled locally with an error. It is not sent to the server. The user must press N to send to the server.
- Conversation UUID is local to the current client-world session and resets when ClientLevel changes.
- `/nika status` reports chat routing state. N key binding is configurable in Controls.
- Do not reintroduce "offline -> public chat" implicit fallback. That would leak private text.

## 5. Previous verified milestones

- Python core, SQLite schema v1/event journal, local runtime and Windows/Linux CI.
- SQLite backup/restore and data migration with preservation/rollback guards.
- Observation schemas v1/v2/v3, manual `/nika observe`, strict Python validation and local persistence. Only explicitly user-triggered, bounded snapshots. No automatic observation polling.
- HMAC bridge handshake and observation with replay protection.
- Nika renderer v0.4.5 manual in-game feedback accepted for follow spacing variation.
- Fabric v0.5.0 chat+memory foundation had a successful build and Python CI:
  - Fabric workflow run: `44413370724`, success, artifact ID `14478771154`.
  - Python CI run: `44413370413`, success across six Python/OS matrix jobs, Ruff, tests and source overlay.
  - That artifact is historical v0.5.0 only. Do not use it as v0.5.1.
- A docs-only commit `2b60bcf...` later showed a GitHub Actions failure on all matrix jobs and Fabric build; no useful job logs were available from the connector. The preceding code commit `8d6d668...` had passed. Treat this as unexplained/transient until the current head CI proves otherwise.

## 6. Current branch / PR state

- Private repo: `Dharma2500/Nika-Companion`
- Active branch: `feature/companion-renderer-v0.4.0`
- PR #1 draft: `Nika Companion v0.5.1: private plain-text chat and intelligence foundation`, base `main`.
- Do not merge automatically. Keep all development on the feature branch.
- Current intended mod release after fail-closed privacy fix: **v0.5.1**.
- Current branch head (at latest handoff refresh): `afbd5ff6b043634334f4b3d6bc0f809fe01f7fb0`.
- v0.5.1 code and version fields are in sync: `MOD_VERSION=0.5.1`, `gradle.properties mod_version=0.5.1`, Fabric artifact path `nika-companion-0.5.1.jar`.
- Fail-closed private chat is implemented in `NikaChatClient.java`: when bridge/provider is unavailable, ordinary message returns `false` and is not sent to the server; local warning instructs Vitaly to press N to switch explicitly to server chat.
- Added backend test `test_bridge_chat_without_provider_does_not_persist_user_message` in `agent/tests/test_runtime.py`; it expects authenticated `/bridge/v1/chat` to return 503 without persisting the user turn if provider is not configured.
- Latest changes on branch:
  - `NikaChatClient.java` uses fail-closed private chat behavior.
  - `agent/tests/test_runtime.py` adds a test that an authenticated chat request with no provider returns 503 without persisting a user message.
  - `docs/architecture.md`, `docs/roadmap.md`, `docs/memory-dialogue-design.md` and READMEs are being aligned to fail-closed behavior.
  - Gradle and Fabric workflow artifact path are set to 0.5.1.
  - `NikaCompanionClient.java` reports MOD_VERSION 0.5.1.
- Confirm current branch HEAD and PR head from GitHub before updating; the branch has had overlapping sequential commits and one GitHub 409 conflict. Always fetch the latest file SHA immediately before each update_file call. Never reuse a stale SHA.

## 7. Release and verification rules

JAR may be delivered only when all are true:
1. Fabric GitHub Actions build run for the current head completed with conclusion `success`.
2. Artifact exists and is not expired.
3. Artifact ZIP is downloaded and contents verified to include the exact current-version JAR.
4. Link points to the extracted JAR, not an old artifact or source archive.
Python CI should also pass for the current head before calling the milestone verified.
Do not claim CI success from a previous commit as validation of the current version.
Do not claim that in-game behavior is proven by CI.

Manual Minecraft 1.21.11 acceptance checklist for plain private chat:
1. Run Python Nika runtime with a configured, reachable local LM Studio model.
2. Enter world and run `/nika`; local private chat becomes active.
3. Type an ordinary message in Minecraft chat. No slash command or prefix. Confirm local user echo and local Nika reply.
4. Confirm the typed message and reply do not appear in server/global chat and other players cannot see them.
5. Press N outside chat input to toggle public server chat; ordinary message now reaches server.
6. Press N again; private mode is active.
7. Try `/nika status`, `/nika observe`, other slash commands; ensure commands still work.
8. Stop Python runtime or remove provider config while private mode is active. Type a message: it must be blocked locally and never sent to server; N must explicitly switch to public.
9. Force a provider/network error after a message is intercepted: show a local error; never retry by sending to multiplayer server.
10. Change dimension/world; conversation ID resets and chat mode behavior remains explicit.
11. Retry the same chat request ID in backend test; no duplicate model completion/message persistence.

Visual companion acceptance still required:
- idle camera turn: fixed world-space anchor; no orbit
- occasional idle gestures and glances
- follow spacing/pace variance, start/stop/turn smoothing
- dismiss and dimension/world cleanup

## 8. Next work (priority order)

1. v0.5.1 fail-closed private chat safety patch is implemented; current CI is blocked before runner allocation and must be rerun successfully before JAR delivery.
2. Update PR #1 description and this context file with exact latest commit/run/artifact state.
3. On Vitaly's PC, configure and verify actual LM Studio URL/model ID using local environment only. Do not ask user to paste API keys.
4. Manual Minecraft acceptance of private chat and no server leakage, especially provider-offline behavior.
5. Improve provider diagnostics, budgets/failover and stable Nika personality/fallbacks.
6. Add explicit user-controlled memory teaching/review (e.g. only save when Vitaly says "запомни" and confirm stored fact); never promote every model output automatically.
7. Add fresh, scoped world observation context only after a freshness/scope contract.
8. Voice only after text dialogue and memory are reliable.
9. Skills/planning/permissioned actions much later; no autonomous world-changing behavior until action auth, capability checks, approval gates, emergency stop and disposable-world tests exist.

## 9. Secrets and local configuration

Never write these to Git or this handoff:
- `NIKA_LLM_API_KEY`
- bridge tokens from `NIKA_DATA/runtime/status.json`
- local SQLite databases/backups, message content, logs, world snapshots, account/server identity.
Local environment names only: `NIKA_LLM_BASE_URL`, `NIKA_LLM_MODEL`, optional `NIKA_LLM_API_KEY`.
The local data directory is outside repository; never migrate it or change its schema without a migration/backup plan.
