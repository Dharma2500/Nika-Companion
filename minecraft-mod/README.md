# Nika Companion: Fabric client mod

The Fabric 1.21.11 client-side component of the Nika-Companion project.

## Current milestone

- Client-only Fabric mod entry point
- Client commands: `/nika status`, `/nika connect`, `/nika observe`
- Reproducible Gradle wrapper build
- GitHub Actions build artifact
- Authenticated protocol-v1 read-only handshake via `/nika connect`
- Explicit one-shot observation via `/nika observe` (player status plus a loaded-only 5×3×5 block sample; maximum 32 blocks)
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
build/libs/nika-companion-0.2.0.jar
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
against the versioned observation schemas (`observation-v1` and `observation-v2`) and appends it to the local
SQLite event journal. Observation is user-triggered, bounded to 8 KiB and
v2 includes up to 32 non-air blocks from a loaded-only 5×3×5 region, with block IDs and up to 12 state properties per block. It does not read block entities, container contents, chat, inventories, server address or other players. The request remains bounded to 8 KiB.
