from __future__ import annotations

from datetime import datetime
from html import escape
from hashlib import sha256
from math import isfinite
from urllib.parse import quote as url_quote

import altair as alt
import pandas as pd
import requests
import streamlit as st

from backtest import HistoryUnavailable, calculate_backtest
from market_filters import (
    CLASS_LABELS, TRADFI_CLASSES, asset_classes, available_exchanges,
    exchange_ids, filter_asset_group,
)


API_URL = "https://bendbasis.com/api/v1/public/funding/arbitrage"
HISTORY_URL = "https://bendbasis.com/api/v1/public/funding/markets/{market_id}/history"
MARKETS_URL = "https://bendbasis.com/api/v1/public/funding/markets"
DEFAULT_EXCHANGES = [
    "binance",
    "bybit",
    "coinbase_intx",
    "dydx",
    "hyperliquid",
    "kraken",
    "lighter",
    "okx",
]


def exchange_label(value: str) -> str:
    return "Coinbase International" if value == "coinbase_intx" else value.replace("_", " ").title()


st.set_page_config(
    page_title="Basis Watch",
    page_icon="↗",
    layout="wide",
    initial_sidebar_state="auto",
)


st.markdown(
    """
    <style>
        :root {
            --ink: #112238;
            --muted: #617087;
            --line: #D8E1EB;
            --mist: #F4F7FA;
            --teal: #087E70;
            --teal-soft: #DDF3EE;
            --amber: #B56B13;
        }

        .stApp {
            background: #FBFCFD;
            color: var(--ink);
            font-family: "Avenir Next", Avenir, "Segoe UI", sans-serif;
        }

        [data-testid="stHeader"] {
            background: rgba(251, 252, 253, 0.88);
        }

        [data-testid="stSidebar"] {
            background: #EEF3F7;
            border-right: 1px solid var(--line);
        }

        [data-testid="stSidebar"] h2 {
            color: var(--ink);
            letter-spacing: -0.02em;
        }

        .block-container {
            max-width: 1220px;
            padding-top: 2.6rem;
            padding-bottom: 4rem;
        }

        .masthead {
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
            gap: 2rem;
            padding-bottom: 1.35rem;
            border-bottom: 1px solid var(--line);
            margin-bottom: 1rem;
        }

        .masthead h1 {
            color: var(--ink);
            font-size: clamp(2.25rem, 6vw, 4.4rem);
            font-weight: 650;
            letter-spacing: -0.065em;
            line-height: 0.92;
            margin: 0;
        }

        .masthead p {
            color: var(--muted);
            font-size: 1rem;
            line-height: 1.55;
            max-width: 34rem;
            margin: 0;
        }

        .live-ribbon {
            display: flex;
            align-items: center;
            gap: 0.65rem;
            color: #075E54;
            background: var(--teal-soft);
            border: 1px solid #B8DED6;
            border-radius: 999px;
            width: fit-content;
            padding: 0.45rem 0.8rem;
            font-size: 0.82rem;
            font-weight: 650;
            margin: 0 0 1.75rem 0;
        }

        .live-dot {
            background: var(--teal);
            border-radius: 50%;
            height: 0.52rem;
            width: 0.52rem;
            box-shadow: 0 0 0 3px rgba(8, 126, 112, 0.13);
        }

        .summary-strip {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            border-top: 1px solid var(--line);
            border-bottom: 1px solid var(--line);
            margin: 0.6rem 0 1.5rem 0;
        }

        .summary-item {
            padding: 1rem 1.2rem 1rem 0;
        }

        .summary-item + .summary-item {
            border-left: 1px solid var(--line);
            padding-left: 1.2rem;
        }

        .summary-label {
            color: var(--muted);
            font-size: 0.8rem;
            margin-bottom: 0.25rem;
        }

        .summary-value {
            color: var(--ink);
            font-size: 1.45rem;
            font-weight: 650;
            font-variant-numeric: tabular-nums;
            letter-spacing: -0.025em;
        }

        .table-heading {
            color: var(--ink);
            font-size: 1.25rem;
            font-weight: 650;
            letter-spacing: -0.025em;
            margin: 0.25rem 0 0.1rem 0;
        }

        .table-note {
            color: var(--muted);
            font-size: 0.88rem;
            margin: 0 0 0.85rem 0;
        }

        .history-rule {
            border-top: 1px solid var(--line);
            margin: 2rem 0 1.65rem 0;
        }

        .history-guide {
            background: #F3F7F8;
            border-left: 3px solid var(--teal);
            color: var(--muted);
            font-size: 0.9rem;
            line-height: 1.55;
            margin-top: 1.2rem;
            padding: 0.85rem 1rem;
        }

        .return-strip {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            background: #F3F7F8;
            border-top: 1px solid var(--line);
            border-bottom: 1px solid var(--line);
            margin: 0.8rem 0 0.75rem 0;
        }

        .return-item {
            padding: 1rem 1.2rem 1rem 0;
        }

        .return-item + .return-item {
            border-left: 1px solid var(--line);
            padding-left: 1.2rem;
        }

        .return-label {
            color: var(--muted);
            font-size: 0.8rem;
            margin-bottom: 0.25rem;
        }

        .return-value {
            color: var(--teal);
            font-size: 1.45rem;
            font-weight: 650;
            font-variant-numeric: tabular-nums;
            letter-spacing: -0.025em;
        }

        .venue-list {
            border-top: 1px solid var(--line);
            border-bottom: 1px solid var(--line);
            margin-top: 0.8rem;
        }

        .venue-row {
            display: grid;
            grid-template-columns: minmax(180px, 1.2fr) repeat(2, minmax(0, 1fr));
            gap: 1.25rem;
            align-items: center;
            padding: 1rem 0;
        }

        .venue-row + .venue-row {
            border-top: 1px solid var(--line);
        }

        a.venue-row {
            color: inherit;
            text-decoration: none;
            cursor: pointer;
        }

        a.venue-row:hover {
            background: #EEF5F4;
            text-decoration: none;
        }

        a.venue-row:hover .venue-name {
            text-decoration: underline;
            text-underline-offset: 3px;
        }

        a.venue-row:focus-visible {
            outline: 3px solid var(--teal);
            outline-offset: -3px;
        }

        .venue-link-icon {
            color: var(--teal);
            font-size: 0.85rem;
        }

        .venue-identity {
            display: flex;
            align-items: center;
            gap: 0.65rem;
            min-width: 0;
        }

        .venue-side {
            border-radius: 999px;
            flex: 0 0 auto;
            font-size: 0.75rem;
            font-weight: 650;
            padding: 0.28rem 0.58rem;
        }

        .venue-side.long {
            background: var(--teal-soft);
            color: #075E54;
        }

        .venue-side.short {
            background: #F8E9D5;
            color: #89500C;
        }

        .venue-name {
            color: var(--ink);
            font-weight: 650;
        }

        .venue-market {
            color: var(--muted);
            font-size: 0.82rem;
        }

        .venue-metric-label {
            color: var(--muted);
            font-size: 0.78rem;
            margin-bottom: 0.2rem;
        }

        .venue-metric-value {
            color: var(--ink);
            font-size: 0.95rem;
            font-variant-numeric: tabular-nums;
            overflow-wrap: anywhere;
        }

        [data-testid="stDataFrame"] {
            border: 1px solid var(--line);
            border-radius: 10px;
            overflow: hidden;
        }

        .stButton > button {
            border: 1px solid #AEBECD;
            color: var(--ink);
            background: white;
            border-radius: 8px;
            font-weight: 600;
        }

        .stButton > button:hover {
            border-color: var(--teal);
            color: var(--teal);
        }

        .stButton > button:focus-visible,
        input:focus-visible,
        button:focus-visible {
            outline: 3px solid rgba(8, 126, 112, 0.25) !important;
            outline-offset: 2px;
        }

        @media (max-width: 760px) {
            .block-container { padding-top: 1.5rem; }
            .masthead { align-items: flex-start; flex-direction: column; gap: 0.8rem; }
            .masthead h1 { font-size: 3.1rem; }
            .summary-strip { grid-template-columns: 1fr; }
            .return-strip { grid-template-columns: 1fr; }
            .summary-item + .summary-item {
                border-left: 0;
                border-top: 1px solid var(--line);
                padding-left: 0;
            }
            .return-item + .return-item {
                border-left: 0;
                border-top: 1px solid var(--line);
                padding-left: 0;
            }
            .venue-row {
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 0.85rem 1rem;
            }
            .venue-identity { grid-column: 1 / -1; }
        }

        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after { scroll-behavior: auto !important; }
        }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=60, show_spinner=False)
def fetch_opportunities() -> tuple[pd.DataFrame, int, int, str]:
    """Fetch and normalize Bend Basis arbitrage opportunities."""
    response = requests.get(
        API_URL,
        timeout=20,
        headers={"User-Agent": "BasisWatch/1.0"},
    )
    response.raise_for_status()
    payload = response.json()

    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        payload = payload["data"]
    if not isinstance(payload, list):
        raise ValueError("The API returned an unexpected response format.")

    rows: list[dict[str, object]] = []
    skipped = 0

    for item in payload:
        if not isinstance(item, dict):
            skipped += 1
            continue

        try:
            asset = str(item["base_asset"]).strip().upper()
            apr = float(item["apr"])
            stability = float(item["stability"])
            long_exchange = str(item["long_exchange"]).strip().lower()
            short_exchange = str(item["short_exchange"]).strip().lower()
            long_market_id = int(item["long_market_id"])
            short_market_id = int(item["short_market_id"])
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue

        if not asset or not long_exchange or not short_exchange:
            skipped += 1
            continue

        rows.append(
            {
                "Asset": asset,
                "APR": apr,
                "Stability": stability * 100,
                "Long exchange": exchange_label(long_exchange),
                "Short exchange": exchange_label(short_exchange),
                "_long": long_exchange,
                "_short": short_exchange,
                "_long_market_id": long_market_id,
                "_short_market_id": short_market_id,
            }
        )

    columns = [
        "Asset",
        "APR",
        "Stability",
        "Long exchange",
        "Short exchange",
        "_long",
        "_short",
        "_long_market_id",
        "_short_market_id",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    fetched_at = datetime.now().astimezone().strftime("%I:%M:%S %p")
    return frame, len(payload), skipped, fetched_at


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_asset_classes() -> dict[str, str]:
    response = requests.get("https://api.bendbasis.com/v1/assets", timeout=20)
    response.raise_for_status()
    return asset_classes(response.json())


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_exchange_ids() -> list[str]:
    response = requests.get("https://api.bendbasis.com/v1/exchanges", timeout=20)
    response.raise_for_status()
    return exchange_ids(response.json())


@st.cache_data(ttl=600, show_spinner=False)
def fetch_history(market_id: int) -> pd.DataFrame:
    """Fetch the latest 30 days of APR history for one funding market."""
    response = requests.get(
        HISTORY_URL.format(market_id=market_id),
        params={"days": 30},
        timeout=20,
        headers={"User-Agent": "BasisWatch/1.0"},
    )
    response.raise_for_status()
    payload = response.json()

    if not isinstance(payload, list):
        raise ValueError("The history API returned an unexpected response format.")

    rows: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("The history API returned an invalid payout.")
        try:
            funding_time = pd.to_datetime(item["funding_time"], utc=True)
            apr = float(item["apr"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("The history API returned an invalid payout.")
        if pd.isna(funding_time) or not isfinite(apr):
            raise ValueError("The history API returned an invalid payout.")
        rows.append({"Time": funding_time, "APR": apr})

    history = pd.DataFrame(rows, columns=["Time", "APR"])
    if not history.empty:
        history = history.sort_values("Time", kind="stable").reset_index(drop=True)
    return history


@st.cache_data(ttl=300, show_spinner=False)
def fetch_market_snapshots(
    market_ids: tuple[int, ...],
) -> dict[int, dict[str, object]]:
    """Fetch current liquidity data for the selected funding markets."""
    response = requests.get(
        MARKETS_URL,
        params={"market_ids": ",".join(str(market_id) for market_id in market_ids)},
        timeout=20,
        headers={"User-Agent": "BasisWatch/1.0"},
    )
    response.raise_for_status()
    payload = response.json()

    if not isinstance(payload, list):
        raise ValueError("The markets API returned an unexpected response format.")

    snapshots: dict[int, dict[str, object]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            market_id = int(item["market_id"])
        except (KeyError, TypeError, ValueError):
            continue
        snapshots[market_id] = item
    return snapshots


def format_quote_amount(value: object, quote_asset: str) -> str:
    """Format an API liquidity value with its reported quote asset."""
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "Not reported"
    if pd.isna(amount):
        return "Not reported"
    return f"{amount:,.2f} {quote_asset}"


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_venue_symbols(venue: str) -> dict[str, list[str]]:
    """Read native contract names; Bend Basis can normalize multiplier symbols."""
    symbols: dict[str, list[str]] = {}

    def get_json(url: str, **kwargs):
        response = requests.get(url, timeout=10, **kwargs)
        response.raise_for_status()
        return response.json()

    if venue == "binance":
        payload = get_json("https://fapi.binance.com/fapi/v1/exchangeInfo")
        for row in payload["symbols"]:
            if row.get("contractType") in {"PERPETUAL", "TRADIFI_PERPETUAL"}:
                symbols.setdefault(row["quoteAsset"], []).append(row["baseAsset"])
    elif venue == "bybit":
        cursor = ""
        seen = set()
        while True:
            payload = get_json(
                "https://api.bybit.com/v5/market/instruments-info",
                params={"category": "linear", "limit": 1000, "cursor": cursor},
            )
            if payload.get("retCode") != 0:
                raise ValueError("Bybit market catalogue unavailable")
            for row in payload["result"]["list"]:
                if row.get("contractType") == "LinearPerpetual":
                    symbols.setdefault(row["quoteCoin"], []).append(row["baseCoin"])
            cursor = payload["result"].get("nextPageCursor", "")
            if not cursor or cursor in seen:
                break
            seen.add(cursor)
    elif venue == "hyperliquid":
        response = requests.post(
            "https://api.hyperliquid.xyz/info", json={"type": "meta"}, timeout=10
        )
        response.raise_for_status()
        symbols["USDC"] = [row["name"] for row in response.json()["universe"]]
    elif venue == "lighter":
        payload = get_json("https://mainnet.zklighter.elliot.ai/api/v1/orderBooks")
        symbols["USDC"] = [
            row["symbol"] for row in payload["order_books"]
            if row.get("market_type") == "perp"
        ]
    return symbols


def native_market_base(venue: str, base: str, native_symbols: list[str]) -> str:
    """Resolve normalized names against the venue's own contract catalogue."""
    aliases = {
        "binance": {
            "STX_EQ": "STXX", "BOB_BNB": "BOB", "BOB": "1000000BOB",
            "WTI": "CL", "BRENTOIL": "BZ",
            "XCU": "COPPER", "TENCENTHKD": "HK0700", "XIAOMIHKD": "HK1810",
        },
        "bybit": {
            "STX_EQ": "STXX", "CAT_EQ": "CATSTOCK", "WEN_EQ": "WENSTOCK",
            "RAY": "RAYDIUM", "LAYER": "SOLAYER", "WTI": "CL",
            "BRENTOIL": "BZ", "GIGADEV": "GIGADEVICE", "NES": "NESA", "NOK": "NOKIA",
        },
        "lighter": {"SP500": "US500", "NASDAQ100": "US100"},
    }
    base = aliases.get(venue, {}).get(base, base)
    for suffix in ("_EQ", "_LIGHTER"):
        if base.endswith(suffix):
            base = base[:-len(suffix)]
    names = {name.upper(): name for name in native_symbols}
    if base in names:
        return names[base]
    candidates = [
        prefix + base for prefix in ("1000", "10000", "1000000", "1M", "K")
    ] + [base + "1000"]
    matches = [names[name] for name in candidates if name in names]
    if len(matches) == 1:
        return matches[0]
    if base + "STOCK" in names:
        return names[base + "STOCK"]
    return base


def perpetual_market_url(
    exchange: str, base_asset: str, quote_asset: str,
    native_symbols: list[str] | None = None,
) -> str | None:
    """Build market-specific perpetual links for every allowed exchange."""
    venue = exchange.strip().lower()
    base = base_asset.strip().upper()
    quote = quote_asset.strip().upper()
    if not base or not base.replace("_", "").isalnum():
        return None
    base = url_quote(native_market_base(venue, base, native_symbols or []), safe="")
    if venue == "binance" and quote in {"USDT", "USDC", "USD1"}:
        return f"https://www.binance.com/en/futures/{base}{quote}"
    if venue == "bybit" and quote == "USDT":
        return f"https://www.bybit.com/trade/usdt/{base}{quote}"
    if venue == "bybit" and quote == "USDC":
        return f"https://www.bybit.com/trade/usdc/{base}-PERP"
    if venue == "okx" and quote in {"USDT", "USDC", "USD"}:
        return f"https://www.okx.com/trade-swap/{base.lower()}-{quote.lower()}-swap"
    if venue == "kraken" and quote == "USD":
        return f"https://pro.kraken.com/app/trade/futures-{base.lower()}-usd-perp"
    if venue == "dydx" and quote in {"USD", "USDC"}:
        return f"https://trade.dydx.exchange/trade/{base}-USD"
    if venue == "hyperliquid" and quote in {"USD", "USDC"}:
        return f"https://app.hyperliquid.xyz/trade/{base}"
    if venue == "lighter" and quote in {"USD", "USDC"}:
        return f"https://app.lighter.xyz/trade/{base}"
    if venue in {"coinbase", "coinbase_intx"} and quote in {"USD", "USDC"}:
        return f"https://www.coinbase.com/advanced-trade/perpetuals/{base}-PERP-INTX"
    return None


st.markdown(
    """
    <div class="masthead">
        <h1>Basis<br>Watch</h1>
        <p>
            A focused view of funding-rate arbitrage opportunities across the
            exchanges you trust. Tune the thresholds, compare both legs, and
            inspect the strongest spreads first.
        </p>
    </div>
    <div class="live-ribbon">
        <span class="live-dot"></span>
        Live Bend Basis market data · cached for up to 60 seconds
    </div>
    """,
    unsafe_allow_html=True,
)


with st.sidebar:
    st.header("Opportunity filters")
    st.caption("Choose an asset group and the venues you want to compare.")

    asset_group = st.radio("Asset group", ["All", "Crypto", "TradFi"], horizontal=True,
                           key="asset_group")
    tradfi_categories = list(TRADFI_CLASSES)
    if asset_group == "TradFi":
        tradfi_categories = st.multiselect(
            "TradFi categories", options=[key for key in CLASS_LABELS if key in TRADFI_CLASSES],
            default=[key for key in CLASS_LABELS if key in TRADFI_CLASSES],
            format_func=CLASS_LABELS.get, key="tradfi_categories",
        )
    st.caption("Asset classes come from Bend Basis. Unclassified assets appear only in All.")

    min_apr = st.number_input(
        "Minimum APR",
        min_value=0.0,
        max_value=10000.0,
        value=15.0,
        step=1.0,
        format="%.1f",
        help="Only show opportunities at or above this annualized percentage.",
    )
    min_stability = st.slider(
        "Minimum stability",
        min_value=0,
        max_value=100,
        value=80,
        step=1,
        format="%d%%",
        help="Higher stability can mean a more consistent historical spread.",
    )
    asset_search = st.text_input(
        "Find an asset",
        placeholder="Try BTC, TSLA or XAU",
    ).strip().upper()

    if st.button("Refresh market data", width="stretch"):
        fetch_opportunities.clear()
        fetch_history.clear()
        fetch_market_snapshots.clear()
        fetch_venue_symbols.clear()
        fetch_asset_classes.clear()
        fetch_exchange_ids.clear()
        st.rerun()


try:
    with st.spinner("Checking current funding spreads…"):
        opportunities, total_rows, skipped_rows, fetched_at = fetch_opportunities()
except requests.RequestException as error:
    st.error(
        "Bend Basis could not be reached. Check your internet connection, then "
        "select **Refresh market data**."
    )
    with st.expander("Technical details"):
        st.code(str(error))
    st.stop()
except (ValueError, TypeError) as error:
    st.error("Bend Basis returned data in a format this app does not recognize.")
    with st.expander("Technical details"):
        st.code(str(error))
    st.stop()


try:
    classes = fetch_asset_classes()
except (requests.RequestException, ValueError, TypeError):
    classes = {}
    st.warning("Asset classifications are temporarily unavailable. All still works; "
               "Crypto and TradFi cannot classify results until Refresh market data succeeds.")
try:
    exchange_catalogue = fetch_exchange_ids()
except (requests.RequestException, ValueError, TypeError):
    exchange_catalogue = []
    st.warning("The full exchange catalogue is temporarily unavailable. "
               "The selector includes every exchange in the current opportunity feed.")

opportunities = opportunities.copy()
opportunities["_asset_class"] = opportunities["Asset"].map(classes).fillna("unknown")
opportunities["Asset class"] = opportunities["_asset_class"].map(CLASS_LABELS)
exchange_options = available_exchanges(opportunities, exchange_catalogue)
if "selected_exchanges" not in st.session_state:
    st.session_state.selected_exchanges = [x for x in DEFAULT_EXCHANGES if x in exchange_options]
else:
    st.session_state.selected_exchanges = [x for x in st.session_state.selected_exchanges if x in exchange_options]

with st.sidebar:
    st.divider()
    st.caption(f"{len(exchange_options)} exchanges available · both trade legs must be selected")
    select_all, clear_all = st.columns(2)
    if select_all.button("Select all", width="stretch"):
        st.session_state.selected_exchanges = exchange_options
    if clear_all.button("Clear all", width="stretch"):
        st.session_state.selected_exchanges = []
    selected_exchanges = st.multiselect(
        "Allowed exchanges", options=exchange_options, key="selected_exchanges",
        format_func=exchange_label,
        help="Every exchange in Bend Basis's catalogue or live opportunities is available. "
             "The original eight venues are selected by default.",
    )
    st.divider()
    sort_label = st.selectbox(
        "Sort results by",
        options=["APR", "Stability", "Asset", "Long exchange", "Short exchange"],
    )
    descending = st.toggle("Highest first", value=True)

selected = set(selected_exchanges)
if selected:
    filtered = opportunities[
        (opportunities["APR"] >= min_apr)
        & (opportunities["Stability"] >= min_stability)
        & (opportunities["_long"].isin(selected))
        & (opportunities["_short"].isin(selected))
    ].copy()
else:
    filtered = opportunities.iloc[0:0].copy()

filtered = filter_asset_group(filtered, asset_group, tradfi_categories)

if asset_search:
    filtered = filtered[
        filtered["Asset"].str.contains(asset_search, case=False, regex=False)
    ]

filtered = filtered.sort_values(
    by=sort_label,
    ascending=not descending,
    kind="stable",
).reset_index(drop=True)

highest_apr = f"{filtered['APR'].max():,.2f}%" if not filtered.empty else "—"
summary_html = f"""
<div class="summary-strip">
    <div class="summary-item">
        <div class="summary-label">Matches</div>
        <div class="summary-value">{len(filtered):,}</div>
    </div>
    <div class="summary-item">
        <div class="summary-label">Highest matching APR</div>
        <div class="summary-value">{highest_apr}</div>
    </div>
    <div class="summary-item">
        <div class="summary-label">Last checked</div>
        <div class="summary-value">{fetched_at}</div>
    </div>
</div>
"""
st.markdown(summary_html, unsafe_allow_html=True)

st.markdown('<div class="table-heading">Current opportunities</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="table-note">Select the checkbox beside a position to compare both markets over the last 30 days. Select any column heading to sort.</div>',
    unsafe_allow_html=True,
)

selected_position = None
if filtered.empty:
    st.info(
        "No opportunities meet every filter right now. Try Select all exchanges, "
        "lower APR or stability, or choose another asset group/category."
    )
else:
    display_columns = [
        "Asset",
        "Asset class",
        "APR",
        "Stability",
        "Long exchange",
        "Short exchange",
    ]
    table_event = st.dataframe(
        filtered[display_columns],
        hide_index=True,
        width="stretch",
        height=min(720, 39 + (len(filtered) * 35)),
        key="opportunity_table_" + sha256(
            repr(list(zip(filtered["_long_market_id"], filtered["_short_market_id"]))).encode()
        ).hexdigest()[:16],
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Asset": st.column_config.TextColumn("Asset", width="small"),
            "Asset class": st.column_config.TextColumn("Asset class", width="small"),
            "APR": st.column_config.NumberColumn(
                "APR", format="%.2f%%", width="small"
            ),
            "Stability": st.column_config.ProgressColumn(
                "Stability",
                format="%.1f%%",
                min_value=0,
                max_value=100,
                width="medium",
            ),
            "Long exchange": st.column_config.TextColumn(
                "Long exchange", width="medium"
            ),
            "Short exchange": st.column_config.TextColumn(
                "Short exchange", width="medium"
            ),
        },
    )
    if table_event.selection.rows:
        selected_row = table_event.selection.rows[0]
        if 0 <= selected_row < len(filtered):
            selected_position = filtered.iloc[selected_row]


st.markdown('<div class="history-rule"></div>', unsafe_allow_html=True)

if selected_position is None:
    st.markdown(
        """
        <div class="history-guide">
            Select any opportunity in the table to open its 30-day funding
            history. The long and short markets will appear together on one chart.
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    asset = str(selected_position["Asset"])
    long_exchange = str(selected_position["Long exchange"])
    short_exchange = str(selected_position["Short exchange"])
    long_market_id = int(selected_position["_long_market_id"])
    short_market_id = int(selected_position["_short_market_id"])

    st.subheader(f"{asset} funding history")
    st.caption(
        f"Long on {long_exchange} compared with short on {short_exchange} · "
        "latest 30 days"
    )

    history_parts: list[pd.DataFrame] = []
    history_errors: list[str] = []
    histories_by_side: dict[str, pd.DataFrame] = {}
    window_end = pd.Timestamp.now(tz="UTC")
    window_start = window_end - pd.Timedelta(days=30)

    with st.spinner("Loading both funding histories…"):
        for side, exchange, market_id in (
            ("Long", long_exchange, long_market_id),
            ("Short", short_exchange, short_market_id),
        ):
            try:
                history = fetch_history(market_id)
            except (requests.RequestException, ValueError, TypeError):
                history_errors.append(f"{side.lower()} market on {exchange}")
                continue

            if history.empty:
                history_errors.append(f"{side.lower()} market on {exchange}")
                continue

            histories_by_side[side] = history
            history = history[
                (history["Time"] > window_start) & (history["Time"] <= window_end)
            ].copy()
            history["Market"] = f"{side} · {exchange}"
            history_parts.append(history)

    if history_parts:
        combined_history = pd.concat(history_parts, ignore_index=True)
        long_label = f"Long · {long_exchange}"
        short_label = f"Short · {short_exchange}"

        rate_lines = (
            alt.Chart(combined_history)
            .mark_line(strokeWidth=2.2)
            .encode(
                x=alt.X(
                    "Time:T",
                    title=None,
                    scale=alt.Scale(
                        domain=[
                            window_start.to_pydatetime(),
                            window_end.to_pydatetime(),
                        ]
                    ),
                    axis=alt.Axis(format="%d %b", labelAngle=0, tickCount=7),
                ),
                y=alt.Y(
                    "APR:Q",
                    title="Funding APR (%)",
                    axis=alt.Axis(format=".1f"),
                ),
                color=alt.Color(
                    "Market:N",
                    title=None,
                    scale=alt.Scale(
                        domain=[long_label, short_label],
                        range=["#087E70", "#B56B13"],
                    ),
                    legend=alt.Legend(orient="top", direction="horizontal"),
                ),
                tooltip=[
                    alt.Tooltip("Market:N", title="Market"),
                    alt.Tooltip("Time:T", title="Funding time", format="%d %b %Y, %H:%M"),
                    alt.Tooltip("APR:Q", title="APR (%)", format=".2f"),
                ],
            )
        )

        chart = (
            rate_lines
            .properties(height=420, width="container")
            .configure_view(stroke=None)
            .configure_axis(
                gridColor="#E5EBF1",
                domainColor="#C9D4DF",
                labelColor="#617087",
                titleColor="#617087",
                tickColor="#C9D4DF",
            )
            .configure_legend(labelColor="#112238", symbolStrokeWidth=3)
        )
        st.altair_chart(chart, theme=None)
        st.caption(
            "History updates after each market publishes its actual funding payout."
        )

        if history_errors:
            st.warning(
                "No history was available for the " + " and ".join(history_errors) + "."
            )
    else:
        st.warning(
            "Bend Basis has not published history for either market in this "
            "30-day window. Select another opportunity to try again."
        )

    st.markdown('<div class="history-rule"></div>', unsafe_allow_html=True)
    st.subheader("30-day funding backtest")
    st.caption(
        "Replays both markets' historical funding payouts · equal long and short "
        "positions · 2× leverage · 0.2% entry + 0.2% exit fees on each leg."
    )
    capital = st.number_input(
        "Capital allocated (USD)",
        min_value=0.0,
        value=10_000.0,
        step=1_000.0,
        format="%.2f",
        help="Total collateral across both venues. Half is allocated to each side "
             "at 2× leverage: $10,000 capital gives a $10,000 long and $10,000 short.",
        key="position_capital",
    )

    if capital <= 0:
        st.info("Enter capital greater than zero to calculate your funding return.")
    else:
        try:
            result = calculate_backtest(
                histories_by_side.get("Long", pd.DataFrame()),
                histories_by_side.get("Short", pd.DataFrame()),
                capital, window_end,
            )
        except HistoryUnavailable as error:
            st.warning(f"A full 30-day backtest is unavailable. {error} "
                       "No missing payouts have been filled with today's rate. "
                       "Try Refresh market data or select another opportunity.")
        else:
            if result.notes:
                st.warning(
                    "Rough historical estimate — payout timing or recent coverage is uncertain. "
                    "This is not a verified 30-day return. See the assumptions below."
                )
                for note in result.notes:
                    st.caption(note)
            result_color = "#087E70" if result.net >= 0 else "#B42318"
            estimate_label = "Estimated " if result.notes else ""
            cards = (
                (f"{estimate_label}Net 30-day funding (after fees)", f"${result.net:,.2f}"),
                (f"{estimate_label}30-day return on capital", f"{result.return_pct:,.2f}%"),
                (f"{estimate_label}Annualised return (simple)", f"{result.annualised_pct:,.2f}%"),
            )
            st.markdown(
                '<div class="return-strip">' + ''.join(
                    f'<div class="return-item"><div class="return-label">{label}</div>'
                    f'<div class="return-value" style="color:{result_color}">{value}</div></div>'
                    for label, value in cards
                ) + '</div>', unsafe_allow_html=True,
            )
            with st.expander("Payouts, fees and calculation details"):
                st.write(
                    f"${capital:,.2f} total collateral → ${capital / 2:,.2f} per venue "
                    f"at 2× leverage → ${result.notional_per_side:,.2f} notional per side."
                )
                st.table(pd.DataFrame({
                    "Component": [f"Long funding · {long_exchange}",
                                  f"Short funding · {short_exchange}",
                                  "Entry fees · both sides", "Exit fees · both sides", "Net return"],
                    "USD": [f"${value:,.2f}" for value in (
                        result.long.funding, result.short.funding,
                        -result.entry_fee, -result.exit_fee, result.net)],
                }))
                st.write(
                    f"Window (UTC): {window_start:%d %b %Y %H:%M} → "
                    f"{window_end:%d %b %Y %H:%M}."
                )
                for side, leg in (("Long", result.long), ("Short", result.short)):
                    intervals = ', '.join(f"{hours:g}h" for hours in leg.intervals_hours)
                    st.caption(
                        f"{side}: {leg.payments:,} history records; inferred intervals {intervals}. "
                        f"First {leg.first:%d %b %H:%M} UTC; last {leg.last:%d %b %H:%M} UTC."
                    )
                st.write(
                    "Each payment = notional × (historical APR ÷ 100) × interval hours "
                    "÷ 8,760. Positive rates are paid by the long and received by the short; "
                    "negative rates reverse those cash flows. Each venue is summed independently. "
                    "Net return subtracts 0.2% entry and 0.2% exit fees from each leg's notional. "
                    "Annualised return = net 30-day return on capital × 365 ÷ 30, without compounding."
                )
    st.caption(
        "Funding-only backtest reconstructed from historical APR, not actual total trading profit. "
        "The API omits settlement durations, so intervals are inferred from payout timestamps "
        "(the first uses the next interval). Includes full inferred payouts after entry through exit. "
        "For irregular histories, the ending historical APR is applied across each gap; "
        "these results are labelled rough estimates. No current APR is substituted, and "
        "no funding is added after the last available timestamp. Assumes fixed equal USD notionals and "
        "1:1 quote-currency/USD value. Excludes price/basis P&L, slippage, collateral changes "
        "and liquidation; assumes both positions remain open throughout. "
        "Coverage checks cannot prove the feed is complete. "
        "Annualisation repeats this net 30-day outcome, including fees; it is not a forecast."
    )

    st.markdown('<div class="history-rule"></div>', unsafe_allow_html=True)
    st.subheader("Venue liquidity")
    st.caption(
        "Current open interest and trailing 24-hour volume, reported in each "
        "market's quote currency. Rows marked ↗ have direct market links."
    )

    try:
        with st.spinner("Loading venue liquidity…"):
            snapshots = fetch_market_snapshots(
                tuple(sorted({long_market_id, short_market_id}))
            )
    except (requests.RequestException, ValueError, TypeError):
        st.warning(
            "Bend Basis could not provide venue liquidity right now. Select "
            "Refresh market data to try again."
        )
    else:
        venue_rows_html: list[str] = []
        for side, exchange, market_id in (
            ("Long", long_exchange, long_market_id),
            ("Short", short_exchange, short_market_id),
        ):
            snapshot = snapshots.get(market_id, {})
            quote_asset = str(snapshot.get("quote_asset") or "quote units").upper()
            market_base = str(snapshot.get("base_asset") or asset).strip().upper()
            venue_slug = str(selected_position["_long" if side == "Long" else "_short"])
            try:
                native_symbols = fetch_venue_symbols(venue_slug).get(quote_asset, [])
            except (requests.RequestException, ValueError, KeyError, TypeError):
                native_symbols = []
            market_url = perpetual_market_url(
                venue_slug, market_base, quote_asset, native_symbols
            )
            row_open = '<div class="venue-row">'
            row_close = '</div>'
            link_icon = ''
            if market_url:
                link_label = escape(
                    f"Open {exchange} {market_base}/{quote_asset} perpetual market in a new tab",
                    quote=True,
                )
                row_open = (
                    f'<a class="venue-row" href="{escape(market_url, quote=True)}" '
                    f'target="_blank" rel="noopener noreferrer" '
                    f'aria-label="{link_label}" title="{link_label}">'
                )
                row_close = '</a>'
                link_icon = '<span class="venue-link-icon" aria-hidden="true">↗</span>'
            open_interest = format_quote_amount(
                snapshot.get("open_interest"), quote_asset
            )
            volume_24h = format_quote_amount(
                snapshot.get("volume_24h"), quote_asset
            )
            venue_rows_html.append(
                row_open +
                f'<div class="venue-identity">'
                f'<span class="venue-side {side.lower()}">{escape(side)}</span>'
                f'<span class="venue-name">{escape(exchange)}</span>'
                f'<span class="venue-market">{escape(market_base)}/{escape(quote_asset)}</span>'
                f'{link_icon}'
                f'</div>'
                f'<div>'
                f'<div class="venue-metric-label">Open interest</div>'
                f'<div class="venue-metric-value">{escape(open_interest)}</div>'
                f'</div>'
                f'<div>'
                f'<div class="venue-metric-label">24h volume</div>'
                f'<div class="venue-metric-value">{escape(volume_24h)}</div>'
                f'</div>' +
                row_close
            )

        st.markdown(
            '<div class="venue-list">' + "".join(venue_rows_html) + "</div>",
            unsafe_allow_html=True,
        )

if skipped_rows:
    st.caption(
        f"Read {total_rows:,} API rows. Ignored {skipped_rows:,} incomplete "
        "or unexpected rows."
    )
else:
    st.caption(f"Read {total_rows:,} API rows from Bend Basis.")

st.caption(
    "APR and stability are supplied by Bend Basis. This scanner is for "
    "research only and is not financial advice."
)
