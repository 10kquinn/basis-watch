"""Research orchestration shared by Streamlit and the read-only CLI."""
from __future__ import annotations

from dataclasses import asdict
from uuid import uuid4
import pandas as pd
import requests

from bend_api import load_history, load_market_snapshots
from execution import pair_books, live_estimate
from paper import archive_history
from research import analyse, utc, VERSION


def serial(value):
    if isinstance(value, pd.DataFrame):
        # ISO dates and JSON null, never NaN or Python-specific types.
        import json
        return json.loads(value.to_json(orient="records", date_format="iso"))
    if isinstance(value, dict):
        return {k: serial(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serial(v) for v in value]
    return value


def scan(pairs, settings, store=None, progress=None):
    observed = utc()
    run = dict(id=str(uuid4()), version=VERSION, started_at=observed.isoformat(),
               assumptions=asdict(settings), universe=serial(pairs), results=[],
               warning="Today's filtered universe: selection/survivorship bias. Historical marks are not executable prices. Not a validated profitable strategy.")
    histories, markets = {}, {}
    for i, pair in enumerate(pairs):
        row = dict(asset=pair["Asset"], long=pair["_long"], short=pair["_short"],
                   long_id=int(pair["_long_market_id"]), short_id=int(pair["_short_market_id"]), error=None)
        try:
            ids = [row["long_id"], row["short_id"]]
            for identifier in ids:
                if identifier not in markets:
                    markets.update(load_market_snapshots([identifier]))
                if identifier not in histories:
                    histories[identifier] = load_history(identifier, observed)
                    if store:
                        archive_history(store, markets[identifier], histories[identifier])
            ms = [markets[x] for x in ids]
            result = analyse(*[histories[x] for x in ids], *ms, settings)
            for market in ms:
                latest = histories[market["market_id"]].Time.max()
                interval = market.get("funding_interval") or 1
                if (observed - latest).total_seconds() > (interval + 1) * 3600:
                    result["summary"]["notes"].append(f"{market['exchange']}: latest settlement is stale or delayed.")
            row.update(markets=ms, backtest=serial(result))
            try:
                books = pair_books(*ms)
                row["live"] = live_estimate(ms, books, settings)
                row["books"] = books
            except (ValueError, KeyError, TypeError, requests.RequestException) as e:
                row["live_error"] = str(e)
        except (ValueError, KeyError, TypeError, requests.RequestException) as e:
            row["error"] = str(e)
        run["results"].append(row)
        if progress:
            progress((i+1)/len(pairs), f"Checked {i+1} of {len(pairs)} pairs")
    run["finished_at"] = utc().isoformat()
    if store:
        store.put("research", run["id"], run)
    return run


def result_table(run):
    rows = []
    for item in run["results"]:
        base = {"Asset": item["asset"], "Long": item["long"], "Short": item["short"],
                "Pair": f"{item['long_id']}/{item['short_id']}"}
        if item.get("error"):
            rows.append(dict(base, Status="History unavailable", Detail=item["error"]))
            continue
        bt, live = item["backtest"]["summary"], item.get("live", {})
        rules = item["backtest"]["rules"]
        for name, trades in rules.items():
            base[name+" net $"] = sum(t["Net P&L"] for t in trades) if trades else None
            base[name+" trades"] = len(trades)
        rule_ok = any(trades and sum(t["Net P&L"] for t in trades) > 0 and not any(t["Margin alert"] for t in trades) for trades in rules.values())
        candidate = (bt["net"] > 0 and live.get("projected_net", -1) > 0 and rule_ok
                     and not bt["notes"] and not bt["margin_alert"])
        status = "Research candidate" if candidate else "Does not pass"
        if not live:
            status = "Current quotes unavailable"
        if bt["notes"]:
            status = "Incomplete history"
        base.update({"Status": status, "Days": bt["days"], "Historical net $": bt["net"],
                     "Historical funding $": bt["funding"], "Historical price P&L $": bt["price_pnl"],
                     "Historical return %": bt["return_pct"], "Drawdown $ (sampled)": bt["max_drawdown"],
                     "Live funding $/day": live.get("daily_funding"), "Projected hold net $": live.get("projected_net"),
                     "Stress net $": live.get("stressed_net"), "Fee break-even days": live.get("break_even_days"),
                     "Detail": item.get("live_error") or "; ".join(bt["notes"]) or "Conditional on surviving between price samples"})
        rows.append(base)
    return pd.DataFrame(rows)
