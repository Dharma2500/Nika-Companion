# Nika Companion: Fabric client mod

The Fabric 1.21.11 client-side component of the Nika-Companion project.

## Current milestone

- Client-only Fabric mod entry point
- Client commands: `/nika status`, `/nika connect`
- Reproducible Gradle wrapper build
- GitHub Actions build artifact
- Authenticated protocol-v1 read-only handshake via `/nika connect`
- No world observation, chat transfer or world-changing actions yet

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
- World observation: not enabled

The `/nika connect` command checks the Python runtime through the authenticated
loopback handshake. Start the Python runtime first. The first protocol version
only confirms service identity and health; it does not transmit world state,
chat, or memory.
