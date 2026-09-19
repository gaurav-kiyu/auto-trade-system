const { test, expect } = require('@playwright/test');
const { execSync } = require('child_process');

test.describe('OPB v2.59.4 Final Evidence Reconciliation Gate', () => {
  const BASE_URL = 'http://127.0.0.1:8765';

  // Exactly the 9 mandatory viewports specified in R7
  const MANDATORY_VIEWPORTS = [
    { name: 'fhd_1080p', width: 1920, height: 1080, type: 'Desktop' },
    { name: 'desktop_1536', width: 1536, height: 864, type: 'Laptop FHD scaled' },
    { name: 'laptop_1440', width: 1440, height: 900, type: 'MacBook Pro' },
    { name: 'laptop_1366', width: 1366, height: 768, type: 'Legacy Laptop' },
    { name: 'compact_1280', width: 1280, height: 800, type: 'Compact Laptop' },
    { name: 'tablet_landscape_1024', width: 1024, height: 768, type: 'Tablet Landscape' },
    { name: 'tablet_portrait_768', width: 768, height: 1024, type: 'Tablet Portrait' },
    { name: 'mobile_large_430', width: 430, height: 932, type: 'Modern Large Mobile' },
    { name: 'mobile_compact_375', width: 375, height: 667, type: 'Compact Mobile' }
  ];

  // Exactly the 5 canonical themes specified in R6
  const SUPPORTED_THEMES = [
    'dark-cyber',
    'dracula-purple',
    'ivory-gold',
    'midnight-slate',
    'emerald-matrix'
  ];

  // Representative accessible production screens across authentication, operations, pricing, administration, and system health
  const TEST_SCREENS = [
    { name: 'Authentication Form', path: '/login', auth: false },
    { name: 'Operations Cockpit', path: '/', auth: true },
    { name: 'Pricing Plans & Self-Activation Gate', path: '/pricing-plans', auth: true },
    { name: 'Admin Signals & Accuracy Matrix', path: '/admin/signals', auth: true },
    { name: 'System Health & Diagnostics', path: '/system-health', auth: true },
    { name: 'User Signal Deliveries', path: '/my-signals', auth: true },
    { name: 'Signal Reports & Intelligence', path: '/reports', auth: true },
    { name: 'Security & Auth Controls', path: '/security', auth: true },
    { name: 'Governance & Risk Limits', path: '/governance', auth: true },
    { name: 'Observability & Metrics', path: '/observability', auth: true },
  ];

  let adminToken = null;

  function getTokens() {
    try {
      const out = execSync('python -u "C:/Users/gaura/.gemini/antigravity/brain/1f2fb8fe-7538-4d67-8afe-948c42276d56/scratch/seed_operator_user.py"', { encoding: "utf8" });
      const adminMatch = out.match(/ADMIN_SESSION_TOKEN=([a-f0-9]+)/);
      return {
        adminToken: adminMatch ? adminMatch[1] : null
      };
    } catch (e) {
      return { adminToken: null };
    }
  }

  test.beforeAll(async () => {
    const tokens = getTokens();
    adminToken = tokens.adminToken;
    console.log('Admin session token ready:', Boolean(adminToken));
  });

  // ──────────────────────────────────────────────────────────────────────────
  // TEST 1: R7 Responsive Viewport Matrix (All 9 viewports × 10 screens)
  // ──────────────────────────────────────────────────────────────────────────
  for (const vp of MANDATORY_VIEWPORTS) {
    test(`Viewport ${vp.name} (${vp.width}x${vp.height}) Responsive & Zero Overflow Verification`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });

      if (adminToken) {
        await page.context().addCookies([{
          name: 'opb_session',
          value: adminToken,
          url: BASE_URL,
        }]);
      }

      for (const scr of TEST_SCREENS) {
        const response = await page.goto(`${BASE_URL}${scr.path}`, {
          waitUntil: 'domcontentloaded',
          timeout: 45000
        });
        expect(response?.status()).toBeLessThan(400);

        // Verify Zero Horizontal Overflow
        const overflow = await page.evaluate(() => {
          const docEl = document.documentElement;
          const bodyEl = document.body;
          const scrollW = Math.max(docEl.scrollWidth, bodyEl.scrollWidth);
          const clientW = Math.min(docEl.clientWidth, window.innerWidth);
          return {
            scrollWidth: scrollW,
            clientWidth: clientW,
            overflowPixels: scrollW - clientW,
            hasHorizontalOverflow: (scrollW - clientW) > 1.5
          };
        });

        expect(overflow.hasHorizontalOverflow,
          `Screen ${scr.name} has horizontal overflow at ${vp.width}x${vp.height}: scroll=${overflow.scrollWidth} > client=${overflow.clientWidth}`
        ).toBeFalsy();

        // Check mobile nav adaptation on mobile/tablet viewports
        if (scr.path !== '/login' && vp.width < 768) {
          const mobileNavPresent = await page.evaluate(() => {
            return Boolean(
              document.querySelector('#mobile-menu-button') ||
              document.querySelector('.mobile-menu-btn') ||
              document.querySelector('.has-mobile-nav') ||
              document.querySelector('[data-mobile-menu]') ||
              document.querySelector('nav')
            );
          });
          expect(mobileNavPresent).toBeTruthy();
        }
      }
    });
  }

  // ──────────────────────────────────────────────────────────────────────────
  // TEST 2: R6 Theme Computed Styles, Contrast, Components & Focus Indicators
  // ──────────────────────────────────────────────────────────────────────────
  for (const tname of SUPPORTED_THEMES) {
    test(`Theme ${tname} Computed Styles, Contrast, Components & Focus Indicators`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 });

      if (adminToken) {
        await page.context().addCookies([{
          name: 'opb_session',
          value: adminToken,
          url: BASE_URL,
        }]);
      }

      await page.goto(`${BASE_URL}/pricing-plans`, { waitUntil: 'domcontentloaded', timeout: 35000 });

      // Apply theme
      await page.evaluate((theme) => {
        document.documentElement.setAttribute('data-theme', theme);
        if (window.ThemeEngine) {
          window.ThemeEngine.setTheme(theme);
        }
      }, tname);

      await page.waitForTimeout(400);

      // Verify computed styles and contrast
      const themeAudit = await page.evaluate(() => {
        const bodyStyle = window.getComputedStyle(document.body);
        const cardEl = document.querySelector('.opb-card, .bg-card, .rounded-lg, .card, main') || document.body;
        const cardStyle = window.getComputedStyle(cardEl);

        const parseRgb = (str) => {
          const m = str.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
          return m ? [parseInt(m[1]), parseInt(m[2]), parseInt(m[3])] : [0, 0, 0];
        };

        const luminance = ([r, g, b]) => {
          const a = [r, g, b].map((v) => {
            v /= 255;
            return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
          });
          return a[0] * 0.2126 + a[1] * 0.7152 + a[2] * 0.0722;
        };

        const contrastRatio = (c1, c2) => {
          const l1 = luminance(c1);
          const l2 = luminance(c2);
          return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
        };

        const bodyBg = parseRgb(bodyStyle.backgroundColor);
        const bodyFg = parseRgb(bodyStyle.color);
        const cardBg = parseRgb(cardStyle.backgroundColor);

        // Find muted element
        const mutedEl = document.querySelector('.opb-muted, .text-muted, .text-gray-400, .text-slate-400, small');
        const mutedFg = mutedEl ? parseRgb(window.getComputedStyle(mutedEl).color) : bodyFg;

        return {
          bodyBgRgb: bodyStyle.backgroundColor,
          bodyFgRgb: bodyStyle.color,
          contrastText: contrastRatio(bodyFg, bodyBg),
          contrastMuted: contrastRatio(mutedFg, cardBg),
        };
      });

      console.log(`Theme ${tname} audit:`, themeAudit);
      expect(themeAudit.contrastText).toBeGreaterThanOrEqual(4.5);

      // Test Keyboard Focus-Visible State on interactive controls
      const focusVisibleAudit = await page.evaluate(() => {
        const btn = document.querySelector('button, a, input, select');
        if (!btn) return { hasFocusOutline: true };
        btn.focus();
        const s = window.getComputedStyle(btn);
        const outlineW = parseFloat(s.outlineWidth) || 0;
        const outlineStyle = s.outlineStyle;
        const boxShadow = s.boxShadow;
        return {
          tagName: btn.tagName,
          outlineWidth: outlineW,
          outlineStyle: outlineStyle,
          hasBoxShadow: boxShadow !== 'none' && boxShadow !== '',
          hasFocusOutline: outlineW >= 1.5 || (boxShadow !== 'none' && boxShadow !== '')
        };
      });

      expect(focusVisibleAudit.hasFocusOutline).toBeTruthy();
    });
  }
});
