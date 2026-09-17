"""Streamlit research and private paper journal, keeping the scanner lightweight."""
from __future__ import annotations

import hmac
import json
import os
from dataclasses import asdict
from uuid import uuid4
import pandas as pd
import requests
import streamlit as st

from lab import scan, result_table
from paper import open_trade, refresh_trade, trade_rows
from research import Assumptions, VENUES
from storage import configured_store, encode


def private_store():
    config = dict(os.environ)
    try:
        config.update(dict(st.secrets))
    except FileNotFoundError:
        pass
    password = config.get("LEDGER_PASSWORD", "")
    if not password:
        st.info("Saving is locked. Set LEDGER_PASSWORD in server-side secrets to enable your private research and ledger. See README → Persistent paper trading.")
        return None
    supplied = st.text_input("Private journal password", type="password", key="journal_password")
    if not supplied or not hmac.compare_digest(supplied.encode(), password.encode()):
        if supplied:
            st.warning("Incorrect journal password.")
        return None
    try:
        store = configured_store(config)
        st.caption(store.backend)
        if not store.url and config.get("RAILWAY_VOLUME_MOUNT_PATH"):
            st.caption("Railway persistent volume · records survive deployments. Keep volume backups enabled.")
        elif not store.url:
            st.warning("Local storage only: Streamlit Cloud can erase this database on redeploy/restart. Connect Supabase before relying on hosted records.")
        return store
    except (ValueError, requests.RequestException) as error:
        st.error(str(error))
        return None


def render_research(filtered):
    st.header("Research lab")
    st.write("Test the funding edge against price divergence and trading costs, then record a forward paper trade.")
    st.caption("Universe: TradeXYZ, Hyperliquid, Lighter, Binance, Bybit and OKX. Sidebar filters apply to both legs.")
    with st.expander("Assumptions and evidence", expanded=False):
        st.write("Historical replay holds equal underlying quantities, at no more than 2× leverage on each half of capital. "
                 "Funding uses quantity × the mark price at each settlement × the settled rate. Entry and exit use shared mark timestamps plus adverse slippage; these are not real fills.")
        st.write("Two fixed rules: use the previous 1 or 3 days of funding to decide whether a 7-day hold is projected to cover costs. "
                 "Enter after the signal timestamp and do not overlap holds within a pair/rule. All completed outcomes, including losses, are shown. "
                 "This is a historical timing test on TODAY'S selected pairs, not an unbiased universe backtest or portfolio result.")
        st.write("Current projections hold today's funding and prices constant and use visible book depth for all four fills. Stress: halve funding and widen basis adversely by 1% of one leg's notional. Neither is a forecast.")
        st.write("USDT/USDC are assumed worth $1. No lot-size rounding, compounding, borrowing, transfers, rebalancing, execution latency, depegs, venue-specific liquidation or intraperiod margin simulation. "
                 "A 10% equity/notional alert is a warning only; sparse mark samples can miss liquidation. TradeXYZ shares Hyperliquid infrastructure, so these are not independent venue risks.")
    a, b, c = st.columns(3)
    capital = a.number_input("Research capital (USD)", min_value=100., value=10000., step=1000.)
    fee = b.number_input("Fee per leg per entry/exit (%)", min_value=0., max_value=2., value=.2, step=.01)
    slip = c.number_input("Historical slippage per fill (%)", min_value=0., max_value=2., value=.05, step=.01)
    settings = Assumptions(capital=capital, fee=fee/100, slippage=slip/100)
    pool = filtered[filtered._long.isin(VENUES) & filtered._short.isin(VENUES)].sort_values("APR", ascending=False)
    limit = st.number_input("Maximum pairs to check (highest filtered APR first)", min_value=1, max_value=100, value=12, step=1)
    st.caption(f"{len(pool)} filtered pairs available. API failures and excluded pairs remain visible in the results.")
    with st.expander("Save research / unlock paper trading"):
        store = private_store()
        if store and st.button("Load latest saved research"):
            try:
                saved = store.records("research")
                if saved:
                    st.session_state.research_run = saved[-1]["payload"]
                    st.session_state.paper_intent = str(uuid4())
                else:
                    st.info("No saved research yet. Your next scan will be saved here.")
            except (ValueError, requests.RequestException) as error:
                st.error(str(error))
    if st.button("Run research", type="primary", disabled=pool.empty):
        progress = st.progress(0., text="Loading histories and current books…")
        try:
            run = scan(pool.head(int(limit)).to_dict("records"), settings, store,
                       lambda value, message: progress.progress(value, text=message))
            st.session_state.research_run = run
            st.session_state.paper_intent = str(uuid4())
        except (ValueError, requests.RequestException) as error:
            st.error("Research could not be saved: " + str(error))
        finally:
            progress.empty()
    run = st.session_state.get("research_run")
    if not run:
        st.info("Run research to see which filtered pairs survive costs and price divergence. No orders will be placed.")
        return
    st.caption(f"Snapshot started {run['started_at']} · finished {run['finished_at']}. Results retain the assumptions used for that run.")
    if run["assumptions"] != asdict(settings):
        st.warning("Inputs changed. Run research again to apply them; results below still use the saved assumptions.")
    table = result_table(run)
    candidates = int((table.Status == "Research candidate").sum()) if not table.empty else 0
    st.subheader(f"{candidates} research candidate{'s' if candidates != 1 else ''}")
    st.caption("Pass = positive historical hold net, positive current projection, at least one profitable timing rule, no detected gaps or sampled margin alert. This is a shortlist, not proof of profitability.")
    visible = [c for c in ("Asset", "Long", "Short", "Status", "Days", "Historical net $",
                           "Projected hold net $", "Stress net $") if c in table]
    st.dataframe(table[visible], hide_index=True, width="stretch", column_config={
        "Days": st.column_config.NumberColumn(format="%.1f"),
        "Historical net $": st.column_config.NumberColumn(format="$%.2f"),
        "Projected hold net $": st.column_config.NumberColumn("Current 7d scenario", format="$%.2f"),
        "Stress net $": st.column_config.NumberColumn("Stressed 7d scenario", format="$%.2f"),
    })
    with st.expander("All rule results, coverage and exclusions"):
        st.dataframe(table, hide_index=True, width="stretch")
    st.download_button("Download research evidence (JSON)", encode(run), file_name="basis-research-"+run["id"]+".json", mime="application/json")
    valid = [r for r in run["results"] if r.get("backtest")]
    if not valid:
        return
    indices = list(range(len(valid)))
    i = st.selectbox("Inspect a pair", indices, format_func=lambda k: f"{valid[k]['asset']} · long {valid[k]['long']} / short {valid[k]['short']} ({valid[k]['long_id']}/{valid[k]['short_id']})")
    result = valid[i]
    bt = result["backtest"]
    summary = bt["summary"]
    st.caption(f"Shared historical window: {summary['start']} to {summary['end']} ({summary['days']:.2f} days).")
    cols = st.columns(4)
    for col, label, field in zip(cols, ("Funding", "Price P&L after slippage", "Trading fees", "Net historical P&L"), ("funding", "price_pnl", "fees", "net")):
        col.metric(label, f"${summary[field]:,.2f}")
    curve = pd.DataFrame(bt["curve"])
    curve["Time"] = pd.to_datetime(curve.Time, utc=True)
    st.line_chart(curve.set_index("Time")[["Net P&L", "Funding", "Price P&L"]], color=["#112238", "#087E70", "#B56B13"])
    with st.expander("Price divergence and margin warnings"):
        st.line_chart(curve.set_index("Time")[["Basis bps"]])
        st.line_chart(curve.set_index("Time")[["Long equity", "Short equity"]])
        st.write(f"Worst sampled drawdown: ${summary['max_drawdown']:,.2f}. Lowest sampled leg equity: ${summary['minimum_leg_equity']:,.2f}.")
        st.warning("These are settlement-time samples, not continuous margin monitoring. Survival between samples is assumed.")
    for name, trades in bt["rules"].items():
        with st.expander(name):
            if trades:
                st.dataframe(pd.DataFrame(trades), hide_index=True, width="stretch")
                st.caption("Each rule reuses the same fixed capital sequentially. Different pairs/rules are independent experiments; do not add their returns as one portfolio.")
            else:
                st.info("No complete qualifying forward holds. This is not a zero-return successful strategy.")
    live = result.get("live")
    if live:
        st.subheader("At current rates and visible prices")
        cols = st.columns(3)
        cols[0].metric("Projected 7-day net", f"${live['projected_net']:,.2f}")
        cols[1].metric("Stressed 7-day net", f"${live['stressed_net']:,.2f}")
        cols[2].metric("Fee break-even", f"{live['break_even_days']:.1f} days" if live['break_even_days'] is not None else "No positive carry")
        st.caption(f"Observed {live['observed_at']}. Uses fresh book depth at the time of the scan, not an executable offer or guaranteed funding.")
    if store:
        st.subheader("Start a theoretical trade")
        st.caption("Fetches NEW entry books when you save. No real order is sent. Historical slippage is not charged again on book-based paper fills.")
        thesis = st.text_area("Entry reason and exit rule", placeholder="Example: carry covers costs over 7 days; review daily and close if carry reverses or basis loss exceeds my limit.")
        confirm = st.checkbox("I understand this is a manual paper experiment, not a proven strategy.")
        if st.button("Open paper trade", disabled=not confirm or not thesis.strip()):
            try:
                key = f"{st.session_state.setdefault('paper_intent', str(uuid4()))}:{result['long_id']}:{result['short_id']}"
                open_trade(store, result["markets"], Assumptions(**run["assumptions"]), thesis, key)
                st.success("Paper entry saved. Open Paper ledger to refresh its P&L or close it.")
            except (ValueError, requests.RequestException) as error:
                st.error(str(error))


def render_ledger():
    st.header("Paper ledger")
    st.write("A private journal of theoretical two-leg positions. Entries are fixed; each refresh appends a new valuation.")
    store = private_store()
    if store is None:
        return
    try:
        trades, rows = trade_rows(store)
        closed = {r["id"] for r in store.records("close")}
        active = [t for t in trades if t["id"] not in closed]
        st.caption(f"{len(active)} open experiments · ${sum(t['settings']['capital'] for t in active):,.2f} total allocated paper capital. These are separate manual experiments, not an automatically managed portfolio.")
        if os.environ.get("RECORDER_ENABLED") == "1":
            st.info("A background recorder is configured to refresh open paper trades every " + os.environ.get("RECORDER_INTERVAL", "900") + " seconds while the service is running. Check valuation timestamps to confirm updates. It never opens or closes trades.")
        else:
            st.info("Refreshes are manual unless you run the included recorder. Streamlit does not collect while asleep. Funding can be recovered for up to 30 days; missed quotes and longer funding gaps cannot be reconstructed.")
        if active and st.button("Refresh all open trades"):
            with st.spinner("Archiving settlements and valuing both legs…"):
                for trade in active:
                    try:
                        refresh_trade(store, trade)
                    except (ValueError, requests.RequestException) as error:
                        st.warning(f"{trade['markets'][0]['base_asset']}: {error}. Previous valuation retained; it is not current.")
            trades, rows = trade_rows(store)
        if not trades:
            st.info("No paper trades yet. Run a Research lab scan, unlock saving and record your first entry.")
        else:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            ids = [t["id"] for t in trades]
            identifier = st.selectbox("Trade details", ids, format_func=lambda i: next(f"{r['Asset']} · {r['Long']} / {r['Short']} · {r['Opened']}" for r in rows if r["ID"] == i))
            trade = next(t for t in trades if t["id"] == identifier)
            st.write(trade["thesis"])
            st.caption(f"Saved {trade['opened_at']}; {trade['quantity']:.8g} underlying units on each side. Entry fees ${trade['entry_fee']:,.2f}.")
            vals = [r["payload"] for r in store.records("valuation", identifier+":")] + [r["payload"] for r in store.records("close", identifier) if r["id"] == identifier]
            if vals:
                values = pd.DataFrame(vals).sort_values("at")
                values["at"] = pd.to_datetime(values["at"], utc=True)
                st.line_chart(values.set_index("at")[["net", "funding", "price_pnl"]])
                last = vals[-1]
                for note in last.get("notes", []):
                    st.warning(note)
                if last.get("margin_alert"):
                    st.error("A leg's sampled equity/notional is below 10%. This experiment may not have survived real margin requirements.")
                st.caption("Open P&L is the estimated net if closed at that snapshot, including exit fees. Between-refresh drawdowns and liquidations are not observed.")
            if identifier not in closed:
                confirmed = st.checkbox("Close both theoretical legs at fresh book prices")
                if st.button("Close paper trade", disabled=not confirmed):
                    refresh_trade(store, trade, close=True)
                    st.success("Final paper result saved. It will not change on later refreshes.")
                    st.rerun()
        research = store.records("research")
        if research:
            with st.expander(f"Saved research snapshots ({len(research)})"):
                st.dataframe(pd.DataFrame([{"ID": r["id"], "Saved": r["created_at"], "Pairs": len(r["payload"]["results"])} for r in research]), hide_index=True)
        if st.button("Prepare full journal export"):
            st.session_state.journal_export = encode(store.records())
        if "journal_export" in st.session_state:
            st.download_button("Download journal backup (JSON)", st.session_state.journal_export, file_name="basis-journal.json", mime="application/json")
    except (ValueError, requests.RequestException) as error:
        st.error(str(error))
