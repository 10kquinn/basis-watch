"""Run on an always-on machine: python recorder.py --interval 900.

Only archives/values existing PAPER trades. Never opens a trade or sends orders.
"""
import argparse
import os
import time
from datetime import datetime, timezone

from paper import trade_rows, refresh_trade
from storage import configured_store


def record_once(store):
    trades, _ = trade_rows(store)
    closed = {r["id"] for r in store.records("close")}
    failures = 0
    for trade in trades:
        if trade["id"] in closed:
            continue
        try:
            valuation = refresh_trade(store, trade)
            print(f"{valuation['at']} {trade['id']} net={valuation['net']:.2f} coverage={valuation['notes']}", flush=True)
        except Exception as error:
            failures += 1
            print(f"{datetime.now(timezone.utc).isoformat()} {trade['id']} not updated: {type(error).__name__}: {error}", flush=True)
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=int, default=0, help="Seconds between updates; 0 runs once. Minimum 60.")
    args = parser.parse_args()
    if args.interval and args.interval < 60:
        parser.error("Interval must be at least 60 seconds.")
    config = dict(os.environ)
    # Same secrets as the app, when run from the project directory.
    try:
        import streamlit as st
        config.update(dict(st.secrets))
    except FileNotFoundError:
        pass
    store = configured_store(config)
    while True:
        failures = record_once(store)
        if not args.interval:
            raise SystemExit(1 if failures else 0)
        time.sleep(args.interval)
