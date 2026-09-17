# Basis Watch

Basis Watch turns the Bend Basis funding arbitrage feed into a clean local
website. It uses the live public endpoint and the current `apr` response field.

The app uses `https://api.bendbasis.com/v1` (the old `bendbasis.com/api/v1/public`
routes are retired). Arbitrage requests follow every `next_cursor` page, with a
15-day spread window and up to 500 rows per page. A failed page stops the load
rather than silently presenting an incomplete opportunity list. History uses
`/funding/history/{market_id}` with explicit 30-day `from`/`to` timestamps and
`resolution=event`; liquidity uses `/markets/{market_id}`.

The default filters match the original scanner:

- Minimum APR: 15%
- Minimum stability: 80%
- Research universe and initially selected exchanges: TradeXYZ (`tradexyz`),
  Hyperliquid, Lighter, Binance, Bybit and OKX
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
- The exchange selector is limited to the six research venues. **Select all**
  enables these venues; **Clear all** removes them. Both legs must be selected.
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
- Each historical payment is calculated as notional × settled funding rate
  (decimal). Positive rates cost the long and pay the short;
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
- The current history endpoint supplies settled rates and funding intervals.
  The chart converts rates to APR as rate × 100 × 8,760 / interval hours.
  Missing intervals omit that event from the APR chart, but its settled rate
  remains usable by the backtest. Backtesting sums settled rates directly and
  never multiplies them by inferred gaps. Null funding rates are excluded with
  a completeness note; missing payments are not filled with today's rate.
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
**Refresh market data** to fetch fresh data. Keep `backtest.py`, `bend_api.py` and `market_filters.py`
alongside `app.py`. To check calculations and filters locally:
`python3 -m unittest test_backtest.py test_market_filters.py test_bend_api.py`.

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
4. Attach one persistent volume at `/app/data`. Use one service/replica: the
   website and recorder share SQLite on this disk, not separate services.
5. Set service variables `LEDGER_DB_PATH=/app/data/basis-watch.sqlite3`,
   `RAILWAY_RUN_UID=0`, `RECORDER_ENABLED=1`, `RECORDER_INTERVAL=900` and a strong
   private `LEDGER_PASSWORD`. The launcher initializes volume permissions then
   drops root privileges before starting either process. No Supabase is needed.
6. Disable serverless/sleeping so recording continues with no browser open.
   Enable daily volume backups and account spending alerts. A volume survives
   redeployment, but is not itself a backup. Never delete it to redeploy.
7. In **Settings → Networking**, generate a public domain and share its HTTPS
   address. Give the journal password only to trusted coworkers.

The launcher stops both processes if either exits, allowing Railway to restart
them together. Recording updates only existing paper trades; it never sends real
orders. New deployments have a brief interruption while the volume moves. Local
research records are not uploaded automatically; export/import them separately
if required. A missing volume blocks startup rather than silently losing data.

The public scanner needs no secrets. The private journal needs the database and
password configuration below. Keep Streamlit's default
security protections enabled. Railway hosting can incur usage charges; review
your plan and configure spending alerts in your account. GitHub-connected
services can redeploy when you push updates to the selected branch.

### Streamlit Community Cloud (free alternative)

1. Sign in at [Streamlit Community Cloud](https://share.streamlit.io/) with GitHub.
2. Create an app from this repository, branch `main`, main file `app.py`.
3. Choose Python 3.12 in advanced settings and deploy.
4. Share the generated app address. The scanner works without secrets; configure
   the journal below before relying on hosted persistence.

## Research lab: funding plus price divergence

Choose **Research lab** above the scanner. The sidebar's asset, APR, stability and
six-venue filters apply. Set capital (default $10,000), fee per leg per transaction
(default 0.2%), historical slippage per fill (default 0.05%) and how many pairs to
check (default 12; maximum 100). **Run research** fetches each unique market once.
If the strict 80% stability filter returns too few candidates, explicitly lower it
in the sidebar; the application never silently relaxes your filters.

The research replay differs from the scanner's legacy funding-only panel:

- Equal **underlying quantity**, fixed through the trade, with at most 2x leverage
  on each half of collateral. Different prices mean slightly different notionals.
- Native bundle contracts such as 1000PEPE/kPEPE are converted into common units.
  Only USDT/USDC linear perps are included, assuming both stablecoins equal $1.
  Prices differing by over 20% are rejected for contract/data review.
- Funding is quantity × the mark price at each settlement × the decimal rate,
  negative for the long and positive for the short. Each venue's events are
  summed separately even when schedules differ.
- Price P&L uses simultaneous mark timestamps shared by both markets; no stale
  8-hour mark is passed off as a current price. No future interpolation. Entry
  and exit marks include adverse slippage; fees are charged on actual simulated
  entry/exit notionals. These prices are estimates, NOT historical bid/ask fills.
- The longest available shared span inside the last 30 days is displayed.
  Detected payout gaps remain flagged and disqualify a research candidate; no
  payout is invented. Missing marks/rates can make total-P&L replay unavailable.
- Two fixed timing rules use trailing 1-day or 3-day settled funding to predict
  whether a 7-day hold covers a four-fill cost hurdle. Only completed subsequent
  holds are scored; holds within each pair/rule do not overlap. No parameter
  optimisation. Today's pair selection still creates selection/survivorship bias.
- Current projections use the venue's public book depth for the intended size,
  both opening and hypothetical immediate closing prices, plus fees. There is
  no double-counting of the spread as extra slippage. Insufficient depth or stale
  quotes fail explicitly. Rates and prices are assumed constant for seven days.
- A stress column halves funding and adds a 1% adverse basis movement on one
  leg's notional. This is a scenario, not a forecast or confidence interval.
- A **Research candidate** needs positive historical hold net, positive current
  projection and at least one positive timing rule, with no detected coverage or
  sampled-margin alert. It is NOT a proven profitable strategy. Negative and
  excluded results remain visible. Different pairs/rules are separate experiments,
  not one finite-capital portfolio backtest.

The system does not model contract lot-size rounding/minimum orders, exchange-specific liquidation/maintenance tiers,
intraperiod price paths, ADL, depegs, transfers, borrowing or rebalancing. Mark
samples can miss liquidation. The 10% leg-equity/notional alert is only a coarse
warning. TradeXYZ and Hyperliquid also share infrastructure; do not treat them as
independent operational risks. The app never places real orders.

Public data sources: [Bend Basis](https://docs.bendbasis.com/),
[Binance](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Order-Book),
[Bybit](https://bybit-exchange.github.io/docs/v5/market/orderbook),
[OKX](https://www.okx.com/docs-v5/en/),
[Hyperliquid / TradeXYZ](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint),
and Lighter's public `https://mainnet.zklighter.elliot.ai/api/v1/orderBookOrders`.
Regional exchange API blocks are not bypassed: those pairs are marked unavailable.

## Persistent paper trading

### Local Mac: no external database account needed

Create `.streamlit/secrets.toml` beside `.streamlit/config.toml`, with a strong,
unique journal password (do not commit it):

```toml
LEDGER_PASSWORD = "replace-with-a-long-random-private-password"
```

Run the app normally. Unlock **Research lab → Save research / unlock paper
trading** with that password. Scans then save their assumptions, filtered universe,
raw history archive, simulated cashflows and current order books. **Load latest
saved research** restores a previous run after restarting.

Inspect a pair, write an entry reason and exit rule, acknowledge the limitations,
then **Open paper trade**. This fetches fresh books and saves fixed quantities and
entry prices. No trades are opened automatically by a research scan.

In **Paper ledger**, unlock the same private journal, then **Refresh all open
trades** to archive settled funding and append close-at-current-book valuations.
Each valuation includes funding, price P&L, all four trading fees and per-leg equity.
**Close paper trade** saves a final immutable result. Missing funding prevents a
final close; refresh/reconcile rather than silently claiming a complete profit.

The SQLite database defaults to `data/basis-watch.sqlite3` next to `app.py`. It
survives local restarts, but not deletion of that folder. Use **Prepare full journal
export → Download journal backup** for a portable JSON audit backup. The database,
secrets and exports must stay out of public GitHub. Entries and cashflow records
are insert-only; provider revisions are reported rather than rewriting history.

### Streamlit Cloud: add durable Supabase storage

Streamlit's local disk is NOT a durable database. Without Supabase the app shows
an explicit warning: hosted records may disappear on a redeploy/restart.

1. Create/use your own Supabase project (review its current free-plan limits).
2. Run `supabase.sql` in its SQL editor. The table has RLS enabled and grants no
   access to anonymous or signed-in browser clients. Only server-side read/insert
   access is enabled. No public policies are needed.
3. In Streamlit app settings → Secrets, add:

   ```toml
   LEDGER_PASSWORD = "your-long-random-private-password"
   SUPABASE_URL = "https://your-project.supabase.co"
   SUPABASE_SERVICE_ROLE_KEY = "your-server-side-service-role-or-sb_secret-key"
   ```

4. Save/restart, unlock the journal and confirm it says **Supabase · durable shared
   storage**. Share only the journal password with your coworker, not database keys.

Never paste keys into chat, source control or a public form. This is a simple
shared-password journal, not multi-user identity management. Use a long random
password and Streamlit app-level access restrictions where available. Existing
local records do not automatically migrate when you switch databases.

### Collect over time

By default updates are MANUAL. Streamlit Cloud sleeps; leaving the app deployed
does not create a background recorder. Funding can be caught up within the API's
30-day event retention, but missed quotes and intraperiod margin states cannot.

From the project directory, on a machine that stays awake:

```bash
source .venv/bin/activate
python recorder.py                 # one refresh of all open paper trades
python recorder.py --interval 900  # refresh every 15 minutes; Ctrl+C stops
```

The recorder uses the same secrets/database. With Supabase it writes the same
journal the hosted app reads. It only refreshes existing paper trades, never opens
or closes positions. No background process or paid hosting is automatically
enabled. For 24/7 recording, choose an always-on runner separately. If collection
stops for over 30 days, unavailable funding stays flagged rather than fabricated.

Run all tests: `python -m unittest discover -v`.

### Container testing (optional)

With Docker installed, run these from the repository folder:

```bash
docker build -t basis-watch .
docker run --rm -p 8501:8501 basis-watch
```

Then open [localhost:8501](http://localhost:8501). The container runs as a non-root
user and includes only the app, configuration, dependencies, and calculation tests.
