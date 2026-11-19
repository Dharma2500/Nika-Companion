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


## 2026-11-19: public repository, CI recovery and v0.5.1 artifact

- Verified repository visibility is now public. Branches remain `main` and `feature/companion-renderer-v0.4.0`; PR #1 is still open/draft/unmerged.
- Reran the previously runner-blocked workflows: Fabric run #130 (44419018875) passed the JDK 21/Gradle build and artifact upload. Python CI run #346 (44419018898) passed all six Ubuntu/Windows × Python 3.11/3.12/3.13 jobs; all six ran 157 tests each with compileall and Ruff passing. The dependent source-overlay archive job also passed.
- Downloaded and verified Fabric v0.5.1 artifact ID 14481446390. JAR: `nika-companion-0.5.1.jar`, 31,822 bytes, SHA-256 `d1793fbe8e41a9c0d183b156dc28733ee042f0ec83d5e4e8b8285075e513334d`. GitHub artifact expires 2026-12-02 23:18 UTC.
- Targeted inspection of current ignore rules/provider config/security docs/workflows found no configured credentials and confirmed local-data ignore rules, read-only workflow permissions and standard hosted runners. This is not a complete forensic scan of all historical blobs/commits/logs. Do not claim the entire public history is secret-free without a full scan.
- Corrected stale project docs: README no longer calls the public repository itself private and now reports current CI/artifact status; roadmap now correctly says offline private messages are blocked locally, never silently forwarded to public server chat. Dashboard roadmap now records loopback-only UI, status, provider settings and OS-backed credential storage.
- Canonical handoff updated with current public visibility, CI/artifact evidence, honest secret-audit limitations, remaining manual Minecraft acceptance and dashboard as the next milestone.
- No source-code changes in this recovery turn. No token/API key has been added to Git.


## 2026-11-19: read-only local dashboard MVP

- Added agent/src/nika/dashboard.py: responsive local status page, self-contained HTML/CSS/JS, no external scripts/CDNs.
- Added nika dashboard / python -m nika.cli dashboard. It starts the runtime when needed and opens a browser session via one-time ticket.
- Added runtime routes on the existing 127.0.0.1 server: /dashboard/, /dashboard/session/create, /dashboard/session/exchange, /dashboard/api/status.
- Security design: 60-second single-use in-memory ticket, URL fragment not query, immediate fragment removal, exact Host/Origin/Sec-Fetch-Site checks, one-hour HttpOnly; SameSite=Strict cookie, in-memory session, standard-base64 CSP nonce, strict CSP, no CORS, no remote resources, no localStorage, no secret-bearing status fields.
- The page only shows runtime uptime/state, SQLite health/schema/counts, provider configured boolean and advertised capabilities. It is read-only; no provider editor or credential entry yet.
- Added tests for dashboard authentication, Origin rejection, one-time ticket replay prevention, cookie flags, status redaction and CLI browser launch.
- Latest code commit validated: 0a83e9eabd63b1ab03b6bd2c8ffd9049dbcbbecb. Python CI #358 (run 44420882249) passed all six Ubuntu/Windows × Python 3.11/3.12/3.13 jobs; each ran 159 tests. Ruff and compileall passed. Source overlay artifact ID 14481548796.
- Fabric build #142 (run 44420882364) passed; v0.5.1 JAR artifact ID 14482470879. No Minecraft Java source changed in this milestone.
- Corrected CLI status wording to accurately state that the bootstrap ticket is one-time while the active session is stored in an HttpOnly cookie for up to one hour.
- Manual acceptance on Vitaly's Windows PC remains: run python -m nika.cli dashboard, inspect status, refresh, check browser errors, restart runtime and ensure the old session is rejected. Provider settings and API key management remain deliberately postponed; API keys should be added near the end through OS credential storage.


## 2026-11-19: final validation after dashboard docs and CLI wording

- Verified latest feature branch head before this documentation-only update: `a13ad5b78b7d3e2b93a1835d76e83758862cdaa2`; repo visibility public; PR #1 remains open/draft/unmerged.
- Latest Fabric run #146 (44421335808) succeeded and uploaded artifact ID 14481902637.
- Latest Python CI run #362 (44421335790) completed all six Ubuntu/Windows × Python 3.11/3.12/3.13 jobs successfully. Each job passed all 159 tests; compileall and Ruff passed. Source overlay job completes as part of Python CI.
- The latest CI run includes the minor CLI output correction explaining that the one-time ticket is exchanged for an HttpOnly one-hour session cookie.
- README, canonical handoff and chronological chat log refreshed with these latest workflow IDs. No new credentials or secrets have been added.


## 2026-11-19: dashboard provider configuration and connection test

- User confirmed dashboard opens and private Minecraft chat activates, but screenshot showed bridge/model unavailable. Diagnosed provider not configured: the Python runtime advertised dialogue.chat only when environment-based model configuration existed; dashboard was still read-only.
- Added dashboard fields for OpenAI-compatible Base URL and exact Model ID, save action, and a real generation connection test.
- Settings persist as non-secret JSON at NIKA_DATA/config/provider.json with schema version 1. API keys are not stored in that file or entered through the UI.
- Runtime loads saved config when environment overrides are absent. ProviderManager supports thread-safe hot reconfiguration, so a successful dashboard save activates the provider without restarting the runtime.
- Authenticated dashboard write/test routes enforce local Host, valid HttpOnly session, exact Origin, Sec-Fetch-Site, JSON content type, body limits and strict fields. Test generation is not stored in conversation history.
- Dashboard now shows configured state, non-secret Base URL/model and updates bridge capabilities. Existing Minecraft client re-handshakes automatically; after dialogue.chat becomes available, the existing JAR should be sufficient. No Java source changed.
- Added tests for persistence without secrets, environment override, duplicate JSON keys, provider manager connection test, and a runtime integration test that saves config and sends a real test request to a fake OpenAI-compatible server.
- Fixed lint issues in the first CI attempts (CSS/footer line length, import ordering, unused import, test import sorting) and corrected dashboard form value restoration.
- Python CI #370 (run 44569289812): all six Ubuntu/Windows × Python 3.11/3.12/3.13 jobs passed; 164 tests in every job; Ruff and compileall passed. Source overlay artifact ID 14552468722.
- Fabric build #154 (run 44569289697) succeeded; artifact ID 14554765345. No mod/JAR update is needed for provider settings.
- Current code head: 5d2d16726f80804ed13f4e92b8c92cc8f828e99f. PR #1 remains open/draft/unmerged. The Windows/manual test against Vitaly's real LM Studio endpoint remains.
- Next user operation after the updated source ZIP: stop runtime, unzip directly over C:\Nika-Companion, preserve .venv and NIKA_DATA, run python -m nika.cli dashboard, enter the actual Base URL and Model ID, save, test connection, then return to Minecraft and verify the no-leak private-chat behavior.


## 2026-11-19: authoritative correction to OpenAI + local learning architecture

- Vitaly confirmed the intended provider topology: OpenAI API is primary; two keys are configured, key 1 is primary and key 2 is automatic failover when the primary's usable quota is exhausted/unavailable.
- Keep LM Studio generic OpenAI-compatible pathway as optional future alternative. Do not set up a remote LM Studio PC and do not test LM Studio now.
- Core product priority is local learning/memory. All dialogue, corrections, facts, outcomes and approved memories remain in NIKA_DATA/SQLite regardless of provider status. No continuous background API polling.
- Learning means provenance-aware local memories, user preferences, project facts, corrections and verified reusable skills, not fine-tuning model weights after every chat.
- "Remember" and straightforward corrections should be persisted locally without a model call; uncertain inferred memories become reviewable candidates; model-assisted extraction is sparse and only on meaningful learning signals.
- API economy requirements: local request gate, compact relevant context, short recent tail/rolling summary, small number of retrieved memories, strict input/output limits, lower-cost routine model routing, explicit escalation, local request/cost ceilings and usage telemetry from provider response metadata.
- New primary OpenAI adapter should use Responses API. The current generic Chat Completions adapter and generic endpoint/model dashboard are retained as optional LM Studio groundwork only; not the finished OpenAI setup.
- Failover must classify quota exhaustion, rate limit, authentication, model/permission, malformed request and service/network failures separately. Never endlessly retry or waste the secondary key on a request-format error.
- Important billing nuance: API credits belong to an API organization and are separate from ChatGPT subscription. Two keys in one organization do not create a second organization credit balance; project-level budgets/rate limits may differ but organization limits remain. A truly independent quota reserve generally requires a separately billed organization. Explain this without promising that two keys double token capacity.
- No API keys have been pasted into chat or stored in the repository. Dashboard must set them locally using an OS-backed credential store; never expose keys back to page JavaScript or logs.
- Documentation now records this decision as authoritative. Next implementation order: OpenAI Responses two-key manager and safe Windows credential store; cost gate and telemetry; then local-first memory learning/review.


## 2026-11-19: implemented OpenAI dual-key, economy gate and local learning

- Implemented official OpenAI Responses API client (agent/src/nika/openai_provider.py) as primary provider. Default model gpt-6-luna, reasoning.effort=none, store=false, tools omitted, 320 output-token cap; connection test caps output at 64 tokens.
- Implemented two credential slots backed by Windows Credential Manager (agent/src/nika/credentials.py). Keys are entered in a same-origin native password form in dashboard and posted directly to loopback Python runtime. Keys never enter Git, provider.json, SQLite, logs or JavaScript/browser storage.
- Failover is error-aware. Key 2 is attempted after quota exhaustion, invalid key or permissions/access issue. Transient 429 rate limits do not burn the secondary key. Invalid model/request errors and network/server errors are not treated as quota depletion.
- Dashboard exposes primary/secondary configured flags, active slot, model, daily token usage, and a local daily ceiling (60,000 tokens default). It does not expose secret values.
- provider_usage SQLite schema v3 records model/key slot/input/output/cached/reasoning/total counts only. New v3 migration also includes learning_candidates; existing v1/v2 schema data is preserved.
- Context budget reduced to max 8 recent messages, 4 relevant memories and 8 KiB. Runtime applies a conservative local token estimate plus output cap before paid requests.
- Local learning captures clear explicit "запомни ..." and explicit correction phrases, storing them as user_taught memories with confidence 1.0. Repeated exact explicit facts/corrections are deduplicated. These operations generate local replies without OpenAI. Ordinary text is saved before provider checks but not automatically promoted to memory.
- Bridge advertises dialogue.chat without needing API keys so the client can reach the local learning gate. The private text is still local only; no code changes in the Fabric mod.
- Generic OpenAI-compatible Chat Completions pathway and advanced LM Studio settings remain optional future configuration; we do not set up or test LM Studio in this milestone.
- OpenAI real-account credentials and generation have not yet been tested. Windows Credential Manager still requires manual acceptance on Vitaly's PC. Review UI, automatic candidate creation/review, verified skill episodes, monthly USD budget, per-key cost estimate and emergency off switch remain future tasks.
- Python CI #423 (run 44595717972) completed all six Ubuntu/Windows × Python 3.11/3.12/3.13 jobs successfully. Later CI runs cover additional dashboard/credential fixes; check the latest completed result before packaging.
- Fabric builds remained successful; no Java code changed, so no new JAR.
- Latest branch remains feature/companion-renderer-v0.4.0; PR #1 stays draft/open/unmerged.


## 2026-11-19: final successful CI and source overlay package

- Final source head for this package: f325bd0b1bdaff24b124b084f59e194df7366b3b.
- Python CI #433 (run 44596575853) passed all six Ubuntu/Windows × Python 3.11/3.12/3.13 matrix jobs. Each ran 185 passing tests. Ruff, compileall and the source-overlay archive job also passed.
- Source overlay artifact ID 14566815689. The nested source overlay was extracted and re-verified as Nika-Companion-Update.zip. ZIP root contains repo-relative paths; .venv and NIKA_DATA are excluded. SHA-256: 2bbc04183d1899e92d2232ee1f97afabecacd759dfba5c0ad449f51cc3ee6132.
- Fabric build #217 (run 44596575788) passed. No Java source changed, so no JAR is required.
- PR #1 remains open/draft/unmerged. Manual Windows/OpenAI key acceptance is still required after local installation; no actual user key was used in CI.


## 2026-11-19: package handoff correction

- Python CI #433 (run 44596575853) is the code-validation run: 185 tests passed in each of six Ubuntu/Windows × Python 3.11/3.12/3.13 jobs; Ruff and compileall passed.
- Documentation synchronization after #433 was also checked by Python CI #437 (run 44597059597), all six jobs plus source overlay succeeded. Artifact #14566416589 contains that docs snapshot.
- A final handoff correction is committed after #437; therefore #14566416589 is not the final user ZIP source. Build the final user ZIP from the newest successful workflow/source-overlay artifact after this correction.
- No Java source changed. The JAR remains unchanged.
