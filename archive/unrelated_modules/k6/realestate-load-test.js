// k6 Load Test — Real Estate Platform API
// ─────────────────────────────────────────────────────────────────────────────
// Usage:
//   k6 run k6/realestate-load-test.js
//   k6 run --vus 20 --duration 60s k6/realestate-load-test.js
//   k6 run --env BASE_URL=http://localhost:8765 k6/realestate-load-test.js
//
// Install k6: https://k6.io/docs/getting-started/installation/
// ─────────────────────────────────────────────────────────────────────────────

import { check, sleep, group } from "k6";
import http from "k6/http";

// ── Configuration ────────────────────────────────────────────────────────────
const BASE_URL = __ENV.BASE_URL || "http://localhost:8765";
const RAMP_UP = __ENV.RAMP_UP || "30s";
const STEADY_STATE = __ENV.STEADY_STATE || "60s";

export const options = {
  stages: [
    { duration: RAMP_UP, target: 50 },   // Ramp up to 50 users
    { duration: STEADY_STATE, target: 50 }, // Stay at 50 users
    { duration: "30s", target: 0 },       // Ramp down to 0
  ],
  thresholds: {
    http_req_duration: ["p(95)<500", "p(99)<1000"], // 95% under 500ms, 99% under 1000ms
    http_req_failed: ["rate<0.01"],                  // Less than 1% failure rate
    checks: ["rate>0.95"],                           // 95%+ checks pass
  },
};

// ── Setup ────────────────────────────────────────────────────────────────────
export function setup() {
  // Authenticate as guest to get a session
  const loginRes = http.post(`${BASE_URL}/api/realestate/auth/guest-login`, "{}", {
    headers: { "Content-Type": "application/json" },
  });
  const token = loginRes.json("token");
  return { token };
}

// ── Main Test ────────────────────────────────────────────────────────────────
export default function (data) {
  const headers = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${data.token}`,
  };

  // ── Group: Home & Discovery ────────────────────────────────────────────────
  group("Home & Discovery", function () {
    // Home page (not cached)
    const homeRes = http.get(`${BASE_URL}/api/realestate/properties?page=1&limit=10`, {
      headers,
    });
    check(homeRes, {
      "home properties 200": (r) => r.status === 200,
      "home has properties": (r) => {
        try { return JSON.parse(r.body).properties?.length > 0; } catch { return false; }
      },
    });
    sleep(Math.random() * 0.5 + 0.1);

    // Autocomplete
    const autoRes = http.get(`${BASE_URL}/api/realestate/autocomplete?q=mu`, {
      headers,
    });
    check(autoRes, {
      "autocomplete 200": (r) => r.status === 200,
      "autocomplete suggestions": (r) => {
        try { return JSON.parse(r.body).suggestions?.length > 0; } catch { return false; }
      },
    });
    sleep(Math.random() * 0.3 + 0.1);
  });

  // ── Group: Search & Filtering ──────────────────────────────────────────────
  group("Search & Filtering", function () {
    // Search by city
    const searchRes = http.get(
      `${BASE_URL}/api/realestate/properties/search?city=Mumbai&min_bedrooms=2&max_price=5000000&page=1&limit=20`,
      { headers }
    );
    check(searchRes, {
      "search 200": (r) => r.status === 200,
      "search results found": (r) => {
        try { return JSON.parse(r.body).properties?.length > 0; } catch { return false; }
      },
    });
    sleep(Math.random() * 0.5 + 0.1);
  });

  // ── Group: Property Detail ─────────────────────────────────────────────────
  group("Property Detail", function () {
    // Get first property ID
    const listRes = http.get(`${BASE_URL}/api/realestate/properties?page=1&limit=1`, {
      headers,
    });
    if (listRes.status === 200) {
      try {
        const props = JSON.parse(listRes.body).properties || [];
        if (props.length > 0) {
          const propId = props[0].property_id;
          const detailRes = http.get(`${BASE_URL}/api/realestate/properties/${propId}`, {
            headers,
          });
          check(detailRes, {
            "detail 200": (r) => r.status === 200,
            "detail has title": (r) => {
              try { return JSON.parse(r.body).title?.length > 0; } catch { return false; }
            },
          });
          sleep(Math.random() * 0.5 + 0.1);

          // Enquire on this property
          const enquiryRes = http.post(
            `${BASE_URL}/api/realestate/enquiries`,
            JSON.stringify({
              property_id: propId,
              name: "Test User",
              phone: "9876543210",
              email: "test@example.com",
              message: "I am interested in this property",
            }),
            { headers }
          );
          check(enquiryRes, {
            "enquiry 200": (r) => r.status === 200 || r.status === 201,
          });
          sleep(Math.random() * 0.5 + 0.2);
        }
      } catch {
        // skip if parsing fails
      }
    }
  });

  // ── Group: Chatbot & AI ────────────────────────────────────────────────────
  group("Chatbot & AI", function () {
    const chatRes = http.post(
      `${BASE_URL}/api/realestate/chat`,
      JSON.stringify({
        message: "Show me 2 BHK apartments in Mumbai under 2 crore",
        user_id: "load-test-user",
      }),
      { headers }
    );
    check(chatRes, {
      "chat 200": (r) => r.status === 200,
      "chat responds": (r) => {
        try { return JSON.parse(r.body).message?.length > 0; } catch { return false; }
      },
    });
    sleep(Math.random() * 1.0 + 0.5);
  });

  // ── Group: Admin & Dashboard ──────────────────────────────────────────────
  group("Admin & Dashboard", function () {
    // Analytics
    const analyticsRes = http.get(`${BASE_URL}/api/realestate/analytics/overview`, {
      headers,
    });
    check(analyticsRes, {
      "analytics 200": (r) => r.status === 200,
    });
    sleep(Math.random() * 0.3 + 0.1);

    // RERA compliance check
    const reraRes = http.get(
      `${BASE_URL}/api/realestate/rera/verify/MH/RERA12345`,
      { headers }
    );
    check(reraRes, {
      "RERA 200": (r) => r.status === 200,
    });
    sleep(Math.random() * 0.3 + 0.1);

    // Fraud check status
    const fraudRes = http.get(`${BASE_URL}/api/realestate/fraud/stats`, {
      headers,
    });
    check(fraudRes, {
      "fraud stats 200": (r) => r.status === 200,
    });
    sleep(Math.random() * 0.3 + 0.1);
  });

  // ── Health Check (always succeeds) ─────────────────────────────────────────
  const healthRes = http.get(`${BASE_URL}/api/realestate/health`);
  check(healthRes, {
    "health 200": (r) => r.status === 200,
    "health status": (r) => {
      try { return JSON.parse(r.body).status === "healthy"; } catch { return false; }
    },
  });
}

// ── Teardown ─────────────────────────────────────────────────────────────────
export function teardown(data) {
  // Cleanup if needed
}
