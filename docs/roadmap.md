# Roadmap

Work proceeds by verified milestones. A milestone is not complete until its tests and acceptance checks pass.

## Phase 0: repository and local core

- [x] Establish Python package and CI checks
- [x] Add versioned SQLite schema
- [x] Add append-only local event journal
- [x] Keep local runtime data outside Git
- [x] Verify GitHub Actions matrix on Windows and Linux (Python 3.11, 3.12 and 3.13)

## Phase 1: reliable local agent

- [x] Structured storage foundation and schema migration rollback test
- [x] Consistent SQLite backup creation, verification and retention
- [x] Verify detached local runtime with authenticated loopback control
- [x] Verify start, status and graceful stop commands
- [x] Verify Windows batch launch and graceful console-close shutdown
- [x] Restore workflow with safe shutdown protection (CI-verified on Windows and Linux)
  - [x] Validate restore integrity and exact schema compatibility
  - [x] Preserve pre-restore database and SQLite sidecars
  - [x] Stage and atomically replace the database
  - [x] Automatic rollback tests for failed replacement and post-install validation
  - [x] Runtime shutdown guard and end-to-end CLI restore test
  - [x] Perform a manual restore exercise with a disposable Windows data directory
- [x] Structured JSONL logging with secret redaction and rotation
- [x] Verify secret redaction in messages, structured fields and tracebacks
- [x] Verify CLI and runtime logs use separate process-owned files
- [x] Crash/restart tests and stale runtime recovery (CI: Python 3.11–3.13; verified locally on Windows with Python 3.15.1)
- [x] Configuration validation and diagnostics
- [x] Safe data-directory migration to another disk
  - [x] Separate configurable learning/model storage path
  - [x] Runtime maintenance lock and fresh pre-migration database backup
  - [x] Copy-first migration that preserves source and skips volatile runtime state
  - [x] SQLite online backup, integrity/schema verification and destination staging
  - [x] Verify migration on Vitaly's Windows machine and switch NIKA_DATA to D:\\NIKA_DATA (doctor, runtime start/status/stop verified)
  - [x] Reject explicitly empty or invalid path environment variables
  - [x] Validate data, logs, backups, runtime and database locations before startup
  - [x] Check existing database file access and warn when it is outside NIKA_DATA
  - [x] Fail before logging or SQLite initialization when configuration is invalid
  - [x] Cover invalid paths and CLI fail-fast behavior with automated tests

## Phase 2: Minecraft client integration

- [x] Fabric 1.21.11 client mod skeleton and reproducible JAR build (CI verified on JDK 21)
- [x] Versioned localhost protocol v1 with a read-only handshake
- [x] Dedicated bridge token, HMAC-SHA256 authentication and nonce replay protection
- [ ] Verify Minecraft `/nika connect` against the updated Python runtime on Vitaly's Windows machine
- [ ] Versioned JSON payload schemas and strict validation for future observation requests
- [ ] Action-request authentication, capability validation and approval gates
- [ ] Client-only companion renderer
- [ ] Capability discovery and read-only observation first

## Phase 3: memory, skills and dialogue

- [ ] Provenance-aware memory API and retrieval
- [ ] Versioned skill format and user demonstration capture
- [ ] Dialogue engine and stable personality constitution
- [ ] Provider manager with budgets, rotation and graceful degradation

## Phase 4: safe autonomy

- [ ] Task planner with preconditions and postconditions
- [ ] Permission-aware action engine
- [ ] Approval gates for destructive or irreversible actions
- [ ] Simulation/dry-run mode and emergency stop
- [ ] Regression scenarios in a disposable test world

## Phase 5: dashboard and voice

- [ ] Local dashboard and status panel
- [ ] Memory review and correction tools
- [ ] Voice input/output
- [ ] Context-aware initiative controls

## Release gate

No autonomous world-changing behavior is enabled until the bridge, capability model, approval gates, emergency stop and disposable-world regression tests are in place.
