package ru.vitaly.nika;

import com.mojang.blaze3d.platform.InputConstants;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.fabricmc.fabric.api.client.message.v1.ClientSendMessageEvents;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;
import net.minecraft.client.multiplayer.ClientLevel;

import java.util.UUID;

/**
 * Routes ordinary outgoing chat to Nika privately when the local chat mode is
 * active. Slash commands use a separate Fabric event and are never intercepted.
 */
final class NikaChatClient {
    private static final KeyMapping.Category CATEGORY = KeyMapping.Category.register(
        Identifier.fromNamespaceAndPath("nika_companion", "general")
    );

    private static final KeyMapping TOGGLE_PRIVATE_CHAT = KeyBindingHelper.registerKeyBinding(
        new KeyMapping(
            "key.nika_companion.toggle_private_chat",
            InputConstants.Type.KEYSYM,
            InputConstants.KEY_N,
            CATEGORY
        )
    );

    private static boolean privateMode;
    private static ClientLevel conversationLevel;
    private static String conversationId = UUID.randomUUID().toString();

    private NikaChatClient() {
    }

    static void initialize() {
        ClientSendMessageEvents.ALLOW_CHAT.register(NikaChatClient::allowOutgoingChat);
        ClientTickEvents.END_CLIENT_TICK.register(NikaChatClient::tick);
    }

    static void setPrivateMode(boolean enabled) {
        privateMode = enabled;
        if (enabled) {
            resetConversationIfNeeded(Minecraft.getInstance());
        }
    }

    static String getStatus() {
        if (!privateMode || !CompanionRenderer.isEnabled()) {
            return "server chat";
        }
        return BridgeClient.isChatAvailable()
            ? "private Nika chat"
            : "private Nika chat (offline; messages blocked locally)";
    }

    private static void tick(Minecraft client) {
        resetConversationIfNeeded(client);

        // Do not react to N while another screen is open: the player may be
        // typing that letter in chat. Consume and discard any queued key press.
        if (client.screen != null) {
            while (TOGGLE_PRIVATE_CHAT.consumeClick()) {
                // Discard key presses made while typing or using another screen.
            }
            return;
        }

        while (TOGGLE_PRIVATE_CHAT.consumeClick()) {
            if (!CompanionRenderer.isEnabled()) {
                privateMode = false;
                showLocal(client, "Ника скрыта. Сначала вызови /nika.");
                continue;
            }

            privateMode = !privateMode;
            if (privateMode) {
                resetConversationIfNeeded(client);
                if (BridgeClient.isChatAvailable()) {
                    showLocal(client, "Ника: приватный чат включён. Пиши обычным сообщением.");
                } else {
                    showLocal(
                        client,
                        "Ника: приватный режим включён, но bridge/модель недоступны. "
                            + "Сообщения не будут отправлены. Нажми N, чтобы включить чат сервера."
                    );
                }
            } else {
                showLocal(client, "Ника: приватный чат выключен. Сообщения идут в чат сервера.");
            }
        }
    }

    private static boolean allowOutgoingChat(String message) {
        if (!privateMode || !CompanionRenderer.isEnabled()) {
            return true;
        }

        // ALLOW_CHAT is separate from ALLOW_COMMAND, but keep this guard as a
        // defence against future API changes or custom chat-screen callers.
        if (message.startsWith("/")) {
            return true;
        }

        Minecraft client = Minecraft.getInstance();
        if (client.player == null || client.level == null) {
            return true;
        }

        if (!BridgeClient.isChatAvailable()) {
            client.execute(() -> showLocal(
                client,
                "Ника пока недоступна. Сообщение не отправлено. "
                    + "Нажми N, чтобы явно переключиться на чат сервера."
            ));
            return false;
        }

        String text = message.strip();
        if (text.isEmpty()) {
            return true;
        }
        if (text.length() > 4000) {
            client.execute(() -> showLocal(
                client,
                "Ника: сообщение длиннее 4000 символов. Оно не отправлено."
            ));
            return false;
        }

        String activeConversationId = resetConversationIfNeeded(client);
        client.execute(() -> showLocal(client, "Ты → Ника: " + text));

        BridgeClient.submitChat(activeConversationId, text).whenComplete((reply, error) ->
            client.execute(() -> {
                if (client.player == null) {
                    return;
                }
                if (error != null) {
                    showLocal(
                        client,
                        "Ника: ошибка связи. Текст не был отправлен в чат сервера. "
                            + "Нажми N, чтобы переключиться на серверный чат."
                    );
                    return;
                }
                showLocal(client, "Ника: " + reply);
            })
        );

        // The user message is now handled only by the local Python bridge.
        return false;
    }

    private static String resetConversationIfNeeded(Minecraft client) {
        ClientLevel level = client.level;
        if (level != conversationLevel) {
            conversationLevel = level;
            conversationId = UUID.randomUUID().toString();
        }
        return conversationId;
    }

    private static void showLocal(Minecraft client, String message) {
        if (client.player != null) {
            client.player.displayClientMessage(Component.literal(message), false);
        }
    }
}
