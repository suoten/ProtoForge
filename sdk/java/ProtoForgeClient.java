package io.github.suoten.protoforge;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;
import java.util.HashMap;
import java.util.List;
import java.util.ArrayList;
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

    public void register(String username, String password) throws Exception {
        Map<String, String> body = new HashMap<>();
        body.put("username", username);
        body.put("password", password);
        post("/api/v1/auth/register", body);
    }

    public JsonNode listUsers() throws Exception {
        return get("/api/v1/auth/users");
    }

    public void changePassword(String username, String oldPassword, String newPassword) throws Exception {
        Map<String, String> body = new HashMap<>();
        body.put("username", username);
        body.put("old_password", oldPassword);
        body.put("new_password", newPassword);
        post("/api/v1/auth/change-password", body);
    }

    public void adminResetPassword(String username, String newPassword) throws Exception {
        Map<String, String> body = new HashMap<>();
        body.put("username", username);
        body.put("new_password", newPassword);
        post("/api/v1/auth/admin/reset-password", body);
    }

    public void adminUnlockUser(String username) throws Exception {
        post("/api/v1/auth/admin/unlock/" + username, new HashMap<>());
    }

    public void updateUserRole(String username, String role) throws Exception {
        Map<String, String> body = new HashMap<>();
        body.put("role", role);
        put("/api/v1/auth/users/" + username + "/role", body);
    }

    public void deleteUser(String username) throws Exception {
        delete("/api/v1/auth/users/" + username);
    }

    public JsonNode getHealth() throws Exception {
        return get("/health");
    }

    public JsonNode listProtocols() throws Exception {
        return get("/api/v1/protocols");
    }

    public JsonNode getProtocolInfo() throws Exception {
        return get("/api/v1/protocols/info");
    }

    public JsonNode getProtocolConfig(String name) throws Exception {
        return get("/api/v1/protocols/" + name + "/config");
    }

    public JsonNode getProtocolDeviceConfig(String name) throws Exception {
        return get("/api/v1/protocols/" + name + "/device-config");
    }

    public JsonNode startProtocol(String name) throws Exception {
        return post("/api/v1/protocols/" + name + "/start", new HashMap<>());
    }

    public JsonNode startProtocol(String name, Map<String, Object> config) throws Exception {
        return post("/api/v1/protocols/" + name + "/start", config);
    }

    public JsonNode stopProtocol(String name) throws Exception {
        return post("/api/v1/protocols/" + name + "/stop", new HashMap<>());
    }

    public JsonNode listDevices() throws Exception {
        return get("/api/v1/devices");
    }

    public JsonNode listDevices(String protocol) throws Exception {
        return get("/api/v1/devices?protocol=" + protocol);
    }

    public JsonNode getDevice(String deviceId) throws Exception {
        return get("/api/v1/devices/" + deviceId);
    }

    public JsonNode getDeviceConfig(String deviceId) throws Exception {
        return get("/api/v1/devices/" + deviceId + "/config");
    }

    public JsonNode getDeviceConnectionGuide(String deviceId) throws Exception {
        return get("/api/v1/devices/" + deviceId + "/connection-guide");
    }

    public JsonNode createDevice(Map<String, Object> config) throws Exception {
        return post("/api/v1/devices", config);
    }

    public JsonNode quickCreateDevice(String templateId, String name, String deviceId, Map<String, Object> protocolConfig) throws Exception {
        // FIXED: P1 - Q17: 后端 POST /devices/quick-create 接受 protocol_config 参数；id 不应始终等于 name
        Map<String, Object> body = new HashMap<>();
        body.put("template_id", templateId);
        body.put("name", name);
        body.put("id", deviceId != null && !deviceId.isEmpty() ? deviceId : name);
        body.put("protocol_config", protocolConfig != null ? protocolConfig : new HashMap<>());
        return post("/api/v1/devices/quick-create", body);
    }

    public JsonNode updateDevice(String deviceId, Map<String, Object> config) throws Exception {
        return put("/api/v1/devices/" + deviceId, config);
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

    public JsonNode batchCreateDevices(List<Map<String, Object>> configs) throws Exception {
        return post("/api/v1/devices/batch", configs);
    }

    public JsonNode batchDeleteDevices(List<String> deviceIds) throws Exception {
        Map<String, Object> body = new HashMap<>();
        body.put("device_ids", deviceIds);
        return post("/api/v1/devices/batch/delete", body);  // FIXED: 后端为POST /devices/batch/delete
    }

    public JsonNode batchStartDevices(List<String> deviceIds) throws Exception {
        Map<String, Object> body = new HashMap<>();
        body.put("device_ids", deviceIds);
        return post("/api/v1/devices/batch/start", body);
    }

    public JsonNode batchStopDevices(List<String> deviceIds) throws Exception {
        Map<String, Object> body = new HashMap<>();
        body.put("device_ids", deviceIds);
        return post("/api/v1/devices/batch/stop", body);
    }

    public JsonNode listTemplates() throws Exception {
        return get("/api/v1/templates");
    }

    public JsonNode listTemplates(String protocol) throws Exception {
        return get("/api/v1/templates?protocol=" + protocol);
    }

    public JsonNode getTemplate(String templateId) throws Exception {
        return get("/api/v1/templates/" + templateId);
    }

    public JsonNode createTemplate(Map<String, Object> template) throws Exception {
        return post("/api/v1/templates", template);
    }

    public JsonNode updateTemplate(String templateId, Map<String, Object> data) throws Exception {
        return put("/api/v1/templates/" + templateId, data);
    }

    public JsonNode deleteTemplate(String templateId) throws Exception {
        return delete("/api/v1/templates/" + templateId);
    }

    public JsonNode searchTemplates(String query) throws Exception {
        return get("/api/v1/templates/search?q=" + java.net.URLEncoder.encode(query, "UTF-8"));  // FIXED: URL编码query参数
    }

    public JsonNode listTemplateTags() throws Exception {
        return get("/api/v1/templates/tags");
    }

    public JsonNode instantiateTemplate(String templateId, String deviceId, String deviceName, Map<String, Object> protocolConfig) throws Exception {
        // FIXED: S4 - wrap protocolConfig in {"protocol_config": ...} to match backend body.get("protocol_config")
        Map<String, Object> body = new HashMap<>();
        body.put("protocol_config", protocolConfig != null ? protocolConfig : new HashMap<>());
        return post("/api/v1/templates/" + templateId + "/instantiate?device_id=" + deviceId + "&device_name=" + deviceName, body);
    }

    public JsonNode listScenarios() throws Exception {
        return get("/api/v1/scenarios");
    }

    public JsonNode getScenario(String scenarioId) throws Exception {
        return get("/api/v1/scenarios/" + scenarioId);
    }

    public JsonNode createScenario(Map<String, Object> config) throws Exception {
        return post("/api/v1/scenarios", config);
    }

    public JsonNode updateScenario(String scenarioId, Map<String, Object> config) throws Exception {
        return put("/api/v1/scenarios/" + scenarioId, config);
    }

    public JsonNode deleteScenario(String scenarioId) throws Exception {
        return delete("/api/v1/scenarios/" + scenarioId);
    }

    public JsonNode startScenario(String scenarioId) throws Exception {
        return post("/api/v1/scenarios/" + scenarioId + "/start", new HashMap<>());
    }

    public JsonNode stopScenario(String scenarioId) throws Exception {
        return post("/api/v1/scenarios/" + scenarioId + "/stop", new HashMap<>());
    }

    public JsonNode exportScenario(String scenarioId) throws Exception {
        return get("/api/v1/scenarios/" + scenarioId + "/export");
    }

    public JsonNode importScenario(Map<String, Object> config) throws Exception {
        return post("/api/v1/scenarios/import", config);
    }

    public JsonNode getScenarioSnapshot(String scenarioId) throws Exception {
        return get("/api/v1/scenarios/" + scenarioId + "/snapshot");
    }

    public JsonNode getLogs(int count) throws Exception {
        return get("/api/v1/logs?count=" + count);
    }

    public JsonNode clearLogs() throws Exception {
        return delete("/api/v1/logs");
    }

    public JsonNode createTestCase(Map<String, Object> caseDef) throws Exception {
        return post("/api/v1/tests/cases", caseDef);
    }

    public JsonNode listTestCases() throws Exception {
        return get("/api/v1/tests/cases");
    }

    public JsonNode getTestCase(String caseId) throws Exception {
        return get("/api/v1/tests/cases/" + caseId);
    }

    public JsonNode updateTestCase(String caseId, Map<String, Object> caseDef) throws Exception {
        return put("/api/v1/tests/cases/" + caseId, caseDef);
    }

    public JsonNode deleteTestCase(String caseId) throws Exception {
        return delete("/api/v1/tests/cases/" + caseId);
    }

    public JsonNode createTestSuite(Map<String, Object> suiteDef) throws Exception {
        return post("/api/v1/tests/suites", suiteDef);
    }

    public JsonNode listTestSuites() throws Exception {
        return get("/api/v1/tests/suites");
    }

    public JsonNode getTestSuite(String suiteId) throws Exception {
        return get("/api/v1/tests/suites/" + suiteId);
    }

    public JsonNode deleteTestSuite(String suiteId) throws Exception {
        return delete("/api/v1/tests/suites/" + suiteId);
    }

    public JsonNode runTests(List<Map<String, Object>> testCases) throws Exception {
        // FIXED: P1 - W19-21: 后端 POST /tests/run 期望 {test_cases: [...]} 而非裸数组
        Map<String, Object> body = new HashMap<>();
        body.put("test_cases", testCases);
        return post("/api/v1/tests/run", body);
    }

    public JsonNode runTestCase(String caseId) throws Exception {
        return post("/api/v1/tests/run/case/" + caseId, new HashMap<>());
    }

    public JsonNode runTestSuite(String suiteId) throws Exception {
        return post("/api/v1/tests/run/suite/" + suiteId, new HashMap<>());
    }

    public JsonNode quickTest(String scope) throws Exception {
        return post("/api/v1/tests/quick-test?scope=" + scope, new HashMap<>());
    }

    public JsonNode quickTest(String scope, String targetId) throws Exception {  // FIXED: 添加target_id参数，与后端对齐
        StringBuilder params = new StringBuilder("?scope=").append(java.net.URLEncoder.encode(scope, "UTF-8"));
        if (targetId != null && !targetId.isEmpty()) {
            params.append("&target_id=").append(java.net.URLEncoder.encode(targetId, "UTF-8"));
        }
        return post("/api/v1/tests/quick-test" + params, new HashMap<>());
    }

    public JsonNode listTestReports() throws Exception {
        return get("/api/v1/tests/reports");
    }

    public JsonNode getTestReport(String reportId) throws Exception {
        return get("/api/v1/tests/reports/" + reportId);
    }

    public JsonNode getTestReportHtml(String reportId) throws Exception {
        return get("/api/v1/tests/reports/" + reportId + "/html");
    }

    public JsonNode getReportTrend(int count) throws Exception {
        return get("/api/v1/tests/reports/trend?count=" + count);
    }

    public JsonNode getTestSuggestions() throws Exception {
        return get("/api/v1/tests/suggestions");
    }

    public JsonNode getTestActionTypes() throws Exception {
        return get("/api/v1/tests/action-types");
    }

    public JsonNode getTestAssertionTypes() throws Exception {
        return get("/api/v1/tests/assertion-types");
    }

    public JsonNode listForwardTargets() throws Exception {
        return get("/api/v1/forward/targets");
    }

    public JsonNode addForwardTarget(Map<String, Object> config) throws Exception {
        return post("/api/v1/forward/targets", config);
    }

    public JsonNode removeForwardTarget(String name) throws Exception {
        return delete("/api/v1/forward/targets/" + name);
    }

    public JsonNode startForward() throws Exception {
        return post("/api/v1/forward/start", new HashMap<>());
    }

    public JsonNode stopForward() throws Exception {
        return post("/api/v1/forward/stop", new HashMap<>());
    }

    public JsonNode getForwardStats() throws Exception {
        return get("/api/v1/forward/stats");
    }

    public JsonNode startRecording(Map<String, Object> config) throws Exception {
        return post("/api/v1/recorder/start", config);
    }

    public JsonNode stopRecording() throws Exception {
        return post("/api/v1/recorder/stop", new HashMap<>());
    }

    public JsonNode listRecordings() throws Exception {
        return get("/api/v1/recorder/recordings");
    }

    public JsonNode getRecording(String recordingId) throws Exception {
        return get("/api/v1/recorder/recordings/" + recordingId);
    }

    public JsonNode deleteRecording(String recordingId) throws Exception {
        return delete("/api/v1/recorder/recordings/" + recordingId);
    }

    public JsonNode replayRecording(String recordingId, double speed) throws Exception {
        Map<String, Object> body = new HashMap<>();
        body.put("speed", speed);
        return post("/api/v1/recorder/recordings/" + recordingId + "/replay", body);
    }

    public JsonNode exportRecording(String recordingId) throws Exception {
        return get("/api/v1/recorder/recordings/" + recordingId + "/export");
    }

    public JsonNode getRecorderStats() throws Exception {
        return get("/api/v1/recorder/stats");
    }

    public JsonNode listWebhooks() throws Exception {
        return get("/api/v1/webhooks");
    }

    public JsonNode addWebhook(Map<String, Object> config) throws Exception {
        return post("/api/v1/webhooks", config);
    }

    public JsonNode updateWebhook(String webhookId, Map<String, Object> config) throws Exception {
        return put("/api/v1/webhooks/" + webhookId, config);
    }

    public JsonNode deleteWebhook(String webhookId) throws Exception {
        return delete("/api/v1/webhooks/" + webhookId);
    }

    public JsonNode testWebhook(String webhookId) throws Exception {
        return post("/api/v1/webhooks/" + webhookId + "/test", new HashMap<>());
    }

    public JsonNode getWebhookStats() throws Exception {
        return get("/api/v1/webhooks/stats");
    }

    public JsonNode getIntegrationStatus() throws Exception {
        return get("/api/v1/integration/status");
    }

    public JsonNode getIntegrationMetrics() throws Exception {
        return get("/api/v1/integration/metrics");
    }

    public JsonNode getIntegrationProtocols() throws Exception {
        return get("/api/v1/integration/protocols");
    }

    public JsonNode validateDeviceCompatibility(String deviceId, String protocol, List<Map<String, Object>> points, Map<String, Object> driverConfig) throws Exception {
        // FIXED: P1 - W26: 后端 integration.py 读取 device_id, protocol, points, driver_config，不能只发 device_id
        Map<String, Object> body = new HashMap<>();
        body.put("device_id", deviceId);
        body.put("protocol", protocol != null ? protocol : "");
        body.put("points", points != null ? points : new ArrayList<>());
        body.put("driver_config", driverConfig != null ? driverConfig : new HashMap<>());
        return post("/api/v1/integration/validate", body);
    }

    public JsonNode batchPush(List<String> deviceIds) throws Exception {
        Map<String, Object> body = new HashMap<>();
        body.put("device_ids", deviceIds);
        return post("/api/v1/integration/batch-push", body);
    }

    public JsonNode startIntegrationDevice(String deviceId) throws Exception {
        return post("/api/v1/integration/device/" + deviceId + "/start", new HashMap<>());
    }

    public JsonNode stopIntegrationDevice(String deviceId) throws Exception {
        return post("/api/v1/integration/device/" + deviceId + "/stop", new HashMap<>());
    }

    public JsonNode getBackhaulData(String deviceId) throws Exception {
        return get("/api/v1/integration/backhaul-data?device_id=" + deviceId);
    }

    public JsonNode getDeviceStatusCache() throws Exception {
        return get("/api/v1/integration/device-status");
    }

    public JsonNode getAlarmRules() throws Exception {
        return get("/api/v1/integration/alarm-rules");
    }

    public JsonNode addAlarmRule(Map<String, Object> rule) throws Exception {
        return post("/api/v1/integration/alarm-rules", rule);
    }

    public JsonNode deleteAlarmRule(String ruleId) throws Exception {
        return delete("/api/v1/integration/alarm-rules/" + ruleId);
    }

    public JsonNode sendIntegrationMessage(String type, Map<String, Object> payload) throws Exception {  // FIXED: 添加缺失的POST /integration/message方法
        Map<String, Object> body = new HashMap<>();
        body.put("type", type);
        body.put("payload", payload);
        return post("/api/v1/integration/message", body);
    }

    public JsonNode importEdgelite(Map<String, Object> config) throws Exception {
        return post("/api/v1/edgelite", config);  // FIXED: 后端路由为POST /edgelite，非/integration/edgelite
    }

    public JsonNode importPygbsentry(Map<String, Object> config) throws Exception {
        return post("/api/v1/edgelite/pygbsentry", config);  // FIXED: 后端路由为POST /edgelite/pygbsentry，非/integration/pygbsentry
    }

    // FIXED: 添加缺失的EdgeLite方法，与Go/C# SDK对齐
    public JsonNode testIntegrationConnection(Map<String, Object> config) throws Exception {
        return post("/api/v1/edgelite/test", config);
    }

    public JsonNode pushDeviceIntegration(String deviceId) throws Exception {
        return post("/api/v1/edgelite/push/" + deviceId, new HashMap<>());
    }

    public void deleteDeviceFromEdgelite(String deviceId) throws Exception {
        delete("/api/v1/edgelite/push/" + deviceId);
    }

    public JsonNode getEdgeliteDeviceStatus(String deviceId) throws Exception {
        return get("/api/v1/edgelite/status/" + deviceId);
    }

    public JsonNode getEdgeliteDevicePoints(String deviceId) throws Exception {
        return get("/api/v1/edgelite/points/" + deviceId);
    }

    public JsonNode getSettings() throws Exception {
        return get("/api/v1/settings");
    }

    public JsonNode updateSettings(Map<String, Object> settings) throws Exception {
        return put("/api/v1/settings", settings);
    }

    public JsonNode setupDemo() throws Exception {
        return post("/api/v1/setup/demo", new HashMap<>());
    }

    public JsonNode getSetupStatus() throws Exception {
        return get("/api/v1/setup/status");
    }

    public JsonNode queryAuditLog(int limit) throws Exception {
        return get("/api/v1/audit?limit=" + limit);
    }

    public JsonNode queryAuditLog(int limit, String action, String username, String startTime, String endTime) throws Exception {  // FIXED: 支持完整审计日志查询参数
        StringBuilder params = new StringBuilder("?limit=").append(limit);
        if (action != null && !action.isEmpty()) params.append("&action=").append(java.net.URLEncoder.encode(action, "UTF-8"));
        if (username != null && !username.isEmpty()) params.append("&username=").append(java.net.URLEncoder.encode(username, "UTF-8"));
        if (startTime != null && !startTime.isEmpty()) params.append("&start_time=").append(java.net.URLEncoder.encode(startTime, "UTF-8"));  // FIXED: 后端参数名为start_time
        if (endTime != null && !endTime.isEmpty()) params.append("&end_time=").append(java.net.URLEncoder.encode(endTime, "UTF-8"));  // FIXED: 后端参数名为end_time
        return get("/api/v1/audit" + params);
    }

    public JsonNode getAuditStats() throws Exception {
        return get("/api/v1/audit/stats");
    }

    public JsonNode deleteAuditEntry(int entryId) throws Exception {
        return delete("/api/v1/audit/" + entryId);
    }

    public JsonNode exportBackup() throws Exception {
        return get("/api/v1/backup");
    }

    public JsonNode importBackup(Map<String, Object> data) throws Exception {
        return post("/api/v1/backup/restore", data);
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

    private JsonNode deleteWithBody(String path, Object body) throws Exception {
        String json = objectMapper.writeValueAsString(body);
        HttpRequest.Builder builder = HttpRequest.newBuilder()
                .uri(URI.create(baseUrl + path))
                .timeout(Duration.ofSeconds(30))
                .header("Content-Type", "application/json")
                .method("DELETE", HttpRequest.BodyPublishers.ofString(json));
        if (token != null) {
            builder.header("Authorization", "Bearer " + token);
        }
        HttpResponse<String> response = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofString());
        return objectMapper.readTree(response.body());
    }
}
