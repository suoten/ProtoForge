using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace ProtoForge
{
    public class ProtoForgeClient
    {
        private readonly string _baseUrl;
        private readonly HttpClient _httpClient;
        private string? _token;

        public ProtoForgeClient(string baseUrl)
        {
            _baseUrl = baseUrl.TrimEnd('/');
            _httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(30) };
        }

        public async Task LoginAsync(string username, string password)
        {
            var body = new { username, password };
            var response = await PostAsync("/api/v1/auth/login", body);
            _token = response?.GetProperty("access_token").GetString();
        }

        public async Task<JsonElement?> RegisterAsync(string username, string password, string role = "user")
        {
            var body = new { username, password, role };
            return await PostAsync("/api/v1/auth/register", body);
        }

        public async Task<JsonElement?> RefreshTokenAsync(string refreshToken)
        {
            var body = new { refresh_token = refreshToken };
            return await PostAsync("/api/v1/auth/refresh", body);
        }

        public async Task<JsonElement?> ChangePasswordAsync(string username, string oldPassword, string newPassword)
        {
            var body = new { username, old_password = oldPassword, new_password = newPassword };
            return await PostAsync("/api/v1/auth/change-password", body);
        }

        public async Task<JsonElement?> ListUsersAsync()
        {
            return await GetAsync("/api/v1/auth/users");
        }

        public async Task<JsonElement?> AdminResetPasswordAsync(string username, string newPassword)
        {
            var body = new { username, new_password = newPassword };
            return await PostAsync("/api/v1/auth/admin/reset-password", body);
        }

        public async Task<JsonElement?> UpdateUserRoleAsync(string username, string role)
        {
            var body = new { role };
            return await PutAsync($"/api/v1/auth/users/{username}/role", body);
        }

        public async Task<JsonElement?> AdminUnlockUserAsync(string username)
        {
            return await PostAsync($"/api/v1/auth/admin/unlock/{username}", new { });
        }

        public async Task DeleteUserAsync(string username)
        {
            await DeleteAsync($"/api/v1/auth/users/{username}");
        }

        public async Task<JsonElement?> GetHealthAsync()
        {
            return await GetAsync("/health");
        }

        public async Task<JsonElement?> ListProtocolsAsync()
        {
            return await GetAsync("/api/v1/protocols");
        }

        public async Task<JsonElement?> GetProtocolsInfoAsync()
        {
            return await GetAsync("/api/v1/protocols/info");
        }

        public async Task<JsonElement?> GetProtocolConfigAsync(string protocolName)
        {
            return await GetAsync($"/api/v1/protocols/{protocolName}/config");
        }

        public async Task<JsonElement?> GetProtocolDeviceConfigAsync(string protocolName)
        {
            return await GetAsync($"/api/v1/protocols/{protocolName}/device-config");
        }

        public async Task<JsonElement?> StartProtocolAsync(string name, object? config = null)
        {
            return await PostAsync($"/api/v1/protocols/{name}/start", config ?? new { });
        }

        public async Task<JsonElement?> StopProtocolAsync(string name)
        {
            return await PostAsync($"/api/v1/protocols/{name}/stop", new { });
        }

        public async Task<JsonElement?> ListDevicesAsync(string? protocol = null)
        {
            var path = "/api/v1/devices";
            if (!string.IsNullOrEmpty(protocol))
                path += $"?protocol={Uri.EscapeDataString(protocol)}";
            return await GetAsync(path);
        }

        public async Task<JsonElement?> GetDeviceAsync(string deviceId)
        {
            return await GetAsync($"/api/v1/devices/{deviceId}");
        }

        public async Task<JsonElement?> GetDeviceConfigAsync(string deviceId)
        {
            return await GetAsync($"/api/v1/devices/{deviceId}/config");
        }

        public async Task<JsonElement?> GetDeviceConnectionGuideAsync(string deviceId)
        {
            return await GetAsync($"/api/v1/devices/{deviceId}/connection-guide");
        }

        public async Task<JsonElement?> CreateDeviceAsync(object config)
        {
            return await PostAsync("/api/v1/devices", config);
        }

        public async Task<JsonElement?> QuickCreateAsync(string templateId, string name, string? deviceId = null)
        {
            var body = new { template_id = templateId, name, id = deviceId ?? name };
            return await PostAsync("/api/v1/devices/quick-create", body);
        }

        public async Task<JsonElement?> UpdateDeviceAsync(string deviceId, object updates)
        {
            return await PutAsync($"/api/v1/devices/{deviceId}", updates);
        }

        public async Task DeleteDeviceAsync(string deviceId)
        {
            await DeleteAsync($"/api/v1/devices/{deviceId}");
        }

        public async Task<JsonElement?> StartDeviceAsync(string deviceId)
        {
            return await PostAsync($"/api/v1/devices/{deviceId}/start", new { });
        }

        public async Task<JsonElement?> StopDeviceAsync(string deviceId)
        {
            return await PostAsync($"/api/v1/devices/{deviceId}/stop", new { });
        }

        public async Task<JsonElement?> ReadPointsAsync(string deviceId)
        {
            return await GetAsync($"/api/v1/devices/{deviceId}/points");
        }

        public async Task<JsonElement?> WritePointAsync(string deviceId, string pointName, object value)
        {
            return await PutAsync($"/api/v1/devices/{deviceId}/points/{pointName}", new { value });
        }

        public async Task<JsonElement?> BatchCreateDevicesAsync(object configs)
        {
            return await PostAsync("/api/v1/devices/batch", configs);
        }

        public async Task<JsonElement?> BatchDeleteDevicesAsync(object deviceIds)
        {
            return await DeleteWithBodyAsync("/api/v1/devices/batch", deviceIds);
        }

        public async Task<JsonElement?> BatchStartDevicesAsync(object deviceIds)
        {
            return await PostAsync("/api/v1/devices/batch/start", deviceIds);
        }

        public async Task<JsonElement?> BatchStopDevicesAsync(object deviceIds)
        {
            return await PostAsync("/api/v1/devices/batch/stop", deviceIds);
        }

        public async Task<JsonElement?> ListTemplatesAsync(string? protocol = null)
        {
            var path = "/api/v1/templates";
            if (!string.IsNullOrEmpty(protocol))
                path += $"?protocol={Uri.EscapeDataString(protocol)}";
            return await GetAsync(path);
        }

        public async Task<JsonElement?> GetTemplateAsync(string templateId)
        {
            return await GetAsync($"/api/v1/templates/{templateId}");
        }

        public async Task<JsonElement?> CreateTemplateAsync(object template)
        {
            return await PostAsync("/api/v1/templates", template);
        }

        public async Task<JsonElement?> UpdateTemplateAsync(string templateId, object template)
        {
            return await PutAsync($"/api/v1/templates/{templateId}", template);
        }

        public async Task DeleteTemplateAsync(string templateId)
        {
            await DeleteAsync($"/api/v1/templates/{templateId}");
        }

        public async Task<JsonElement?> SearchTemplatesAsync(string? q = null, string? protocol = null, string? tag = null)
        {
            var queryParams = new List<string>();
            if (!string.IsNullOrEmpty(q)) queryParams.Add($"q={Uri.EscapeDataString(q)}");
            if (!string.IsNullOrEmpty(protocol)) queryParams.Add($"protocol={Uri.EscapeDataString(protocol)}");
            if (!string.IsNullOrEmpty(tag)) queryParams.Add($"tag={Uri.EscapeDataString(tag)}");
            var path = "/api/v1/templates/search";
            if (queryParams.Count > 0) path += "?" + string.Join("&", queryParams);
            return await GetAsync(path);
        }

        public async Task<JsonElement?> ListTemplateTagsAsync()
        {
            return await GetAsync("/api/v1/templates/tags");
        }

        public async Task<JsonElement?> InstantiateTemplateAsync(string templateId, string deviceId, string deviceName, object? protocolConfig = null)
        {
            var path = $"/api/v1/templates/{templateId}/instantiate?device_id={Uri.EscapeDataString(deviceId)}&device_name={Uri.EscapeDataString(deviceName)}";
            return await PostAsync(path, protocolConfig ?? new { });
        }

        public async Task<JsonElement?> ListScenariosAsync()
        {
            return await GetAsync("/api/v1/scenarios");
        }

        public async Task<JsonElement?> GetScenarioAsync(string scenarioId)
        {
            return await GetAsync($"/api/v1/scenarios/{scenarioId}");
        }

        public async Task<JsonElement?> CreateScenarioAsync(object scenario)
        {
            return await PostAsync("/api/v1/scenarios", scenario);
        }

        public async Task<JsonElement?> UpdateScenarioAsync(string scenarioId, object config)
        {
            return await PutAsync($"/api/v1/scenarios/{scenarioId}", config);
        }

        public async Task DeleteScenarioAsync(string scenarioId)
        {
            await DeleteAsync($"/api/v1/scenarios/{scenarioId}");
        }

        public async Task<JsonElement?> StartScenarioAsync(string scenarioId)
        {
            return await PostAsync($"/api/v1/scenarios/{scenarioId}/start", new { });
        }

        public async Task<JsonElement?> StopScenarioAsync(string scenarioId)
        {
            return await PostAsync($"/api/v1/scenarios/{scenarioId}/stop", new { });
        }

        public async Task<JsonElement?> ExportScenarioAsync(string scenarioId)
        {
            return await GetAsync($"/api/v1/scenarios/{scenarioId}/export");
        }

        public async Task<JsonElement?> ImportScenarioAsync(object config)
        {
            return await PostAsync("/api/v1/scenarios/import", config);
        }

        public async Task<JsonElement?> GetScenarioSnapshotAsync(string scenarioId)
        {
            return await GetAsync($"/api/v1/scenarios/{scenarioId}/snapshot");
        }

        public async Task<JsonElement?> GetLogsAsync(int count = 100, string? protocol = null, string? deviceId = null)
        {
            var queryParams = new List<string> { $"count={count}" };
            if (!string.IsNullOrEmpty(protocol)) queryParams.Add($"protocol={Uri.EscapeDataString(protocol)}");
            if (!string.IsNullOrEmpty(deviceId)) queryParams.Add($"device_id={Uri.EscapeDataString(deviceId)}");
            return await GetAsync("/api/v1/logs?" + string.Join("&", queryParams));
        }

        public async Task<JsonElement?> ClearLogsAsync()
        {
            return await DeleteAsync("/api/v1/logs");
        }

        public async Task<JsonElement?> CreateTestCaseAsync(object caseDef)
        {
            return await PostAsync("/api/v1/tests/cases", caseDef);
        }

        public async Task<JsonElement?> ListTestCasesAsync(string? tag = null)
        {
            var path = "/api/v1/tests/cases";
            if (!string.IsNullOrEmpty(tag)) path += $"?tag={Uri.EscapeDataString(tag)}";
            return await GetAsync(path);
        }

        public async Task<JsonElement?> GetTestCaseAsync(string caseId)
        {
            return await GetAsync($"/api/v1/tests/cases/{caseId}");
        }

        public async Task<JsonElement?> UpdateTestCaseAsync(string caseId, object caseDef)
        {
            return await PutAsync($"/api/v1/tests/cases/{caseId}", caseDef);
        }

        public async Task DeleteTestCaseAsync(string caseId)
        {
            await DeleteAsync($"/api/v1/tests/cases/{caseId}");
        }

        public async Task<JsonElement?> CreateTestSuiteAsync(object suiteDef)
        {
            return await PostAsync("/api/v1/tests/suites", suiteDef);
        }

        public async Task<JsonElement?> ListTestSuitesAsync()
        {
            return await GetAsync("/api/v1/tests/suites");
        }

        public async Task<JsonElement?> GetTestSuiteAsync(string suiteId)
        {
            return await GetAsync($"/api/v1/tests/suites/{suiteId}");
        }

        public async Task DeleteTestSuiteAsync(string suiteId)
        {
            await DeleteAsync($"/api/v1/tests/suites/{suiteId}");
        }

        public async Task<JsonElement?> RunTestsAsync(object testCases)
        {
            return await PostAsync("/api/v1/tests/run", testCases);
        }

        public async Task<JsonElement?> RunTestCaseAsync(string caseId)
        {
            return await PostAsync($"/api/v1/tests/run/case/{caseId}", new { });
        }

        public async Task<JsonElement?> RunTestSuiteAsync(string suiteId)
        {
            return await PostAsync($"/api/v1/tests/run/suite/{suiteId}", new { });
        }

        public async Task<JsonElement?> QuickTestAsync(string scope = "all", string? targetId = null)
        {
            var queryParams = new List<string> { $"scope={Uri.EscapeDataString(scope)}" };
            if (!string.IsNullOrEmpty(targetId)) queryParams.Add($"target_id={Uri.EscapeDataString(targetId)}");
            return await PostAsync("/api/v1/tests/quick-test?" + string.Join("&", queryParams), new { });
        }

        public async Task<JsonElement?> ListTestReportsAsync()
        {
            return await GetAsync("/api/v1/tests/reports");
        }

        public async Task<JsonElement?> GetTestReportAsync(string reportId)
        {
            return await GetAsync($"/api/v1/tests/reports/{reportId}");
        }

        public async Task<string> GetTestReportHtmlAsync(string reportId)
        {
            using var request = CreateRequest(HttpMethod.Get, $"/api/v1/tests/reports/{reportId}/html");
            using var response = await _httpClient.SendAsync(request);
            response.EnsureSuccessStatusCode();
            return await response.Content.ReadAsStringAsync();
        }

        public async Task<JsonElement?> GetReportTrendAsync(int count = 20)
        {
            return await GetAsync($"/api/v1/tests/reports/trend?count={count}");
        }

        public async Task<JsonElement?> GetTestSuggestionsAsync()
        {
            return await GetAsync("/api/v1/tests/suggestions");
        }

        public async Task<JsonElement?> GetTestActionTypesAsync()
        {
            return await GetAsync("/api/v1/tests/action-types");
        }

        public async Task<JsonElement?> GetTestAssertionTypesAsync()
        {
            return await GetAsync("/api/v1/tests/assertion-types");
        }

        public async Task<JsonElement?> ListForwardTargetsAsync()
        {
            return await GetAsync("/api/v1/forward/targets");
        }

        public async Task<JsonElement?> AddForwardTargetAsync(object target)
        {
            return await PostAsync("/api/v1/forward/targets", target);
        }

        public async Task<JsonElement?> RemoveForwardTargetAsync(string name)
        {
            return await DeleteAsync($"/api/v1/forward/targets/{name}");
        }

        public async Task<JsonElement?> StartForwardAsync()
        {
            return await PostAsync("/api/v1/forward/start", new { });
        }

        public async Task<JsonElement?> StopForwardAsync()
        {
            return await PostAsync("/api/v1/forward/stop", new { });
        }

        public async Task<JsonElement?> GetForwardStatsAsync()
        {
            return await GetAsync("/api/v1/forward/stats");
        }

        public async Task<JsonElement?> StartRecordingAsync(string? protocol = null, string? deviceId = null)
        {
            var body = new Dictionary<string, object> { { "name", "SDK Recording" } };
            if (!string.IsNullOrEmpty(protocol)) body["protocol"] = protocol;
            if (!string.IsNullOrEmpty(deviceId)) body["device_id"] = deviceId;
            return await PostAsync("/api/v1/recorder/start", body);
        }

        public async Task<JsonElement?> StopRecordingAsync()
        {
            return await PostAsync("/api/v1/recorder/stop", new { });
        }

        public async Task<JsonElement?> ListRecordingsAsync()
        {
            return await GetAsync("/api/v1/recorder/recordings");
        }

        public async Task<JsonElement?> GetRecordingAsync(string recordingId)
        {
            return await GetAsync($"/api/v1/recorder/recordings/{recordingId}");
        }

        public async Task DeleteRecordingAsync(string recordingId)
        {
            await DeleteAsync($"/api/v1/recorder/recordings/{recordingId}");
        }

        public async Task<JsonElement?> ReplayRecordingAsync(string recordingId, double speed = 1.0)
        {
            return await PostAsync($"/api/v1/recorder/recordings/{recordingId}/replay", new { speed });
        }

        public async Task<JsonElement?> ExportRecordingAsync(string recordingId)
        {
            return await GetAsync($"/api/v1/recorder/recordings/{recordingId}/export");
        }

        public async Task<JsonElement?> GetRecorderStatsAsync()
        {
            return await GetAsync("/api/v1/recorder/stats");
        }

        public async Task<JsonElement?> ListWebhooksAsync()
        {
            return await GetAsync("/api/v1/webhooks");
        }

        public async Task<JsonElement?> AddWebhookAsync(object config)
        {
            return await PostAsync("/api/v1/webhooks", config);
        }

        public async Task<JsonElement?> UpdateWebhookAsync(string webhookId, object config)
        {
            return await PutAsync($"/api/v1/webhooks/{webhookId}", config);
        }

        public async Task DeleteWebhookAsync(string webhookId)
        {
            await DeleteAsync($"/api/v1/webhooks/{webhookId}");
        }

        public async Task<JsonElement?> TestWebhookAsync(string webhookId)
        {
            return await PostAsync($"/api/v1/webhooks/{webhookId}/test", new { });
        }

        public async Task<JsonElement?> GetWebhookStatsAsync()
        {
            return await GetAsync("/api/v1/webhooks/stats");
        }

        public async Task<JsonElement?> GetIntegrationStatusAsync()
        {
            return await GetAsync("/api/v1/integration/status");
        }

        public async Task<JsonElement?> GetIntegrationMetricsAsync()
        {
            return await GetAsync("/api/v1/integration/metrics");
        }

        public async Task<JsonElement?> GetProtocolMappingsAsync()
        {
            return await GetAsync("/api/v1/integration/protocols");
        }

        public async Task<JsonElement?> ValidateDeviceCompatibilityAsync(string deviceId)
        {
            return await PostAsync("/api/v1/integration/validate", new { device_id = deviceId });
        }

        public async Task<JsonElement?> TestIntegrationConnectionAsync(object config)
        {
            return await PostAsync("/api/v1/integration/test-connection", config);
        }

        public async Task<JsonElement?> PushDeviceIntegrationAsync(string deviceId)
        {
            return await PostAsync($"/api/v1/integration/push-device/{deviceId}", new { });
        }

        public async Task<JsonElement?> BatchPushAsync(object deviceIds)
        {
            return await PostAsync("/api/v1/integration/batch-push", deviceIds);
        }

        public async Task DeleteDeviceFromEdgeliteAsync(string deviceId)
        {
            await DeleteAsync($"/api/v1/integration/device/{deviceId}");
        }

        public async Task<JsonElement?> StartDeviceCollectAsync(string deviceId)
        {
            return await PostAsync($"/api/v1/integration/device/{deviceId}/start", new { });
        }

        public async Task<JsonElement?> StopDeviceCollectAsync(string deviceId)
        {
            return await PostAsync($"/api/v1/integration/device/{deviceId}/stop", new { });
        }

        public async Task<JsonElement?> GetBackhaulDataAsync(string? deviceId = null, int limit = 100)
        {
            var queryParams = new List<string> { $"limit={limit}" };
            if (!string.IsNullOrEmpty(deviceId)) queryParams.Add($"device_id={Uri.EscapeDataString(deviceId)}");
            return await GetAsync("/api/v1/integration/backhaul-data?" + string.Join("&", queryParams));
        }

        public async Task<JsonElement?> GetDeviceStatusCacheAsync()
        {
            return await GetAsync("/api/v1/integration/device-status");
        }

        public async Task<JsonElement?> GetAlarmRulesAsync()
        {
            return await GetAsync("/api/v1/integration/alarm-rules");
        }

        public async Task<JsonElement?> AddAlarmRuleAsync(object rule)
        {
            return await PostAsync("/api/v1/integration/alarm-rules", rule);
        }

        public async Task DeleteAlarmRuleAsync(string ruleId)
        {
            await DeleteAsync($"/api/v1/integration/alarm-rules/{ruleId}");
        }

        public async Task<JsonElement?> ImportEdgeliteAsync(object config)
        {
            return await PostAsync("/api/v1/integration/edgelite", config);
        }

        public async Task<JsonElement?> ImportPygbsentryAsync(object config)
        {
            return await PostAsync("/api/v1/integration/pygbsentry", config);
        }

        public async Task<JsonElement?> GetSettingsAsync()
        {
            return await GetAsync("/api/v1/settings");
        }

        public async Task<JsonElement?> UpdateSettingsAsync(object settings)
        {
            return await PutAsync("/api/v1/settings", settings);
        }

        public async Task<JsonElement?> SetupDemoAsync()
        {
            return await PostAsync("/api/v1/setup/demo", new { });
        }

        public async Task<JsonElement?> GetSetupStatusAsync()
        {
            return await GetAsync("/api/v1/setup/status");
        }

        public async Task<JsonElement?> QueryAuditLogAsync(int? limit = null, string? action = null, string? username = null, string? start = null, string? end = null)
        {
            var queryParams = new List<string>();
            if (limit.HasValue) queryParams.Add($"limit={limit.Value}");
            if (!string.IsNullOrEmpty(action)) queryParams.Add($"action={Uri.EscapeDataString(action)}");
            if (!string.IsNullOrEmpty(username)) queryParams.Add($"username={Uri.EscapeDataString(username)}");
            if (!string.IsNullOrEmpty(start)) queryParams.Add($"start={Uri.EscapeDataString(start)}");
            if (!string.IsNullOrEmpty(end)) queryParams.Add($"end={Uri.EscapeDataString(end)}");
            var path = "/api/v1/audit";
            if (queryParams.Count > 0) path += "?" + string.Join("&", queryParams);
            return await GetAsync(path);
        }

        public async Task<JsonElement?> GetAuditStatsAsync()
        {
            return await GetAsync("/api/v1/audit/stats");
        }

        public async Task<JsonElement?> ExportBackupAsync()
        {
            return await GetAsync("/api/v1/backup");
        }

        public async Task<JsonElement?> ImportBackupAsync(object data)
        {
            return await PostAsync("/api/v1/backup/restore", data);
        }

        private HttpRequestMessage CreateRequest(HttpMethod method, string path, object? body = null)
        {
            var request = new HttpRequestMessage(method, _baseUrl + path);
            if (_token != null)
                request.Headers.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", _token);
            if (body != null)
            {
                var json = JsonSerializer.Serialize(body);
                request.Content = new StringContent(json, Encoding.UTF8, "application/json");
            }
            return request;
        }

        private async Task<JsonElement?> SendAsync(HttpMethod method, string path, object? body = null)
        {
            using var request = CreateRequest(method, path, body);
            using var response = await _httpClient.SendAsync(request);
            response.EnsureSuccessStatusCode();
            var json = await response.Content.ReadAsStringAsync();
            if (string.IsNullOrEmpty(json)) return null;
            return JsonDocument.Parse(json).RootElement;
        }

        private async Task<JsonElement?> GetAsync(string path) => await SendAsync(HttpMethod.Get, path);
        private async Task<JsonElement?> PostAsync(string path, object body) => await SendAsync(HttpMethod.Post, path, body);
        private async Task<JsonElement?> PutAsync(string path, object body) => await SendAsync(HttpMethod.Put, path, body);
        private async Task<JsonElement?> DeleteAsync(string path) => await SendAsync(HttpMethod.Delete, path);
        private async Task<JsonElement?> DeleteWithBodyAsync(string path, object body) => await SendAsync(HttpMethod.Delete, path, body);
    }
}
