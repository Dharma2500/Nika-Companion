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

## 2026-11-19: Nika Companion v0.5.0 private plain-text chat

- Added strict private chat request schema v1 in `agent/src/nika/dialogue.py`: canonical UUIDs, duplicate/unknown field rejection, UTF-8 checks, max user text 4,000 chars, max request body 16 KiB.
- Added authenticated Python `POST /bridge/v1/chat` using the existing bridge HMAC-SHA256, timestamp and nonce/replay protection.
- Runtime now wires ConversationStore, ContextBuilder and ProviderManager. It persists the user message first, calls the provider outside SQLite write transactions, persists the assistant answer, then returns it.
- Chat request IDs are idempotent: same request ID/content returns the stored assistant response without a second provider call; same ID with changed content returns HTTP 409. Provider-unconfigured requests return HTTP 503 before user-message persistence. Chat bodies are not written to runtime logs.
- Hello advertises `dialogue.chat` only when explicit provider config is valid at runtime start.
- Added Fabric `NikaChatClient.java`: standard unprefixed outgoing chat is privately routed only while Nika is summoned/private mode active AND the bridge advertises `dialogue.chat`. It is cancelled before server send, sent async over signed localhost bridge, and reply is rendered locally.
- /nika summon activates private mode; /nika dismiss disables it. Configurable key binding N (default) toggles private Nika chat vs normal server chat. Slash commands remain untouched. Presses while a screen/chat input is open are discarded so a typed N does not toggle unexpectedly.
- If provider/bridge is unavailable before sending, ordinary chat falls back to public server chat with a local warning. If a request fails after interception, the local message says the text was not sent to the server.
- Added ru_ru/en_us translations and updated Fabric/root README. MOD_VERSION and Gradle mod_version both set to 0.5.0.
- Fabric build 44413370724 passed; Python CI 44413370413 passed all six Python 3.11/3.12/3.13 Windows/Ubuntu jobs plus source overlay.
- Artifact ID 14478771154. Delivered JAR nika-companion-0.5.0.jar, SHA-256 `8fcc2912fa894cbeb8c85b49d81e57067191860331f6c8fc901ad3cb0707ef62`. Verified Fabric metadata version and NikaChatClient/BridgeClient classes.
- Actual LM Studio endpoint/model remains unconfigured/unverified on the PC running Nika. In-game privacy/keybind/slash/fallback acceptance remains untested. Next: verify local /v1/models, configure NIKA_LLM_BASE_URL/NIKA_LLM_MODEL (and optional key) locally, test end-to-end private chat with a trusted server.

## 2026-11-19: recovery after interrupted chat and v0.5.1 CI re-check

- Recovered prior project decisions from conversation history and checked the live private repository, PR #1 and the canonical handoff.
- Confirmed PR #1 remains open/draft, branch feature/companion-renderer-v0.4.0, current head 69c6ac0d8ea0346ee43b77d2d80d043c70ec37b3; main remains unchanged.
- Reconfirmed v0.5.1 ordinary unprefixed Minecraft chat with configurable N toggle and fail-closed privacy. Slash commands remain separate. If Nika is unavailable while private mode is active, text is blocked locally and is not sent to multiplayer chat.
- Latest Fabric run 44416364837 and Python CI run 44416364976 failed before steps started. Job step lists are empty, Fabric logs return BlobNotFound, and neither run has artifacts. This is not evidence of a source-code/test failure; v0.5.1 remains CI-unverified and no v0.5.1 JAR exists.
- Current blocker is runner allocation. Account billing/usage/budget and repository Actions settings must be checked by Vitaly; billing exhaustion is only a hypothesis until verified.
- Found that this file's sibling PROJECT_CONTEXT.md was an outdated v0.5.0 snapshot with contradictory public-chat fallback behavior. Consolidated the canonical handoff in docs/CHAT_CONTEXT.md and replaced the duplicate with a pointer.
- Next: inspect GitHub Billing & licensing → Usage / Budgets and alerts, then repository Settings → Actions → General; restore runner allocation; run current-head Fabric and Python checks; deliver only a verified v0.5.1 JAR; configure local LM Studio and complete manual Minecraft privacy acceptance. Do not merge PR #1 without explicit approval.
## 2026-11-19: handoff consolidation committed

- Updated docs/CHAT_CONTEXT.md with the latest live repository/CI re-check and exact next actions.
- Replaced docs/continuity/PROJECT_CONTEXT.md with a clear pointer to the canonical handoff; this removes a dangerous stale v0.5.0 description that told Nika to fall back to public chat when offline.
- Added a canonical handoff link to README.md.
- Updated PR #1 description with the latest observed workflow run IDs 44416364837 and 44416364976. Latest inspected jobs have no steps/logs/artifacts; v0.5.1 is still not CI-verified.
- Documentation commits: 02ea7b6cbd571a9249df3963f93351a1ac0e83f9 (handoff), 67df949de0d36539cd8587c32c8888fce39e2f27 (stale context pointer), 54f616a32685e6c090ef619d6f30a8fe1449afab (chat log), ceeaa7fcc66cc80a2d577fe7311527394dcd7ac9 (README link). No source code changed.

## 2026-11-19: public repository decision and preflight

- Vitaly chose to make `Dharma2500/Nika-Companion` public rather than wait for the private-repository Actions allowance. The visibility is still private at the time of this update; Vitaly will change it manually.
- Targeted review of the current feature branch: `.gitignore` excludes local environment files, NIKA_DATA, databases, logs and key/certificate files; the checked provider config contains no credential values and reads configuration locally; security docs explicitly prohibit committing secrets.
- The Python and Fabric workflows have `contents: read`, use standard hosted runners, and use `pull_request` rather than `pull_request_target`. No self-hosted runners were found in these two workflow files.
- Important limitation: this is not a forensic scan of all 159 PR commits, all branches or historical Actions logs. These become visible when the repo is public. Any credential found in history must be revoked/rotated, not merely deleted.
- GitHub UI path: Settings → General → Danger Zone → Change repository visibility → Make public. Verify the exact repository name before confirming.
- Next: verify actual public visibility, review Actions history/logs, enable available secret-scanning/push-protection settings, then re-check Actions and continue development. PR #1 remains draft/open/unmerged.
