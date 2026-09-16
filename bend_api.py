"""Adapters for Bend Basis's public v1 API (api.bendbasis.com)."""
from math import isfinite

import pandas as pd
import requests

BASE_URL = "https://api.bendbasis.com/v1"


def get_json(path, params=None):
    response = requests.get(BASE_URL + path, params=params, timeout=20,
                            headers={"User-Agent": "BasisWatch/2.0"})
    response.raise_for_status()
    return response.json()


def collection_data(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Bend Basis returned an unexpected collection format.")
    return payload["data"]


def load_opportunities():
    """Read every page, preserving query parameters and opaque cursors."""
    rows = []
    seen_cursors = set()
    params = {"limit": 500, "window": 15, "sort": "apr", "order": "desc"}
    for _ in range(200):
        payload = get_json("/funding/arbitrage", params=dict(params))
        rows.extend(collection_data(payload))
        if "next_cursor" not in payload:
            raise ValueError("Bend Basis omitted pagination information; results may be incomplete.")
        cursor = payload["next_cursor"]
        if cursor is None:
            # Moving live snapshots can repeat an opportunity across pages.
            unique = {}
            malformed = []
            for row in rows:
                if isinstance(row, dict) and isinstance(row.get("long_market_id"), int) and isinstance(row.get("short_market_id"), int):
                    unique.setdefault((row["long_market_id"], row["short_market_id"]), row)
                else:
                    malformed.append(row)
            return list(unique.values()) + malformed
        if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
            raise ValueError("Bend Basis pagination did not advance. Refresh to retry the complete feed.")
        seen_cursors.add(cursor)
        params["cursor"] = cursor
    raise ValueError("Bend Basis returned too many pages; refusing to show a truncated feed.")


def normalize_events(payload):
    rows = []
    missing = 0
    for item in collection_data(payload):
        if not isinstance(item, dict):
            raise ValueError("Invalid history event.")
        timestamp = pd.to_datetime(item.get("funding_time"), utc=True, errors="coerce")
        if pd.isna(timestamp):
            raise ValueError("Invalid funding timestamp.")
        if item.get("funding_rate") is None:
            missing += 1
            continue
        try:
            rate = float(item["funding_rate"])
        except (TypeError, ValueError):
            raise ValueError("Invalid settled funding rate.")
        if not isfinite(rate):
            raise ValueError("Invalid settled funding rate.")
        try:
            interval = float(item.get("funding_interval"))
        except (TypeError, ValueError):
            interval = float("nan")
        if not isfinite(interval) or interval <= 0:
            interval = float("nan")
        try:
            mark = float(item.get("mark_price"))
        except (TypeError, ValueError):
            mark = float("nan")
        if not isfinite(mark) or mark <= 0:
            mark = float("nan")
        rows.append({"Time": timestamp, "Funding rate": rate, "Funding interval": interval,
                     "Mark price": mark})
    history = pd.DataFrame(rows, columns=["Time", "Funding rate", "Funding interval", "Mark price"])
    history = history.sort_values("Time", kind="stable").reset_index(drop=True)
    # APR is a display conversion only; cash flows always use settled rates.
    hours = history["Funding interval"]
    history["APR"] = history["Funding rate"] * 100 * 8760 / hours
    history.attrs["missing_rates"] = missing
    return history


def load_history(market_id, window_end=None):
    end = pd.Timestamp.now(tz="UTC") if window_end is None else pd.Timestamp(window_end)
    end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
    start = end - pd.Timedelta(days=30)
    return normalize_events(get_json(f"/funding/history/{int(market_id)}", {
        "resolution": "event", "from": start.isoformat(), "to": end.isoformat(),
    }))


def load_market_snapshots(market_ids):
    snapshots = {}
    for market_id in sorted(set(market_ids)):
        payload = get_json(f"/markets/{int(market_id)}")
        item = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(item, dict) or item.get("market_id") != market_id:
            raise ValueError("Bend Basis returned an unexpected market snapshot.")
        snapshots[market_id] = item
    return snapshots


def request_error_message(error):
    response = getattr(error, "response", None)
    code = response.status_code if response is not None else None
    if code == 404:
        return "Bend Basis returned 404 (API route not found). This is an API-address problem, not your internet connection."
    if code == 429:
        return "Bend Basis is rate-limiting requests. Please wait a minute, then select Refresh market data."
    if code in (401, 403):
        return "Bend Basis denied API access. The provider may have changed its access requirements."
    if code and code >= 500:
        return "Bend Basis is reporting a server error. Please try Refresh market data shortly."
    return "The app could not retrieve Bend Basis data. The request may have timed out or the service may be unavailable. Try Refresh market data."
