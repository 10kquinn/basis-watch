"""Read-only public order books. No credentials, wallet, or order API."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from math import isfinite
import requests
import pandas as pd

from research import multiplier, utc, validate_pair


def get(url, **kwargs):
    r = requests.get(url, timeout=15, **kwargs)
    r.raise_for_status()
    return r.json()


@lru_cache(maxsize=1)
def lighter_markets():
    return get("https://mainnet.zklighter.elliot.ai/api/v1/orderBooks")["order_books"]


@lru_cache(maxsize=512)
def okx_contract(symbol):
    data = get("https://www.okx.com/api/v5/public/instruments", params={"instType": "SWAP", "instId": symbol})
    if data.get("code") != "0" or len(data.get("data", [])) != 1:
        raise ValueError("OKX contract specifications unavailable.")
    row = data["data"][0]
    if row["ctType"] != "linear" or row["ctValCcy"] != symbol.split("-")[0]:
        raise ValueError("Unsupported OKX contract units.")
    return float(row["ctVal"]) * float(row.get("ctMult") or 1)


def book(market):
    venue, symbol = market["exchange"], market["symbol"]
    scale = multiplier(market)
    size_scale = scale
    timestamp = None
    started = utc()
    if venue == "binance":
        raw = get("https://fapi.binance.com/fapi/v1/depth", params={"symbol": symbol, "limit": 100})
        bids, asks = raw["bids"], raw["asks"]
        timestamp = raw.get("E")
    elif venue == "bybit":
        raw = get("https://api.bybit.com/v5/market/orderbook", params={"category": "linear", "symbol": symbol, "limit": 200})
        if raw.get("retCode") != 0:
            raise ValueError("Bybit book unavailable: " + str(raw.get("retMsg")))
        bids, asks = raw["result"]["b"], raw["result"]["a"]
        timestamp = raw["result"].get("ts")
    elif venue == "okx":
        size_scale *= okx_contract(symbol)
        raw = get("https://www.okx.com/api/v5/market/books", params={"instId": symbol, "sz": 100})
        if raw.get("code") != "0" or not raw.get("data"):
            raise ValueError("OKX book unavailable.")
        bids, asks = raw["data"][0]["bids"], raw["data"][0]["asks"]
        timestamp = raw["data"][0].get("ts")
    elif venue in {"hyperliquid", "tradexyz"}:
        coin = ("xyz:" + symbol.split(":")[-1]) if venue == "tradexyz" else symbol
        response = requests.post("https://api.hyperliquid.xyz/info", json={"type": "l2Book", "coin": coin}, timeout=15)
        response.raise_for_status()
        raw = response.json()
        if not isinstance(raw, dict) or raw.get("coin") != coin:
            raise ValueError("Hyperliquid/TradeXYZ contract book unavailable.")
        bids, asks = ([[r["px"], r["sz"]] for r in side] for side in raw["levels"])
        timestamp = raw.get("time")
    elif venue == "lighter":
        matches = [r for r in lighter_markets() if r["symbol"] == symbol and r.get("market_type") == "perp"]
        if len(matches) != 1:
            lighter_markets.cache_clear()
            raise ValueError("Lighter contract mapping unavailable. Retry after catalogue refresh.")
        raw = get("https://mainnet.zklighter.elliot.ai/api/v1/orderBookOrders", params={"market_id": matches[0]["market_id"], "limit": 100})
        if raw.get("code") != 200:
            raise ValueError("Lighter book unavailable.")
        bids, asks = ([[r["price"], r["remaining_base_amount"]] for r in raw[side]] for side in ("bids", "asks"))
    else:
        raise ValueError("Unsupported venue.")
    received = utc()
    if (received - started).total_seconds() > 20:
        raise ValueError("Order book request took too long; retry.")
    if timestamp:
        timestamp = utc(pd.Timestamp(int(timestamp), unit="ms", tz="UTC"))
        age = (received - timestamp).total_seconds()
        if age > 60 or age < -10:
            raise ValueError("Stale venue order book. A fresh paper fill cannot be estimated.")
    def levels(rows, reverse):
        data = [(float(r[0]) / scale, float(r[1]) * size_scale) for r in rows]
        if any(not isfinite(p) or not isfinite(q) or p <= 0 or q < 0 for p, q in data):
            raise ValueError("Invalid order-book levels.")
        return sorted([(p, q) for p, q in data if q > 0], reverse=reverse)
    bids, asks = levels(bids, True), levels(asks, False)
    if not bids or not asks or bids[0][0] >= asks[0][0]:
        raise ValueError("Empty or crossed order book.")
    return dict(venue=venue, symbol=symbol, market_id=market["market_id"], bids=bids, asks=asks,
                observed_at=received.isoformat(), venue_time=timestamp.isoformat() if timestamp else None,
                source="venue public order book", mid=(bids[0][0] + asks[0][0]) / 2)


def pair_books(long, short):
    validate_pair(long, short)
    with ThreadPoolExecutor(max_workers=2) as pool:
        books = list(pool.map(book, [long, short]))
    if abs((utc(books[0]["observed_at"]) - utc(books[1]["observed_at"])).total_seconds()) > 20:
        raise ValueError("Leg quotes are too far apart. Refresh both books.")
    if not .8 < books[1]["mid"] / books[0]["mid"] < 1.2:
        raise ValueError("Contract price mismatch; verify underlying units.")
    return books


def vwap(levels, quantity):
    if not isfinite(quantity) or quantity <= 0:
        raise ValueError("Quantity must be positive.")
    left, cost = quantity, 0.
    for price, size in levels:
        take = min(left, size)
        cost += take * price
        left -= take
        if left <= quantity * 1e-10:
            return cost / quantity
    raise ValueError("Insufficient visible order-book depth for this size. Reduce capital.")


def fills(books, quantity, opening=True):
    return (vwap(books[0]["asks" if opening else "bids"], quantity),
            vwap(books[1]["bids" if opening else "asks"], quantity))


def entry(books, settings):
    cap = settings.capital * settings.leverage / 2
    q = cap / max(b["mid"] for b in books)
    # Scale down to ensure each leg stays at or below 2x after walking the book.
    for _ in range(5):
        lp, sp = fills(books, q)
        if q * max(lp, sp) <= cap * (1 + 1e-10):
            return q, lp, sp
        q *= cap / (q * max(lp, sp))
    raise ValueError("Could not size both legs within the collateral limit.")


def live_estimate(markets, books, settings):
    q, lp, sp = entry(books, settings)
    close_l, close_s = fills(books, q, opening=False)
    rates = [float(m["funding_rate_apr"]["live"]) for m in markets]
    if not all(isfinite(r) for r in rates):
        raise ValueError("Current funding APR is unavailable.")
    daily = q * (sp * rates[1] - lp * rates[0]) / 100 / 365
    fees = q * (lp + sp + close_l + close_s) * settings.fee
    # Depth spread already in fills; do not subtract it again as slippage.
    price_pnl = q * (close_l - lp + sp - close_s)
    costs = fees - price_pnl
    expected = daily * settings.hold_days - costs
    stress = daily * settings.hold_days * .5 - costs - settings.adverse_basis * q * max(lp, sp)
    return dict(quantity=q, long_entry=lp, short_entry=sp, daily_funding=daily,
                live_spread_apr=rates[1] - rates[0], projected_net=expected,
                stressed_net=stress, round_trip_cost=costs,
                break_even_days=costs / daily if daily > 0 else None,
                basis_bps=(sp / lp - 1) * 10000, observed_at=max(b["observed_at"] for b in books))
