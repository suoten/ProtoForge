package protoforge

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
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

func (c *Client) GetHealth() (map[string]interface{}, error) {
	return c.get("/health")
}

func (c *Client) ListDevices() (map[string]interface{}, error) {
	return c.get("/api/v1/devices")
}

func (c *Client) GetDevice(deviceID string) (map[string]interface{}, error) {
	return c.get("/api/v1/devices/" + deviceID)
}

func (c *Client) CreateDevice(config map[string]interface{}) (map[string]interface{}, error) {
	return c.post("/api/v1/devices", config)
}

func (c *Client) DeleteDevice(deviceID string) error {
	_, err := c.delete("/api/v1/devices/" + deviceID)
	return err
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

func (c *Client) ListScenarios() (map[string]interface{}, error) {
	return c.get("/api/v1/scenarios")
}

func (c *Client) StartScenario(scenarioID string) (map[string]interface{}, error) {
	return c.post("/api/v1/scenarios/"+scenarioID+"/start", nil)
}

func (c *Client) StopScenario(scenarioID string) (map[string]interface{}, error) {
	return c.post("/api/v1/scenarios/"+scenarioID+"/stop", nil)
}

func (c *Client) GetSettings() (map[string]interface{}, error) {
	return c.get("/api/v1/settings")
}

func (c *Client) UpdateSettings(settings map[string]interface{}) (map[string]interface{}, error) {
	return c.put("/api/v1/settings", settings)
}

func (c *Client) ExportBackup() (map[string]interface{}, error) {
	return c.get("/api/v1/backup")
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
