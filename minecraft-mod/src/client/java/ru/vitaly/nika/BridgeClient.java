package ru.vitaly.nika;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.util.HexFormat;
import java.util.UUID;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Protocol-v1 read-only handshake with the local Python runtime.
 *
 * The bridge token is read from the runtime status file and is never logged,
 * displayed, or sent anywhere except the loopback HMAC calculation.
 */
final class BridgeClient {
    private static final int PROTOCOL_VERSION = 1;
    private static final String HELLO_PATH = "/bridge/v1/hello";
    private static final long MAX_STATUS_FILE_BYTES = 16 * 1024;

    private static final HttpClient HTTP = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(2))
        .followRedirects(HttpClient.Redirect.NEVER)
        .build();

    private static final ExecutorService IO = Executors.newSingleThreadExecutor(task -> {
        Thread thread = new Thread(task, "nika-bridge-client");
        thread.setDaemon(true);
        return thread;
    });

    private static volatile String lastStatus = "not checked (run /nika connect)";

    private BridgeClient() {
    }

    static String getLastStatus() {
        return lastStatus;
    }

    static CompletableFuture<String> connect() {
        return CompletableFuture.supplyAsync(BridgeClient::performHandshake, IO);
    }

    private static String performHandshake() {
        try {
            BridgeConfig config = readConfig();
            String timestamp = Long.toString(Instant.now().getEpochSecond());
            String nonce = UUID.randomUUID().toString();
            String signature = sign(config.bridgeToken(), "GET", HELLO_PATH, timestamp, nonce);

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

            lastStatus = "connected (protocol v1)";
            return "Nika bridge: connected to Python runtime (protocol v1).";
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
        String nonce
    ) throws GeneralSecurityException {
        String bodyHash = HexFormat.of().formatHex(
            MessageDigest.getInstance("SHA-256").digest(new byte[0])
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
        return message;
    }

    private record BridgeConfig(int port, int pid, String bridgeToken) {
    }
}
