"""Position Bridge — Converts trader position types to domain model types.

Bridges the gap between:

  CommodityTrader (CommodityTradePosition)  →  core.domains.commodity.CommodityPosition
  CurrencyTrader (CurrencyTradePosition)    →  core.domains.currency.CurrencyPosition
  FuturesTrader (FuturesPosition)           →  core.domains.fo.FuturePosition
  EquityTrader (dict-based positions)       →  core.domains.equity.EquityPosition
  ETFTrader     (ETFTradePosition)          →  core.domains.etf.ETF
  REITTrader    (REITTradePosition)         →  core.domains.reit.REITInvIT
  IPOTrader     (IPOTradePosition)          →  core.domains.corporate_actions.IPOEvent

These conversions enable the MultiAssetPortfolioAggregator to consume
positions from all trading engines for a unified portfolio view.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from core.domains.commodity.models import CommodityContract, CommodityPosition
from core.domains.currency.models import CurrencyContract, CurrencyPair, CurrencyPosition
from core.domains.equity.models import EquityPosition, Stock
from core.domains.fo.models import FutureContract, FuturePosition

# Lazy-import domain models for ETF, REIT, IPO to avoid circular imports
from core.etf_trader import ETFTradePosition
from core.ipo_trader import IPOTradePosition
from core.reit_trader import REITTradePosition


def _current_price(tp: Any) -> float:
    """Safely extract current_price from a trader position."""
    return float(tp.current_price) if hasattr(tp, "current_price") and tp.current_price else float(tp.entry_price)


def _parse_expiry(expiry_str: str) -> date:
    """Parse expiry string to date, default to last day of next month."""
    if not expiry_str:
        today = date.today()
        if today.month == 12:
            return date(today.year + 1, 1, 1)
        return date(today.year, today.month + 1, 1)
    try:
        return date.fromisoformat(expiry_str)
    except (ValueError, TypeError):
        return date.today()


def commodity_trade_to_domain(
    trade_positions: dict[str, Any],
) -> list[CommodityPosition]:
    """Convert CommodityTrader positions to domain model CommodityPosition list.

    Args:
        trade_positions: Dict of symbol -> CommodityTradePosition

    Returns:
        List of CommodityPosition domain objects.
    """
    result: list[CommodityPosition] = []
    for sym, tp in trade_positions.items():
        qty = tp.qty if tp.direction == "BUY" else -tp.qty
        current = _current_price(tp)
        expiry = _parse_expiry(tp.expiry if hasattr(tp, "expiry") else "")
        contract = CommodityContract(
            symbol=tp.symbol,
            expiry=expiry,
        )
        result.append(
            CommodityPosition(
                contract=contract,
                quantity=qty,
                average_price=tp.entry_price,
                current_price=current,
                unrealized_pnl=(current - tp.entry_price) * qty,
                realized_pnl=0.0,
                margin_used=tp.margin_used or 0.0,
            )
        )
    return result


def currency_trade_to_domain(
    trade_positions: dict[str, Any],
) -> list[CurrencyPosition]:
    """Convert CurrencyTrader positions to domain model CurrencyPosition list.

    Args:
        trade_positions: Dict of symbol -> CurrencyTradePosition

    Returns:
        List of CurrencyPosition domain objects.
    """
    result: list[CurrencyPosition] = []
    for sym, tp in trade_positions.items():
        qty = tp.qty if tp.direction == "BUY" else -tp.qty
        current = _current_price(tp)
        expiry = _parse_expiry(tp.expiry if hasattr(tp, "expiry") else "")

        pair_map = {
            "USDINR": CurrencyPair.USD_INR,
            "EURINR": CurrencyPair.EUR_INR,
            "GBPINR": CurrencyPair.GBP_INR,
            "JPYINR": CurrencyPair.JPY_INR,
        }
        pair = pair_map.get(tp.symbol.upper(), CurrencyPair.USD_INR)

        contract = CurrencyContract(pair=pair, expiry=expiry)
        result.append(
            CurrencyPosition(
                contract=contract,
                quantity=qty,
                average_price=tp.entry_price,
                current_price=current,
                unrealized_pnl=(current - tp.entry_price) * qty,
                realized_pnl=0.0,
                margin_used=tp.margin_used or 0.0,
            )
        )
    return result


def futures_trade_to_domain(
    trade_positions: dict[str, Any],
) -> list[FuturePosition]:
    """Convert FuturesTrader positions to domain model FuturePosition list.

    Args:
        trade_positions: Dict of symbol -> FuturesPosition

    Returns:
        List of FuturePosition domain objects.
    """
    result: list[FuturePosition] = []
    for sym, tp in trade_positions.items():
        qty = tp.qty if tp.direction == "BUY" else -tp.qty
        current = _current_price(tp)
        expiry = _parse_expiry(tp.expiry if hasattr(tp, "expiry") else "")
        contract = FutureContract(symbol=tp.symbol, expiry=expiry)
        result.append(
            FuturePosition(
                contract=contract,
                quantity=qty,
                average_price=tp.entry_price,
                current_price=current,
                unrealized_pnl=(current - tp.entry_price) * qty,
                realized_pnl=0.0,
                margin_used=tp.margin_used or 0.0,
            )
        )
    return result


def equity_trade_to_domain(
    trade_positions: dict[str, dict[str, Any]],
) -> list[EquityPosition]:
    """Convert EquityTrader positions (dict-based) to domain model EquityPosition list.

    Args:
        trade_positions: Dict of symbol -> {direction, qty, entry_price, ...}

    Returns:
        List of EquityPosition domain objects.
    """
    result: list[EquityPosition] = []
    for sym, pos_dict in trade_positions.items():
        qty = pos_dict["qty"] if pos_dict.get("direction") == "BUY" else -pos_dict["qty"]
        entry_price = float(pos_dict.get("entry_price", 0.0))
        current_price = float(pos_dict.get("current_price", entry_price))
        if entry_price <= 0:
            continue

        stock = Stock(symbol=sym)
        result.append(
            EquityPosition(
                stock=stock,
                quantity=qty,
                average_price=entry_price,
                current_price=current_price,
                unrealized_pnl=(current_price - entry_price) * qty,
                realized_pnl=0.0,
                margin_used=float(pos_dict.get("margin_used", 0.0)),
            )
        )
    return result


def etf_trade_to_domain(
    trade_positions: dict[str, ETFTradePosition],
) -> list[dict[str, Any]]:
    """Convert ETFTrader positions to domain model ETF list.

    Args:
        trade_positions: Dict of symbol -> ETFTradePosition

    Returns:
        List of ETF domain dicts.
    """
    result: list[dict[str, Any]] = []
    for sym, tp in trade_positions.items():
        result.append(tp.to_dict())
    return result


def reit_trade_to_domain(
    trade_positions: dict[str, REITTradePosition],
) -> list[dict[str, Any]]:
    """Convert REITTrader positions to domain model REITInvIT list.

    Args:
        trade_positions: Dict of symbol -> REITTradePosition

    Returns:
        List of REIT/InvIT domain dicts.
    """
    result: list[dict[str, Any]] = []
    for sym, tp in trade_positions.items():
        result.append(tp.to_dict())
    return result


def ipo_trade_to_domain(
    trade_positions: dict[str, IPOTradePosition],
) -> list[dict[str, Any]]:
    """Convert IPOTrader positions to domain model IPOEvent list.

    Args:
        trade_positions: Dict of symbol -> IPOTradePosition

    Returns:
        List of IPO/FPO/OFS/QIP domain dicts.
    """
    result: list[dict[str, Any]] = []
    for sym, tp in trade_positions.items():
        result.append(tp.to_dict())
    return result


def wire_trader_positions_to_aggregator(
    trader_refs: dict[str, Any],
) -> dict[str, list]:
    """Convert all trader positions to domain models for portfolio aggregation.

    Reads trader instances from trader_refs and converts their positions.

    Args:
        trader_refs: Dict with keys like "commodity_trader", "currency_trader",
                     "futures_trader", "equity_trader", "etf_trader",
                     "reit_trader", "ipo_trader" mapping to trader instances.

    Returns:
        Dict with keys for each asset class containing domain-model position lists.
    """
    result: dict[str, list] = {}

    ct = trader_refs.get("commodity_trader")
    if ct and hasattr(ct, "positions"):
        result["commodity_positions"] = commodity_trade_to_domain(ct.positions)

    cct = trader_refs.get("currency_trader")
    if cct and hasattr(cct, "positions"):
        result["currency_positions"] = currency_trade_to_domain(cct.positions)

    ft = trader_refs.get("futures_trader")
    if ft and hasattr(ft, "positions"):
        result["fo_futures"] = futures_trade_to_domain(ft.positions)

    et = trader_refs.get("equity_trader")
    if et and hasattr(et, "positions"):
        result["equity_positions"] = equity_trade_to_domain(et.positions)

    etf_t = trader_refs.get("etf_trader")
    if etf_t and hasattr(etf_t, "positions"):
        result["etf_positions"] = etf_trade_to_domain(etf_t.positions)

    reit_t = trader_refs.get("reit_trader")
    if reit_t and hasattr(reit_t, "positions"):
        result["reit_positions"] = reit_trade_to_domain(reit_t.positions)

    ipo_t = trader_refs.get("ipo_trader")
    if ipo_t and hasattr(ipo_t, "positions"):
        result["ipo_positions"] = ipo_trade_to_domain(ipo_t.positions)

    return result


__all__ = [
    "commodity_trade_to_domain",
    "currency_trade_to_domain",
    "equity_trade_to_domain",
    "etf_trade_to_domain",
    "futures_trade_to_domain",
    "ipo_trade_to_domain",
    "reit_trade_to_domain",
    "wire_trader_positions_to_aggregator",
]
