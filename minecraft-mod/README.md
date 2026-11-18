# Nika Companion: Fabric client mod

The Fabric 1.21.11 client-side component of the Nika-Companion project.

## Current milestone

- Client-only Fabric mod entry point
- Client commands: `/nika status`, `/nika connect`, `/nika observe`
- Reproducible Gradle wrapper build
- GitHub Actions build artifact
- Authenticated protocol-v1 read-only handshake via `/nika connect`
- Explicit one-shot observation via `/nika observe` (dimension, coordinates, health, food and selected item only)
- No automatic polling, chat transfer, inventory dump or world-changing actions

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
build/libs/nika-companion-0.1.0.jar
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
against `docs/schemas/observation-v1.schema.json` and appends it to the local
SQLite event journal. Observation is user-triggered, bounded to 8 KiB and
contains no chat, inventory contents, server address or other players.
