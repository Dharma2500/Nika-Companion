# Nika Companion — durable project context / handoff

Last updated: 2026-11-19
Repository: `Dharma2500/Nika-Companion` (**public**, verified 2026-11-19)
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
- Current branch head before this handoff refresh: `578f3105f267c2f899ea2438d286869f1c197fe6` (`Normalize Python runtime test spacing`, 2026-11-18).
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

1. **Extend the read-only dashboard** with non-secret provider URL/model settings and a connection test. Keep it loopback-only and same-origin.
2. **Finish manual dashboard acceptance** on Vitaly's Windows machine: launch, refresh, database status, provider state, browser session expiry and runtime restart.
3. **Complete manual Minecraft acceptance** for private chat, no server leakage, N toggle, slash passthrough, offline local blocking, repeated messages and world transitions.
4. **Add API credentials near the end** through an OS-backed local credential store. Never commit them, return them to browser JavaScript, put them in logs, or store them in localStorage.
5. **Strengthen the dialogue experience:** stable personality constitution, truthful fallback behavior, explicit memory teaching/review and provider budgets/diagnostics/failover.
6. Add fresh, scoped world observation context only after a freshness/scope contract.
7. Voice only after text dialogue and memory are reliable.
8. Skills/planning/permissioned actions much later; no autonomous world-changing behavior until action auth, capability checks, approval gates, emergency stop and disposable-world tests exist.

CI status for the dashboard implementation:
- Fabric v0.5.1 run #146 succeeded and uploaded artifact ID `14481902637`.
- Python CI run #362 succeeded on all six OS/Python matrix jobs; each job ran 159 tests successfully. Ruff and compileall passed; the dependent source-overlay archive also succeeded.
- The dashboard source is on the validated feature branch head preceding this documentation update. The latest run #362 also validates the CLI wording correction.

## 9. Secrets and local configuration

Never write these to Git or this handoff:
- `NIKA_LLM_API_KEY`
- bridge tokens from `NIKA_DATA/runtime/status.json`
- local SQLite databases/backups, message content, logs, world snapshots, account/server identity.
Local environment names only: `NIKA_LLM_BASE_URL`, `NIKA_LLM_MODEL`, optional `NIKA_LLM_API_KEY`.
The local data directory is outside repository; never migrate it or change its schema without a migration/backup plan.


## 10. Historical CI runner diagnosis (superseded by section 13)

Current state was rechecked against GitHub immediately before this handoff update:
- PR #1 remains open, draft, base `main`, not merged. PR head and feature branch head both matched `578f3105f267c2f899ea2438d286869f1c197fe6` before this docs-only commit.
- Latest Fabric run: `44415811997`, run #125, commit `578f3105f267c2f899ea2438d286869f1c197fe6`.
  - Job `135195682729`, label `ubuntu-24.04`, completed failure at 2026-11-18 22:53:30 UTC.
  - Raw jobs API: `runner_id=0`, `runner_name=""`, `runner_group_id=0`, `steps=[]`.
  - No job logs and no artifacts.
- Latest Python CI run: `44415811971`, run #341, same commit.
  - Six matrix jobs failed in about 3 seconds with labels `ubuntu-latest` / `windows-latest`.
  - All six actual jobs report `runner_id=0`, empty runner names, and empty steps. The dependent source-overlay job was skipped because the test matrix failed.
  - No job logs and no artifacts.
- Workflow YAML was inspected. Fabric requests a standard GitHub-hosted `ubuntu-24.04` runner; Python CI requests standard GitHub-hosted `ubuntu-latest` and `windows-latest` runners. Both workflows have ordinary triggers and read-only `contents: read` permissions. No custom/self-hosted labels or suspicious workflow command explain an immediate pre-step failure.
- Therefore this is not a compiler, pytest, Ruff, Gradle, checkout, or source-code failure observed in CI. None of those steps has started. Current v0.5.1 code remains unverified.
- A highly similar public GitHub Community report dated 2026-11-15 documented private GitHub Free jobs with the exact signature (`runner_id=0`, no steps/logs, 2–5 seconds); that report's owner also showed included Actions compute fully consumed ($12/$12), Actions budget $0, usage blocked, and no payment method. This is only an analogue, not evidence of Vitaly's billing state: https://github.com/orgs/community/discussions/213180
- Official billing docs: https://docs.github.com/en/actions/concepts/billing-and-usage . Private repository hosted runner costs draw from included compute; the account's settings determine whether further usage is permitted.
- User must inspect GitHub **Settings → Billing & licensing → Usage / Budgets and alerts**, specifically included compute used vs allowance and whether Actions usage/budget is blocked. Also inspect repository **Settings → Actions → General** to ensure Actions are enabled and standard GitHub-hosted actions/runners are permitted.
- If billing and repository policies are clean, collect exact failing run URLs/job IDs and open a GitHub Support request. A minimal diagnostic workflow in another repository under the same account can distinguish repository-specific settings from account-level restrictions, but do not create a public repo or expose private source.
- Do not add a fake code change, switch to a public repository, or deliver v0.5.0 in place of v0.5.1 just to bypass the runner failure. No v0.5.1 JAR artifact exists.
- Next: wait for Vitaly's result from the billing/policy check; then retry a current-head workflow only after a relevant setting is corrected or support indicates recovery. Do not keep rerunning identical failures without new evidence.

## 11. Historical recovery snapshot (superseded by section 13)

This section records the live GitHub re-check performed after the previous ChatGPT conversation was interrupted.

### Verified source-control state
- PR #1 is still **open, draft, not merged**, base main.
- Active branch remains feature/companion-renderer-v0.4.0.
- Current PR head: 69c6ac0d8ea0346ee43b77d2d80d043c70ec37b3.
- PR URL: https://github.com/Dharma2500/Nika-Companion/pull/1
- The PR description already contains the v0.5.1 fail-closed chat implementation and the current CI diagnosis.
- No code changes were made during this recovery check.

### Latest CI state at the current PR head
- Fabric workflow run 44416364837 (run #126): failed before any build step; job 135197604079; the Jobs API returns an empty steps array, logs endpoint returns BlobNotFound, and the run has no artifacts.
- Python CI run 44416364976 (run #342): all six Python/OS matrix jobs failed before execution; each has an empty steps array; the dependent source-overlay job was skipped. No artifacts were produced.
- Combined commit statuses endpoint returned no status entries.
- These results do **not** indicate a Gradle, Java, pytest or Ruff failure: none of those steps ran. Current v0.5.1 remains unverified by CI.
- No v0.5.1 JAR exists. The successful v0.5.0 artifact is historical and must not be substituted.

### Current code facts rechecked
- The feature branch contains NikaChatClient.java using Fabric ClientSendMessageEvents.ALLOW_CHAT for outgoing ordinary text. No prefix or /nika ask is required.
- Slash commands remain on their separate event path.
- Private mode is enabled when /nika summons Nika; key N explicitly toggles public server chat.
- v0.5.1 is fail-closed: when the local chat capability is unavailable, ordinary text is canceled locally and a warning tells Vitaly to press N to switch to server chat. No silent fallback to multiplayer chat.
- BridgeClient uses the local runtime status file and signed loopback HMAC requests. The provider endpoint/model are not hard-coded.
- Python chat schema enforces canonical UUIDs, strict JSON, max 4,000 characters and 16 KiB body. The runtime's no-provider test expects HTTP 503 without persisting the user turn.
- Actual LM Studio host/model configuration and manual in-game privacy acceptance are still pending.

### CI blocker and decision
- The repeated signature is pre-runner failure: failed jobs have no steps and no logs. Repository workflow YAML uses ordinary GitHub-hosted runner labels and read-only contents permissions.
- Most useful next check is account Settings → Billing & licensing → Usage / Budgets and alerts, then repository Settings → Actions → General. Inspect included Actions compute usage and whether usage/budget is blocked; also confirm Actions and GitHub-hosted runners are permitted.
- This is a diagnostic hypothesis, **not a confirmed account billing cause**. Do not claim the account has exhausted its quota unless Vitaly verifies it.
- GitHub documentation: https://docs.github.com/en/actions/concepts/billing-and-usage . It explains that private-repository hosted-runner use draws from included compute and can be blocked when the allowance is exhausted without a valid payment method; self-hosted runners are separately free.
- If billing and repository policy are clean, escalate these run/job identifiers to GitHub Support: Fabric run 44416364837, job 135197604079; Python run 44416364976, jobs 135197604818, 135197605112, 135197605226, 135197605232, 135197605247, 135197605388.
- Do not repeatedly rerun unchanged workflows without new evidence. Do not make the private repository public to bypass billing.

### Documentation consistency
- docs/CHAT_CONTEXT.md is the single canonical full handoff.
- docs/continuity/PROJECT_CONTEXT.md previously contained an older v0.5.0 snapshot that contradicted the v0.5.1 fail-closed implementation. It is being replaced with a pointer to this canonical file to prevent a future assistant from following stale instructions.
- docs/continuity/CHAT_LOG.md remains the chronological concise log and must receive a dated entry after substantive project turns.

### Exact next actions
1. Vitaly checks GitHub account billing/usage/budgets and repository Actions settings. Report only the visible status; do not share payment details or secrets.
2. Once runner allocation is restored or a safe self-hosted runner is deliberately configured, run current-head Fabric + Python CI.
3. Only after successful current-head Fabric build, retrieve and verify the v0.5.1 artifact. Never use v0.5.0 as a replacement.
4. Configure the real LM Studio endpoint/model locally on the PC running Nika; keep environment values and any key out of Git.
5. Complete manual Minecraft tests for private chat, no server leakage, N toggle, slash passthrough, offline blocking and world transition.
6. Do not merge PR #1 until Vitaly explicitly approves and required acceptance checks pass.
## 12. Documentation consolidation commits (2026-11-19)

The recovery check also corrected conflicting handoff documentation without touching source code:
- 02ea7b6cbd571a9249df3963f93351a1ac0e83f9 — append recovery state and current CI evidence to this canonical file.
- 67df949de0d36539cd8587c32c8888fce39e2f27 — replace the obsolete docs/continuity/PROJECT_CONTEXT.md v0.5.0 snapshot with a pointer to this file. This prevents stale fallback-to-public-chat instructions from being followed.
- 54f616a32685e6c090ef619d6f30a8fe1449afab — append the recovery event to docs/continuity/CHAT_LOG.md.
- ceeaa7fcc66cc80a2d577fe7311527394dcd7ac9 — add handoff links to README.md.
- The PR description was updated to list the latest observed code-triggered CI runs 44416364837 and 44416364976. The inspected jobs still have no steps/logs/artifacts. No code changes were made and no new JAR was produced.
- The current PR head moved due only to documentation updates. The last source-code head remains 69c6ac0d8ea0346ee43b77d2d80d043c70ec37b3; it is still the v0.5.1 code that requires CI and manual acceptance.

## 2026-11-19: repository visibility decision

- Latest verified repository visibility is still **private**. Do not describe it as public until GitHub metadata confirms the change.
- Vitaly has decided to make the repository public to restore reliable GitHub-hosted CI without exposing runtime credentials. He intends to keep API tokens and machine-specific configuration local and add them only during later local setup.
- Preflight inspection of the current development branch found: `.gitignore` excludes `.env`, `.env.*`, `NIKA_DATA`, SQLite files, JSONL logs, keys and certificates; the checked provider configuration reads secrets from local environment only; the security document forbids committing credentials and local data.
- Both current workflow files declare `permissions: contents: read`; they use standard GitHub-hosted runners and `pull_request`, not `pull_request_target`. No self-hosted runner is configured in these workflows.
- This was a targeted working-tree inspection, **not a complete secret audit of every historical commit, branch or past Actions log**. All of those may become publicly visible after the visibility change. Review old workflow logs and historical content before/after publishing; rotate any credential found in history because deleting a file later does not make an exposed credential safe.
- GitHub public-repository standard hosted runners are free for the current workflow labels (`ubuntu-24.04`, `ubuntu-latest`, `windows-latest`). Public visibility also makes source, branches, PRs, Actions history/logs and activity public and allows forks.
- Vitaly will perform the visibility switch manually in GitHub: repository Settings → General → Danger Zone → Change repository visibility → Public, confirm the repository name and acknowledge the effects. Re-check repository metadata before proceeding with post-publication CI.
- Current draft PR #1 remains open and unmerged. Do not merge it without explicit approval.
- Next: verify visibility changed; inspect/enable secret-scanning push protection and review Actions logs; rerun CI only after the visibility/runner status has changed; then resume Nika implementation on the existing feature branch.


## 13. Public repository and restored CI (2026-11-19)

### Verified visibility and source-control state
- GitHub repository metadata now reports visibility `public`.
- Default branch remains `main`; active development remains `feature/companion-renderer-v0.4.0`.
- PR #1 remains open, draft and unmerged. Do not merge without Vitaly's explicit approval.
- Latest branch head before this documentation-only update: `495c20ae388867992fecf2f548507b5f7956439e`. Its source-code tree is the v0.5.1 implementation; the code commit remains `69c6ac0d8ea0346ee43b77d2d80d043c70ec37b3`.

### GitHub Actions restored
- The previous jobs were rerun after the repository became public. GitHub assigned standard hosted runners and executed all workflow steps.
- Fabric run #130: [44419018875](https://github.com/Dharma2500/Nika-Companion/actions/runs/44419018875), job `135208138233`, **success**. Gradle wrapper validation, JDK 21 setup, Fabric build and artifact upload all passed.
- Python CI run #346: [44419018898](https://github.com/Dharma2500/Nika-Companion/actions/runs/44419018898), **success**. All six jobs passed:
  - Python 3.11, 3.12 and 3.13 on Ubuntu
  - Python 3.11, 3.12 and 3.13 on Windows
  - Each job collected and passed 157 tests; compileall and Ruff also passed.
  - Dependent source-overlay archive job passed and uploaded its artifact.
- Fabric JAR artifact: `nika-companion-fabric-1.21.11`, artifact ID `14481446390`, 30,301-byte ZIP, expires 2026-12-02 23:18 UTC.
- The downloaded JAR was extracted and checked: valid ZIP/JAR, mod ID `nika_companion`, version `0.5.1`, environment `client`, client entrypoint `ru.vitaly.nika.NikaCompanionClient`, chat and renderer classes present. JAR size 31,822 bytes; SHA-256 `d1793fbe8e41a9c0d183b156dc28733ee042f0ec83d5e4e8b8285075e513334d`.
- The prior runner-allocation blocker is therefore resolved for these observed workflows. Do not keep retrying run #130/#346; new code changes will trigger normal CI.

### Public-repository security notes
- Targeted current-branch review confirmed `.gitignore` excludes `.env`, `.env.*`, local NIKA_DATA, SQLite files, JSONL logs, key/certificate files and common runtime output. The checked provider configuration reads environment variables and contains no configured credential value. Security docs prohibit committing secrets.
- Workflow files use `permissions: contents: read`, standard GitHub-hosted runners and ordinary `pull_request` triggers; no self-hosted runner or `pull_request_target` usage was found in the checked workflows.
- Vitaly plans to add provider credentials only during later local dashboard setup. No credential has been intentionally added by this project work. Keep credentials local and use an OS-backed secret store once implemented.
- This was a targeted review, **not a forensic scan of every historical blob, all 161 PR commits, external forks, or every past Actions log**. GitHub code search returned no matches for several common token markers, but indexing/search results are not proof of a clean history. If a real credential is ever discovered in history, revoke/rotate it; deleting it from the latest tree is insufficient.
- GitHub's current documentation says secret scanning runs automatically for public repositories; repository-level push protection is not automatically enabled for every existing public repository. Push protection for users is on by default on GitHub.com unless disabled in account settings. Vitaly should verify repository **Settings → Security → Advanced Security** and enable the available secret-scanning alerts/push-protection controls. References: https://docs.github.com/en/code-security/how-tos/secure-your-secrets/detect-secret-leaks/enable-secret-scanning and https://docs.github.com/en/code-security/concepts/secret-security/push-protection .
- No source code was changed as part of this visibility/CI recovery; this section and the associated README/roadmap changes are documentation updates.

### Remaining acceptance boundary
- v0.5.1 is now CI-verified, and its JAR exists. This does **not** complete manual Minecraft acceptance.
- Still required: install the v0.5.1 JAR in Fabric 1.21.11 with matching Fabric API, start the local Python runtime, then test private chat, local-only replies, N toggle, slash passthrough and provider-offline blocking. Never test private routing on a public server with sensitive text until the no-leak behavior has been verified.
- The next development milestone is the local dashboard. Design/build it as a loopback-only surface; keep secrets outside Git and outside browser persistence.


## 14. Local dashboard MVP (2026-11-19)

### User-facing entry point
- New command: python -m nika.cli dashboard or installed nika dashboard.
- If the local runtime is not running, the command starts it. It then uses the existing local runtime control token to request a one-time dashboard ticket and opens the browser.
- The UI is a read-only first milestone. It displays runtime state/uptime, SQLite health/schema/counts, provider configured state and advertised bridge capabilities. It does not display chat contents or secret values.

### Implementation
- New page: agent/src/nika/dashboard.py, a self-contained HTML/CSS/JS page with no third-party scripts, fonts, images or CDN references.
- agent/src/nika/runtime.py serves /dashboard/, POST /dashboard/session/create, POST /dashboard/session/exchange and session-protected GET /dashboard/api/status on the existing 127.0.0.1 HTTP server.
- Bootstrap ticket lifetime: 60 seconds; one-use; stored only in runtime memory; CLI places it in the URL fragment, which the initial HTTP request does not transmit. The page removes the fragment and exchanges it after checking same-origin server-side headers.
- Cookie: HttpOnly, SameSite=Strict, path /dashboard, one-hour lifetime. Session map is memory-only and is reset when the runtime stops/restarts.
- Security: strict Host match to 127.0.0.1:port, exact Origin, Sec-Fetch-Site same-origin, 4 KiB exchange body limit, no CORS, nonce-based CSP using a standard-base64 nonce, no remote assets, no localStorage and Cache-Control: no-store.
- Status JSON is intentionally allowlisted. It returns only runtime uptime/state, database health/schema and aggregate counts, provider configured boolean and advertised capabilities. It excludes API key, provider endpoint, runtime control token, bridge HMAC token and conversation contents.
- The page is read-only. Provider URL/model settings, connection test, API credential configuration, memory review, chat UI and runtime controls are not implemented yet.
- API keys are intentionally deferred until near the end of the dashboard phase. When added, they must use OS-backed local credential storage and must never be returned to browser JavaScript or written to Git/logs/browser storage.

### Validation
- Added a runtime test for dashboard page/CSP, unauthorized API access, authenticated single-use ticket exchange, Origin rejection, cookie properties, redacted status response and replay rejection.
- Added a CLI test for automatic runtime start and browser launch without printing the one-time ticket.
- Latest Python CI run #362: all six Python 3.11/3.12/3.13 × Ubuntu/Windows jobs passed; each job ran 159 tests; compileall and Ruff passed. The source overlay artifact also uploaded successfully.
- Latest Fabric build #146 succeeded and uploaded artifact ID 14481902637. No Minecraft client mod source changed in this dashboard milestone.
- The automated tests verify HTTP/session behavior but do not replace a manual browser test on Vitaly's Windows PC.
- The earlier failed lint runs #354 and #356 exposed long inline page lines and an import-order issue. These were corrected; current source commit 0a83e9e... passed the latest CI.


## 15. Dashboard model configuration milestone (2026-11-19)

### Diagnosis
- Vitaly confirmed that the dashboard page opened and Minecraft private chat mode activated, but the client displayed: "приватный режим включён, но bridge/модель недоступны".
- The Fabric client blocks ordinary messages locally when private mode is active but dialogue.chat is not advertised by the bridge. This is intentional fail-closed privacy behavior: no private text is silently forwarded to the multiplayer server.
- The Python runtime previously advertised dialogue.chat only when a provider was configured through environment variables. The dashboard was read-only, so a model had not yet been configured.
- BridgeClient retries the local handshake at bounded intervals (about five seconds). Once the Python runtime advertises dialogue.chat, the existing client can observe it on its next handshake; no JAR update is required for this provider-only milestone.

### Implemented
- agent/src/nika/provider.py:
  - load_provider_config() still supports explicit environment overrides (NIKA_LLM_BASE_URL, NIKA_LLM_MODEL, optional NIKA_LLM_API_KEY) and now also reads NIKA_DATA/config/provider.json.
  - The persisted JSON schema is version 1 and contains exactly schema_version, base_url and model. No secret is stored in this file.
  - The file is size-bounded, duplicate-key checked, validated through ProviderConfig and written atomically via a temporary file plus os.replace. POSIX permissions are restricted to owner read/write.
  - ProviderManager is thread-safe and can atomically swap the active provider without restarting the runtime.
  - The connection test performs a minimal real chat-completion generation; it does not add test messages to the user's conversation history.
- agent/src/nika/runtime.py:
  - Runtime loads the non-secret config from NIKA_DATA when environment variables do not override it.
  - Authenticated session-protected dashboard POST routes save provider settings and run the generation test. They validate loopback Host, one-hour session cookie, exact Origin, Sec-Fetch-Site, Content-Type, body size and exact JSON shape.
  - Dashboard status now returns configured state, Base URL and Model ID (not an API key or bridge/runtime secret), and advertises dialogue.chat only while a provider is configured.
  - If Base URL or Model ID environment overrides are present, dashboard editing returns HTTP 409 with an explanation instead of silently overriding them.
- agent/src/nika/dashboard.py:
  - Added Base URL and Model ID fields, Save and Test buttons, loading/error/success feedback and status refresh.
  - UI input values are refreshed from the saved configuration.
  - For LM Studio on the same computer as the Python runtime, the common Base URL is http://127.0.0.1:1234/v1, but the user must use the actual configured port. When LM Studio runs on a different computer, use that PC's reachable LAN address and make its local server reachable on the network.
- No API-key input was added. Local LM Studio without a key is the intended first acceptance target. Cloud/provider credentials remain deferred until an OS-backed local credential store is implemented. No secret may be placed into Git, browser storage, logs or provider.json.

### Automated validation
- Latest code head before this documentation refresh: 5d2d16726f80804ed13f4e92b8c92cc8f828e99f.
- Python CI #370: run 44569289812; all six Ubuntu/Windows × Python 3.11/3.12/3.13 jobs passed; each collected and passed 164 tests; Ruff and compileall passed. Source overlay artifact ID 14552468722.
- Fabric build #154: run 44569289697 succeeded; artifact ID 14554765345. No Java source change was required for this milestone.
- Earlier lint-only failures in runs #367–#369 were corrected; they were import ordering and line-length issues. The latest run #370 is fully green.
- These CI results validate the fake-server integration path, not Vitaly's actual LM Studio server. Manual Windows acceptance remains.

### Exact local setup after receiving the source overlay ZIP
1. Stop the current runtime from C:\Nika-Companion with:
   .\.venv\Scripts\python.exe -m nika.cli stop
2. Extract the source ZIP directly over C:\Nika-Companion and overwrite tracked files. Preserve .venv and NIKA_DATA; neither is included in the overlay.
3. Run:
   .\.venv\Scripts\python.exe -m nika.cli dashboard
4. Enter the real OpenAI-compatible Base URL and exact Model ID from the LM Studio server, click Save, then Test Connection.
5. After a successful generation test, the running Python provider is active immediately. The Minecraft client should see dialogue.chat on the next automatic handshake. Test first in a safe/private world and verify messages/replies are local only.

### Current repository state and next work
- Repository: Dharma2500/Nika-Companion; active branch: feature/companion-renderer-v0.4.0; PR #1 remains open, draft and unmerged. Do not merge without Vitaly's explicit approval.
- Python source overlay artifact for the code head above: 14552468722. It is superseded if any newer docs or source commits are pushed; always package from the latest successful source-overlay run.
- Manual Windows dashboard/model acceptance and real LM Studio endpoint/model verification are still outstanding.
- Next: confirm Vitaly's actual LM Studio listener address and model ID via the dashboard's connection test; improve error diagnostics from sanitized provider status; then continue safe text dialogue and explicit memory review. API-key handling remains deferred.


## 16. Authoritative product decision: OpenAI dual-key + memory-first learning (2026-11-19)

This section supersedes earlier provider assumptions in this handoff and in the original memory/dialogue design. If older text below says LM Studio is the first/primary provider, treats memory insertion as manual-only forever, or describes the dashboard's generic Base URL/model form as the final setup, this section is authoritative.

### User-confirmed decisions
- Main provider is the OpenAI API, not a local LM Studio server.
- Two OpenAI API credential slots are required:
  - Key 1: primary.
  - Key 2: automatic secondary failover when the primary's usable quota/availability is exhausted.
- The dashboard must allow both keys to be entered/updated without ever displaying them again. Store secrets using an OS-backed local credential manager, not provider.json, SQLite, Git, logs or browser storage.
- Keep the current generic OpenAI-compatible provider as an optional future LM Studio pathway. Do not remove it, but do not test or activate LM Studio for this milestone.
- Nika must learn and remember locally. API calls are an occasional reasoning/generation resource, not a continuous dependency. Durable memory must keep working when both keys are unavailable.
- Do not fine-tune model weights for every conversation. Learning is structured local memory, knowledge, corrections and reusable skills.

### Required OpenAI integration
- Use the official OpenAI Responses API for the primary OpenAI adapter. The current code's generic /chat/completions adapter is an optional LM Studio-compatible adapter, not the final primary OpenAI integration. The Assistants API is not an option for new work; OpenAI documents it as sunset on 2026-08-26.
- Implement error-aware failover with bounded retries, cooldown/circuit breaker and clear local status. Quota exhaustion, rate limiting, invalid credentials, invalid model/permissions, malformed requests and service/network failures must be distinguished.
- Quota exhaustion errors should fail over to key 2 only when it can actually use an independent remaining quota. A key is a credential, not a bucket of tokens: API credits are associated with an organization; organization and project spend/rate limits can both apply. Two keys in the same organization do not double organization quota. Different projects can have distinct project limits but still share organization-level controls. Truly independent reserve generally means a separately billed organization. Explain this honestly in dashboard help text.
- Record usage from the Responses API response metadata: input, output, cached and (when exposed) reasoning tokens, model and selected key slot. Never record prompts, replies or actual credentials in operational usage logs.

### Required token economy
- Local request gate before any paid request.
- No API calls for memory reads/writes, local status, background idle loops, Minecraft ticks, movement/block updates or routine event ingestion.
- Save every private conversation locally. Use approved memories and a compact recent tail/summary; never resend the complete chat history each time.
- Explicit "запомни" actions and straightforward facts/corrections should be saved locally without a separate model call. Uncertain inferences go into a pending candidate queue; show review/approve/edit/reject controls.
- Trigger model-assisted learning extraction only for meaningful learning signals, preferably within the ordinary response rather than a second API request.
- Store successful/failed problem-solving episodes and reusable skills with provenance, scope, prerequisites, steps, result and confidence. Do not claim a skill is verified merely because the model suggested it.
- Use compact stable instructions, strict input/output token ceilings, low-cost routine model routing and deliberate escalation only when needed. Prompt caching may reduce repeated-prefix input cost where supported; do not assume it replaces trimming.
- Local daily/monthly usage ceilings, per-request caps, visible alerts and an emergency disable switch are required.

### Current code status after previous incorrect provider assumption
- The most recent source milestone added a generic OpenAI-compatible endpoint/model editor and a test-generation button to the dashboard. This is still present in the feature branch and has passed CI, but it does not implement the confirmed two-key OpenAI design.
- Do not ask Vitaly to configure a LAN LM Studio server, do not instruct him to test LM Studio, and do not present the prior Nika-Companion-Update.zip as the correct dual-key installation.
- Keep LM Studio pathway optional, behind an advanced provider selection/config section. The OpenAI primary/secondary route must be the default.
- No user has supplied actual API keys in chat. Never ask him to paste keys into the conversation. Keys are entered only into the local dashboard's protected fields.
- Repository remains Dharma2500/Nika-Companion, branch feature/companion-renderer-v0.4.0, PR #1 open/draft/unmerged. Do not merge without explicit approval.

### Next development sequence
1. Keep canonical docs/roadmap/README and PR description aligned with this decision across future chats.
2. Refactor provider management into a multi-credential OpenAI Responses provider with error classification, failover and telemetry; preserve the existing LM Studio-compatible adapter as optional but untested.
3. Add Windows OS credential-store adapter plus a testable fake backend; build dashboard key-entry/update/delete controls and redacted status.
4. Add request gate, token/cost accounting, hard local caps and user-configurable economy settings before increasing API traffic.
5. Evolve memory from manual-only insertion to local-first learning candidates, review controls, automatic capture of explicit memory instructions, and verified reusable skill episodes. Keep API-assisted extraction sparse and batched/in-band only on learning signals.
6. Test with fake OpenAI Responses endpoints and simulated quota/rate/auth/server failures. Only after those pass should Vitaly enter his own keys and conduct a real minimal-cost API test.
7. Keep the Minecraft JAR unchanged unless the bridge protocol or client behavior actually changes.

### Source references checked for this decision
- OpenAI Assistants API sunset and Responses API migration: https://platform.openai.com/playground/assistants
- OpenAI API credits are separate from ChatGPT subscription and associated with an API organization: https://help.openai.com/en/articles/9039756-managing-billing-for-chatgpt-and-the-api-platform
- Organization/project usage, quota and spend-limit errors: https://help.openai.com/en/articles/6614457-troubleshooting-api-usage-and-spend-limits
- Project keys, project-level budgets and rate limits: https://help.openai.com/en/articles/9186755-managing-projects-in-the-api-platform
- Rate-limit errors vs billing/quota errors: https://help.openai.com/en/articles/5955604-troubleshooting-api-rate-limits-and-429-errors


## 17. Implemented OpenAI dual-key + local-learning milestone (2026-11-19)

This section supersedes the earlier "next development" sequence in section 16. It records the code now on the feature branch, not the remaining design wishlist.

### Implemented code
- Primary OpenAI client: agent/src/nika/openai_provider.py, official POST /v1/responses. Default model is gpt-6-luna; the request sets reasoning.effort=none, store=false, no tools, and a 320-token normal output ceiling. The explicit test request uses a 64-token output ceiling.
- Dual credentials: agent/src/nika/credentials.py stores primary and secondary slots in the current Windows user's Credential Manager. Dashboard secrets are posted through a same-origin native HTML password form directly to the loopback runtime. No JavaScript reads them; the keys never go to provider.json, SQLite, Git or logs. The dashboard can replace or remove either key and displays only configured booleans and active slot.
- Failover: key 1 is tried first, key 2 is tried only on quota exhaustion, authentication failure or permission/access error. Quota/auth/permission failures put the affected slot into a one-hour cooldown. HTTP 429 rate-limit responses are classified separately and do not spend the secondary key. Invalid request/model errors, network errors and server errors do not trigger key rotation.
- Quota codes include insufficient_quota, credit_balance_exhausted, billing_hard_limit_reached, organization usage/spend limits and project spend limit. Two keys in one organization still share org-level quota.
- Usage: agent/src/nika/usage.py and schema v3 table provider_usage store only model, selected key slot, timestamp and input/output/cached/reasoning/total token counts. They never store prompts, answers or credentials. Dashboard displays daily totals and a hard daily token ceiling (default 60,000 total tokens).
- Token economy: agent/src/nika/context.py defaults to at most 8 recent messages, 4 relevant memories and an 8 KiB context object. Runtime applies a conservative local input-token estimate plus the output ceiling before a paid request. A request that would exceed the daily token ceiling is blocked locally.
- Local learning: agent/src/nika/learning.py intercepts clear explicit "запомни ..." commands and Поправка:/Исправление:/Уточнение: messages. It writes them directly to SQLite as user_taught memories with confidence 1.0, without an API call. Repeated exact explicit facts/corrections are deduplicated. Ordinary text is not automatically promoted to durable knowledge.
- Offline behavior: user messages are persisted before provider availability is checked. Explicit local learning commands still get a local reply with both OpenAI keys absent. Ordinary dialogue remains stored, but gets a truthful unavailable-provider response until a key is configured. Bridge advertises dialogue.chat so private chat can reach the local learning gate without an API key.
- Optional LM Studio: the existing OpenAI-compatible Chat Completions adapter and Base URL/model section remain as an advanced alternative. It is not primary, not enabled by default, and was not tested during this milestone. Its non-secret config remains in NIKA_DATA/config/provider.json and is now loaded at startup.
- Database schema: v3; adds provider_usage and learning_candidates while preserving schema v1/v2 content. Backups/restore migrate old schemas using the supported current schema version.
- Minecraft mod: no Java source changed. Existing JAR remains the correct one; the bridge capability is now advertised by Python runtime.

### Current limitations; do not claim these are done
- Actual key entry and API generation have not been tested against Vitaly's real OpenAI account. Do not ask him to paste API keys into chat. He will enter them only in the local dashboard after installation.
- Windows Credential Manager integration is covered by a fake-store test contract and CI, but still needs manual acceptance on Vitaly's Windows PC.
- Automatic learning currently captures only explicit remember/correction commands. It does not yet summarize all conversations, infer preferences silently, expose an approve/reject memory review UI, or verify reusable skills.
- learning_candidates table exists but review/create flows are not yet wired into the dashboard.
- Daily token ceiling is implemented. Monthly USD budget, per-key spend display, exact USD cost estimate and emergency API-off switch are still future work. Token counts are recorded per key in SQLite.
- The OpenAI connection test sends one small real request only when the user explicitly presses the dashboard test button. No test or periodic API calls happen automatically.
- No JAR update is required unless Java source or bridge protocol changes later.

### Test status / handoff
- Python CI #423 (run 44595717972) completed all six Ubuntu/Windows × Python 3.11/3.12/3.13 jobs successfully. This includes the new OpenAI adapter, credential fake-store, usage ledger, local learning and corrected offline chat contract tests.
- Later small dashboard/credential changes were in CI runs #424–#429. Verify the latest completed result for the current branch head before packaging the release ZIP.
- Fabric build #210 (run 44595995862) succeeded; no Java source changed. No JAR is to be sent.
- Repository: Dharma2500/Nika-Companion; branch: feature/companion-renderer-v0.4.0; PR #1 stays open, draft and unmerged. Do not merge without Vitaly's explicit approval.

### Local install, when the verified ZIP is delivered
1. Stop runtime: .\.venv\Scripts\python.exe -m nika.cli stop
2. Extract the source overlay ZIP directly over C:\Nika-Companion, overwrite tracked files. Preserve .venv and NIKA_DATA; they are not in the ZIP.
3. Start dashboard: .\.venv\Scripts\python.exe -m nika.cli dashboard
4. Enter key 1 and key 2 in the dashboard and save. Keys are stored in Windows Credential Manager and are not displayed again.
5. Set/keep model gpt-6-luna, daily token ceiling default 60,000. Press the explicit low-output connection test only when ready to spend a tiny amount of API usage.
6. The existing Minecraft JAR is unchanged. Test private chat, public-chat N toggle, and explicit local commands such as "Ника, запомни: ..." before normal API dialogue.



## 18. Final CI validation and source package for the current milestone (2026-11-19)

- Final source head validated: f325bd0b1bdaff24b124b084f59e194df7366b3b.
- Python CI #433, run 44596575853: all six Ubuntu/Windows × Python 3.11/3.12/3.13 jobs passed; 185 tests passed in every matrix job; Ruff and compileall passed; source-overlay job passed.
- Source-overlay artifact ID: 14566815689. This artifact is the source package from the exact head above and contains the handoff, README, roadmap, Python code, tests and tracked mod source.
- Fabric build #217, run 44596575788, also succeeded. No Java or Fabric source changed in this milestone; do not send or replace the JAR.
- The source overlay is packaged as Nika-Companion-Update.zip with relative repository paths at archive root. It intentionally excludes .venv and NIKA_DATA. SHA-256 of the exact extracted overlay ZIP: 2bbc04183d1899e92d2232ee1f97afabecacd759dfba5c0ad449f51cc3ee6132.
- Repository branch remains feature/companion-renderer-v0.4.0, PR #1 open/draft/unmerged. Do not merge without explicit approval.
- Manual Windows acceptance remains: Credential Manager save/read/delete, OpenAI test request with Vitaly's own key(s), private chat/ N toggle and local remember/correction flows. Keys must be typed only in the local dashboard, never into chat or GitHub.
- Current implementation scope is not the full long-term learning system. Explicit remember/correction capture is implemented locally; inference review UI, reusable verified skills, monthly USD budget and emergency API disable remain future milestones.
