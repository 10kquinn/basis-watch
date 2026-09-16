"""Small, deterministic linear-perpetual research engine. No order placement."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from math import isfinite
import pandas as pd

VENUES = ("tradexyz", "hyperliquid", "lighter", "binance", "bybit", "okx")
VERSION = "carry-price-v1"


@dataclass(frozen=True)
class Assumptions:
    capital: float = 10000
    fee: float = .002  # on each leg, each transaction
    slippage: float = .0005  # adverse price movement per historical fill
    leverage: float = 2
    hold_days: int = 7
    adverse_basis: float = .01  # stress widening, NOT a prediction

    def __post_init__(self):
        if not isfinite(self.capital) or self.capital <= 0:
            raise ValueError("Capital must be positive.")
        if self.leverage != 2 or not 1 <= self.hold_days <= 30:
            raise ValueError("Use 2x leverage and a holding period of 1–30 days.")
        if any(not isfinite(x) or not 0 <= x < .1 for x in (self.fee, self.slippage, self.adverse_basis)):
            raise ValueError("Invalid cost or stress assumptions.")


def utc(value=None):
    t = pd.Timestamp.now(tz="UTC") if value is None else pd.Timestamp(value)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def multiplier(market):
    """Native price is per bundle for 1000PEPE/kPEPE, not per PEPE."""
    symbol = market["symbol"].split(":")[-1].upper()
    base = market["base_asset"].upper()
    for suffix in ("-USDT-SWAP", "-USDC-SWAP", "USDT", "USDC", "PERP"):
        if symbol.endswith(suffix):
            symbol = symbol[:-len(suffix)]
            break
    if symbol != base:
        for prefix, factor in (("1000000", 1000000), ("10000", 10000), ("1000", 1000), ("1M", 1000000), ("K", 1000)):
            if symbol == prefix + base:
                return factor
    return 1


def validate_pair(long, short):
    for market in (long, short):
        if market["exchange"] not in VENUES:
            raise ValueError("Venue is outside the six-venue research universe.")
        if market["quote_asset"] not in {"USDT", "USDC"}:
            raise ValueError("Only linear USDT/USDC perps are modelled; inverse/other settlement is excluded.")
    if long["base_asset"] != short["base_asset"] or long["exchange"] == short["exchange"]:
        raise ValueError("Choose the same underlying on two different venues.")


def prepare(history, market):
    required = {"Time", "Funding rate", "Mark price", "Funding interval"}
    if not required.issubset(history.columns) or len(history) < 2:
        raise ValueError("Not enough settled funding and mark-price history.")
    frame = history[list(required)].copy().sort_values("Time")
    frame["Time"] = pd.to_datetime(frame.Time, utc=True, errors="raise")
    for c in required - {"Time"}:
        frame[c] = pd.to_numeric(frame[c], errors="coerce")
    if (frame.groupby("Time")[["Funding rate", "Mark price"]].nunique(dropna=False) > 1).any().any():
        raise ValueError("Conflicting events at the same timestamp.")
    frame = frame.drop_duplicates("Time").set_index("Time")
    if frame[["Funding rate", "Mark price"]].isna().any().any() or not frame[["Funding rate", "Mark price"]].map(isfinite).all().all():
        raise ValueError("Funding or mark prices are missing; a total-return replay would be incomplete.")
    if (frame["Mark price"] <= 0).any():
        raise ValueError("Invalid mark prices.")
    frame["Mark price"] /= multiplier(market)
    notes = []
    if history.attrs.get("missing_rates"):
        notes.append("Provider omitted settled rates; funding total may be incomplete.")
    if frame["Funding interval"].isna().any() or (frame["Funding interval"] <= 0).any():
        notes.append("Some settlement intervals are unknown; coverage cannot be checked.")
    gap = frame.index.to_series().diff().dt.total_seconds() / 3600
    # Use each event's declared interval; never multiply a rate by an inferred gap.
    if ((gap > frame["Funding interval"] * 1.25) | (gap > 24)).any():
        notes.append("History has payout gaps; missing payments are not filled.")
    frame.attrs["notes"] = notes
    return frame


def shared_prices(long, short):
    # Only simultaneous observations: an 8h-old mark is not today's executable price.
    prices = pd.concat([long["Mark price"].rename("Long"), short["Mark price"].rename("Short")], axis=1).dropna()
    if len(prices) < 2:
        raise ValueError("No shared mark-price timestamps. Funding alone cannot establish total P&L.")
    ratio = prices.Short / prices.Long
    if ((ratio < .8) | (ratio > 1.2)).any():
        raise ValueError("Prices differ by more than 20%; verify contract units/specifications before comparing.")
    return prices


def replay(long, short, prices, settings, start=None, end=None):
    marks = prices.loc[start:end]
    if len(marks) < 2:
        raise ValueError("At least two shared prices are needed.")
    start, end = marks.index[0], marks.index[-1]
    entry_l, entry_s = marks.iloc[0].Long * (1 + settings.slippage), marks.iloc[0].Short * (1 - settings.slippage)
    # Same underlying units; neither leg exceeds 2x its half of total collateral.
    q = settings.capital * settings.leverage / 2 / max(entry_l, entry_s)
    entry_fee = q * (entry_l + entry_s) * settings.fee
    cashflows = []
    for side, frame, sign in (("Long", long, -1), ("Short", short, 1)):
        events = frame.loc[(frame.index > start) & (frame.index <= end)].copy()
        events["Cashflow"] = sign * q * events["Mark price"] * events["Funding rate"]
        events["Side"] = side
        cashflows.append(events.reset_index())
    ledger = pd.concat(cashflows, ignore_index=True).sort_values("Time")
    curve = marks.copy()
    for side, entry, sign in (("Long", entry_l, 1), ("Short", entry_s, -1)):
        flows = ledger[ledger.Side == side].set_index("Time").Cashflow
        cumulative = flows.groupby(level=0).sum().cumsum()
        curve[side + " funding"] = cumulative.reindex(curve.index, method="ffill").fillna(0)
        curve[side + " P&L"] = sign * q * (curve[side] - entry)
        curve[side + " equity"] = settings.capital / 2 + curve[side + " funding"] + curve[side + " P&L"] - q * entry * settings.fee
    curve["Funding"] = curve["Long funding"] + curve["Short funding"]
    exit_l, exit_s = curve.Long * (1 - settings.slippage), curve.Short * (1 + settings.slippage)
    curve["Price P&L"] = q * ((exit_l - entry_l) + (entry_s - exit_s))
    curve["Fees"] = entry_fee + q * (exit_l + exit_s) * settings.fee
    curve["Net P&L"] = curve.Funding + curve["Price P&L"] - curve.Fees
    curve["Basis bps"] = (curve.Short / curve.Long - 1) * 10000
    curve["Equity"] = settings.capital + curve["Net P&L"]
    peak = curve.Equity.cummax().clip(lower=settings.capital)
    duration = (end - start).total_seconds() / 86400
    minimum = min(curve["Long equity"].min(), curve["Short equity"].min())
    # An indicative 10% equity/notional alert, NOT venue-specific liquidation modelling.
    margin = min((curve["Long equity"] / (q * curve.Long)).min(), (curve["Short equity"] / (q * curve.Short)).min())
    last = curve.iloc[-1]
    summary = dict(start=start.isoformat(), end=end.isoformat(), days=duration, quantity=q,
                   funding=float(last.Funding), price_pnl=float(last["Price P&L"]), fees=float(last.Fees),
                   net=float(last["Net P&L"]), return_pct=float(last["Net P&L"]) / settings.capital * 100,
                   annualised_pct=float(last["Net P&L"]) / settings.capital * 100 * 365 / duration,
                   max_drawdown=float((peak - curve.Equity).max()), minimum_leg_equity=float(minimum),
                   minimum_margin_ratio=float(margin), margin_alert=bool(margin < .1),
                   notes=long.attrs.get("notes", []) + short.attrs.get("notes", []))
    return summary, curve.reset_index(), ledger


def walk_forward(long, short, prices, settings, lookback_days):
    """Frozen rule, no optimisation: trailing funding must cover projected round trip.

    Complete non-overlapping forward holds only. Pair universe still chosen today.
    """
    rows = []
    earliest = prices.index[0] + pd.Timedelta(days=lookback_days)
    cursor = earliest
    for t in prices.index:
        if t < cursor:
            continue
        end_candidates = prices.index[prices.index >= t + pd.Timedelta(days=settings.hold_days)]
        if len(end_candidates) == 0:
            break
        end = end_candidates[0]
        if end > t + pd.Timedelta(days=settings.hold_days, hours=12):
            continue
        signal = 0
        for frame, sign, col in ((long, -1, "Long"), (short, 1, "Short")):
            trailing = frame.loc[(frame.index > t - pd.Timedelta(days=lookback_days)) & (frame.index <= t)]
            signal += sign * (trailing["Funding rate"] * trailing["Mark price"]).sum() / prices.loc[t, col]
        projected = signal * settings.hold_days / lookback_days
        if projected <= 4 * (settings.fee + settings.slippage):
            cursor = t + pd.Timedelta(days=1)
            continue
        result, _, _ = replay(long, short, prices, settings, t, end)
        rows.append({"Entry": t.isoformat(), "Exit": end.isoformat(), "Signal return %": projected * 100,
                     "Net P&L": result["net"], "Funding": result["funding"], "Price P&L": result["price_pnl"],
                     "Margin alert": result["margin_alert"]})
        cursor = end  # subsequent trade enters after settlement at this timestamp
    return rows


def analyse(long_history, short_history, long_market, short_market, settings):
    validate_pair(long_market, short_market)
    long, short = prepare(long_history, long_market), prepare(short_history, short_market)
    prices = shared_prices(long, short)
    result, curve, ledger = replay(long, short, prices, settings)
    rules = {f"{d}d signal / {settings.hold_days}d hold": walk_forward(long, short, prices, settings, d) for d in (1, 3)}
    return {"version": VERSION, "assumptions": asdict(settings), "summary": result,
            "curve": curve, "cashflows": ledger, "rules": rules}
