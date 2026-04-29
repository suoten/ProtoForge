using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Net.Http.Json;
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

        public async Task<JsonElement?> GetHealthAsync()
        {
            return await GetAsync("/health");
        }

        public async Task<JsonElement?> ListDevicesAsync()
        {
            return await GetAsync("/api/v1/devices");
        }

        public async Task<JsonElement?> GetDeviceAsync(string deviceId)
        {
            return await GetAsync($"/api/v1/devices/{deviceId}");
        }

        public async Task<JsonElement?> CreateDeviceAsync(object config)
        {
            return await PostAsync("/api/v1/devices", config);
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

        public async Task<JsonElement?> ListScenariosAsync()
        {
            return await GetAsync("/api/v1/scenarios");
        }

        public async Task<JsonElement?> StartScenarioAsync(string scenarioId)
        {
            return await PostAsync($"/api/v1/scenarios/{scenarioId}/start", new { });
        }

        public async Task<JsonElement?> StopScenarioAsync(string scenarioId)
        {
            return await PostAsync($"/api/v1/scenarios/{scenarioId}/stop", new { });
        }

        public async Task<JsonElement?> GetSettingsAsync()
        {
            return await GetAsync("/api/v1/settings");
        }

        public async Task<JsonElement?> UpdateSettingsAsync(object settings)
        {
            return await PutAsync("/api/v1/settings", settings);
        }

        public async Task<JsonElement?> ExportBackupAsync()
        {
            return await GetAsync("/api/v1/backup");
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
        private async Task DeleteAsync(string path) => await SendAsync(HttpMethod.Delete, path);
    }
}
