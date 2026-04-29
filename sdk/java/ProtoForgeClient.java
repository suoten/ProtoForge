package io.github.suoten.protoforge;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;
import java.util.HashMap;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.JsonNode;

public class ProtoForgeClient {
    private final String baseUrl;
    private final HttpClient httpClient;
    private final ObjectMapper objectMapper;
    private String token;

    public ProtoForgeClient(String baseUrl) {
        this.baseUrl = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .build();
        this.objectMapper = new ObjectMapper();
    }

    public void login(String username, String password) throws Exception {
        Map<String, String> body = new HashMap<>();
        body.put("username", username);
        body.put("password", password);
        JsonNode response = post("/api/v1/auth/login", body);
        this.token = response.get("access_token").asText();
    }

    public JsonNode getHealth() throws Exception {
        return get("/health");
    }

    public JsonNode listDevices() throws Exception {
        return get("/api/v1/devices");
    }

    public JsonNode getDevice(String deviceId) throws Exception {
        return get("/api/v1/devices/" + deviceId);
    }

    public JsonNode createDevice(Map<String, Object> config) throws Exception {
        return post("/api/v1/devices", config);
    }

    public JsonNode deleteDevice(String deviceId) throws Exception {
        return delete("/api/v1/devices/" + deviceId);
    }

    public JsonNode startDevice(String deviceId) throws Exception {
        return post("/api/v1/devices/" + deviceId + "/start", new HashMap<>());
    }

    public JsonNode stopDevice(String deviceId) throws Exception {
        return post("/api/v1/devices/" + deviceId + "/stop", new HashMap<>());
    }

    public JsonNode readPoints(String deviceId) throws Exception {
        return get("/api/v1/devices/" + deviceId + "/points");
    }

    public JsonNode writePoint(String deviceId, String pointName, Object value) throws Exception {
        Map<String, Object> body = new HashMap<>();
        body.put("value", value);
        return put("/api/v1/devices/" + deviceId + "/points/" + pointName, body);
    }

    public JsonNode listScenarios() throws Exception {
        return get("/api/v1/scenarios");
    }

    public JsonNode startScenario(String scenarioId) throws Exception {
        return post("/api/v1/scenarios/" + scenarioId + "/start", new HashMap<>());
    }

    public JsonNode stopScenario(String scenarioId) throws Exception {
        return post("/api/v1/scenarios/" + scenarioId + "/stop", new HashMap<>());
    }

    public JsonNode getSettings() throws Exception {
        return get("/api/v1/settings");
    }

    public JsonNode updateSettings(Map<String, Object> settings) throws Exception {
        return put("/api/v1/settings", settings);
    }

    public JsonNode exportBackup() throws Exception {
        return get("/api/v1/backup");
    }

    private JsonNode get(String path) throws Exception {
        HttpRequest.Builder builder = HttpRequest.newBuilder()
                .uri(URI.create(baseUrl + path))
                .timeout(Duration.ofSeconds(30))
                .GET();
        if (token != null) {
            builder.header("Authorization", "Bearer " + token);
        }
        HttpResponse<String> response = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofString());
        return objectMapper.readTree(response.body());
    }

    private JsonNode post(String path, Object body) throws Exception {
        String json = objectMapper.writeValueAsString(body);
        HttpRequest.Builder builder = HttpRequest.newBuilder()
                .uri(URI.create(baseUrl + path))
                .timeout(Duration.ofSeconds(30))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(json));
        if (token != null) {
            builder.header("Authorization", "Bearer " + token);
        }
        HttpResponse<String> response = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofString());
        return objectMapper.readTree(response.body());
    }

    private JsonNode put(String path, Object body) throws Exception {
        String json = objectMapper.writeValueAsString(body);
        HttpRequest.Builder builder = HttpRequest.newBuilder()
                .uri(URI.create(baseUrl + path))
                .timeout(Duration.ofSeconds(30))
                .header("Content-Type", "application/json")
                .PUT(HttpRequest.BodyPublishers.ofString(json));
        if (token != null) {
            builder.header("Authorization", "Bearer " + token);
        }
        HttpResponse<String> response = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofString());
        return objectMapper.readTree(response.body());
    }

    private JsonNode delete(String path) throws Exception {
        HttpRequest.Builder builder = HttpRequest.newBuilder()
                .uri(URI.create(baseUrl + path))
                .timeout(Duration.ofSeconds(30))
                .DELETE();
        if (token != null) {
            builder.header("Authorization", "Bearer " + token);
        }
        HttpResponse<String> response = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofString());
        return objectMapper.readTree(response.body());
    }
}
