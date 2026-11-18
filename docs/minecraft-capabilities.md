# Minecraft client capability inventory

Target: Minecraft 1.21.11, Fabric client, official Mojang mappings.

This inventory separates data that the current mod already sends, data that is technically readable from the local client, and data that remains excluded. A Minecraft API exposing a field does not automatically authorize Nika to collect it.

## Collection rules

1. Read only from the active client session and its client-side world/player objects.
2. Do not query server internals, issue server commands, bypass permissions or inspect hidden state.
3. Keep observation read-only and explicitly user-triggered. No tick polling or background world scanning.
4. Never force-load chunks. Any spatial read must first confirm that the relevant position is already loaded.
5. Keep payloads bounded and versioned. Persist observations locally before any optional model analysis.
6. Treat player-owned data as private. A field can be technically available and still remain excluded until separately approved.

## Implemented and locally verified

| Area | Data | Source / limits |
|---|---|---|
| Client | Minecraft version, mod version | Static build metadata |
| World | Dimension identifier | Active ClientLevel |
| Player | X/Y/Z, health, food level, selected item ID | Local player; selected item ID only, not the inventory |
| Nearby blocks | Block IDs and state properties | 5×3×5 sample around the player; loaded client chunks only; up to 32 non-air blocks and 12 properties per block |
| Transport | Runtime handshake and observation acknowledgement | Signed loopback bridge; HMAC and nonce replay protection |

The block observer reads BlockState only. It does not inspect block entities, containers, sign text, NBT or other players.

## Candidate capabilities verified against the 1.21.11 client API

These are technically exposed through the client-side Minecraft API and are candidates for a future observation schema. They are not all collected today.

| Priority | Candidate | Client API surface | Why it may help | Guard |
|---|---|---|---|---|
| P1 | Biome at player position | LevelReader.getBiome(BlockPos) | Identifies the local environment | Query only the player's already-loaded position |
| P1 | Time of day | Level.getDayTime() | Helps interpret daylight, night and timing-sensitive tasks | Send a compact time-of-day value, not a world save or full world metadata |
| P1 | Rain / thunder state | Level.isRaining(), Level.isThundering() | Adds basic environmental context | Read current client-visible weather only |
| P1 | Local light level | LevelReader.getLightLevel(BlockPos) | Helps reason about darkness and spawn safety | Query only the player's current loaded position |
| P1 | Game mode | Player.gameMode() | Changes what actions and advice are appropriate | Report the local player's current mode only |
| P1 | Movement state | Entity.onGround(), isSprinting(), isSwimming(), isCrouching() | Distinguishes standing, running, swimming and crouching | One-shot booleans only; no movement history |
| P2 | Targeted block | Local crosshair hit result plus BlockHitResult | Lets Nika identify the block the player is looking at | Only a block hit in a loaded client chunk; no entity target or raycast expansion |

The project build uses Mojang's official mappings. The methods above were checked against the 1.21.11 mapped API, including ClientLevel inheritance from Level, and LocalPlayer inheritance from the player/entity API.

## Explicitly excluded

- Full player inventory, armor contents, ender chest, item stacks, counts, components or NBT
- Block entity data, chest/container contents, sign text or command block data
- Chat messages, private messages, commands or server chat history
- Server address, server name, account identity, UUID or authentication/session secrets
- Lists or details of other players and entities
- World seed, server files, hidden server state, anti-cheat data or permission bypasses
- Automatic polling, continuous region scans or one-model-call-per-game-event behavior

The currently included selected_item value is only the registry identifier of the item in the selected hotbar slot. It does not authorize reading the rest of the inventory.

## Recommended next increment

Observation v3 should add only the P1 fields: biome, time of day, rain/thunder, local light level, game mode and one-shot movement-state booleans. Keep /nika observe manual, preserve the 8 KiB payload ceiling, and continue to reject unknown fields server-side. The targeted block is deferred to a later, separately tested increment.

Before implementation, update the Python validator, JSON Schema and tests together with the Fabric payload. Preserve v1/v2 compatibility and persist v3 as minecraft.observation.v3.

## References

- [Fabric 1.21.11 client commands](https://github.com/FabricMC/fabric-docs/blob/main/versions/1.21.11/develop/commands/basics.md)
- [Minecraft 1.21.11 ClientLevel](https://mappings.dev/1.21.11/net/minecraft/client/multiplayer/ClientLevel.html)
- [Minecraft 1.21.11 Level](https://mappings.dev/1.21.11/net/minecraft/world/level/Level.html)
- [Minecraft 1.21.11 LevelReader](https://mappings.dev/1.21.11/net/minecraft/world/level/LevelReader.html)
- [Minecraft 1.21.11 Player](https://mappings.dev/1.21.11/net/minecraft/world/entity/player/Player.html)
- [Minecraft 1.21.11 Entity](https://mappings.dev/1.21.11/net/minecraft/world/entity/Entity.html)
- [Minecraft 1.21.11 LocalPlayer](https://mappings.dev/1.21.11/net/minecraft/client/player/LocalPlayer.html)
