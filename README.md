# Basis Watch

Basis Watch turns the Bend Basis funding arbitrage feed into a clean local
website. It uses the live public endpoint and the current `apr` response field.

The default filters match the original scanner:

- Minimum APR: 15%
- Minimum stability: 80%
- Initially selected exchanges: Kraken, OKX, Lighter, Hyperliquid, dYdX, Binance,
  Bybit, Coinbase International (`coinbase_intx` in the current feed)
- Both the long and short exchange must be in the allowed list

## Fastest way to run it on a Mac

1. Install Python 3 from [python.org](https://www.python.org/downloads/) if it
   is not already installed.
2. Open **Terminal** (press Command + Space, type `Terminal`, then press Return).
3. Type `cd `, including the space, then drag this `outputs` folder into the
   Terminal window and press Return.
4. Copy and run these commands one at a time:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python3 -m pip install -r requirements.txt
   python3 -m streamlit run app.py
   ```

5. Your browser should open automatically at
   [http://localhost:8501](http://localhost:8501).

Keep the Terminal window open while using the site. To stop it, return to
Terminal and press **Control + C**.

## Run it again later

Open Terminal, return to the `outputs` folder as described above, then run:

```bash
source .venv/bin/activate
python3 -m streamlit run app.py
```

## Using the site

- Change APR, stability, exchanges, or asset search in the left sidebar.
- Use **Asset group → TradFi** for stocks, ETFs, indices, commodities, forex and
  other TradFi-linked derivatives. **Crypto** includes provider-classified crypto;
  **All** also includes unclassified assets. You can narrow TradFi by category.
- The exchange selector includes the full live Bend Basis exchange catalogue,
  plus any additional venues present in the opportunity feed. **Select all**
  enables every venue; **Clear all** removes them. Both legs must be selected.
  Venue names are preserved separately (including HIP-3 and other sub-venues).
- Asset classifications come from `https://api.bendbasis.com/v1/assets`; exchange
  IDs come from `https://api.bendbasis.com/v1/exchanges`. Both catalogues are cached
  for one hour and cleared by **Refresh market data**. No ticker-name guesses are
  used: for example, SPX remains crypto while SP500 is an index. If classification
  data fails, All remains usable and a warning explains the missing categories.
  If the exchange catalogue fails, every venue in the opportunity feed remains
  selectable. Choosing TradFi does not silently relax APR, stability or venues.
- Select the checkbox beside any opportunity to open a chart comparing the
  long and short markets' funding APR over the latest 30 days.
- Both market histories are overlaid on the same time axis; hover over either
  line to inspect an individual funding observation.
- Enter total collateral below the chart to replay historical funding over the
  longest period both markets actually cover within the last 30 days. The panel
  states the tested period and shows net funding after fees, return on capital,
  and the simple annualised return. It does not use the current spread APR.
- Compare current open interest and trailing 24-hour volume for the long and
  short venues. Liquidity values use each market's reported quote currency.
- Click a liquidity row marked ↗ to open that perpetual market in a new tab.
  Direct market links support the original eight exchanges, including Binance USD1/USDC and
  Bybit USDC contracts. Native symbol catalogues are cached for one hour to
  resolve multiplier contracts such as 1000PEPE and Hyperliquid's kPEPE.
  If a native catalogue is unavailable, the link uses the standard market
  path. Markets removed by a venue may no longer open even if the feed lists them.
  Other exchanges support opportunity selection, history, backtesting and liquidity
  wherever Bend Basis supplies that data; their rows stay unlinked until a direct
  market URL is supported.
- Use **Sort results by**, or select a table column heading to sort.
- Select **Refresh market data** for a fresh API request. Data is otherwise
  refreshed at most once per minute.
- If there are no matches, lower the stability threshold or allow more
  exchanges. An 80% stability requirement is deliberately strict.

## How the funding backtest works

- Capital is split equally between venues at 2× leverage per side. $10,000 total
  collateral means $5,000 collateral and $10,000 notional on each side.
- Each historical payment is reconstructed as notional × historical APR / 100 ×
  funding interval hours / 8,760. Positive rates cost the long and pay the short;
  negative rates reverse this. Each venue is summed independently, so different
  funding schedules do not discard or duplicate payments.
- **The tested period is the overlap of both histories, not a fixed 30 days.**
  Each market's history is split at gaps longer than 24 hours, and the backtest
  uses the longest continuous range both markets cover inside the rolling 30-day
  UTC window; equally long ranges resolve to the more recent one. Both legs are
  replayed over that same period, and the panel states its start, end and length.
  Nothing is extrapolated to fill the rest of 30 days. A pair whose venues only
  overlap for three days is reported as a three-day result.
- Venues are not required to fund on the same schedule or at matching timestamps;
  the overlap is computed from coverage ranges, so hourly and 8-hourly markets
  can be compared.
- The history endpoint supplies timestamps and annualised rates, not settlement
  durations. Durations are inferred from successive timestamps; the first uses
  the next observed interval. Repeated schedule changes are supported. Ambiguous
  isolated intervals produce a **rough historical estimate**: the APR at the
  end of each gap is applied over that gap. This may overstate or understate
  funding if records are missing; it is not a verified realised return.
- A backtest still requires valid rates, no conflicting duplicate records, and at
  least one payout for each leg inside the shared period. Coverage checks cannot
  prove every payout is present.
- Includes full payouts strictly after the shared start through the shared end,
  with no accrued funding beyond the last payout. A leg entering part-way through
  an interval still pays that interval in full, as exchanges settle it.
- Entry costs 0.2% of each leg's notional; exit costs another 0.2% each. On
  $10,000 capital this totals $40 entry + $40 exit = $80 (0.8% of capital).
  Round-trip fees are the same regardless of how short the tested period is.
- Net return = long funding + short funding − entry and exit fees.
  Return on capital = net return / capital. Simple annualised return = return on
  capital × 365 ÷ the actual tested days; no compounding. Annualisation repeats
  the net outcome including round-trip fees, and is not a forecast. Short tested
  periods annualise very aggressively, because fixed fees are scaled up with the
  funding; periods under a day are flagged in the app for this reason.
- This is a **funding-only historical backtest**, not actual total trading profit.
  Fixed equal USD notionals and 1:1 quote-currency/USD conversion are assumed.
  Price/basis P&L, collateral changes, slippage and liquidation are not simulated.
  Results are conditional on the position remaining open throughout the window.

The chart always shows the last 30 days; the backtest covers the shared period
within it. Both share the same cached histories. Use
**Refresh market data** to fetch fresh data. Keep `backtest.py` and `market_filters.py`
alongside `app.py`. To check calculations and filters locally:
`python3 -m unittest test_backtest.py test_market_filters.py`.

## Troubleshooting

If `python3` is not found, install Python 3 and reopen Terminal. If the page does
not open automatically, visit [http://localhost:8501](http://localhost:8501)
manually. If the app reports that Bend Basis cannot be reached, check the Mac's
internet connection and use **Refresh market data**.

## Share it online

The app uses public market APIs and does not require exchange API keys. A public
GitHub repository exposes the application source; a public deployment allows
anyone with the address to view the dashboard. Do not add account credentials,
private trading data, or `.streamlit/secrets.toml` to the repository.

### Railway

1. In Railway, create a project and select **Deploy from GitHub repo**.
2. Select this repository. Its root should contain `app.py` and `Dockerfile`.
3. Railway builds the Python image and runs the calculation tests before starting
   the app. The app listens on Railway's assigned `PORT`.
4. In the service's **Settings → Networking**, generate a public domain.
5. Share the resulting HTTPS address with your coworker.

No database, volume, or environment secrets are needed. Keep Streamlit's default
security protections enabled. Railway hosting can incur usage charges; review
your plan and configure spending alerts in your account. GitHub-connected
services can redeploy when you push updates to the selected branch.

### Streamlit Community Cloud (free alternative)

1. Sign in at [Streamlit Community Cloud](https://share.streamlit.io/) with GitHub.
2. Create an app from this repository, branch `main`, main file `app.py`.
3. Choose Python 3.12 in advanced settings and deploy.
4. Share the generated app address. No secrets are required.

### Container testing (optional)

With Docker installed, run these from the repository folder:

```bash
docker build -t basis-watch .
docker run --rm -p 8501:8501 basis-watch
```

Then open [localhost:8501](http://localhost:8501). The container runs as a non-root
user and includes only the app, configuration, dependencies, and calculation tests.
