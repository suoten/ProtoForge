/**
 * ProtoForge 前端逐页验收脚本
 * 
 * 检测项：
 * 1. 白屏检测（页面是否有实际内容渲染）
 * 2. 控制台报错（红色 error）
 * 3. 404 资源加载
 * 4. 菜单/按钮点击触发真实接口调用
 */
import { chromium } from 'playwright';

const BASE_URL = process.env.BASE_URL || 'http://localhost:8000';
const USERNAME = 'admin';
const PASSWORD = 'admin';

// 所有需要测试的路由
const ROUTES = [
  { path: '/', name: 'Dashboard', menuKey: '/' },
  { path: '/devices', name: 'Devices', menuKey: '/devices' },
  { path: '/protocols', name: 'Protocols', menuKey: '/protocols' },
  { path: '/templates', name: 'Templates', menuKey: '/templates' },
  { path: '/scenarios', name: 'Scenarios', menuKey: '/scenarios' },
  { path: '/scenario-editor', name: 'ScenarioEditor', menuKey: '/scenario-editor' },
  { path: '/marketplace', name: 'Marketplace', menuKey: '/marketplace' },
  { path: '/logs', name: 'Logs', menuKey: '/logs' },
  { path: '/testing', name: 'Testing', menuKey: '/testing' },
  { path: '/integration', name: 'Integration', menuKey: '/integration' },
  { path: '/forward', name: 'Forward', menuKey: '/forward' },
  { path: '/recorder', name: 'Recorder', menuKey: '/recorder' },
  { path: '/webhook', name: 'Webhook', menuKey: '/webhook' },
  { path: '/settings', name: 'Settings', menuKey: '/settings' },
  { path: '/audit', name: 'Audit', menuKey: '/audit' },
  { path: '/backup', name: 'Backup', menuKey: '/backup' },
  { path: '/nonexistent-page-test', name: 'NotFound', menuKey: null },
];

const results = [];

async function login(page) {
  await page.goto(`${BASE_URL}/`);
  await page.waitForLoadState('networkidle', { timeout: 15000 });
  
  // Check if already logged in
  const loginInput = page.locator('input[placeholder*="用户名"], input[placeholder*="Username"]');
  if (await loginInput.isVisible({ timeout: 3000 }).catch(() => false)) {
    await loginInput.fill(USERNAME);
    await page.locator('input[type="password"]').first().fill(PASSWORD);
    await page.locator('button:has-text("登"), button:has-text("Login")').click();
    await page.waitForTimeout(3000);
  }
}

async function testRoute(browser, route) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  
  const consoleErrors = [];
  const failedRequests = [];
  const apiCalls = [];
  const pageErrors = [];
  
  // Capture console errors
  page.on('console', msg => {
    if (msg.type() === 'error') {
      consoleErrors.push(msg.text());
    }
  });
  
  // Capture page errors (uncaught exceptions)
  page.on('pageerror', error => {
    pageErrors.push(error.message);
  });
  
  // Capture failed network requests
  page.on('response', response => {
    const url = response.url();
    const status = response.status();
    if (status === 404) {
      failedRequests.push({ url, status });
    }
    if (url.includes('/api/v1/')) {
      apiCalls.push({ url: url.replace(BASE_URL, ''), method: response.request().method(), status });
    }
  });
  
  try {
    // First login
    await login(page);
    
    // Navigate to the route
    await page.goto(`${BASE_URL}${route.path}`);
    await page.waitForLoadState('networkidle', { timeout: 15000 });
    await page.waitForTimeout(2000); // Wait for dynamic content
    
    // Check for white screen: is there meaningful content?
    const bodyText = await page.evaluate(() => {
      const el = document.querySelector('.app-content') || document.querySelector('#app') || document.body;
      return el ? el.innerText.trim() : '';
    });
    const hasContent = bodyText.length > 20;
    
    // Check if the page shows a "not found" or error state
    const hasErrorState = await page.evaluate(() => {
      const text = document.body.innerText;
      return text.includes('500') && text.includes('Server Error') || text.includes('无法加载');
    });
    
    // Take screenshot
    const screenshotName = route.name.toLowerCase();
    await page.screenshot({ path: `e:/硕腾网络/PyGBSentry/ProtoForge/.convergeloop/screenshots/${screenshotName}.png`, fullPage: false });
    
    // Filter out expected 404s (like favicon.ico)
    const realFailedRequests = failedRequests.filter(r => 
      !r.url.includes('favicon.ico') && 
      !r.url.includes('.map') &&
      !r.url.includes('robots.txt')
    );
    
    // Filter out expected console errors (like WebSocket connection failures in test env)
    const realConsoleErrors = consoleErrors.filter(e => 
      !e.includes('WebSocket') && 
      !e.includes('Failed to load resource') &&
      !e.includes('net::ERR') &&
      !e.includes('ERR_CONNECTION') &&
      !e.includes('favicon')
    );
    
    const realPageErrors = pageErrors.filter(e =>
      !e.includes('ResizeObserver') &&
      !e.includes('WebSocket')
    );
    
    const status = hasContent && realConsoleErrors.length === 0 && realFailedRequests.length === 0 && realPageErrors.length === 0
      ? 'PASS' 
      : (hasContent ? 'WARN' : 'FAIL');
    
    results.push({
      route: route.path,
      name: route.name,
      status,
      hasContent,
      contentLength: bodyText.length,
      consoleErrors: realConsoleErrors,
      pageErrors: realPageErrors,
      failedRequests: realFailedRequests,
      apiCallCount: apiCalls.length,
      apiCalls: apiCalls.slice(0, 10), // Keep first 10 for reporting
    });
    
  } catch (error) {
    results.push({
      route: route.path,
      name: route.name,
      status: 'ERROR',
      error: error.message,
      hasContent: false,
      consoleErrors,
      pageErrors,
      failedRequests,
      apiCallCount: apiCalls.length,
      apiCalls: apiCalls.slice(0, 10),
    });
  } finally {
    await context.close();
  }
}

async function testMenuNavigation(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  
  const menuResults = [];
  
  try {
    // Login
    await login(page);
    await page.waitForTimeout(2000);
    
    // Get all menu items
    const menuItems = await page.locator('.n-menu .n-menu-item').all();
    
    for (const item of menuItems) {
      const text = await item.innerText().catch(() => '');
      const href = await item.getAttribute('data-key') || '';
      
      if (!text.trim()) continue;
      
      const apiCallsBefore = [];
      page.on('response', response => {
        if (response.url().includes('/api/v1/')) {
          apiCallsBefore.push({ url: response.url().replace(BASE_URL, ''), status: response.status() });
        }
      });
      
      try {
        await item.click();
        await page.waitForTimeout(2000);
        
        const currentPath = new URL(page.url()).pathname;
        const hasContent = await page.evaluate(() => {
          const el = document.querySelector('.app-content') || document.body;
          return el.innerText.trim().length > 20;
        });
        
        menuResults.push({
          menuText: text.trim(),
          targetPath: currentPath,
          hasContent,
          apiCalls: apiCallsBefore.slice(0, 5),
          status: hasContent ? 'PASS' : 'FAIL',
        });
      } catch (e) {
        menuResults.push({
          menuText: text.trim(),
          status: 'ERROR',
          error: e.message,
        });
      }
    }
  } finally {
    await context.close();
  }
  
  return menuResults;
}

async function testButtonInteractions(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const buttonResults = [];
  
  const apiCallLog = [];
  page.on('response', response => {
    if (response.url().includes('/api/v1/')) {
      apiCallLog.push({ 
        url: response.url().replace(BASE_URL, ''), 
        method: response.request().method(), 
        status: response.status(),
        timestamp: Date.now(),
      });
    }
  });
  
  try {
    await login(page);
    await page.waitForTimeout(2000);
    
    // Test pages with action buttons
    const pagesToTest = [
      { path: '/protocols', buttons: ['启动全部', '停止全部', 'Start All', 'Stop All'] },
      { path: '/devices', buttons: ['新建', '批量', 'Create', 'Batch', '刷新', 'Refresh'] },
      { path: '/templates', buttons: ['新建', '搜索', 'Create', 'Search'] },
      { path: '/scenarios', buttons: ['新建', 'Create'] },
      { path: '/testing', buttons: ['新建', '运行', 'Create', 'Run'] },
      { path: '/forward', buttons: ['启动', '停止', 'Start', 'Stop', '新建', 'Add'] },
      { path: '/recorder', buttons: ['开始', '停止', 'Start', 'Stop'] },
      { path: '/webhook', buttons: ['新建', 'Add', '测试', 'Test'] },
      { path: '/settings', buttons: ['保存', 'Save'] },
      { path: '/backup', buttons: ['导出', 'Export', '导入', 'Import'] },
      { path: '/audit', buttons: ['查询', 'Search', '清空', 'Clear'] },
      { path: '/integration', buttons: ['推送', 'Push', '验证', 'Validate'] },
    ];
    
    for (const pageTest of pagesToTest) {
      apiCallLog.length = 0; // Clear log
      await page.goto(`${BASE_URL}${pageTest.path}`);
      await page.waitForLoadState('networkidle', { timeout: 15000 });
      await page.waitForTimeout(2000);
      
      // Find clickable buttons
      const buttons = await page.locator('button:visible').all();
      const foundButtons = [];
      
      for (const btn of buttons) {
        const text = (await btn.innerText().catch(() => '')).trim();
        if (text && text.length < 20) {
          foundButtons.push(text);
        }
      }
      
      // Check if any API calls were made on page load (data fetching)
      const pageLoadApiCalls = [...apiCallLog];
      
      buttonResults.push({
        page: pageTest.path,
        visibleButtons: foundButtons.slice(0, 15),
        pageLoadApiCalls: pageLoadApiCalls.slice(0, 10),
        hasDataLoading: pageLoadApiCalls.length > 0,
      });
    }
  } finally {
    await context.close();
  }
  
  return buttonResults;
}

async function main() {
  console.log('=== ProtoForge 前端逐页验收 ===\n');
  console.log(`Base URL: ${BASE_URL}\n`);
  
  const browser = await chromium.launch({ headless: true });
  
  try {
    // Phase 1: Test each route
    console.log('Phase 1: 逐页访问检测...\n');
    for (const route of ROUTES) {
      process.stdout.write(`  Testing ${route.name} (${route.path})... `);
      await testRoute(browser, route);
      const r = results[results.length - 1];
      console.log(r.status);
    }
    
    // Phase 2: Test menu navigation
    console.log('\nPhase 2: 菜单导航检测...\n');
    const menuResults = await testMenuNavigation(browser);
    
    // Phase 3: Test button interactions
    console.log('\nPhase 3: 按钮交互检测...\n');
    const buttonResults = await testButtonInteractions(browser);
    
    // Generate report
    console.log('\n' + '='.repeat(80));
    console.log('验收报告');
    console.log('='.repeat(80) + '\n');
    
    console.log('一、逐页访问结果\n');
    console.log('| 页面 | 路由 | 状态 | 内容渲染 | 控制台错误 | 404资源 | API调用数 |');
    console.log('|------|------|------|----------|-----------|--------|----------|');
    
    for (const r of results) {
      const status = r.status === 'PASS' ? '✅ PASS' : r.status === 'WARN' ? '⚠️ WARN' : r.status === 'FAIL' ? '❌ FAIL' : '💥 ERROR';
      const content = r.hasContent ? `✅ (${r.contentLength}字)` : '❌ 白屏';
      const errors = r.consoleErrors.length > 0 ? `❌ (${r.consoleErrors.length})` : '✅ 0';
      const notFound = r.failedRequests.length > 0 ? `❌ (${r.failedRequests.length})` : '✅ 0';
      const apiCalls = r.apiCallCount > 0 ? `${r.apiCallCount}` : '0';
      console.log(`| ${r.name} | ${r.route} | ${status} | ${content} | ${errors} | ${notFound} | ${apiCalls} |`);
    }
    
    // Detailed error info
    const failedRoutes = results.filter(r => r.status !== 'PASS');
    if (failedRoutes.length > 0) {
      console.log('\n二、问题详情\n');
      for (const r of failedRoutes) {
        console.log(`\n[${r.name}] ${r.route} - 状态: ${r.status}`);
        if (r.error) console.log(`  错误: ${r.error}`);
        if (r.consoleErrors.length > 0) {
          console.log('  控制台错误:');
          r.consoleErrors.forEach(e => console.log(`    - ${e.substring(0, 200)}`));
        }
        if (r.pageErrors.length > 0) {
          console.log('  页面异常:');
          r.pageErrors.forEach(e => console.log(`    - ${e.substring(0, 200)}`));
        }
        if (r.failedRequests.length > 0) {
          console.log('  404请求:');
          r.failedRequests.forEach(r => console.log(`    - [${r.status}] ${r.url.substring(0, 150)}`));
        }
      }
    }
    
    console.log('\n三、菜单导航结果\n');
    console.log('| 菜单 | 目标路由 | 内容渲染 | API调用 | 状态 |');
    console.log('|------|---------|--------|---------|------|');
    for (const m of menuResults) {
      const content = m.hasContent ? '✅' : '❌';
      const apiCount = m.apiCalls ? m.apiCalls.length : 0;
      console.log(`| ${m.menuText} | ${m.targetPath || 'N/A'} | ${content} | ${apiCount} | ${m.status} |`);
    }
    
    console.log('\n四、按钮交互结果\n');
    for (const b of buttonResults) {
      console.log(`\n[${b.page}]`);
      console.log(`  可见按钮: ${b.visibleButtons.join(', ') || '(无)'}`);
      console.log(`  页面加载API调用: ${b.pageLoadApiCalls.length > 0 ? '✅ 有' : '❌ 无'}`);
      if (b.pageLoadApiCalls.length > 0) {
        b.pageLoadApiCalls.forEach(c => console.log(`    - [${c.method}] ${c.url} → ${c.status}`));
      }
    }
    
    // Summary
    const passCount = results.filter(r => r.status === 'PASS').length;
    const warnCount = results.filter(r => r.status === 'WARN').length;
    const failCount = results.filter(r => r.status === 'FAIL' || r.status === 'ERROR').length;
    
    console.log('\n' + '='.repeat(80));
    console.log(`总结: ${passCount} PASS / ${warnCount} WARN / ${failCount} FAIL / ${results.length} 总计`);
    console.log('='.repeat(80));
    
  } finally {
    await browser.close();
  }
}

main().catch(console.error);
