package ru.vitaly.nika;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import net.fabricmc.api.ClientModInitializer;
import net.minecraft.client.Minecraft;
import net.fabricmc.fabric.api.client.command.v2.ClientCommandManager;
import net.fabricmc.fabric.api.client.command.v2.ClientCommandRegistrationCallback;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.chat.Component;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.properties.Property;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;

/**
 * Client-only entry point for Nika Companion.
 *
 * Observations are collected only after an explicit /nika observe command.
 * The client adapter never performs world-changing actions.
 */
public final class NikaCompanionClient implements ClientModInitializer {
    private static final Logger LOGGER = LoggerFactory.getLogger("Nika Companion");
    private static final String MOD_VERSION = "0.4.2";
    private static final int OBSERVATION_SCHEMA_VERSION = 3;
    private static final int BLOCK_SAMPLE_RADIUS_XZ = 2;
    private static final int BLOCK_SAMPLE_RADIUS_Y = 1;
    private static final int MAX_BLOCK_SAMPLE_BLOCKS = 32;
    private static final int MAX_BLOCK_PROPERTIES = 12;
    private static final String MINECRAFT_VERSION = "1.21.11";

    @Override
    public void onInitializeClient() {
        CompanionRenderer.initialize();
        BridgeClient.ensureConnected();
        net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents.END_CLIENT_TICK.register(
            client -> BridgeClient.ensureConnected()
        );

        ClientCommandRegistrationCallback.EVENT.register((dispatcher, registryAccess) -> {
            var nikaCommand = ClientCommandManager.literal("nika")
                .executes(context -> {
                    CompanionRenderer.summon();
                    context.getSource().sendFeedback(Component.literal("Ника: я рядом."));
                    return 1;
                })
                .then(ClientCommandManager.literal("dismiss")
                    .executes(context -> {
                        CompanionRenderer.dismiss();
                        context.getSource().sendFeedback(Component.literal("Ника: я отойду."));
                        return 1;
                    }))
                .then(ClientCommandManager.literal("status")
                    .executes(context -> {
                        String status = """
                            Nika Companion %s
                            Minecraft target: %s
                            Client mod: active
                            Python bridge: %s
                            World observation: manual (/nika observe), last: %s
                            Local companion: %s
                            """.formatted(
                                MOD_VERSION,
                                MINECRAFT_VERSION,
                                BridgeClient.getLastStatus(),
                                BridgeClient.getLastObservationStatus(),
                                CompanionRenderer.isEnabled() ? "summoned" : "hidden"
                            );
                        context.getSource().sendFeedback(Component.literal(status));
                        return 1;
                    }))
                .then(ClientCommandManager.literal("connect")
                    .executes(context -> {
                        context.getSource().sendFeedback(
                            Component.literal("Nika: checking the local Python bridge...")
                        );
                        BridgeClient.connect().thenAccept(message ->
                            Minecraft.getInstance().execute(() -> {
                                if (Minecraft.getInstance().player != null) {
                                    Minecraft.getInstance().player.displayClientMessage(
                                        Component.literal(message), false
                                    );
                                } else {
                                    LOGGER.info(message);
                                }
                            })
                        );
                        return 1;
                    }))
                .then(ClientCommandManager.literal("observe")
                    .executes(context -> {
                        Minecraft client = Minecraft.getInstance();
                        if (client.player == null || client.level == null) {
                            context.getSource().sendFeedback(
                                Component.literal("Nika: enter a world before requesting an observation.")
                            );
                            return 0;
                        }

                        JsonObject observation = new JsonObject();
                        observation.addProperty("schema_version", OBSERVATION_SCHEMA_VERSION);

                        JsonObject clientInfo = new JsonObject();
                        clientInfo.addProperty("minecraft_version", MINECRAFT_VERSION);
                        clientInfo.addProperty("mod_version", MOD_VERSION);
                        observation.add("client", clientInfo);

                        JsonObject world = new JsonObject();
                        world.addProperty(
                            "dimension", client.level.dimension().identifier().toString()
                        );
                        world.add("block_sample", collectBlockSample(client));

                        BlockPos playerPosition = client.player.blockPosition();
                        if (!client.level.hasChunkAt(playerPosition)) {
                            context.getSource().sendFeedback(
                                Component.literal("Nika: the player chunk is not loaded yet. Retry in a moment.")
                            );
                            return 0;
                        }

                        JsonObject environment = new JsonObject();
                        String biomeId = client.level.getBiome(playerPosition)
                            .unwrapKey()
                            .map(key -> key.identifier().toString())
                            .orElse("unknown:unknown");
                        environment.addProperty("biome", biomeId);
                        environment.addProperty(
                            "time_of_day_ticks",
                            (int) Math.floorMod(client.level.getDayTime(), 24000L)
                        );
                        environment.addProperty("raining", client.level.isRaining());
                        environment.addProperty("thundering", client.level.isThundering());
                        environment.addProperty(
                            "light_level",
                            client.level.getMaxLocalRawBrightness(playerPosition)
                        );
                        world.add("environment", environment);
                        observation.add("world", world);

                        JsonObject player = new JsonObject();
                        player.addProperty("x", client.player.getX());
                        player.addProperty("y", client.player.getY());
                        player.addProperty("z", client.player.getZ());
                        player.addProperty("health", client.player.getHealth());
                        player.addProperty(
                            "food_level", client.player.getFoodData().getFoodLevel()
                        );
                        player.addProperty(
                            "selected_item",
                            BuiltInRegistries.ITEM.getKey(
                                client.player.getInventory().getSelectedItem().getItem()
                            ).toString()
                        );

                        JsonObject playerState = new JsonObject();
                        playerState.addProperty("game_mode", client.player.gameMode().getName());
                        playerState.addProperty("on_ground", client.player.onGround());
                        playerState.addProperty("sprinting", client.player.isSprinting());
                        playerState.addProperty("swimming", client.player.isSwimming());
                        playerState.addProperty("crouching", client.player.isCrouching());
                        player.add("state", playerState);
                        observation.add("player", player);

                        context.getSource().sendFeedback(
                            Component.literal("Nika: sending one local observation...")
                        );
                        BridgeClient.submitObservation(observation).thenAccept(message ->
                            Minecraft.getInstance().execute(() -> {
                                if (Minecraft.getInstance().player != null) {
                                    Minecraft.getInstance().player.displayClientMessage(
                                        Component.literal(message), false
                                    );
                                } else {
                                    LOGGER.info(message);
                                }
                            })
                        );
                        return 1;
                    }))

                );

            dispatcher.register(nikaCommand);
        });

        LOGGER.info("Nika Companion {} initialized for Minecraft {}.", MOD_VERSION, MINECRAFT_VERSION);
    }

    /**
     * Read a tiny, loaded-only block region around the player.
     * Only block IDs and state properties are collected. Block entities,
     * inventories, signs, NBT and other private container contents are never read.
     */
    private static JsonObject collectBlockSample(Minecraft client) {
        BlockPos center = client.player.blockPosition();
        List<int[]> offsets = new ArrayList<>();

        for (int dy = -BLOCK_SAMPLE_RADIUS_Y; dy <= BLOCK_SAMPLE_RADIUS_Y; dy++) {
            for (int dz = -BLOCK_SAMPLE_RADIUS_XZ; dz <= BLOCK_SAMPLE_RADIUS_XZ; dz++) {
                for (int dx = -BLOCK_SAMPLE_RADIUS_XZ; dx <= BLOCK_SAMPLE_RADIUS_XZ; dx++) {
                    offsets.add(new int[]{dx, dy, dz});
                }
            }
        }

        offsets.sort(Comparator.comparingInt(
            offset -> Math.abs(offset[0]) + Math.abs(offset[1]) + Math.abs(offset[2])
        ));

        JsonArray blocks = new JsonArray();
        int scannedPositions = 0;
        int nonAirBlocks = 0;
        boolean truncated = false;

        for (int[] offset : offsets) {
            BlockPos position = center.offset(offset[0], offset[1], offset[2]);
            if (!client.level.hasChunkAt(position)) {
                continue;
            }

            scannedPositions++;
            BlockState state = client.level.getBlockState(position);
            if (state.isAir()) {
                continue;
            }

            nonAirBlocks++;
            if (blocks.size() >= MAX_BLOCK_SAMPLE_BLOCKS) {
                truncated = true;
                continue;
            }

            JsonObject block = new JsonObject();
            block.addProperty("dx", offset[0]);
            block.addProperty("dy", offset[1]);
            block.addProperty("dz", offset[2]);
            block.addProperty(
                "id", BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString()
            );

            List<Map.Entry<Property<?>, Comparable<?>>> stateValues =
                new ArrayList<>(state.getValues().entrySet());
            stateValues.sort(Comparator.comparing(entry -> entry.getKey().getName()));

            JsonObject properties = new JsonObject();
            int propertyCount = Math.min(stateValues.size(), MAX_BLOCK_PROPERTIES);
            for (int index = 0; index < propertyCount; index++) {
                Map.Entry<Property<?>, Comparable<?>> entry = stateValues.get(index);
                properties.addProperty(
                    entry.getKey().getName(),
                    formatPropertyValue(entry.getKey(), entry.getValue())
                );
            }
            block.add("properties", properties);
            block.addProperty(
                "properties_truncated", stateValues.size() > MAX_BLOCK_PROPERTIES
            );
            blocks.add(block);
        }

        JsonObject sample = new JsonObject();

        JsonObject centerData = new JsonObject();
        centerData.addProperty("x", center.getX());
        centerData.addProperty("y", center.getY());
        centerData.addProperty("z", center.getZ());
        sample.add("center", centerData);

        JsonObject range = new JsonObject();
        range.addProperty("x", BLOCK_SAMPLE_RADIUS_XZ);
        range.addProperty("y", BLOCK_SAMPLE_RADIUS_Y);
        range.addProperty("z", BLOCK_SAMPLE_RADIUS_XZ);
        sample.add("range", range);

        sample.addProperty("scanned_positions", scannedPositions);
        sample.addProperty("non_air_blocks", nonAirBlocks);
        sample.addProperty("truncated", truncated);
        sample.add("blocks", blocks);
        return sample;
    }

    @SuppressWarnings({"rawtypes", "unchecked"})
    private static String formatPropertyValue(Property<?> property, Comparable<?> value) {
        return ((Property) property).getName(value);
    }

}
