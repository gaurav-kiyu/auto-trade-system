from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import BrokerEvent, JsonlCaptureWriter
from core.datetime_ist import now_ist


def _now_ist() -> str:
    return now_ist().isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description="Append a broker/order event to replay capture JSONL.")
    parser.add_argument("--file", required=True, help="JSONL capture path")
    parser.add_argument("--event", required=True, help="Event name like place_order/verify_fill/manual_trade")
    parser.add_argument("--order-id", default="")
    parser.add_argument("--symbol", default="")
    parser.add_argument("--direction", default="")
    parser.add_argument("--qty", type=int, default=0)
    parser.add_argument("--strike", type=int, default=0)
    parser.add_argument("--price", type=float)
    parser.add_argument("--provider", default="")
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    writer = JsonlCaptureWriter(args.file)
    writer.write(
        BrokerEvent(
            ts=_now_ist(),
            event=args.event,
            order_id=args.order_id or None,
            symbol=args.symbol,
            direction=args.direction,
            qty=int(args.qty),
            strike=int(args.strike),
            price=args.price,
            provider=args.provider,
            note=args.note,
        )
    )
    print(json.dumps({"ok": True, "file": str(writer.path), "event": args.event}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
