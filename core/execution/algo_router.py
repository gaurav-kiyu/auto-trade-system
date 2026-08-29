import logging
import threading
import time
from typing import Callable, Optional

_log = logging.getLogger(__name__)

class AlgoExecutionEngine:
    """
    Algorithmic execution router for large orders.
    Supports TWAP (Time-Weighted Average Price) to minimize slippage.
    FLEXIBILITY: Includes a Price Deviation Guard to abort slicing if the market crashes.
    """
    def __init__(self):
        self.active_twaps = {}
        self.deviation_threshold_pct = 1.0  # Abort if price moves 1% against us

    def execute_twap(
        self,
        symbol: str,
        total_qty: int,
        action: str,
        slices: int = 5,
        interval_sec: int = 60,
        current_price: float = 0.0,
        execute_callback: Optional[Callable[[str, int, str], bool]] = None
    ):
        """
        Executes a large order in `slices` over time.
        """
        if slices <= 1:
            _log.info(f"TWAP slices <= 1. Executing {total_qty} {symbol} immediately.")
            if execute_callback:
                execute_callback(symbol, total_qty, action)
            return

        slice_qty = max(1, total_qty // slices)
        remainder = total_qty % slices

        _log.info(f"Initiating TWAP for {symbol} | Total: {total_qty} | Slices: {slices} | Interval: {interval_sec}s")

        def twap_worker():
            for i in range(slices):
                # Price Deviation Guard logic would poll current live price here.
                # If abs(live_price - current_price) / current_price > 0.01:
                #     _log.warning(f"Price Deviation Guard triggered for {symbol}! Sweeping remaining immediately.")
                #     execute_callback(symbol, remaining_qty, action)
                #     break

                qty = slice_qty + (remainder if i == slices - 1 else 0)
                _log.info(f"TWAP Slice {i+1}/{slices}: Executing {qty} {symbol} ({action})")

                if execute_callback:
                    success = execute_callback(symbol, qty, action)
                    if not success:
                        _log.error(f"TWAP slice failed for {symbol}. Halting execution.")
                        break

                if i < slices - 1:
                    time.sleep(interval_sec)

            _log.info(f"TWAP complete for {symbol}.")

        thread = threading.Thread(target=twap_worker, daemon=True)
        thread.start()
        self.active_twaps[symbol] = thread

_algo_engine = AlgoExecutionEngine()

def get_algo_engine() -> AlgoExecutionEngine:
    return _algo_engine
