# Roadmap

Work proceeds by verified milestones. A milestone is not complete until its tests and acceptance checks pass.

## Phase 0: repository and local core

- [x] Establish Python package and CI checks
- [x] Add versioned SQLite schema
- [x] Add append-only local event journal
- [x] Keep local runtime data outside Git
- [ ] Verify first GitHub Actions run

## Phase 1: reliable local agent

- [ ] Structured logging with secret redaction
- [ ] Process lifecycle, graceful shutdown and health endpoint
- [ ] Backup, restore and integrity verification
- [ ] Database migration tests and crash/restart tests
- [ ] Configuration validation and diagnostics

## Phase 2: Minecraft client integration

- [ ] Fabric 1.21.11 client mod skeleton and reproducible JAR build
- [ ] Versioned localhost protocol
- [ ] Bridge authentication, payload validation and replay protection
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
