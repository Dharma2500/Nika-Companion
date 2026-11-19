# Project context pointer

> **This file is superseded.** It is retained so old links do not break, but it is not an active source of project state.

The only canonical full handoff is [docs/CHAT_CONTEXT.md](../CHAT_CONTEXT.md).

Read that file before continuing development. It contains the current branch and PR, user requirements, architecture, implemented behavior, verification state, CI diagnosis, privacy constraints and exact next actions.

The chronological record is [CHAT_LOG.md](CHAT_LOG.md).

Do not use the historical v0.5.0 or earlier implementation notes in this file's Git history as current instructions. In particular, the current v0.5.1 private chat behavior is fail-closed: when Nika is unavailable in private mode, ordinary text is blocked locally and must never silently fall through to multiplayer chat.