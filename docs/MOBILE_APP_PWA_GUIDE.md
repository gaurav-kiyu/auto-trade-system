# Mobile App Guide — Installable PWA (No Play Store / App Store)

## What this is

The enterprise dashboard (`core/enterprise_dashboard`) is now a **Progressive
Web App (PWA)**. A PWA is a normal website that a phone's browser can install
as a home-screen app: it gets its own icon, launches full-screen without
browser chrome, and (via a service worker) can cache assets for a faster,
partially-offline shell. It is **not** a separate codebase, not published to
any app store, and requires no app review — it's the same FastAPI +
Jinja2 dashboard this project already runs, made installable.

This document is the step-by-step companion to the short "Install this as a
mobile app" card on the dashboard home page (`templates/enterprise/dashboard.html`)
— that card is a summary; this file has the full detail, including the one
real caveat (HTTPS) and how to work around it on a home network.

## What was built

| Piece | File(s) | Purpose |
|---|---|---|
| Web app manifest | `static/dashboard-manifest.json` | Declares the app's name, icons, theme colors, start page, and 3 quick-launch shortcuts (Signal History, Live P&L, Kill Switch) |
| App icons | `static/opb-icon-192.svg`, `static/opb-icon-512.svg` | Home-screen icon at both required sizes |
| Service worker | `static/dashboard-sw.js` (pre-existing, unmodified) | Network-first fetch strategy with a cache fallback — already correct for this app |
| Head partial | `templates/enterprise/_pwa_head.html` (pre-existing) | Links the manifest, sets `theme-color`/Apple meta tags/touch icon; now wired into all 34 authenticated page templates instead of only 2 |
| Registration partial | `templates/enterprise/_pwa_sw_reg.html` (pre-existing) | Registers the service worker at scope `/`; now included on all 34 pages so it activates from whichever page a user lands on first |
| Service worker route | `core/enterprise_dashboard/main.py` (pre-existing, unmodified) | Serves `/dashboard-sw.js` at the root path with `Service-Worker-Allowed: /`, CSRF-exempt — this was already correctly implemented |

Before this change, the PWA scaffold existed but was incomplete: the manifest
and icon files it pointed to didn't exist, and only 2 of the dashboard's 37
templates included the head/registration partials at all. Every page an
authenticated user can reach now consistently declares the manifest and
registers the service worker.

## Is it actually installable? Yes — confirmed

You do **not** need the Play Store or App Store, a developer account, or any
app review. "Installing" a PWA is a browser feature (Chrome on Android,
Safari on iOS) that turns a website into a home-screen icon. The one real
requirement is explained next.

## The one requirement: HTTPS (or localhost)

Browsers only offer the full install experience — the "Install app" banner
and a working service worker — when the page is served over **HTTPS**, or
when it's opened via `localhost`/`127.0.0.1` on the *same machine* running
the server. That localhost exception does **not** extend to a LAN IP address:
if your phone opens `http://192.168.x.x:8765` (the PC's IP address, not
`localhost`, since `localhost` on the phone would mean the phone itself),
that is a different, insecure origin as far as the browser is concerned, and
Chrome/Safari will generally skip the install prompt and may not register
the service worker at all.

This is a browser platform rule, not something this project's code can work
around — the dashboard already runs over plain HTTP for typical local/LAN
use per the existing project defaults, so getting HTTPS onto your phone's
path to the dashboard is the only remaining step. Two practical ways to get
there for a personal, single-admin setup like this one:

### Option 1 — Tailscale (recommended for personal use)

[Tailscale](https://tailscale.com) creates a private network between your PC
and phone and can issue each device a real, browser-trusted HTTPS certificate
(via its `*.ts.net` MagicDNS feature) with no manual certificate management.

1. Install Tailscale on the PC running this bot and on your phone; log both
   into the same Tailscale account/tailnet.
2. On the PC, run `tailscale cert <your-machine-name>.<your-tailnet>.ts.net`
   once (Tailscale's admin console has the exact hostname) — this issues a
   real certificate valid for that hostname.
3. Point a small HTTPS proxy (or Tailscale's built-in `tailscale serve`
   feature) at `localhost:8765` (or whatever port `web_dashboard_enabled`
   serves on) using that certificate.
4. From your phone (also on the tailnet), browse to
   `https://<your-machine-name>.<your-tailnet>.ts.net` — this is a real
   HTTPS origin, so the install prompt and service worker work fully.

This keeps the dashboard off the public internet — only devices on your
Tailscale network can reach it.

### Option 2 — Local reverse proxy with a self-signed certificate

If you'd rather stay fully local without a third-party service, run a
lightweight reverse proxy (e.g. [Caddy](https://caddyserver.com), which can
auto-generate a local certificate authority) in front of the dashboard, and
manually trust that CA's root certificate on your phone (both Android and iOS
support importing a trusted root CA profile). This is more manual than
Tailscale but keeps everything on your own LAN with no external service
involved.

Either option is a one-time setup; day-to-day use afterward is just opening
the HTTPS address on your phone.

## Step-by-step install

### Android (Chrome)

1. Open the dashboard's HTTPS address in Chrome.
2. Log in normally.
3. Tap the **⋮** menu (top-right) → **Install app** (older Chrome versions
   show **Add to Home screen** instead — same effect).
4. Confirm. The OPB icon (a blue/green ascending candlestick glyph) appears
   on your home screen and app drawer, and opens standalone — no address
   bar, no browser tabs.
5. Long-press the icon to see the 3 quick-launch shortcuts (Signal History,
   Live P&L, Kill Switch) declared in the manifest, if your launcher
   supports app shortcuts.

### iPhone / iPad (Safari only — Chrome on iOS cannot install PWAs)

1. Open the dashboard's HTTPS address in **Safari** specifically.
2. Log in normally.
3. Tap the **Share** icon (square with an arrow) → **Add to Home Screen**.
4. Confirm. The OPB icon appears on your home screen.
5. iOS's PWA support is more limited than Android's: full offline caching
   and installability work the same, but Web Push notifications for
   installed PWAs require **iOS 16.4 or later**, and behave differently from
   Android's notification model. If push-style alerts on the phone matter
   more than a home-screen icon, the existing Telegram bot
   (`core/telegram_commander.py` — `/pending`, `/status`, `/pnl`, `/placed`,
   etc.) remains the more reliable mobile notification channel on iOS today.

## What works today vs. what doesn't yet

| Capability | Status |
|---|---|
| Home-screen icon, standalone launch | Works today (once served over HTTPS) |
| Offline shell (cached last-loaded pages) | Works today — `dashboard-sw.js`'s network-first strategy already handles this |
| Quick-launch shortcuts to Signals/P&L/Kill-Switch | Works today on Android; iOS ignores manifest `shortcuts` |
| Push notifications to the installed app | **Not implemented** — would need a separate Web Push subscription flow (different from Telegram's polling bot); use Telegram for real-time mobile alerts in the meantime |
| True native performance / platform APIs (biometric unlock, etc.) | Not available to a PWA — would require the React Native/Flutter path discussed separately if ever pursued |

## Where this is documented in-app

The dashboard home page (`/`, `dashboard.html`) has a collapsible
"📱 Install this as a mobile app" card with the condensed version of the
Android/iOS steps and the HTTPS caveat, so an admin doesn't need to leave the
running app to find this information.
