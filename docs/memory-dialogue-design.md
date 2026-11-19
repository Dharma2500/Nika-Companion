# Nika Intelligence: memory and plain-chat dialogue design

Status: text-first foundation, authenticated private chat, OpenAI Responses dual-key provider, local explicit-learning gate and token-usage ledger are implemented on the feature branch. Real OpenAI account and Windows Credential Manager acceptance remain open. LM Studio is optional and is not being tested.

## Product goal

Nika must accept ordinary text written in the Minecraft chat field. Vitaly must not need to type `/nika ask`, a slash command, a prefix or a special keyword for every message. The chat should feel like talking to a companion standing next to the player.

The first dialogue milestone is text-only. Voice, proactive behavior and world-changing actions remain out of scope until the text pipeline and memory are reliable.

## Chat UX and routing

- When Nika is summoned, local Nika-chat mode becomes active.
- Vitaly opens the regular Minecraft chat and writes an ordinary sentence. No `/nika ask`, slash prefix or command is used.
- A configurable key binding, initially defaulting to **N**, toggles between private Nika chat and normal server chat. The binding is configurable in Minecraft Controls.
- In private Nika-chat mode, an ordinary chat message is consumed locally and is never sent to the multiplayer server. Nika's response is also displayed locally.
- In normal server-chat mode, ordinary text is sent to the server as usual.
- Slash commands remain commands and are never routed as dialogue. The chat interception must not block Minecraft commands or existing `/nika` utility commands.
- If Nika is not summoned, ordinary messages use normal server chat. If private Nika mode is active but the local Python bridge/provider is unavailable before send, the message falls back to normal server chat with a clear local warning. Messages must never be silently swallowed. Vitaly can press N to explicitly choose public server chat.
- The current mode must be visible in the chat UI or a small local status indicator so the player always knows where a message will go.

Implementation hook: Fabric API 1.21.11 `ClientSendMessageEvents.ALLOW_CHAT` can prevent a client chat message from being sent. Commands have a separate `ALLOW_COMMAND` event and command callbacks. The local-mode listener should cancel only ordinary messages while private Nika-chat mode is active. The canceled-message callback then queues the request asynchronously through the bridge.

## Privacy and transport

- The Minecraft client sends only the exact text the player typed, a conversation identifier and bounded client metadata.
- The message is sent only to the local Python runtime over IPv4 loopback.
- The existing HMAC-SHA256, timestamp window and one-use nonce/replay protection are reused.
- New route: `POST /bridge/v1/chat`.
- Request JSON uses a strict versioned schema, duplicate-key rejection, UTF-8 validation and a conservative size limit. Initial user-message ceiling: 4,000 Unicode characters; transport ceiling: 16 KiB.
- Chat content must never be written to diagnostic logs. Message bodies are stored only in the local SQLite database.
- No received server chat, private messages, other players' messages, inventory, container data or hidden server state are collected.
- AI/provider calls must happen outside SQLite write transactions. Persist the user message before model work; persist the assistant reply after a valid response.
- A retry must not duplicate a message. A client-generated request/message ID is stored with a uniqueness constraint for idempotency in addition to HMAC nonce replay protection.

## Python data model

The current SQLite database schema is version 3. It retains the original event, memory, skill and world-fact records; adds conversations/messages and provenance/scope (v2); and adds provider_usage plus learning_candidates (v3). Typed MemoryStore, ConversationStore and UsageStore APIs are implemented.

Schema migration 2 adds:

### Conversation tables

`conversations`
- `conversation_id` primary key
- `created_at`, `updated_at`
- optional `title`
- optional `world_id` (opaque local scope identifier, not server address or account identity)

`conversation_messages`
- `message_id` primary key
- `conversation_id` foreign key with cascade delete
- `role` constrained to `user`, `assistant`, or `system`
- `content` with a strict maximum length
- `created_at`
- `source`
- `metadata_json` with bounded, non-secret metadata
- unique `request_id` for idempotent client submissions when present

### Memory provenance and scope

Extend the existing `memories` table without deleting or rewriting current records:
- `provenance_type`: `user_taught`, `observed`, `verified`, `inferred`, or `hypothesis`
- `scope`: `global` or `world`
- optional `world_id`
- bounded `tags_json`

Keep the existing `source` and `confidence` fields. Existing rows migrate with the cautious `hypothesis` provenance and `global` scope defaults; they must not be presented as user-taught or verified facts.

## Memory API

A dedicated Python module (agent/src/nika/memory.py) owns structured memory access. It exposes typed methods rather than allowing dialogue code to issue arbitrary SQL:

- `add_memory`: validate content, category, provenance, scope, tags and confidence; persist a stable memory ID.
- `get_memory`: fetch one record by ID.
- `search_memories`: retrieve a bounded list of candidate memories using query terms, scope and provenance.
- `list_recent_memories`: support review and correction tools.
- `append_message`: persist one conversation message with role and request-id validation.
- `get_message_by_request_id`: retrieve a previously persisted request for retry/idempotency checks.
- `get_recent_messages`: return recent conversation turns in chronological order.
- `create_conversation` / `get_conversation`: manage conversation identity.

The current v0.5.1 foundation exposes typed memory writes but does not yet implement automatic learning. The target behavior is local-first: an explicit "запомни..." instruction and unambiguous user corrections can be persisted locally without an API call; ambiguous inferred facts become reviewable candidates. Nika must never silently promote every assistant-generated statement into durable verified memory. The full learning loop is specified below.

## Context Builder

The Context Builder is deterministic and provider-independent. It assembles a bounded context object from trusted local sources:

1. Stable Nika personality constitution and response rules.
2. Recent messages from the active conversation, in chronological order.
3. Relevant memory candidates, including provenance, confidence and scope labels.
4. A world observation only when it is fresh and its world/dimension context is known. Manual-only observation policy remains unchanged; the Context Builder must clearly label stale or missing world information rather than inventing current state.

Initial conservative budget:
- recent messages: last 8 turns, each content-bounded
- relevant memories: at most 4
- assembled context: 8 KiB UTF-8 byte ceiling
- world context: one compact latest observation, only when freshness/scope checks pass
- assembled context: hard character/token budget configured independently of provider

The builder returns structured sections, not one unlabelled prompt string. This allows providers to format context safely and allows tests to assert exactly what was included.

## Dialogue pipeline

1. Client routes an ordinary message locally.
2. Bridge authenticates the request and validates the chat schema.
3. Python creates or loads the conversation and persists the user message.
4. Context Builder assembles recent dialogue, relevant memories and eligible world context.
5. Provider Manager selects a configured model provider and enforces timeouts and response-size limits.
6. Nika Core applies the personality constitution and capability boundary.
7. Python validates and persists the assistant response.
8. The bridge returns the reply and conversation/message IDs to the client.
9. The client displays the reply locally. No message is sent to the Minecraft server.

If no provider is configured or the provider is unavailable, Nika must say that she cannot generate a full response right now. She may still report bridge/memory status, but must not pretend that model reasoning occurred.

## Provider strategy

The main provider is the official OpenAI Responses API, using two OS-stored key slots: primary key 1 and secondary failover key 2. The existing generic OpenAI-compatible Chat Completions adapter is retained as an optional future LM Studio pathway; it is not the primary provider and LM Studio is not being tested in the current milestone. The Python Core, SQLite memory and Minecraft mod remain functional if both external keys are unavailable.

## Security and capability boundary

- Dialogue is read-only. It cannot invoke Minecraft world-changing actions.
- The first chat endpoint accepts text only. No arbitrary tool calls, command execution, file access or shell execution.
- The model receives only explicit client-supplied observations and local stored memory selected by the Context Builder.
- Untrusted text in user messages and memories is data, never executable instructions.
- The bridge remains loopback-only and authenticated.
- The user can always switch back to ordinary server chat with the configured key binding.

## Implementation status

Implemented in the current feature branch and released as Fabric v0.5.1 (private chat first shipped in v0.5.0):
- SQLite schema migration 2. Existing v1 memories are preserved; legacy rows receive cautious `hypothesis` provenance.
- Typed `MemoryStore`: add/get/recent/search with provenance, confidence, tags and global/world scope.
- Typed `ConversationStore`: conversation creation, ordered history retrieval, bounded message validation and request-id idempotency.
- Deterministic `ContextBuilder`: stable personality instructions, recent history, relevant memories with provenance labels and a hard UTF-8 byte budget.
- Initial keyword retrieval uses bounded candidate reads and Python Unicode casefolding, so Russian text is searched case-insensitively. Embeddings/semantic retrieval are not implemented.
- Current ContextBuilder intentionally returns `world_context: null`. It does not pretend to know the current world. Fresh observation attachment will be added only after a scoped/freshness contract is implemented.
- Primary OpenAI adapter in `agent/src/nika/openai_provider.py`: official Responses API, default gpt-6-luna model, reasoning effort none, store=false, tools omitted, bounded request/response and output size.
- Two API credential slots in `agent/src/nika/credentials.py`: primary and secondary, stored in Windows Credential Manager. Secrets are submitted through a same-origin native password form and never returned to the browser.
- Generic Chat Completions adapter in `agent/src/nika/provider.py` is retained only as an optional future LM Studio path; it is not primary and is not tested in this milestone.
- Fake Responses endpoint tests cover request shape, token usage parsing, quota failover to key 2, and no key rotation on transient rate-limit or malformed-request errors.
- Strict `POST /bridge/v1/chat` validates schema v1, duplicate/unknown fields, canonical UUIDs, UTF-8, a 4,000-character message ceiling and 16 KiB request ceiling.
- The chat route reuses bridge HMAC-SHA256 authentication, timestamp window and nonce replay protection.
- User messages are persisted before provider work; assistant replies are persisted after validation. Provider calls happen outside SQLite write transactions.
- Request IDs provide idempotency: retrying the same ID and same content returns the stored assistant reply without a second model call; reusing an ID with different content returns HTTP 409.
- Every private user message is persisted before provider availability is checked. If no provider is configured, ordinary dialogue returns HTTP 503 but remains stored locally. Explicit remember/correction phrases are handled locally without API access. Chat bodies are never written to runtime logs.
- The bridge advertises `dialogue.chat` so the local Python learning gate remains reachable even when both API keys are absent.
- Fabric v0.5.1 intercepts ordinary outgoing chat whenever private Nika mode is active. Messages are canceled before server send. If `dialogue.chat` is available, the client forwards the message to the local bridge and displays the reply locally; if it is unavailable, the client blocks the message locally with a warning. Slash commands remain on their separate path.
- Summoning Nika enables private chat. A configurable key binding (default N, visible in Controls) switches to public server chat. If the provider/bridge is unavailable before send, ordinary text is blocked locally with a warning and is never sent to the multiplayer server. Press N explicitly to switch to public server chat. If a request fails after interception, a local error says the text was not sent to the server.
- The conversation UUID is local to the current client-world session and resets when the client level changes.

Not implemented or not yet verified:
- The actual OpenAI account/key acceptance on Vitaly's Windows machine remains open. LM Studio is retained as an optional advanced alternative and has not been configured or tested.
- Full provider budgets, failover/rotation and automatic mode selection.
- Manual in-game acceptance of private routing/no server leakage when dialogue.chat is available, key binding, slash passthrough, explicit public fallback with warning when unavailable and world transitions.
- Automatic memory extraction, voice and autonomous Minecraft actions.

## Implementation order

1. [x] Database schema migration 2 and tests.
2. [x] Typed ConversationStore and MemoryStore APIs.
3. [x] Deterministic ContextBuilder and tests for provenance, scope and budgets; live world context intentionally omitted until freshness checks exist.
4. [x] Provider interface plus explicit environment configuration and bounded OpenAI-compatible adapter with fake-server tests.
5. [x] Strict chat request/response schema and authenticated `/bridge/v1/chat` endpoint.
6. [x] Fabric plain-text private chat routing and local reply rendering.
7. [ ] Verify manually in Minecraft 1.21.11: private routing/no server leakage, N toggle, slash passthrough, provider-offline public fallback with warning, long/repeated messages and world transitions.

Voice and autonomous actions are explicitly deferred until text dialogue is reliable.


## Learning-first memory and token economy (authoritative design, 2026-11-19)

The project's primary learning mechanism is local persistent memory, not continuous API calls and not continuous retraining of model weights.

### What Nika learns locally
- Keep the conversation archive in SQLite independently of provider availability.
- Store durable user preferences, project facts, corrections, decisions, successful procedures, failed attempts and lessons learned as typed memory/skill records.
- Preserve provenance (user_taught, observed, verified, inferred, hypothesis), confidence, timestamp, and global/world scope. Corrections supersede stale facts without erasing history.
- An explicit "запомни ..." instruction may create a user_taught memory locally without a separate model call.
- Deterministic local rules may identify likely learning signals such as corrections, repeated preferences, a confirmed successful fix or a failure. Ambiguous inferred facts become reviewable candidates, not unquestioned truths.
- Where semantic extraction is genuinely needed, perform it only when a learning signal exists and preferably as a small structured sidecar in the already-required dialogue response. Do not launch a second model request just to summarize every message.
- Give Vitaly local controls to review, edit, approve, reject and delete memories. Skill promotion requires a confirmed outcome or repeatable evidence.
- Retrieve memory locally. Initial bounded keyword retrieval already exists; SQLite FTS and optional local embeddings may improve it later without sending memory indexes to OpenAI.
- Keep the learning history and approved memories available if both API keys are unavailable.

### What "learning" does not mean
- Do not fine-tune or update model weights after every conversation. That would be expensive, slow, difficult to validate and unnecessary for remembering personal/project knowledge.
- Model weights are not the source of truth. NIKA_DATA and SQLite are.
- Do not treat every assistant-generated statement as a fact. Assistant text is not automatically verified knowledge.

### API call policy
- Never call OpenAI for background polling, idle time, Minecraft ticks, movement/block updates, memory lookup, local status, or a deterministic local operation.
- Every ordinary user message is persisted locally first. Use a local-only path for explicit memory operations, known local facts, status and cached/deterministic results when possible.
- Use OpenAI when a message actually needs language generation, synthesis, novel reasoning or extraction that deterministic local logic cannot provide.
- Do not resend the whole conversation. Construct a compact request from the stable Nika constitution, a short recent tail or rolling summary, and only a few relevant approved memories.
- Summaries are generated only at deliberate thresholds / session consolidation, not by one API request per message. Prefer local extractive consolidation where adequate.
- Keep prompts compact and stable; cap input/output tokens per request, disable tools by default, and use a cost-efficient configured model for routine work. Escalate to a more capable model only for a task that merits it.
- Cache safe, deterministic results locally with explicit invalidation. Never reuse stale or context-sensitive answers blindly.
- Record token usage and estimated spend from provider response metadata. Provide per-key usage, daily/monthly budget ceilings, warning thresholds and a hard local stop. Do not assume OpenAI's dashboard soft budget blocks traffic.
- The dashboard must clearly show when a local answer used no API, which key/model served a request, and its input/output/cached token usage, without ever revealing secret values.

### Memory vs API
The API is a temporary reasoning/generation capability. It does not own Nika's identity, history or learning. A successful API response is persisted locally; future relevant dialogue can use its compact memory without retrieving the original chat transcript or calling an API just to read it.


## Current implementation status (2026-11-19)

The earlier design text describes the intended architecture; these are the behaviors present in the current feature branch:

- OpenAI Responses API is primary. GPT-6 Luna (gpt-6-luna) is selected for low-cost routine dialogue, with reasoning effort none and a 320-token normal output cap.
- Credential slots are primary and secondary OpenAI API keys stored in Windows Credential Manager. A dashboard-native POST form sends secrets directly to the local Python runtime. The browser never reads or receives secret values.
- Secondary key failover is only for classified quota exhaustion, key authentication failure or permission/access failure. Transient 429 rate limiting does not burn the secondary key. Invalid request/model errors, network failure and server failure do not trigger key rotation.
- The local request gate blocks a paid request before sending when the daily token ceiling would be exceeded. Default ceiling is 60,000 input+output tokens per UTC day. Provider usage details are recorded in schema v3 by key slot and model.
- Context defaults are 8 recent messages, 4 retrieved memories and 8 KiB. The full conversation transcript is not resent.
- Explicit "запомни ..." and correction phrases are stored locally as user_taught memories, confidence 1.0, with exact-repeat deduplication. This is a deterministic local rule, not a model call. Ordinary assistant output is not automatically turned into a memory.
- The learning-candidate table exists for future inferred knowledge review, but automatic uncertain-candidate generation and approve/reject UI are not wired yet. Skill learning/verification is also still future work.
- User turns are persisted locally first even when no provider is available. Bridge private chat capability remains enabled to route local learning commands; ordinary AI chat without keys produces a truthful provider-unavailable response.
- Actual OpenAI credentials and live generation remain untested until Vitaly saves his own keys in the local dashboard. No key is to be sent through chat or committed to Git.
