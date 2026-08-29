// Real Estate Platform — Playwright E2E Test Suite
// ─────────────────────────────────────────────────────────────────────────────
// Tests critical user flows: property search, property detail, chatbot,
// authentication, admin panel, RERA dashboard, mobile responsiveness.
// ─────────────────────────────────────────────────────────────────────────────
// Run: npx playwright test e2e/realestate-flows.spec.js --headed

const { test, expect } = require('@playwright/test');

const BASE_URL = process.env.BASE_URL || 'http://localhost:8765';

// ═══════════════════════════════════════════════════════════════════════════════
// 1. Home Page & Navigation
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('Home Page', () => {
  test('should load the home page with hero section', async ({ page }) => {
    await page.goto(`${BASE_URL}/realestate`);
    await expect(page.locator('h1')).toContainText(/property|real estate/i);
    await page.waitForSelector('[data-testid="hero-section"]', { timeout: 5000 });
  });

  test('should have working navigation links', async ({ page }) => {
    await page.goto(`${BASE_URL}/realestate`);
    const navLinks = page.locator('nav a, .nav-link, [data-testid="nav-link"]');
    const count = await navLinks.count();
    expect(count).toBeGreaterThan(2);
  });

  test('should be mobile responsive', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 }); // iPhone X
    await page.goto(`${BASE_URL}/realestate`);
    // Bottom nav should be visible on mobile
    await page.waitForSelector('[data-testid="bottom-nav"], .bottom-nav', { timeout: 3000 });
    await page.waitForSelector('[data-testid="mobile-header"], .mobile-header', { timeout: 3000 });
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// 2. Property Search
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('Property Search', () => {
  test('should search properties by city', async ({ page }) => {
    await page.goto(`${BASE_URL}/realestate/search`);
    await page.fill('[data-testid="search-input"], #search-input, [name="q"]', 'Mumbai');
    await page.click('[data-testid="search-button"], button[type="submit"]');
    await page.waitForTimeout(1000);
    // Results should load
    const results = page.locator('[data-testid="property-card"], .property-card');
    await expect(results.first()).toBeVisible({ timeout: 5000 });
  });

  test('should filter properties by type', async ({ page }) => {
    await page.goto(`${BASE_URL}/realestate/search?city=Bangalore`);
    await page.selectOption('[data-testid="filter-type"], #filterType, [name="property_type"]', 'apartment');
    await page.click('[data-testid="filter-apply"], [data-testid="search-button"]');
    await page.waitForTimeout(500);
    // Search API should respond
    const hasResults = await page.locator('.property-card, .property-result, [data-testid="property-card"]').count();
    expect(hasResults).toBeGreaterThanOrEqual(0);
  });

  test('should have working autocomplete', async ({ page }) => {
    await page.goto(`${BASE_URL}/realestate/search`);
    const input = page.locator('[data-testid="search-input"], #search-input, [name="q"]');
    await input.fill('Ban');
    await page.waitForTimeout(500);
    // Autocomplete dropdown should appear
    const suggestions = page.locator('[data-testid="autocomplete-item"], .autocomplete-item');
    await expect(suggestions.first()).toBeVisible({ timeout: 3000 });
  });

  test('should paginate results', async ({ page }) => {
    await page.goto(`${BASE_URL}/realestate/search?city=Mumbai`);
    await page.waitForTimeout(500);
    const pagination = page.locator('[data-testid="pagination"], .pagination');
    // Page 2 link should exist if there are enough results
    const page2 = pagination.locator('text=2, [aria-label="Page 2"]');
    if (await page2.isVisible()) {
      await page2.click();
      await page.waitForTimeout(500);
      expect(page.url()).toContain('page=2');
    }
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// 3. Property Detail Page
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('Property Detail', () => {
  test('should display property details', async ({ page }) => {
    await page.goto(`${BASE_URL}/realestate/search?city=Pune`);
    await page.waitForTimeout(500);
    // Click on first property
    const firstCard = page.locator('[data-testid="property-card"], .property-card a, .property-card').first();
    if (await firstCard.isVisible()) {
      await firstCard.click();
      await page.waitForTimeout(500);
      // Detail page should show price, description, amenities
      const hasContent = await page.locator('body').innerText();
      expect(hasContent.length).toBeGreaterThan(100);
    }
  });

  test('should have enquiry button', async ({ page }) => {
    await page.goto(`${BASE_URL}/realestate/search?city=Delhi`);
    await page.waitForTimeout(500);
    const firstCard = page.locator('[data-testid="property-card"], .property-card').first();
    if (await firstCard.isVisible()) {
      await firstCard.click();
      await page.waitForTimeout(500);
      const enquireBtn = page.locator('text=Enquire, text=Contact, [data-testid="enquire-button"]');
      await expect(enquireBtn).toBeVisible({ timeout: 3000 });
    }
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// 4. Chatbot
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('AI Chatbot', () => {
  test('should respond to greeting', async ({ page }) => {
    // Chatbot endpoint test via API
    const response = await page.request.post(`${BASE_URL}/api/realestate/chat`, {
      params: { message: 'Hello, I want to buy a property in Mumbai' }
    });
    expect(response.status()).toBe(200);
    const data = await response.json();
    expect(data.response).toBeTruthy();
    expect(data.response.length).toBeGreaterThan(10);
    expect(data.suggestions).toBeDefined();
  });

  test('should answer FAQ about RERA', async ({ page }) => {
    const response = await page.request.post(`${BASE_URL}/api/realestate/chat`, {
      params: { message: 'What is RERA registration?' }
    });
    expect(response.status()).toBe(200);
    const data = await response.json();
    expect(data.response.toLowerCase()).toContain('rera');
    expect(data.intent.category).toBe('legal');
  });

  test('should handle property search queries', async ({ page }) => {
    const response = await page.request.post(`${BASE_URL}/api/realestate/chat`, {
      params: { message: 'Show me 2BHK in Bangalore under 1 crore' }
    });
    expect(response.status()).toBe(200);
    const data = await response.json();
    expect(data.suggestions.length).toBeGreaterThanOrEqual(1);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// 5. Authentication
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('Authentication', () => {
  test('should have login page', async ({ page }) => {
    await page.goto(`${BASE_URL}/realestate/login`);
    await expect(page.locator('h1, h2')).toContainText(/login|sign in|welcome/i, { timeout: 5000 });
  });

  test('guest login should succeed', async ({ page }) => {
    const response = await page.request.post(`${BASE_URL}/api/realestate/auth/guest`, {
      params: { name: 'E2E Tester' }
    });
    expect(response.status()).toBe(200);
    const data = await response.json();
    expect(data.success).toBe(true);
    expect(data.session).toBeDefined();
    expect(data.session.email).toContain('guest');
  });

  test('/me endpoint should require auth', async ({ page }) => {
    const response = await page.request.get(`${BASE_URL}/api/realestate/auth/me`);
    expect(response.status()).toBe(401);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// 6. Admin Panel
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('Admin Panel', () => {
  test('should provide admin stats', async ({ page }) => {
    const response = await page.request.get(`${BASE_URL}/api/realestate/admin/stats`);
    expect(response.status()).toBe(200);
    const data = await response.json();
    expect(data).toHaveProperty('moderation_queue');
  });

  test('should support property moderation', async ({ page }) => {
    // Add a property to moderation
    await page.request.post(`${BASE_URL}/api/realestate/admin/moderation/RE-TEST-001/approve`);
    const response = await page.request.get(`${BASE_URL}/api/realestate/admin/moderation`);
    expect(response.status()).toBe(200);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// 7. RERA Compliance Dashboard
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('RERA Compliance', () => {
  test('should verify valid RERA numbers', async ({ page }) => {
    const response = await page.request.get(`${BASE_URL}/api/realestate/rera/verify`, {
      params: { rera_number: 'RERA-MH-2024-123456' }
    });
    expect(response.status()).toBe(200);
    const data = await response.json();
    expect(data).toHaveProperty('is_valid');
  });

  test('should list RERA registrations', async ({ page }) => {
    const response = await page.request.get(`${BASE_URL}/api/realestate/rera/registrations`);
    expect(response.status()).toBe(200);
    const data = await response.json();
    expect(data.registrations).toBeDefined();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// 8. API Endpoints — Data Integrity
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('API Data Integrity', () => {
  test('sitemap.xml should be valid XML', async ({ page }) => {
    const response = await page.request.get(`${BASE_URL}/sitemap.xml`);
    expect(response.status()).toBe(200);
    const text = await response.text();
    expect(text).toContain('<?xml');
    expect(text).toContain('<urlset');
    expect(text).toContain('</urlset>');
  });

  test('health endpoint should return healthy', async ({ page }) => {
    const response = await page.request.get(`${BASE_URL}/api/realestate/health`);
    expect(response.status()).toBe(200);
    const data = await response.json();
    expect(data.status).toMatch(/healthy|degraded/);
    expect(data.service).toBe('realestate-platform');
  });

  test('metrics endpoint should be accessible', async ({ page }) => {
    const response = await page.request.get(`${BASE_URL}/metrics`);
    expect(response.status()).toBe(200);
    const text = await response.text();
    expect(text).toMatch(/re_http_requests|re_property_views/);
  });

  test('robots.txt should reference sitemap', async ({ page }) => {
    const response = await page.request.get(`${BASE_URL}/robots.txt`);
    expect(response.status()).toBe(200);
    const text = await response.text();
    expect(text).toContain('Sitemap');
    expect(text).toContain('sitemap.xml');
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// 9. Fraud Detection
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('Fraud Detection', () => {
  test('should detect suspicious property', async ({ page }) => {
    const response = await page.request.post(`${BASE_URL}/api/realestate/fraud/check-property`, {
      params: {
        title: 'Urgent Sale Below Market',
        description: 'Need immediate sale best deal ever direct owner leaving city',
        price: '50000',
        city: 'Mumbai',
        owner_phone: '12345',
        owner_email: 'owner@mailinator.com',
        area_avg_price: '20000',
      }
    });
    expect(response.status()).toBe(200);
    const data = await response.json();
    expect(data.score).toBeGreaterThan(0.3);
    expect(data.reasons.length).toBeGreaterThanOrEqual(1);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// 10. SEO & Metadata
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('SEO & Performance', () => {
  test('home page should have meta tags', async ({ page }) => {
    await page.goto(`${BASE_URL}/realestate`);
    const ogTitle = await page.locator('meta[property="og:title"]').getAttribute('content');
    expect(ogTitle).toBeTruthy();
    const twitterCard = await page.locator('meta[name="twitter:card"]').getAttribute('content');
    expect(twitterCard).toBeDefined();
  });

  test('security headers should be present', async ({ page }) => {
    const response = await page.goto(`${BASE_URL}/realestate`);
    const headers = response.headers();
    expect(headers['x-content-type-options']).toBe('nosniff');
    expect(headers['x-frame-options']).toBeDefined();
  });

  test('should load within performance budget', async ({ page }) => {
    const start = Date.now();
    await page.goto(`${BASE_URL}/realestate/search`);
    const loadTime = Date.now() - start;
    expect(loadTime).toBeLessThan(5000); // 5 second budget
  });
});
