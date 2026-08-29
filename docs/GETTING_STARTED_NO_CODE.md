# Getting Started — No Coding Required

**For anyone using this system on their own Windows PC** — technical or
not. Nothing here needs typing commands into a terminal. If you're
comfortable with terminals/config files already, `docs/HOW_TO_USE_SYSTEM.md`
and `USER_GUIDE.md` go deeper (CLI tools, config keys, Docker, etc.) — this
guide is the click-only path to the same running system.

**Important context:** this system currently runs **only on your own
computer** — it is not hosted anywhere on the internet. Everything you do
happens locally: your data stays on your PC, and the dashboard is only
reachable from a browser while your PC is on and the app is running. There
is nothing to "deploy" or "publish" — just double-click files to run it.

---

## 1. What this actually is

This is a bot that watches the Indian stock market (NSE) and NIFTY/
BANKNIFTY/FINNIFTY options, and tells you — via a web dashboard and
optionally Telegram — when it thinks a good trade setup has appeared. Right
now it is deliberately set up to only **suggest** trades (it is not placing
real orders on its own) so you can build confidence in its signals before
ever risking real money. Everything defaults to safe, simulated ("paper")
behavior.

## 2. What you need before starting (one-time)

1. **Python installed**, version 3.10–3.19. If you're not sure whether you
   have it:
   - Open the Start Menu, type `cmd`, press Enter to open a black command
     window.
   - Type `py --version` and press Enter.
   - If you see something like `Python 3.12.4`, you're set — skip to step 3.
   - If you see an error, download Python from
     [python.org/downloads](https://www.python.org/downloads/) and run the
     installer. **On the very first installer screen, tick the box that
     says "Add python.exe to PATH"** before clicking Install — this is the
     single most common setup mistake, and skipping it is exactly what
     causes a "Python is not found in PATH" error later.
2. **An internet connection** — the bot needs it to fetch live market prices.
3. Nothing else is required to try it out safely. A Telegram account and a
   broker account are both optional, described in later sections.

## 3. One-time setup

1. Open the folder where this project lives in File Explorer.
2. Double-click **`setup.bat`**.
3. A black window opens and runs three checks: Python version, a
   governance/safety self-check, and a database integrity check. Each
   should print `[OK]` or `PASSED`. If anything says `[ERROR]`, see
   [Troubleshooting](#7-troubleshooting) below.
4. When it says "Environment bootstrap complete!", press any key to close
   the window. You only need to do this once (rerun it any time you want to
   re-verify everything is healthy).

## 4. Starting the app

You have two double-click options, depending on what you want to see first:

| File | What it opens |
|---|---|
| **`open_app.bat`** | The main trading dashboard — signals, positions, P&L (`http://localhost:8765/`) |
| **`open_admin.bat`** | The admin configuration screen directly (`http://localhost:8765/admin/config`) |

Either one will: start the bot in the background if it isn't already
running, wait a few seconds for it to be ready, then open the page in your
default browser automatically. You don't need to do anything else — just
double-click and wait for the browser tab to appear.

A console window will stay open in the background (titled after the
launcher) — **that window is the running bot**. Closing it stops everything.
Minimize it, don't close it, while you want the bot running.

### First login

The very first time the app creates its user database, it prints a
one-time admin username and password **directly in that console window** —
look for a block that says `FIRST-RUN ADMIN LOGIN`. Write those down (or
screenshot them) immediately; they are shown only once and are not stored
anywhere in plain text afterward. You'll be forced to pick your own password
on that first login.

## 5. What you'll see — a tour

Once logged in, the navigation bar across the top links to everything. The
pages you'll use most:

- **Dashboard (home page)** — capital, today's P&L, open positions, system
  health at a glance. Also has a collapsible **"Install this as a mobile
  app"** card explaining how to get this same dashboard on your phone's
  home screen (see Section 6).
- **Signal History** (`/admin/signals`) — every signal the system has
  generated, with filters for today/this week/this month/this year. Each
  row has an **"Order Placed?" checkbox** — if you act on a signal by
  placing the order yourself with your broker, tick it so there's a record
  of which signals you actually traded on, separate from the system's own
  automatic win/loss grading.
- **Payoff Calculator** (`/payoff-calculator`) — before you trade a
  multi-leg options strategy, type in the strikes/premiums here to see the
  profit/loss curve and break-even points. Purely a calculator — it never
  places anything.
- **What's New** (`/whats-new`) — a running log of what's changed in the
  system, in plain language, read straight from the project's own
  changelog.
- **Kill Switch** (`/admin/kill-switch`, admin only) — a one-click emergency
  stop if you ever need to halt everything immediately.

## 6. Getting alerts on your phone

Two independent options, and you can use either or both:

### Option A — Telegram (recommended for real-time alerts)
1. In Telegram, search for `@BotFather`, send `/newbot`, and follow the
   prompts to get a bot token.
2. Message your new bot once, then visit
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser to
   find your chat ID (a number).
3. Put both values into `json/config.local.json` (create the file if it
   doesn't exist) — full instructions are in `USER_GUIDE.md` §8. Once
   configured, you'll get a message for every signal, and you can reply
   with commands like `/status`, `/pnl`, or `/placed {signal_id}` right
   from your phone's Telegram app — no need to open the dashboard at all.

### Option B — install the dashboard itself on your phone
The dashboard can be added to your phone's home screen like a real app (no
Play Store/App Store needed) — see the "Install this as a mobile app" card
on the dashboard's home page, or the full walkthrough in
`docs/MOBILE_APP_PWA_GUIDE.md`. One thing to know up front: your phone can
only reach it while your PC is on, running the app, and reachable on the
same network (or via one of the two remote-access options that guide
describes) — there's no cloud server involved.

## 7. Troubleshooting

| What you see | What it means | What to do |
|---|---|---|
| `[ERROR] Neither "py" nor "python" was found in PATH!` | Python isn't installed, or was installed without the PATH option | Reinstall from python.org and tick "Add python.exe to PATH" (see Section 2) |
| Browser opens to a blank/error page | The bot is still starting up | Wait 5–10 seconds and refresh; the console window will show `[OK]`/startup messages when ready |
| "This site can't be reached" at `localhost:8765` | The bot isn't running, or you closed its console window | Double-click `open_app.bat` again |
| Forgot the first-run admin password | It was only ever shown once in the console | Ask a technical user to reset it via `core/auth` tooling, or delete `db/auth.db` to start fresh (this also deletes any other users you created) |
| A pop-up firewall prompt appears | Windows is asking whether to allow the app to use the network | Allow it — the bot needs network access to fetch market data and serve the dashboard |
| Nothing seems to happen when double-clicking a `.bat` file | Some Windows setups block script execution silently | Right-click the file → "Run as administrator", or open a command window, `cd` into the folder, and type the filename directly to see any error message |

## 8. Understanding "modes" (in plain English)

| Mode | What it means | Risk to your money |
|---|---|---|
| **Paper** (default) | Everything is simulated — fake fills at realistic prices | Zero — no real money is ever touched |
| **Manual / Signal-only** | The bot tells you what it would trade; you place the order yourself in your own broker app if you choose to | Only what you choose to risk, manually, in your own broker |
| **Live/Auto** | The bot would place real orders automatically through a connected broker account | Real — **this is deliberately locked off by default** and requires an explicit, deliberate opt-in after a proven paper track record |

Right now, this system is intentionally kept in Paper/Manual mode — that's
the safe, recommended way to build confidence before ever considering Auto
mode.

## 9. Stopping the app

Click into the console window that opened when you started the app, and
press `Ctrl + C`. Wait for it to print that it's shutting down gracefully,
then it's safe to close the window.

## 10. Where to go next

- Deeper technical detail, CLI tools, Docker, config keys: `docs/HOW_TO_USE_SYSTEM.md` and `USER_GUIDE.md`
- Mobile install walkthrough: `docs/MOBILE_APP_PWA_GUIDE.md`
- What changed recently: the in-app **What's New** page, or `CHANGELOG.md`
- How this compares to commercial platforms like Sensibull/Streak: `docs/COMPETITIVE_ANALYSIS.md`

**Remember:** this is a decision-support tool, not a guarantee of profit.
Start in Paper mode, watch it for a while, and only ever risk money you can
afford to lose.
