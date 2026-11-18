# Nika Companion: Fabric client mod

The Fabric 1.21.11 client-side component of the Nika-Companion project.

## Current milestone

- Client-only Fabric mod entry point
- Client commands: `/nika status`, `/nika connect`, `/nika observe`
- Reproducible Gradle wrapper build
- GitHub Actions build artifact
- Authenticated protocol-v1 read-only handshake via `/nika connect`
- Explicit one-shot observation via `/nika observe`
- Observation v3 includes the v2 loaded-only 5×3×5 block sample (maximum 32 non-air blocks), biome, time-of-day ticks, rain/thunder state, local light level, game mode and one-shot movement flags
- v1 and v2 payload validation and SQLite event persistence remain supported
- No automatic polling, chat transfer, inventory dump, block-entity/container contents or world-changing actions

## Requirements

- Minecraft Java Edition 1.21.11
- Fabric Loader 0.19.5 or newer
- Fabric API for Minecraft 1.21.11
- JDK 21 for local development

The mod is client-only. The `/nika status` command runs locally and does not require server permissions.

## Build on Windows

From this directory:

```powershell
.\gradlew.bat build
```

The remapped mod JAR is written to:

```
build/libs/nika-companion-0.3.0.jar
```

Copy that JAR and a matching Fabric API build into the `mods` folder of the Fabric 1.21.11 game profile.

## In-game check

Run:

```
/nika status
```

Expected status includes:

- Client mod: active
- Python bridge: not connected
- World observation: manual only; last: not sent

The `/nika connect` command checks the Python runtime through the authenticated
loopback handshake. Start the Python runtime first. The `/nika observe` command
then sends one signed JSON snapshot to the Python runtime. Python validates it
against the strict versioned observation schemas (`observation-v1`, `observation-v2`
and `observation-v3`) and appends it to the local SQLite event journal.

All observations are user-triggered and bounded to 8 KiB. The v2/v3 block sample
covers a loaded-only 5×3×5 region with up to 32 non-air blocks and up to 12 state
properties per block. V3 additionally reports the biome and environment at the
player's current loaded position, plus game mode and current movement flags.
The mod does not read inventory contents, block entities, containers, sign text,
NBT, chat, server address, account identity, other players or hidden server state.
No automatic polling or world-changing action is enabled.
