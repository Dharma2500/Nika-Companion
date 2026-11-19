# Nika Companion: Fabric client mod

The Fabric 1.21.11 client-side component of the Nika-Companion project.

## Current milestone

- Client-only Fabric mod entry point
- Client commands: `/nika` to summon, `/nika dismiss` to hide, `/nika status`, `/nika connect` (diagnostic), `/nika observe`
- Client-only vanilla Allay companion with independent smooth body/head rotation, critically damped inertial follow with slow random pace phases, local idle gestures, and private plain-text Nika chat (press N to switch to server chat)
- Reproducible Gradle wrapper build
- GitHub Actions build artifact
- Authenticated protocol-v1 read-only handshake with automatic connection and retry; `/nika connect` remains as a diagnostic command
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
build/libs/nika-companion-0.5.1.jar
```

Copy that JAR and a matching Fabric API build into the `mods` folder of the Fabric 1.21.11 game profile.

## In-game check

Run:

```
/nika status
```

Expected status includes:

- Client mod: active
- Python bridge: connected automatically when the local runtime is available
- World observation: manual only; last: not sent

The mod automatically checks the Python runtime through the authenticated loopback handshake and retries every five seconds until connected. `/nika connect` remains available for manual diagnostics. The `/nika observe` command
then sends one signed JSON snapshot to the Python runtime. Python validates it
against the strict versioned observation schemas (`observation-v1`, `observation-v2`
and `observation-v3`) and appends it to the local SQLite event journal.

All observations are user-triggered and bounded to 8 KiB. The v2/v3 block sample
covers a loaded-only 5×3×5 region with up to 32 non-air blocks and up to 12 state
properties per block. V3 additionally reports the biome and environment at the
player's current loaded position, plus game mode and current movement flags.
The mod does not read inventory contents, block entities, containers, sign text,
NBT, chat, server address, account identity, other players or hidden server state.
The optional companion is a local render-only Allay instance. It is never added to the client world and is not visible to the server or other players. Summon it with `/nika`; dismiss it with `/nika dismiss`. While summoned, ordinary unprefixed chat is routed privately to Nika when the local provider is available. Press N (configurable in Controls) to switch between private Nika chat and public server chat. Slash commands are unaffected. If the bridge/provider is unavailable while private mode is active, messages are blocked locally with a warning and never sent to the server. Press N to explicitly switch to public server chat. This fail-closed rule also applies when the local model becomes unavailable after Nika has been summoned. While moving, Nika follows to the right and behind the filtered travel direction. When movement stops, her world-space idle anchor stays in place while you turn to look at her. Body and head yaw are smoothed independently; she periodically glances around and makes tiny movements within a small radius of her idle anchor. Follow motion uses a critically damped spring with continuous velocity and smooth braking. Her follow speed changes randomly every few seconds and eases between slow and fast phases, so the distance to the player naturally varies without per-tick speed jumps. No automatic observation or world-changing action is enabled.
