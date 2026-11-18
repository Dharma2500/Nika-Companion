package ru.vitaly.nika;

import com.google.gson.JsonObject;
import net.fabricmc.api.ClientModInitializer;
import net.minecraft.client.Minecraft;
import net.fabricmc.fabric.api.client.command.v2.ClientCommandManager;
import net.fabricmc.fabric.api.client.command.v2.ClientCommandRegistrationCallback;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.chat.Component;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Client-only entry point for Nika Companion.
 *
 * Observations are collected only after an explicit /nika observe command.
 * The client adapter never performs world-changing actions.
 */
public final class NikaCompanionClient implements ClientModInitializer {
    private static final Logger LOGGER = LoggerFactory.getLogger("Nika Companion");
    private static final String MOD_VERSION = "0.1.0";
    private static final String MINECRAFT_VERSION = "1.21.11";

    @Override
    public void onInitializeClient() {
        ClientCommandRegistrationCallback.EVENT.register((dispatcher, registryAccess) ->
            dispatcher.register(ClientCommandManager.literal("nika")
                .executes(context -> {
                    context.getSource().sendFeedback(
                        Component.literal("Nika Companion: use /nika status, /nika connect or /nika observe")
                    );
                    return 1;
                })
                .then(ClientCommandManager.literal("status")
                    .executes(context -> {
                        String status = """
                            Nika Companion %s
                            Minecraft target: %s
                            Client mod: active
                            Python bridge: %s
                            World observation: manual (/nika observe), last: %s
                            """.formatted(
                                MOD_VERSION,
                                MINECRAFT_VERSION,
                                BridgeClient.getLastStatus(),
                                BridgeClient.getLastObservationStatus()
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
                        observation.addProperty("schema_version", 1);

                        JsonObject clientInfo = new JsonObject();
                        clientInfo.addProperty("minecraft_version", MINECRAFT_VERSION);
                        clientInfo.addProperty("mod_version", MOD_VERSION);
                        observation.add("client", clientInfo);

                        JsonObject world = new JsonObject();
                        world.addProperty(
                            "dimension", client.level.dimension().location().toString()
                        );
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
            )
        );

        LOGGER.info("Nika Companion {} initialized for Minecraft {}.", MOD_VERSION, MINECRAFT_VERSION);
    }
}
