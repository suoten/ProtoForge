import { test, expect } from '@playwright/test';

test.describe('Login Page', () => {
  test('should display login form', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('input[placeholder*="用户名"], input[placeholder*="Username"]')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('input[type="password"]')).toBeVisible();
  });

  test('should login with default credentials', async ({ page }) => {
    await page.goto('/');
    const usernameInput = page.locator('input[placeholder*="用户名"], input[placeholder*="Username"]');
    const passwordInput = page.locator('input[type="password"]').first();
    await usernameInput.fill('admin');
    await passwordInput.fill('admin');
    const loginButton = page.locator('button:has-text("登"), button:has-text("Login")');
    await loginButton.click();
    await expect(page).toHaveURL(/\//, { timeout: 10000 });
  });
});

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    const usernameInput = page.locator('input[placeholder*="用户名"], input[placeholder*="Username"]');
    const passwordInput = page.locator('input[type="password"]').first();
    await usernameInput.fill('admin');
    await passwordInput.fill('admin');
    const loginButton = page.locator('button:has-text("登"), button:has-text("Login")');
    await loginButton.click();
    await page.waitForURL(/\//, { timeout: 10000 });
  });

  test('should display sidebar navigation', async ({ page }) => {
    await expect(page.locator('.n-layout-sider')).toBeVisible();
  });

  test('should navigate to devices page', async ({ page }) => {
    await page.click('text=设备');
    await expect(page).toHaveURL(/\/devices/, { timeout: 5000 });
  });

  test('should navigate to settings page', async ({ page }) => {
    await page.click('text=设置');
    await expect(page).toHaveURL(/\/settings/, { timeout: 5000 });
  });
});

test.describe('Change Password', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    const usernameInput = page.locator('input[placeholder*="用户名"], input[placeholder*="Username"]');
    const passwordInput = page.locator('input[type="password"]').first();
    await usernameInput.fill('admin');
    await passwordInput.fill('admin');
    const loginButton = page.locator('button:has-text("登"), button:has-text("Login")');
    await loginButton.click();
    await page.waitForURL(/\//, { timeout: 10000 });
  });

  test('should open change password dialog', async ({ page }) => {
    await page.click('.n-dropdown-trigger');
    await page.click('text=修改密码, text=Change Password');
    await expect(page.locator('.n-modal')).toBeVisible();
  });
});

test.describe('Language Switch', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    const usernameInput = page.locator('input[placeholder*="用户名"], input[placeholder*="Username"]');
    const passwordInput = page.locator('input[type="password"]').first();
    await usernameInput.fill('admin');
    await passwordInput.fill('admin');
    const loginButton = page.locator('button:has-text("登"), button:has-text("Login")');
    await loginButton.click();
    await page.waitForURL(/\//, { timeout: 10000 });
  });

  test('should switch language to English', async ({ page }) => {
    const langButton = page.locator('button:has(svg)').filter({ hasText: /中文|EN/ });
    await langButton.click();
    await page.click('text=English');
    await expect(page.locator('text=Dashboard')).toBeVisible({ timeout: 5000 });
  });
});

test.describe('Health API', () => {
  test('should return healthy status', async ({ request }) => {
    const response = await request.get('/health');
    expect(response.ok()).toBeTruthy();
    const body = await response.json();
    expect(body.status).toBe('ok');
  });
});
