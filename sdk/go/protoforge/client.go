package protoforge

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"time"
)

type Client struct {
	BaseURL    string
	Token      string
	HTTPClient *http.Client
}

func NewClient(baseURL string) *Client {
	return &Client{
		BaseURL: baseURL,
		HTTPClient: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

func (c *Client) Login(username, password string) (map[string]interface{}, error) {
	body := map[string]string{"username": username, "password": password}
	resp, err := c.post("/api/v1/auth/login", body)
	if err != nil {
		return nil, err
	}
	if token, ok := resp["access_token"].(string); ok {
		c.Token = token
	}
	return resp, nil
}

func (c *Client) Register(username, password, role string) (map[string]interface{}, error) {
	if role == "" {
		role = "user"
	}
	body := map[string]string{"username": username, "password": password, "role": role}
	return c.post("/api/v1/auth/register", body)
}

func (c *Client) RefreshToken(refreshToken string) (map[string]interface{}, error) {
	body := map[string]string{"refresh_token": refreshToken}
	return c.post("/api/v1/auth/refresh", body)
}

func (c *Client) ChangePassword(username, oldPassword, newPassword string) (map[string]interface{}, error) {
	body := map[string]string{"username": username, "old_password": oldPassword, "new_password": newPassword}
	return c.post("/api/v1/auth/change-password", body)
}

func (c *Client) ListUsers() (map[string]interface{}, error) {
	return c.get("/api/v1/auth/users")
}

func (c *Client) AdminResetPassword(username, newPassword string) (map[string]interface{}, error) {
	body := map[string]string{"username": username, "new_password": newPassword}
	return c.post("/api/v1/auth/admin/reset-password", body)
}

func (c *Client) UpdateUserRole(username, role string) (map[string]interface{}, error) {
	body := map[string]string{"role": role}
	return c.put("/api/v1/auth/users/"+username+"/role", body)
}

func (c *Client) AdminUnlockUser(username string) (map[string]interface{}, error) {
	return c.post("/api/v1/auth/admin/unlock/"+username, nil)
}

func (c *Client) DeleteUser(username string) (map[string]interface{}, error) {
	return c.delete("/api/v1/auth/users/" + username)
}

func (c *Client) GetHealth() (map[string]interface{}, error) {
	return c.get("/health")
}

func (c *Client) ListProtocols() (map[string]interface{}, error) {
	return c.get("/api/v1/protocols")
}

func (c *Client) GetProtocolsInfo() (map[string]interface{}, error) {
	return c.get("/api/v1/protocols/info")
}

func (c *Client) GetProtocolConfig(protocolName string) (map[string]interface{}, error) {
	return c.get("/api/v1/protocols/" + protocolName + "/config")
}

func (c *Client) GetProtocolDeviceConfig(protocolName string) (map[string]interface{}, error) {
	return c.get("/api/v1/protocols/" + protocolName + "/device-config")
}

func (c *Client) StartProtocol(name string, config map[string]interface{}) (map[string]interface{}, error) {
	if config == nil {
		config = map[string]interface{}{}
	}
	return c.post("/api/v1/protocols/"+name+"/start", config)
}

func (c *Client) StopProtocol(name string) (map[string]interface{}, error) {
	return c.post("/api/v1/protocols/"+name+"/stop", nil)
}

func (c *Client) ListDevices(protocol string) (map[string]interface{}, error) {
	path := "/api/v1/devices"
	if protocol != "" {
		path += "?protocol=" + url.QueryEscape(protocol)
	}
	return c.get(path)
}

func (c *Client) GetDevice(deviceID string) (map[string]interface{}, error) {
	return c.get("/api/v1/devices/" + deviceID)
}

func (c *Client) GetDeviceConfig(deviceID string) (map[string]interface{}, error) {
	return c.get("/api/v1/devices/" + deviceID + "/config")
}

func (c *Client) GetDeviceConnectionGuide(deviceID string) (map[string]interface{}, error) {
	return c.get("/api/v1/devices/" + deviceID + "/connection-guide")
}

func (c *Client) CreateDevice(config map[string]interface{}) (map[string]interface{}, error) {
	return c.post("/api/v1/devices", config)
}

func (c *Client) QuickCreate(templateID, name, deviceID string) (map[string]interface{}, error) {
	if deviceID == "" {
		deviceID = name
	}
	body := map[string]string{"template_id": templateID, "name": name, "id": deviceID}
	return c.post("/api/v1/devices/quick-create", body)
}

func (c *Client) UpdateDevice(deviceID string, updates map[string]interface{}) (map[string]interface{}, error) {
	return c.put("/api/v1/devices/"+deviceID, updates)
}

func (c *Client) DeleteDevice(deviceID string) (map[string]interface{}, error) {
	return c.delete("/api/v1/devices/" + deviceID)
}

func (c *Client) StartDevice(deviceID string) (map[string]interface{}, error) {
	return c.post("/api/v1/devices/"+deviceID+"/start", nil)
}

func (c *Client) StopDevice(deviceID string) (map[string]interface{}, error) {
	return c.post("/api/v1/devices/"+deviceID+"/stop", nil)
}

func (c *Client) ReadPoints(deviceID string) (map[string]interface{}, error) {
	return c.get("/api/v1/devices/" + deviceID + "/points")
}

func (c *Client) WritePoint(deviceID, pointName string, value interface{}) (map[string]interface{}, error) {
	return c.put("/api/v1/devices/"+deviceID+"/points/"+pointName, map[string]interface{}{"value": value})
}

func (c *Client) BatchCreateDevices(configs []map[string]interface{}) (map[string]interface{}, error) {
	return c.post("/api/v1/devices/batch", configs)
}

func (c *Client) BatchDeleteDevices(deviceIDs []string) (map[string]interface{}, error) {
	return c.deleteWithBody("/api/v1/devices/batch", deviceIDs)
}

func (c *Client) BatchStartDevices(deviceIDs []string) (map[string]interface{}, error) {
	return c.post("/api/v1/devices/batch/start", deviceIDs)
}

func (c *Client) BatchStopDevices(deviceIDs []string) (map[string]interface{}, error) {
	return c.post("/api/v1/devices/batch/stop", deviceIDs)
}

func (c *Client) ListTemplates(protocol string) (map[string]interface{}, error) {
	path := "/api/v1/templates"
	if protocol != "" {
		path += "?protocol=" + url.QueryEscape(protocol)
	}
	return c.get(path)
}

func (c *Client) GetTemplate(templateID string) (map[string]interface{}, error) {
	return c.get("/api/v1/templates/" + templateID)
}

func (c *Client) CreateTemplate(template map[string]interface{}) (map[string]interface{}, error) {
	return c.post("/api/v1/templates", template)
}

func (c *Client) UpdateTemplate(templateID string, template map[string]interface{}) (map[string]interface{}, error) {
	return c.put("/api/v1/templates/"+templateID, template)
}

func (c *Client) DeleteTemplate(templateID string) (map[string]interface{}, error) {
	return c.delete("/api/v1/templates/" + templateID)
}

func (c *Client) SearchTemplates(q, protocol, tag string) (map[string]interface{}, error) {
	params := url.Values{}
	if q != "" {
		params.Set("q", q)
	}
	if protocol != "" {
		params.Set("protocol", protocol)
	}
	if tag != "" {
		params.Set("tag", tag)
	}
	path := "/api/v1/templates/search"
	if len(params) > 0 {
		path += "?" + params.Encode()
	}
	return c.get(path)
}

func (c *Client) ListTemplateTags() (map[string]interface{}, error) {
	return c.get("/api/v1/templates/tags")
}

func (c *Client) InstantiateTemplate(templateID, deviceID, deviceName string, protocolConfig map[string]interface{}) (map[string]interface{}, error) {
	params := url.Values{}
	params.Set("device_id", deviceID)
	params.Set("device_name", deviceName)
	path := "/api/v1/templates/" + templateID + "/instantiate?" + params.Encode()
	if protocolConfig != nil {
		return c.post(path, protocolConfig)
	}
	return c.post(path, nil)
}

func (c *Client) ListScenarios() (map[string]interface{}, error) {
	return c.get("/api/v1/scenarios")
}

func (c *Client) GetScenario(scenarioID string) (map[string]interface{}, error) {
	return c.get("/api/v1/scenarios/" + scenarioID)
}

func (c *Client) CreateScenario(scenarioID, name, description string, devices, rules []map[string]interface{}) (map[string]interface{}, error) {
	if devices == nil {
		devices = []map[string]interface{}{}
	}
	if rules == nil {
		rules = []map[string]interface{}{}
	}
	body := map[string]interface{}{
		"id":          scenarioID,
		"name":        name,
		"description": description,
		"devices":     devices,
		"rules":       rules,
	}
	return c.post("/api/v1/scenarios", body)
}

func (c *Client) UpdateScenario(scenarioID string, config map[string]interface{}) (map[string]interface{}, error) {
	return c.put("/api/v1/scenarios/"+scenarioID, config)
}

func (c *Client) DeleteScenario(scenarioID string) (map[string]interface{}, error) {
	return c.delete("/api/v1/scenarios/" + scenarioID)
}

func (c *Client) StartScenario(scenarioID string) (map[string]interface{}, error) {
	return c.post("/api/v1/scenarios/"+scenarioID+"/start", nil)
}

func (c *Client) StopScenario(scenarioID string) (map[string]interface{}, error) {
	return c.post("/api/v1/scenarios/"+scenarioID+"/stop", nil)
}

func (c *Client) ExportScenario(scenarioID string) (map[string]interface{}, error) {
	return c.get("/api/v1/scenarios/" + scenarioID + "/export")
}

func (c *Client) ImportScenario(config map[string]interface{}) (map[string]interface{}, error) {
	return c.post("/api/v1/scenarios/import", config)
}

func (c *Client) GetScenarioSnapshot(scenarioID string) (map[string]interface{}, error) {
	return c.get("/api/v1/scenarios/" + scenarioID + "/snapshot")
}

func (c *Client) GetLogs(count int, protocol, deviceID string) (map[string]interface{}, error) {
	params := url.Values{}
	params.Set("count", strconv.Itoa(count))
	if protocol != "" {
		params.Set("protocol", protocol)
	}
	if deviceID != "" {
		params.Set("device_id", deviceID)
	}
	return c.get("/api/v1/logs?" + params.Encode())
}

func (c *Client) ClearLogs() (map[string]interface{}, error) {
	return c.delete("/api/v1/logs")
}

func (c *Client) CreateTestCase(caseDef map[string]interface{}) (map[string]interface{}, error) {
	return c.post("/api/v1/tests/cases", caseDef)
}

func (c *Client) ListTestCases(tag string) (map[string]interface{}, error) {
	path := "/api/v1/tests/cases"
	if tag != "" {
		path += "?tag=" + url.QueryEscape(tag)
	}
	return c.get(path)
}

func (c *Client) GetTestCase(caseID string) (map[string]interface{}, error) {
	return c.get("/api/v1/tests/cases/" + caseID)
}

func (c *Client) UpdateTestCase(caseID string, caseDef map[string]interface{}) (map[string]interface{}, error) {
	return c.put("/api/v1/tests/cases/"+caseID, caseDef)
}

func (c *Client) DeleteTestCase(caseID string) (map[string]interface{}, error) {
	return c.delete("/api/v1/tests/cases/" + caseID)
}

func (c *Client) CreateTestSuite(suiteDef map[string]interface{}) (map[string]interface{}, error) {
	return c.post("/api/v1/tests/suites", suiteDef)
}

func (c *Client) ListTestSuites() (map[string]interface{}, error) {
	return c.get("/api/v1/tests/suites")
}

func (c *Client) GetTestSuite(suiteID string) (map[string]interface{}, error) {
	return c.get("/api/v1/tests/suites/" + suiteID)
}

func (c *Client) DeleteTestSuite(suiteID string) (map[string]interface{}, error) {
	return c.delete("/api/v1/tests/suites/" + suiteID)
}

func (c *Client) RunTests(testCases []map[string]interface{}) (map[string]interface{}, error) {
	return c.post("/api/v1/tests/run", testCases)
}

func (c *Client) RunTestCase(caseID string) (map[string]interface{}, error) {
	return c.post("/api/v1/tests/run/case/"+caseID, nil)
}

func (c *Client) RunTestSuite(suiteID string) (map[string]interface{}, error) {
	return c.post("/api/v1/tests/run/suite/"+suiteID, nil)
}

func (c *Client) QuickTest(scope, targetID string) (map[string]interface{}, error) {
	if scope == "" {
		scope = "all"
	}
	params := url.Values{}
	params.Set("scope", scope)
	if targetID != "" {
		params.Set("target_id", targetID)
	}
	return c.post("/api/v1/tests/quick-test?"+params.Encode(), nil)
}

func (c *Client) ListTestReports() (map[string]interface{}, error) {
	return c.get("/api/v1/tests/reports")
}

func (c *Client) GetTestReport(reportID string) (map[string]interface{}, error) {
	return c.get("/api/v1/tests/reports/" + reportID)
}

func (c *Client) GetTestReportHTML(reportID string) (string, error) {
	req, err := http.NewRequest("GET", c.BaseURL+"/api/v1/tests/reports/"+reportID+"/html", nil)
	if err != nil {
		return "", err
	}
	if c.Token != "" {
		req.Header.Set("Authorization", "Bearer "+c.Token)
	}
	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}
	return string(body), nil
}

func (c *Client) GetReportTrend(count int) (map[string]interface{}, error) {
	return c.get("/api/v1/tests/reports/trend?count=" + strconv.Itoa(count))
}

func (c *Client) GetTestSuggestions() (map[string]interface{}, error) {
	return c.get("/api/v1/tests/suggestions")
}

func (c *Client) GetTestActionTypes() (map[string]interface{}, error) {
	return c.get("/api/v1/tests/action-types")
}

func (c *Client) GetTestAssertionTypes() (map[string]interface{}, error) {
	return c.get("/api/v1/tests/assertion-types")
}

func (c *Client) ListForwardTargets() (map[string]interface{}, error) {
	return c.get("/api/v1/forward/targets")
}

func (c *Client) AddForwardTarget(target map[string]interface{}) (map[string]interface{}, error) {
	return c.post("/api/v1/forward/targets", target)
}

func (c *Client) RemoveForwardTarget(name string) (map[string]interface{}, error) {
	return c.delete("/api/v1/forward/targets/" + name)
}

func (c *Client) StartForward() (map[string]interface{}, error) {
	return c.post("/api/v1/forward/start", nil)
}

func (c *Client) StopForward() (map[string]interface{}, error) {
	return c.post("/api/v1/forward/stop", nil)
}

func (c *Client) GetForwardStats() (map[string]interface{}, error) {
	return c.get("/api/v1/forward/stats")
}

func (c *Client) StartRecording(protocol, deviceID string) (map[string]interface{}, error) {
	body := map[string]interface{}{"name": "SDK Recording"}
	if protocol != "" {
		body["protocol"] = protocol
	}
	if deviceID != "" {
		body["device_id"] = deviceID
	}
	return c.post("/api/v1/recorder/start", body)
}

func (c *Client) StopRecording() (map[string]interface{}, error) {
	return c.post("/api/v1/recorder/stop", nil)
}

func (c *Client) ListRecordings() (map[string]interface{}, error) {
	return c.get("/api/v1/recorder/recordings")
}

func (c *Client) GetRecording(recordingID string) (map[string]interface{}, error) {
	return c.get("/api/v1/recorder/recordings/" + recordingID)
}

func (c *Client) DeleteRecording(recordingID string) (map[string]interface{}, error) {
	return c.delete("/api/v1/recorder/recordings/" + recordingID)
}

func (c *Client) ReplayRecording(recordingID string, speed float64) (map[string]interface{}, error) {
	body := map[string]interface{}{"speed": speed}
	return c.post("/api/v1/recorder/recordings/"+recordingID+"/replay", body)
}

func (c *Client) ExportRecording(recordingID string) (map[string]interface{}, error) {
	return c.get("/api/v1/recorder/recordings/" + recordingID + "/export")
}

func (c *Client) GetRecorderStats() (map[string]interface{}, error) {
	return c.get("/api/v1/recorder/stats")
}

func (c *Client) ListWebhooks() (map[string]interface{}, error) {
	return c.get("/api/v1/webhooks")
}

func (c *Client) AddWebhook(config map[string]interface{}) (map[string]interface{}, error) {
	return c.post("/api/v1/webhooks", config)
}

func (c *Client) UpdateWebhook(webhookID string, config map[string]interface{}) (map[string]interface{}, error) {
	return c.put("/api/v1/webhooks/"+webhookID, config)
}

func (c *Client) DeleteWebhook(webhookID string) (map[string]interface{}, error) {
	return c.delete("/api/v1/webhooks/" + webhookID)
}

func (c *Client) TestWebhook(webhookID string) (map[string]interface{}, error) {
	return c.post("/api/v1/webhooks/"+webhookID+"/test", nil)
}

func (c *Client) GetWebhookStats() (map[string]interface{}, error) {
	return c.get("/api/v1/webhooks/stats")
}

func (c *Client) GetIntegrationStatus() (map[string]interface{}, error) {
	return c.get("/api/v1/integration/status")
}

func (c *Client) GetIntegrationMetrics() (map[string]interface{}, error) {
	return c.get("/api/v1/integration/metrics")
}

func (c *Client) GetProtocolMappings() (map[string]interface{}, error) {
	return c.get("/api/v1/integration/protocols")
}

func (c *Client) ValidateDeviceCompatibility(deviceID string) (map[string]interface{}, error) {
	body := map[string]string{"device_id": deviceID}
	return c.post("/api/v1/integration/validate", body)
}

func (c *Client) TestIntegrationConnection(config map[string]interface{}) (map[string]interface{}, error) {
	return c.post("/api/v1/integration/edgelite/test", config)  // FIXED: 路由与后端edgelite_routes.py对齐
}

func (c *Client) PushDeviceIntegration(deviceID string) (map[string]interface{}, error) {
	return c.post("/api/v1/integration/edgelite/push/"+deviceID, nil)  // FIXED: 路由与后端edgelite_routes.py对齐
}

func (c *Client) BatchPush(deviceIDs []string) (map[string]interface{}, error) {
	body := map[string]interface{}{"device_ids": deviceIDs}
	return c.post("/api/v1/integration/batch-push", body)
}

func (c *Client) DeleteDeviceFromEdgelite(deviceID string) (map[string]interface{}, error) {
	return c.delete("/api/v1/integration/device/" + deviceID)
}

func (c *Client) StartDeviceCollect(deviceID string) (map[string]interface{}, error) {
	return c.post("/api/v1/integration/device/"+deviceID+"/start", nil)
}

func (c *Client) StopDeviceCollect(deviceID string) (map[string]interface{}, error) {
	return c.post("/api/v1/integration/device/"+deviceID+"/stop", nil)
}

func (c *Client) GetBackhaulData(deviceID string, limit int) (map[string]interface{}, error) {
	params := url.Values{}
	params.Set("limit", strconv.Itoa(limit))
	if deviceID != "" {
		params.Set("device_id", deviceID)
	}
	return c.get("/api/v1/integration/backhaul-data?" + params.Encode())
}

func (c *Client) GetDeviceStatusCache() (map[string]interface{}, error) {
	return c.get("/api/v1/integration/device-status")
}

func (c *Client) GetAlarmRules() (map[string]interface{}, error) {
	return c.get("/api/v1/integration/alarm-rules")
}

func (c *Client) AddAlarmRule(rule map[string]interface{}) (map[string]interface{}, error) {
	return c.post("/api/v1/integration/alarm-rules", rule)
}

func (c *Client) DeleteAlarmRule(ruleID string) (map[string]interface{}, error) {
	return c.delete("/api/v1/integration/alarm-rules/" + ruleID)
}

func (c *Client) ImportEdgelite(config map[string]interface{}) (map[string]interface{}, error) {
	return c.post("/api/v1/integration/edgelite", config)
}

func (c *Client) ImportPygbsentry(config map[string]interface{}) (map[string]interface{}, error) {
	return c.post("/api/v1/integration/pygbsentry", config)
}

func (c *Client) GetSettings() (map[string]interface{}, error) {
	return c.get("/api/v1/settings")
}

func (c *Client) UpdateSettings(settings map[string]interface{}) (map[string]interface{}, error) {
	return c.put("/api/v1/settings", settings)
}

func (c *Client) SetupDemo() (map[string]interface{}, error) {
	return c.post("/api/v1/setup/demo", nil)
}

func (c *Client) GetSetupStatus() (map[string]interface{}, error) {
	return c.get("/api/v1/setup/status")
}

func (c *Client) QueryAuditLog(limit int, action, username, start, end string) (map[string]interface{}, error) {
	params := url.Values{}
	if limit > 0 {
		params.Set("limit", strconv.Itoa(limit))
	}
	if action != "" {
		params.Set("action", action)
	}
	if username != "" {
		params.Set("username", username)
	}
	if start != "" {
		params.Set("start", start)
	}
	if end != "" {
		params.Set("end", end)
	}
	path := "/api/v1/audit"
	if len(params) > 0 {
		path += "?" + params.Encode()
	}
	return c.get(path)
}

func (c *Client) GetAuditStats() (map[string]interface{}, error) {
	return c.get("/api/v1/audit/stats")
}

func (c *Client) ExportBackup() (map[string]interface{}, error) {
	return c.get("/api/v1/backup")
}

func (c *Client) ImportBackup(data map[string]interface{}) (map[string]interface{}, error) {
	return c.post("/api/v1/backup/restore", data)
}

func (c *Client) doRequest(method, path string, body interface{}) (map[string]interface{}, error) {
	var reqBody io.Reader
	if body != nil {
		jsonBody, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		reqBody = bytes.NewBuffer(jsonBody)
	}
	req, err := http.NewRequest(method, c.BaseURL+path, reqBody)
	if err != nil {
		return nil, err
	}
	if c.Token != "" {
		req.Header.Set("Authorization", "Bearer "+c.Token)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	var result map[string]interface{}
	if err := json.Unmarshal(respBody, &result); err != nil {
		return nil, fmt.Errorf("status %d: %s", resp.StatusCode, string(respBody))
	}
	return result, nil
}

func (c *Client) get(path string) (map[string]interface{}, error) {
	return c.doRequest("GET", path, nil)
}

func (c *Client) post(path string, body interface{}) (map[string]interface{}, error) {
	return c.doRequest("POST", path, body)
}

func (c *Client) put(path string, body interface{}) (map[string]interface{}, error) {
	return c.doRequest("PUT", path, body)
}

func (c *Client) delete(path string) (map[string]interface{}, error) {
	return c.doRequest("DELETE", path, nil)
}

func (c *Client) deleteWithBody(path string, body interface{}) (map[string]interface{}, error) {
	return c.doRequest("DELETE", path, body)
}
