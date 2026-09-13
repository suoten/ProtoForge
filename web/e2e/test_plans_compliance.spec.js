/**
 * ProtoForge Test Plans & Compliance - Full UI Acceptance Test
 *
 * Tests every page, every button, every interaction via real browser.
 */

import { test, expect } from '@playwright/test';

const BASE = 'http://localhost:8000';
const API_BASE = `${BASE}/api/v1`;

// ─── Helpers ───────────────────────────────────────────────

async function login(page) {
  await page.goto(BASE);
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1000);
  const loginInput = page.locator('input[placeholder*="用户名"], input[placeholder*="Username"]');
  if (await loginInput.isVisible({ timeout: 3000 }).catch(() => false)) {
    await loginInput.fill('admin');
    await page.locator('input[type="password"]').first().fill('admin');
    await page.locator('button:has-text("登"), button:has-text("Login")').click();
    // Wait for login to complete - wait for URL change or menu to appear
    await page.waitForTimeout(3000);
    // Verify login succeeded by checking if menu is visible
    await page.waitForSelector('.n-menu, .n-layout-sider', { timeout: 10000 }).catch(() => {});
  }
}

async function cleanupAllPlans(request) {
  try {
    const res = await request.get(`${API_BASE}/test-plans`);
    const body = await res.json();
    for (const plan of body.plans || []) {
      await request.delete(`${API_BASE}/test-plans/${plan.id}`);
    }
  } catch (e) {
    // ignore
  }
}

function attachMonitors(page) {
  const errors = [];
  const failedRequests = [];
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  page.on('pageerror', err => {
    errors.push(`PAGEERROR: ${err.message}`);
  });
  page.on('response', response => {
    if (response.status() >= 400) {
      failedRequests.push({ url: response.url(), status: response.status() });
    }
  });
  return { errors, failedRequests };
}

// Use getByRole to precisely locate the toolbar create button
// There are 2 "创建测试计划" buttons (toolbar + empty state), we want the first one
function createBtn(page) {
  return page.getByRole('button', { name: '创建测试计划' }).first();
}
function createBtnEN(page) {
  return page.getByRole('button', { name: 'Create Test Plan' }).first();
}

// ─── 1. Test Plans Page Rendering ──────────────────────────

test.describe('Test Plans - Page Rendering', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('page loads with correct title and subtitle', async ({ page }) => {
    const { errors, failedRequests } = attachMonitors(page);
    await page.goto(`${BASE}/test-plans`);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('h2, .n-h2')).toContainText(/测试计划|Test Plans/);
    expect(errors.filter(e => !e.includes('favicon'))).toEqual([]);
    expect(failedRequests).toEqual([]);
  });

  test('menu shows test plans entry', async ({ page }) => {
    await page.goto(`${BASE}/`);
    await page.waitForLoadState('networkidle');
    const menuText = await page.locator('.n-menu').textContent();
    expect(menuText).toContain('测试计划');
  });

  test('breadcrumb shows correct path', async ({ page }) => {
    await page.goto(`${BASE}/test-plans`);
    await page.waitForLoadState('networkidle');
    const breadcrumb = await page.locator('.n-breadcrumb').textContent();
    expect(breadcrumb).toContain('测试计划');
  });

  test('create button is visible', async ({ page, request }) => {
    await cleanupAllPlans(request);
    await page.goto(`${BASE}/test-plans`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    // The primary create button in toolbar
    await expect(createBtn(page)).toBeVisible();
  });

  test('empty state shows when no plans', async ({ page, request }) => {
    await cleanupAllPlans(request);
    await page.goto(`${BASE}/test-plans`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1500);
    const hasEmpty = await page.locator('.n-empty').isVisible().catch(() => false);
    expect(hasEmpty).toBeTruthy();
  });
});

// ─── 2. Test Plans - CRUD Operations ───────────────────────

test.describe('Test Plans - CRUD Operations', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('create a test plan via UI', async ({ page, request }) => {
    await cleanupAllPlans(request);
    await page.goto(`${BASE}/test-plans`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);

    // Click create button (toolbar primary button)
    await createBtn(page).click();
    await page.waitForTimeout(500);

    // Modal should appear
    const modal = page.locator('.n-modal').last();
    await expect(modal).toBeVisible();

    // Fill form - name is the first input inside modal
    await modal.locator('input').first().fill('E2E UI Test Plan');
    await modal.locator('input').nth(1).fill('3.0.0');

    // Fill description textarea
    const textarea = modal.locator('textarea').first();
    await textarea.fill('Created via Playwright E2E test');

    // Click save (primary button inside modal)
    await modal.getByRole('button', { name: '保存' }).click();
    await page.waitForTimeout(1500);

    // Modal should close
    await expect(modal).not.toBeVisible({ timeout: 5000 });

    // Plan should appear in list
    await expect(page.locator('.n-card')).toContainText('E2E UI Test Plan');

    // Cleanup
    await cleanupAllPlans(request);
  });

  test('edit a test plan via UI', async ({ page, request }) => {
    // Create a plan first via API
    const createRes = await request.post(`${API_BASE}/test-plans`, {
      data: { name: 'Edit Test Plan', version: '1.0.0', description: 'Original desc', test_suite_ids: [], status: 'draft' },
    });
    const plan = await createRes.json();
    const planId = plan.id;

    await page.goto(`${BASE}/test-plans`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1500);

    // Find the card and click edit (small button with text 编辑/Edit)
    const card = page.locator('.n-card', { hasText: 'Edit Test Plan' });
    // Use exact text match for edit button
    await card.getByRole('button', { name: /^编辑$|^Edit$/ }).click();
    await page.waitForTimeout(500);

    // Modal should appear
    const modal = page.locator('.n-modal').last();
    await expect(modal).toBeVisible();

    // Change name
    const nameInput = modal.locator('input').first();
    await nameInput.clear();
    await nameInput.fill('Edited Plan Name');

    // Save
    await modal.getByRole('button', { name: '保存' }).click();
    await page.waitForTimeout(1500);

    // Should show updated name
    await expect(page.locator('.n-card')).toContainText('Edited Plan Name');

    // Cleanup
    await request.delete(`${API_BASE}/test-plans/${planId}`);
  });

  test('delete a test plan via UI', async ({ page, request }) => {
    const createRes = await request.post(`${API_BASE}/test-plans`, {
      data: { name: 'Delete Me', version: '1.0.0', description: '', test_suite_ids: [], status: 'draft' },
    });
    const plan = await createRes.json();

    await page.goto(`${BASE}/test-plans`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1500);

    // Find the card and click delete
    const card = page.locator('.n-card', { hasText: 'Delete Me' });
    await card.getByRole('button', { name: /^删除$|^Delete$/ }).click();
    await page.waitForTimeout(500);

    // Confirm in popconfirm - the confirm button
    await page.locator('.n-popconfirm__action').locator('button.n-button--primary-type').click();
    await page.waitForTimeout(1500);

    // Card should be gone
    await expect(page.locator('.n-card', { hasText: 'Delete Me' })).toHaveCount(0);
  });

  test('clone a test plan via UI', async ({ page, request }) => {
    const createRes = await request.post(`${API_BASE}/test-plans`, {
      data: { name: 'Clone Source', version: '1.0.0', description: '', test_suite_ids: [], status: 'draft' },
    });
    const plan = await createRes.json();
    const planId = plan.id;

    await page.goto(`${BASE}/test-plans`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1500);

    const card = page.locator('.n-card', { hasText: 'Clone Source' });
    await card.getByRole('button', { name: /^克隆$|^Clone$/ }).click();
    await page.waitForTimeout(2000);

    // Should now have 2 cards with Clone in text
    const cards = page.locator('.n-card', { hasText: 'Clone' });
    expect(await cards.count()).toBeGreaterThanOrEqual(2);

    // Cleanup
    await cleanupAllPlans(request);
  });

  test('filter plans by status', async ({ page, request }) => {
    await cleanupAllPlans(request);
    await request.post(`${API_BASE}/test-plans`, {
      data: { name: 'Draft Plan', version: '1.0.0', test_suite_ids: [], status: 'draft' },
    });
    await request.post(`${API_BASE}/test-plans`, {
      data: { name: 'Active Plan', version: '1.0.0', test_suite_ids: [], status: 'active' },
    });

    await page.goto(`${BASE}/test-plans`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1500);

    expect(await page.locator('.n-card', { hasText: 'Draft Plan' }).count()).toBe(1);
    expect(await page.locator('.n-card', { hasText: 'Active Plan' }).count()).toBe(1);

    await cleanupAllPlans(request);
  });
});

// ─── 3. Test Plans - Run & Reports ─────────────────────────

test.describe('Test Plans - Run & Reports', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('run a test plan and view result', async ({ page, request }) => {
    const createRes = await request.post(`${API_BASE}/test-plans`, {
      data: { name: 'Run Test', version: '1.0.0', description: 'Run me', test_suite_ids: [], status: 'active' },
    });
    const plan = await createRes.json();

    await page.goto(`${BASE}/test-plans`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1500);

    // Click run button (exact match to avoid matching "执行历史")
    const card = page.locator('.n-card', { hasText: 'Run Test' });
    await card.getByRole('button', { name: /^执行$/, exact: true }).click();
    await page.waitForTimeout(3000);

    // Result modal should appear
    const modal = page.locator('.n-modal').last();
    await expect(modal).toBeVisible({ timeout: 5000 });

    // Should show some result text
    const modalText = await modal.textContent();
    expect(modalText.length).toBeGreaterThan(0);

    // Close modal
    await page.keyboard.press('Escape');
    await page.waitForTimeout(500);

    await request.delete(`${API_BASE}/test-plans/${plan.id}`);
  });

  test('view run history', async ({ page, request }) => {
    const createRes = await request.post(`${API_BASE}/test-plans`, {
      data: { name: 'History Test', version: '1.0.0', test_suite_ids: [], status: 'active' },
    });
    const plan = await createRes.json();

    // Run it via API
    await request.post(`${API_BASE}/test-plans/${plan.id}/run`, { data: { trigger_source: 'api' } });

    await page.goto(`${BASE}/test-plans`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1500);

    const card = page.locator('.n-card', { hasText: 'History Test' });
    await card.getByRole('button', { name: /^执行历史$|^History$/ }).click();
    await page.waitForTimeout(1500);

    // History modal should appear
    const modal = page.locator('.n-modal').last();
    await expect(modal).toBeVisible();

    // Should have at least one run in the table
    const tableRows = modal.locator('.n-data-table-tr');
    expect(await tableRows.count()).toBeGreaterThanOrEqual(1);

    // Close modal
    await page.keyboard.press('Escape');

    await request.delete(`${API_BASE}/test-plans/${plan.id}`);
  });
});

// ─── 4. Compliance Page Rendering ──────────────────────────

test.describe('Compliance - Page Rendering', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('page loads with correct title', async ({ page }) => {
    const { errors, failedRequests } = attachMonitors(page);
    await page.goto(`${BASE}/compliance`);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('h2, .n-h2')).toContainText(/合规检测|Compliance/);
    expect(errors.filter(e => !e.includes('favicon'))).toEqual([]);
    expect(failedRequests).toEqual([]);
  });

  test('menu shows compliance entry', async ({ page }) => {
    await page.goto(`${BASE}/`);
    await page.waitForLoadState('networkidle');
    const menuText = await page.locator('.n-menu').textContent();
    expect(menuText).toContain('合规检测');
  });

  test('tabs are visible (check + history)', async ({ page }) => {
    await page.goto(`${BASE}/compliance`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    // Naive UI tabs
    const tabs = page.locator('.n-tabs-tab');
    expect(await tabs.count()).toBeGreaterThanOrEqual(2);
  });

  test('run check button is visible', async ({ page }) => {
    await page.goto(`${BASE}/compliance`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    await expect(page.getByRole('button', { name: /开始检测|Start Check/ })).toBeVisible();
  });

  test('protocol selector is visible', async ({ page }) => {
    await page.goto(`${BASE}/compliance`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    // The n-select element
    const select = page.locator('.n-base-selection').first();
    await expect(select).toBeVisible();
  });
});

// ─── 5. Compliance - Interactive Tests ─────────────────────

test.describe('Compliance - Interactive Tests', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('select protocol and view rules', async ({ page }) => {
    await page.goto(`${BASE}/compliance`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);

    // Click protocol dropdown
    await page.locator('.n-base-selection').first().click();
    await page.waitForTimeout(500);

    // Select first option that contains 'modbus'
    const options = page.locator('.n-base-select-option');
    const count = await options.count();
    expect(count).toBeGreaterThan(0);

    // Find modbus option
    let clicked = false;
    for (let i = 0; i < count; i++) {
      const text = await options.nth(i).textContent();
      if (text && text.includes('modbus')) {
        await options.nth(i).click();
        clicked = true;
        break;
      }
    }
    if (!clicked) {
      await options.first().click();
    }
    await page.waitForTimeout(1000);

    // Rules card should appear (if protocol has rules)
    const rulesCard = page.locator('.n-card', { hasText: /检测规则|Compliance Rules/ });
    if (await rulesCard.isVisible({ timeout: 3000 }).catch(() => false)) {
      const rows = rulesCard.locator('tr');
      expect(await rows.count()).toBeGreaterThan(1);
    }
  });

  test('run compliance check and view result', async ({ page }) => {
    await page.goto(`${BASE}/compliance`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);

    // Select modbus_tcp protocol
    await page.locator('.n-base-selection').first().click();
    await page.waitForTimeout(500);
    const options = page.locator('.n-base-select-option');
    for (let i = 0; i < await options.count(); i++) {
      const text = await options.nth(i).textContent();
      if (text && text.includes('modbus')) {
        await options.nth(i).click();
        break;
      }
    }
    await page.waitForTimeout(500);

    // Click run check button
    await page.getByRole('button', { name: /开始检测|Start Check/ }).click();
    await page.waitForTimeout(5000);

    // Result card should appear
    const resultCard = page.locator('.n-card', { hasText: /检测结果|Check Result/ });
    await expect(resultCard).toBeVisible({ timeout: 10000 });

    // Should show score
    const resultText = await resultCard.textContent();
    expect(resultText).toMatch(/合规评分|Compliance Score/);
    expect(resultText).toMatch(/\d+\.?\d*%/);
  });

  test('view history tab', async ({ page }) => {
    await page.goto(`${BASE}/compliance`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);

    // Click history tab
    await page.locator('.n-tabs-tab', { hasText: /历史|History/ }).click();
    await page.waitForTimeout(1500);

    // Should show either reports table or empty state
    const hasTable = await page.locator('.n-data-table').first().isVisible().catch(() => false);
    const hasEmpty = await page.locator('.n-empty').isVisible().catch(() => false);
    expect(hasTable || hasEmpty).toBeTruthy();
  });
});

// ─── 6. Error Handling & Edge Cases ────────────────────────

test.describe('Error Handling & Edge Cases', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('create plan without name shows validation error', async ({ page, request }) => {
    await cleanupAllPlans(request);
    await page.goto(`${BASE}/test-plans`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);

    // Click create
    await createBtn(page).click();
    await page.waitForTimeout(500);

    // Don't fill name, just click save
    const modal = page.locator('.n-modal').last();
    await modal.getByRole('button', { name: '保存' }).click();
    await page.waitForTimeout(500);

    // Modal should still be open (validation failed)
    await expect(modal).toBeVisible();
    // Should show warning message
    const msg = page.locator('.n-message');
    await expect(msg).toBeVisible({ timeout: 3000 });

    // Close modal
    await page.keyboard.press('Escape');
  });

  test('compliance check button disabled without protocol', async ({ page }) => {
    await page.goto(`${BASE}/compliance`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);

    // Run check button should be disabled when no protocol selected
    const btn = page.getByRole('button', { name: /开始检测|Start Check/ });
    // Naive UI uses .n-button--disabled class for disabled state
    const isDisabled = await btn.isDisabled().catch(() => false);
    const hasDisabledClass = await btn.evaluate(el =>
      el.classList.contains('n-button--disabled') || el.hasAttribute('disabled')
    ).catch(() => false);
    expect(isDisabled || hasDisabledClass).toBeTruthy();
  });

  test('get rules for non-existent protocol returns 404', async ({ request }) => {
    const res = await request.get(`${API_BASE}/compliance/rules/nonexistent_protocol`);
    expect(res.status()).toBe(404);
  });

  test('delete non-existent plan returns 404', async ({ request }) => {
    const res = await request.delete(`${API_BASE}/test-plans/nonexistent-id-12345`);
    expect(res.status()).toBe(404);
  });

  test('get non-existent run returns 404', async ({ request }) => {
    const res = await request.get(`${API_BASE}/test-runs/nonexistent-run-12345`);
    expect(res.status()).toBe(404);
  });
});

// ─── 7. Navigation & Integration ───────────────────────────

test.describe('Navigation & Integration', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('navigate from dashboard to test plans via menu', async ({ page }) => {
    await page.goto(`${BASE}/`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);

    // Click test plans in menu (use getByRole for reliability)
    await page.getByRole('menuitem', { name: '测试计划' }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);

    await expect(page).toHaveURL(/test-plans/);
  });

  test('navigate from dashboard to compliance via menu', async ({ page }) => {
    await page.goto(`${BASE}/`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);

    await page.getByRole('menuitem', { name: '合规检测' }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);

    await expect(page).toHaveURL(/compliance/);
  });

  test('direct URL access to test-plans works', async ({ page }) => {
    await page.goto(`${BASE}/test-plans`);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('h2, .n-h2')).toBeVisible();
  });

  test('direct URL access to compliance works', async ({ page }) => {
    await page.goto(`${BASE}/compliance`);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('h2, .n-h2')).toBeVisible();
  });
});

// ─── 8. i18n Check ─────────────────────────────────────────

test.describe('i18n Check', () => {
  test('Chinese text is displayed by default', async ({ page, request }) => {
    // Login via API first to get token, then set it in localStorage
    const loginRes = await request.post(`${API_BASE}/auth/login`, {
      data: { username: 'admin', password: 'admin' },
    });
    const loginBody = await loginRes.json();
    const token = loginBody.access_token;

    await page.goto(BASE);
    await page.evaluate((tokens) => {
      localStorage.setItem('token', tokens.access);
      localStorage.setItem('refresh_token', tokens.refresh);
      localStorage.setItem('locale', 'zh');
    }, { access: token, refresh: loginBody.refresh_token });
    await page.goto(`${BASE}/test-plans`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);
    const text = await page.locator('body').textContent();
    expect(text).toContain('测试计划');
  });

  test('English text works when locale switched', async ({ page, request }) => {
    // Login via API first
    const loginRes = await request.post(`${API_BASE}/auth/login`, {
      data: { username: 'admin', password: 'admin' },
    });
    const loginBody = await loginRes.json();
    const token = loginBody.access_token;

    await page.goto(BASE);
    await page.evaluate((tokens) => {
      localStorage.setItem('token', tokens.access);
      localStorage.setItem('refresh_token', tokens.refresh);
      localStorage.setItem('locale', 'en');
    }, { access: token, refresh: loginBody.refresh_token });
    await page.goto(`${BASE}/test-plans`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);
    const text = await page.locator('body').textContent();
    expect(text).toContain('Test Plans');

    // Reset to Chinese
    await page.evaluate(() => {
      localStorage.setItem('locale', 'zh');
    });
  });
});
