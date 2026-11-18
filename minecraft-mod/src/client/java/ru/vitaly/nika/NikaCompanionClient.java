package ru.vitaly.nika;

import net.fabricmc.api.ClientModInitializer;
import net.minecraft.client.Minecraft;
import net.fabricmc.fabric.api.client.command.v2.ClientCommandManager;
import net.fabricmc.fabric.api.client.command.v2.ClientCommandRegistrationCallback;
import net.minecraft.network.chat.Component;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Client-only entry point for Nika Companion.
 *
 * This first milestone deliberately registers no networking and performs no
 * world-changing actions. It provides a small, verifiable in-game foothold.
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
                        Component.literal("Nika Companion: use /nika status or /nika connect")
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
                            World observation: not enabled
                            """.formatted(MOD_VERSION, MINECRAFT_VERSION, BridgeClient.getLastStatus());
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
            )
        );

        LOGGER.info("Nika Companion {} initialized for Minecraft {}.", MOD_VERSION, MINECRAFT_VERSION);
    }
}
