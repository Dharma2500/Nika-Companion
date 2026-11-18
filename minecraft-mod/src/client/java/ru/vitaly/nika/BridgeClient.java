package ru.vitaly.nika;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.util.HexFormat;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.UUID;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Authenticated, loopback-only client for the local Python runtime.
 *
 * The bridge token is read from the runtime status file and is never logged,
 * displayed, or sent anywhere except the loopback HMAC calculation.
 */
final class BridgeClient {
    private static final int PROTOCOL_VERSION = 1;
    private static final String HELLO_PATH = "/bridge/v1/hello";
    private static final String OBSERVE_PATH = "/bridge/v1/observe";
    private static final String CHAT_PATH = "/bridge/v1/chat";
    private static final long MAX_STATUS_FILE_BYTES = 16 * 1024;
    private static final int MAX_OBSERVATION_BYTES = 8 * 1024;
    private static final int MAX_CHAT_REQUEST_BYTES = 16 * 1024;
    private static final int MAX_CHAT_RESPONSE_BYTES = 64 * 1024;
    private static final int MAX_CHAT_MESSAGE_CHARS = 4000;
    private static final int MAX_CHAT_REPLY_CHARS = 12000;
    private static final long AUTO_CONNECT_RETRY_NANOS = Duration.ofSeconds(5).toNanos();
    private static final AtomicBoolean AUTO_CONNECT_IN_PROGRESS = new AtomicBoolean();

    private static final HttpClient HTTP = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(2))
        .followRedirects(HttpClient.Redirect.NEVER)
        .build();

    private static final ExecutorService IO = Executors.newSingleThreadExecutor(task -> {
        Thread thread = new Thread(task, "nika-bridge-client");
        thread.setDaemon(true);
        return thread;
    });

    private static final ExecutorService CHAT_IO = Executors.newSingleThreadExecutor(task -> {
        Thread thread = new Thread(task, "nika-chat-bridge");
        thread.setDaemon(true);
        return thread;
    });

    private static volatile String lastStatus = "waiting for local runtime (automatic reconnect enabled)";
    private static volatile long lastAutoConnectAttemptNanos;
    private static volatile String lastObservationStatus = "not sent";
    private static volatile boolean chatAvailable;

    private BridgeClient() {
    }

    static String getLastStatus() {
        return lastStatus;
    }

    static String getLastObservationStatus() {
        return lastObservationStatus;
    }

    static boolean isChatAvailable() {
        return chatAvailable;
    }

    static CompletableFuture<String> connect() {
        return CompletableFuture.supplyAsync(BridgeClient::performHandshake, IO);
    }

    /**
     * Keep the local bridge connected without requiring a manual command.
     * The check is throttled and serialized; failed attempts are retried so
     * Nika also connects when the Python runtime starts after Minecraft.
     */
    static void ensureConnected() {
        long now = System.nanoTime();
        long previousAttempt = lastAutoConnectAttemptNanos;
        if (previousAttempt != 0L && now - previousAttempt < AUTO_CONNECT_RETRY_NANOS) {
            return;
        }
        if (!AUTO_CONNECT_IN_PROGRESS.compareAndSet(false, true)) {
            return;
        }

        lastAutoConnectAttemptNanos = now;
        connect().whenComplete((message, error) -> {
            if (error != null) {
                lastStatus = "unavailable";
            }
            AUTO_CONNECT_IN_PROGRESS.set(false);
        });
    }

    static CompletableFuture<String> submitObservation(JsonObject observation) {
        byte[] body = fitObservationPayload(observation);
        if (body.length == 0 || body.length > MAX_OBSERVATION_BYTES) {
            lastObservationStatus = "rejected (payload size)";
            return CompletableFuture.completedFuture(
                "Nika observation: payload exceeds the 8 KiB limit."
            );
        }
        return CompletableFuture.supplyAsync(() -> performObservation(body), IO);
    }

    static CompletableFuture<String> submitChat(String conversationId, String message) {
        if (conversationId == null || message == null || message.isBlank()
            || message.length() > MAX_CHAT_MESSAGE_CHARS) {
            return CompletableFuture.completedFuture(
                "Ника: сообщение пустое или превышает 4000 символов."
            );
        }
        try {
            if (!UUID.fromString(conversationId).toString().equals(conversationId)) {
                return CompletableFuture.completedFuture(
                    "Ника: неверный идентификатор диалога."
                );
            }
        } catch (IllegalArgumentException error) {
            return CompletableFuture.completedFuture(
                "Ника: неверный идентификатор диалога."
            );
        }

        JsonObject payload = new JsonObject();
        payload.addProperty("schema_version", 1);
        payload.addProperty("request_id", UUID.randomUUID().toString());
        payload.addProperty("conversation_id", conversationId);
        payload.addProperty("message", message);
        byte[] body = payload.toString().getBytes(StandardCharsets.UTF_8);
        if (body.length == 0 || body.length > MAX_CHAT_REQUEST_BYTES) {
            return CompletableFuture.completedFuture(
                "Ника: сообщение превышает лимит локального моста."
            );
        }
        return CompletableFuture.supplyAsync(() -> performChat(body), CHAT_IO);
    }

    private static byte[] fitObservationPayload(JsonObject observation) {
        byte[] body = observation.toString().getBytes(StandardCharsets.UTF_8);
        if (body.length <= MAX_OBSERVATION_BYTES) {
            return body;
        }

        JsonObject world = observation.getAsJsonObject("world");
        if (world == null) {
            return body;
        }
        JsonObject sample = world.getAsJsonObject("block_sample");
        if (sample == null) {
            return body;
        }
        JsonArray blocks = sample.getAsJsonArray("blocks");
        if (blocks == null) {
            return body;
        }

        // Drop the farthest sampled blocks first. The payload remains explicit
        // about the omitted data and never exceeds the transport size limit.
        while (body.length > MAX_OBSERVATION_BYTES && !blocks.isEmpty()) {
            blocks.remove(blocks.size() - 1);
            sample.addProperty("truncated", true);
            body = observation.toString().getBytes(StandardCharsets.UTF_8);
        }
        return body;
    }

    private static String performHandshake() {
        try {
            BridgeConfig config = readConfig();
            String timestamp = Long.toString(Instant.now().getEpochSecond());
            String nonce = UUID.randomUUID().toString();
            String signature = sign(
                config.bridgeToken(), "GET", HELLO_PATH, timestamp, nonce, new byte[0]
            );

            URI endpoint = URI.create("http://127.0.0.1:" + config.port() + HELLO_PATH);
            HttpRequest request = HttpRequest.newBuilder(endpoint)
                .timeout(Duration.ofSeconds(3))
                .header("X-Nika-Bridge-Timestamp", timestamp)
                .header("X-Nika-Bridge-Nonce", nonce)
                .header("X-Nika-Bridge-Signature", signature)
                .GET()
                .build();

            HttpResponse<byte[]> response = HTTP.send(
                request, HttpResponse.BodyHandlers.ofByteArray()
            );
            if (response.body().length > MAX_STATUS_FILE_BYTES) {
                return fail("Python bridge returned an oversized response.");
            }
            if (response.statusCode() == 403) {
                return fail("Bridge authentication failed. Restart Nika and retry.");
            }
            if (response.statusCode() != 200) {
                return fail("Python bridge returned HTTP " + response.statusCode() + ".");
            }

            JsonObject payload = JsonParser.parseString(
                new String(response.body(), StandardCharsets.UTF_8)
            ).getAsJsonObject();

            int protocolVersion = payload.get("protocol_version").getAsInt();
            if (!"nika".equals(payload.get("service").getAsString())
                || !"running".equals(payload.get("state").getAsString())) {
                return fail("Unexpected response from the local bridge.");
            }
            if (protocolVersion != PROTOCOL_VERSION) {
                return fail("Bridge protocol mismatch: Python uses v"
                    + protocolVersion + ", mod supports v" + PROTOCOL_VERSION + ".");
            }
            if (payload.get("pid").getAsInt() != config.pid()) {
                return fail("Runtime identity changed during the handshake. Retry.");
            }

            chatAvailable = false;
            JsonArray capabilities = payload.getAsJsonArray("capabilities");
            if (capabilities != null) {
                for (int index = 0; index < capabilities.size(); index++) {
                    if ("dialogue.chat".equals(capabilities.get(index).getAsString())) {
                        chatAvailable = true;
                        break;
                    }
                }
            }
            lastStatus = "connected (protocol v1)";
            return chatAvailable
                ? "Nika bridge: connected; private text chat is available."
                : "Nika bridge: connected; private text chat is not configured.";
        } catch (java.nio.file.NoSuchFileException error) {
            return fail("Nika runtime status not found. Start the Python runtime first.");
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            return fail("Bridge connection was interrupted.");
        } catch (GeneralSecurityException error) {
            return fail("Could not create the secure bridge signature.");
        } catch (IOException error) {
            return fail("Local bridge unavailable. Is the Nika runtime running?");
        } catch (RuntimeException error) {
            return fail("Invalid local runtime status. Restart Nika and retry.");
        }
    }

    private static String performObservation(byte[] body) {
        try {
            BridgeConfig config = readConfig();
            String timestamp = Long.toString(Instant.now().getEpochSecond());
            String nonce = UUID.randomUUID().toString();
            String signature = sign(
                config.bridgeToken(), "POST", OBSERVE_PATH, timestamp, nonce, body
            );

            URI endpoint = URI.create("http://127.0.0.1:" + config.port() + OBSERVE_PATH);
            HttpRequest request = HttpRequest.newBuilder(endpoint)
                .timeout(Duration.ofSeconds(3))
                .header("Content-Type", "application/json")
                .header("X-Nika-Bridge-Timestamp", timestamp)
                .header("X-Nika-Bridge-Nonce", nonce)
                .header("X-Nika-Bridge-Signature", signature)
                .POST(HttpRequest.BodyPublishers.ofByteArray(body))
                .build();

            HttpResponse<byte[]> response = HTTP.send(
                request, HttpResponse.BodyHandlers.ofByteArray()
            );
            if (response.body().length > MAX_STATUS_FILE_BYTES) {
                return observationFail("Python bridge returned an oversized response.");
            }
            if (response.statusCode() == 403) {
                lastStatus = "unavailable";
                return observationFail("Bridge authentication failed. Restart Nika and retry.");
            }
            if (response.statusCode() == 400) {
                return observationFail("Python rejected the observation payload (HTTP 400).");
            }
            if (response.statusCode() == 413) {
                return observationFail("Python rejected the observation as too large.");
            }
            if (response.statusCode() != 202) {
                return observationFail(
                    "Python bridge returned HTTP " + response.statusCode() + "."
                );
            }

            JsonObject acknowledgement = JsonParser.parseString(
                new String(response.body(), StandardCharsets.UTF_8)
            ).getAsJsonObject();
            if (!"nika".equals(acknowledgement.get("service").getAsString())
                || !acknowledgement.get("accepted").getAsBoolean()
                || acknowledgement.get("schema_version").getAsInt() < 1
                || acknowledgement.get("schema_version").getAsInt() > 3) {
                return observationFail("Unexpected observation acknowledgement.");
            }

            String eventId = acknowledgement.get("event_id").getAsString();
            if (eventId.length() < 8) {
                return observationFail("Python returned an invalid event identifier.");
            }
            lastStatus = "connected (protocol v1)";
            lastObservationStatus = "accepted";
            return "Nika observation: accepted and saved locally (event "
                + eventId.substring(0, 8) + ").";
        } catch (java.nio.file.NoSuchFileException error) {
            lastObservationStatus = "unavailable";
            return "Nika runtime status not found. Start the Python runtime first.";
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            return observationFail("Observation submission was interrupted.");
        } catch (GeneralSecurityException error) {
            return observationFail("Could not create the secure observation signature.");
        } catch (IOException error) {
            return observationFail("Local bridge unavailable. Is the Nika runtime running?");
        } catch (RuntimeException error) {
            return observationFail("Invalid response from the local Python runtime.");
        }
    }

    private static String performChat(byte[] body) {
        try {
            BridgeConfig config = readConfig();
            String timestamp = Long.toString(Instant.now().getEpochSecond());
            String nonce = UUID.randomUUID().toString();
            String signature = sign(
                config.bridgeToken(), "POST", CHAT_PATH, timestamp, nonce, body
            );

            URI endpoint = URI.create("http://127.0.0.1:" + config.port() + CHAT_PATH);
            HttpRequest request = HttpRequest.newBuilder(endpoint)
                .timeout(Duration.ofSeconds(40))
                .header("Content-Type", "application/json")
                .header("X-Nika-Bridge-Timestamp", timestamp)
                .header("X-Nika-Bridge-Nonce", nonce)
                .header("X-Nika-Bridge-Signature", signature)
                .POST(HttpRequest.BodyPublishers.ofByteArray(body))
                .build();

            HttpResponse<InputStream> response = HTTP.send(
                request, HttpResponse.BodyHandlers.ofInputStream()
            );
            byte[] responseBody;
            try (InputStream stream = response.body()) {
                responseBody = stream.readNBytes(MAX_CHAT_RESPONSE_BYTES + 1);
            }
            if (responseBody.length > MAX_CHAT_RESPONSE_BYTES) {
                return "Ника: ответ превышает допустимый размер.";
            }
            if (response.statusCode() == 403) {
                chatAvailable = false;
                lastStatus = "unavailable";
                return "Ника: ошибка авторизации локального моста. Перезапусти Python runtime.";
            }
            if (response.statusCode() == 503) {
                return "Ника сейчас не может ответить: проверь доступность локальной модели.";
            }
            if (response.statusCode() == 400 || response.statusCode() == 409) {
                return "Ника: Python отклонил сообщение. Попробуй отправить его ещё раз.";
            }
            if (response.statusCode() != 200) {
                return "Ника: локальный мост вернул HTTP " + response.statusCode() + ".";
            }

            JsonObject result = JsonParser.parseString(
                new String(responseBody, StandardCharsets.UTF_8)
            ).getAsJsonObject();
            if (!"nika".equals(result.get("service").getAsString())
                || !result.get("accepted").getAsBoolean()
                || !result.has("reply")
                || !result.has("assistant_message_id")) {
                return "Ника: получен некорректный ответ локального моста.";
            }

            String reply = result.get("reply").getAsString();
            if (reply.isBlank() || reply.length() > MAX_CHAT_REPLY_CHARS) {
                return "Ника: ответ пустой или превышает лимит.";
            }
            lastStatus = "connected (protocol v1)";
            return reply;
        } catch (java.nio.file.NoSuchFileException error) {
            chatAvailable = false;
            lastStatus = "unavailable";
            return "Ника: локальный Python runtime не найден.";
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            return "Ника: отправка сообщения прервана.";
        } catch (GeneralSecurityException error) {
            return "Ника: не удалось создать подпись локального сообщения.";
        } catch (IOException error) {
            chatAvailable = false;
            lastStatus = "unavailable";
            return "Ника: локальный мост недоступен. Сообщение не отправлено на сервер.";
        } catch (RuntimeException error) {
            return "Ника: получен некорректный ответ локальной модели.";
        }
    }

    private static BridgeConfig readConfig() throws IOException {
        String configuredDirectory = System.getenv("NIKA_DATA");
        Path dataDirectory;
        if (configuredDirectory == null) {
            dataDirectory = Path.of(System.getProperty("user.home"), "NIKA_DATA");
        } else {
            if (configuredDirectory.isBlank()) {
                throw new IOException("NIKA_DATA is empty.");
            }
            dataDirectory = Path.of(configuredDirectory);
        }
        dataDirectory = dataDirectory.toAbsolutePath().normalize();

        Path statusPath = dataDirectory.resolve("runtime").resolve("status.json").normalize();
        if (!statusPath.startsWith(dataDirectory)
            || Files.isSymbolicLink(statusPath)
            || !Files.isRegularFile(statusPath, LinkOption.NOFOLLOW_LINKS)) {
            throw new java.nio.file.NoSuchFileException(statusPath.toString());
        }
        long size = Files.size(statusPath);
        if (size <= 0 || size > MAX_STATUS_FILE_BYTES) {
            throw new IOException("Runtime status file has an invalid size.");
        }

        JsonObject status = JsonParser.parseString(
            Files.readString(statusPath, StandardCharsets.UTF_8)
        ).getAsJsonObject();

        int port = status.get("port").getAsInt();
        int pid = status.get("pid").getAsInt();
        int protocolVersion = status.get("bridge_protocol_version").getAsInt();
        String bridgeToken = status.get("bridge_token").getAsString();

        if (port < 1 || port > 65535 || pid <= 0 || protocolVersion != PROTOCOL_VERSION
            || bridgeToken.length() < 32) {
            throw new IOException("Runtime status fields are invalid or outdated.");
        }
        return new BridgeConfig(port, pid, bridgeToken);
    }

    private static String sign(
        String token,
        String method,
        String path,
        String timestamp,
        String nonce,
        byte[] body
    ) throws GeneralSecurityException {
        String bodyHash = HexFormat.of().formatHex(
            MessageDigest.getInstance("SHA-256").digest(body)
        );
        String canonical = String.join(
            "\n", method.toUpperCase(), path, timestamp, nonce, bodyHash
        );
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(token.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
        return HexFormat.of().formatHex(mac.doFinal(canonical.getBytes(StandardCharsets.UTF_8)));
    }

    private static String fail(String message) {
        lastStatus = "unavailable";
        chatAvailable = false;
        return message;
    }

    private static String observationFail(String message) {
        lastObservationStatus = "failed";
        return message;
    }

    private record BridgeConfig(int port, int pid, String bridgeToken) {
    }
}
