# Nika Intelligence: memory and plain-chat dialogue design

Status: text-first intelligence foundation is being implemented. Memory, conversation storage, bounded context assembly and a provider adapter exist; the authenticated chat endpoint and Minecraft chat routing do not exist yet.

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
- If Nika is not summoned or the local Python bridge is unavailable, ordinary messages must not be silently swallowed. The mod falls back to normal server chat and provides a local status indication.
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

The current database schema is version 1. It already creates `event_log`, `memories`, `skills` and `world_facts`, but there is no full Memory API or conversation history API.

The planned schema migration 2 adds:

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

Keep the existing `source` and `confidence` fields. Existing rows migrate to `user_taught` / `global` defaults only as a the cautious `hypothesis` default; they must not be presented as user-taught or verified facts.

## Memory API

A dedicated Python module owns structured memory access. It will expose typed methods rather than allowing dialogue code to issue arbitrary SQL:

- `add_memory`: validate content, category, provenance, scope, tags and confidence; persist a stable memory ID.
- `get_memory`: fetch one record by ID.
- `search_memories`: retrieve a bounded list of candidate memories using query terms, scope and provenance.
- `list_recent_memories`: support review and correction tools.
- `append_message`: persist one conversation message with role and request-id validation.
- `get_recent_messages`: return recent conversation turns in chronological order.
- `create_conversation` / `get_conversation`: manage conversation identity.

Memory insertion is explicit in the first iteration. Nika must not silently convert every generated statement into durable memory. An explicit user request such as "запомни..." can be added later as a dedicated memory operation with clear confirmation.

## Context Builder

The Context Builder is deterministic and provider-independent. It assembles a bounded context object from trusted local sources:

1. Stable Nika personality constitution and response rules.
2. Recent messages from the active conversation, in chronological order.
3. Relevant memory candidates, including provenance, confidence and scope labels.
4. A world observation only when it is fresh and its world/dimension context is known. Manual-only observation policy remains unchanged; the Context Builder must clearly label stale or missing world information rather than inventing current state.

Initial conservative budget:
- recent messages: last 12 turns, each content-bounded
- relevant memories: at most 6
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

The provider interface will be OpenAI-compatible and provider-independent. Local LM Studio is the first candidate, but no endpoint, model name or credentials are assumed until configured and tested on the machine running Nika. The Python Core, SQLite memory and Minecraft mod remain functional if the model endpoint is offline.

## Security and capability boundary

- Dialogue is read-only. It cannot invoke Minecraft world-changing actions.
- The first chat endpoint accepts text only. No arbitrary tool calls, command execution, file access or shell execution.
- The model receives only explicit client-supplied observations and local stored memory selected by the Context Builder.
- Untrusted text in user messages and memories is data, never executable instructions.
- The bridge remains loopback-only and authenticated.
- The user can always switch back to ordinary server chat with the configured key binding.

## Implementation status

Implemented in the current feature branch:
- SQLite schema migration 2. Existing v1 memories are preserved; legacy rows receive compatibility defaults and are not marked verified.
- Typed `MemoryStore`: add/get/recent/search with provenance, confidence, tags and global/world scope.
- Typed `ConversationStore`: conversation creation, ordered history retrieval, bounded message validation and request-id idempotency.
- Deterministic `ContextBuilder`: stable personality instructions, recent history, relevant memories with provenance labels and a hard UTF-8 byte budget.
- Initial keyword retrieval uses bounded candidate reads and Python Unicode casefolding, so Russian text is searched case-insensitively. Embeddings/semantic retrieval are not implemented.
- Current ContextBuilder intentionally returns `world_context: null`. It does not pretend to know the current world. Fresh observation attachment will be added only after a scoped/freshness contract is implemented.
- Provider adapter in `agent/src/nika/provider.py`: explicit `NIKA_LLM_BASE_URL`, `NIKA_LLM_MODEL` and optional `NIKA_LLM_API_KEY`; no hard-coded model or host.
- OpenAI-compatible `/chat/completions` request via Python standard library, without third-party HTTP dependencies.
- Bounded provider timeout (1–120 seconds), request payload (32 KiB), response body (64 KiB), reply text (12,000 characters), model name, token limit and temperature.
- Sanitized provider errors; request/response body and API key are not written to diagnostics logs.
- Fake local HTTP-server tests cover config validation, response parsing, payload shape, HTTP errors and oversized output.

Not implemented yet:
- Verification/configuration of the real LM Studio endpoint and model ID on the PC running Nika.
- Full provider budgets, failover/rotation and automatic mode selection.
- Authenticated chat endpoint.
- Fabric chat input interception, key binding and local response rendering.
- Automatic memory extraction or voice.

## Implementation order

1. Database schema migration 2 and tests.
2. Typed ConversationStore and MemoryStore APIs.
3. Deterministic ContextBuilder and tests for provenance, scope, freshness and budgets.
4. [x] Provider interface plus explicit environment configuration and bounded OpenAI-compatible adapter with fake-server tests. Verify the real LM Studio endpoint/model before enabling it.
5. Strict chat request/response schema and authenticated `/bridge/v1/chat` endpoint.
6. Fabric chat routing and local reply rendering.
7. Manual Minecraft 1.21.11 tests: private routing, server-chat toggle, slash-command passthrough, offline fallback, long messages, repeated submissions, world changes and no chat leakage to the server.

Voice and autonomous actions are explicitly deferred until the text dialogue milestone passes.
