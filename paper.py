"""Manual theoretical positions, immutable entries, deduplicated funding ledger."""
from __future__ import annotations

from dataclasses import asdict
from uuid import uuid4
import pandas as pd

from bend_api import load_history
from execution import pair_books, entry, fills
from research import VERSION, multiplier, utc, validate_pair


def archive_history(store, market, history):
    records = []
    for _, row in history.iterrows():
        time = utc(row.Time).isoformat()
        values = {k: (None if pd.isna(v) else float(v)) for k, v in row.items() if k != "Time"}
        records.append((str(market["market_id"]) + ":" + time, dict(time=time, values=values)))
    # First-seen facts are immutable, retaining observed_at in the storage row.
    # Detect provider corrections rather than silently rewriting past evidence.
    old = {r["id"]: r["payload"] for r in store.records("funding", str(market["market_id"]) + ":")}
    conflicts = [key for key, value in records if key in old and old[key] != value]
    if conflicts:
        raise ValueError("Provider revised archived funding/marks. Review the data before changing recorded P&L.")
    store.put_many("funding", records)


def open_trade(store, markets, settings, thesis, identifier=None):
    if identifier:
        existing = [r for r in store.records("trade", identifier) if r["id"] == identifier]
        if existing:
            return existing[0]["payload"]
    validate_pair(*markets)
    books = pair_books(*markets)
    q, lp, sp = entry(books, settings)
    trade = dict(id=identifier or str(uuid4()), opened_at=utc().isoformat(), version=VERSION,
                 markets=markets, settings=asdict(settings), quantity=q, long_entry=lp, short_entry=sp,
                 entry_fee=q * (lp + sp) * settings.fee, entry_books=books, thesis=thesis.strip(),
                 sizing="Equal underlying quantity; maximum 2x on each half of collateral.")
    if not trade["thesis"]:
        raise ValueError("Write the entry reason and exit rule before saving the trade.")
    store.put("trade", trade["id"], trade)
    return trade


def funding_total(store, trade, end):
    totals, notes, rows = [], [], []
    start = utc(trade["opened_at"])
    for market, sign in zip(trade["markets"], (-1, 1)):
        records = store.records("funding", str(market["market_id"]) + ":")
        events = sorted([r["payload"] for r in records], key=lambda r: r["time"])
        selected = [r for r in events if start < utc(r["time"]) <= end]
        total = 0.
        times = [start]
        for event in selected:
            values = event["values"]
            price, rate = values.get("Mark price"), values.get("Funding rate")
            if price is None or rate is None:
                notes.append(f"{market['exchange']}: missing payout rate/mark; P&L incomplete.")
                continue
            cash = sign * trade["quantity"] * price / multiplier(market) * rate
            total += cash
            rows.append(dict(time=event["time"], venue=market["exchange"], funding=cash))
            interval = values.get("Funding interval") or market.get("funding_interval") or 1
            if (utc(event["time"]) - times[-1]).total_seconds() > interval * 3600 * 1.25:
                notes.append(f"{market['exchange']}: payout gap; recorded funding may be incomplete.")
            times.append(utc(event["time"]))
        interval = market.get("funding_interval") or 1
        if (end - times[-1]).total_seconds() > (interval + 1) * 3600:
            notes.append(f"{market['exchange']}: latest settlement may be missing or delayed.")
        totals.append(total)
    return totals, sorted(set(notes)), rows


def refresh_trade(store, trade, close=False):
    if any(r["id"] == trade["id"] for r in store.records("close", trade["id"])):
        raise ValueError("This trade is already closed; its result is immutable.")
    markets = trade["markets"]
    missing = []
    for market in markets:
        history = load_history(market["market_id"])
        archive_history(store, market, history)
        if history.attrs.get("missing_rates"):
            missing.append(f"{market['exchange']}: provider omitted rates; result is incomplete.")
    # Fetch quotes after histories to keep the valuation contemporaneous.
    books = pair_books(*markets)
    end = utc()
    lp, sp = fills(books, trade["quantity"], opening=False)
    totals, notes, cashflows = funding_total(store, trade, end)
    q, fee = trade["quantity"], trade["settings"]["fee"]
    long_pnl, short_pnl = q * (lp - trade["long_entry"]), q * (trade["short_entry"] - sp)
    exit_fee = q * (lp + sp) * fee
    net = sum(totals) + long_pnl + short_pnl - trade["entry_fee"] - exit_fee
    capital = trade["settings"]["capital"]
    leg_equity = [capital / 2 + totals[0] + long_pnl - q * trade["long_entry"] * fee - q * lp * fee,
                  capital / 2 + totals[1] + short_pnl - q * trade["short_entry"] * fee - q * sp * fee]
    valuation = dict(trade_id=trade["id"], at=end.isoformat(), closed=close,
                     funding=sum(totals), long_funding=totals[0], short_funding=totals[1],
                     price_pnl=long_pnl+short_pnl, fees=trade["entry_fee"]+exit_fee, net=net,
                     return_pct=net/capital*100, long_exit=lp, short_exit=sp,
                     long_equity=leg_equity[0], short_equity=leg_equity[1],
                     margin_alert=min(leg_equity[0]/(q*lp),leg_equity[1]/(q*sp)) < .1,
                     notes=sorted(set(notes+missing)), books=books, cashflows=cashflows)
    if close and valuation["notes"]:
        raise ValueError("Closing is blocked while funding coverage is incomplete. Refresh later; the position remains open.")
    store.put("close" if close else "valuation", trade["id"] if close else trade["id"]+":"+end.isoformat(), valuation)
    return valuation


def trade_rows(store):
    trades = [r["payload"] for r in store.records("trade")]
    closed = {r["id"]: r["payload"] for r in store.records("close")}
    marks = {}
    for row in store.records("valuation"):
        value = row["payload"]
        if value["at"] > marks.get(value["trade_id"], {}).get("at", ""):
            marks[value["trade_id"]] = value
    rows = []
    for trade in trades:
        last = closed.get(trade["id"], marks.get(trade["id"], {}))
        rows.append(dict(ID=trade["id"], Asset=trade["markets"][0]["base_asset"],
                         Long=trade["markets"][0]["exchange"], Short=trade["markets"][1]["exchange"],
                         Status="Closed" if trade["id"] in closed else "Open",
                         Capital=trade["settings"]["capital"], Opened=trade["opened_at"],
                         Updated=last.get("at"), Funding=last.get("funding"),
                         **{"Price P&L": last.get("price_pnl"), "Fees": last.get("fees"),
                            "Net P&L": last.get("net"), "Return %": last.get("return_pct"),
                            "Coverage": "; ".join(last.get("notes", [])) or ("Observed payouts" if last else "Not valued yet")}))
    return trades, rows
