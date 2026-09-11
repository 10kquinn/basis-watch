"""Provider-supplied asset classes and dynamic exchange selection."""
CLASS_LABELS = {
    "crypto": "Crypto", "equity": "Stocks", "etf": "ETFs", "index": "Indices",
    "commodity": "Commodities", "fx": "Forex", "tradfi": "Other TradFi",
    "unknown": "Unclassified",
}
TRADFI_CLASSES = frozenset({"equity", "etf", "index", "commodity", "fx", "tradfi"})


def asset_classes(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Unexpected asset catalogue format.")
    result = {}
    for row in payload["data"]:
        if isinstance(row, dict) and isinstance(row.get("asset"), str):
            kind = row.get("asset_class", "unknown")
            result[row["asset"].strip().upper()] = kind if kind in CLASS_LABELS else "unknown"
    return result


def exchange_ids(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Unexpected exchange catalogue format.")
    return sorted({row["exchange"].strip().lower() for row in payload["data"]
                   if isinstance(row, dict) and isinstance(row.get("exchange"), str)
                   and row["exchange"].strip()})


def available_exchanges(frame, catalogue):
    return sorted(set(catalogue) | set(frame["_long"]) | set(frame["_short"]))


def filter_asset_group(frame, group, categories):
    if group == "TradFi":
        return frame[frame["_asset_class"].isin(TRADFI_CLASSES & set(categories))].copy()
    if group == "Crypto":
        return frame[frame["_asset_class"] == "crypto"].copy()
    return frame.copy()
