"""Stage and commit all changes with a comprehensive message."""
import subprocess
import sys

commit_msg = """feat: notification system, performance dashboard, and DashboardNotifier wiring

## Features Delivered
- NotificationManager with SSE streaming (thread-safe, 4 severity levels)
- GET /api/system/notifications/stream SSE endpoint with auto-reconnect
- Notification REST API: list/acknowledge/acknowledge-all/push endpoints
- Notification bell UI with badge count, dropdown panel, real-time toast popups
- Performance comparison dashboard API with 5-dimension breakdowns
- Tabbed Performance page in dashboard UI
- DashboardNotifier HTTP client wired into TradingLoopService bot lifecycle
- 48 comprehensive tests (188 total dashboard tests, all passing)
- Dead code cleanup (_prevPerfTab removed, diagnostics decorator fixed)"""

result = subprocess.run(
    ["git", "commit", "-m", commit_msg],
    capture_output=True, text=True, cwd="D:/AI_APPS/TRADING_APP/OPB_FINAL_MT"
)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)
print("RC:", result.returncode)
sys.exit(result.returncode)
