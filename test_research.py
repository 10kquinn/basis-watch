import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import pandas as pd

from research import Assumptions, analyse, prepare, shared_prices, replay, multiplier, validate_pair, walk_forward
from execution import vwap, entry, live_estimate
from storage import Store
from paper import archive_history, funding_total, open_trade, refresh_trade, trade_rows


def market(venue="binance", identifier=1, symbol="BTCUSDT", base="BTC"):
    return dict(exchange=venue, market_id=identifier, symbol=symbol, base_asset=base, quote_asset="USDT",
                funding_interval=8, funding_rate_apr={"live":10})


def history(rate=.0001, prices=100, count=91, freq="8h"):
    index = pd.date_range("2026-08-15", periods=count, freq=freq, tz="UTC")
    return pd.DataFrame({"Time": index, "Funding rate": rate, "Mark price": prices, "Funding interval":pd.Timedelta(freq).total_seconds()/3600, "APR": 0})


def books():
    return [dict(bids=[(100, 10000)], asks=[(100.01, 10000)], mid=100.005, observed_at="2026-09-16T01:00:00Z"),
            dict(bids=[(100.1, 10000)], asks=[(100.11, 10000)], mid=100.105, observed_at="2026-09-16T01:00:00Z")]


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.markets = [market(), market("bybit", 2)]
        self.settings = Assumptions(slippage=0)

    def test_fee_and_rate_units(self):
        result = analyse(history(0), history(.001), *self.markets, self.settings)["summary"]
        self.assertAlmostEqual(result["funding"], 900)
        self.assertAlmostEqual(result["fees"], 80)
        self.assertAlmostEqual(result["net"], 820)

    def test_price_divergence_can_overwhelm_funding(self):
        h = history(.00001)
        h["Mark price"] = [100+i*.1 for i in range(len(h))]
        result = analyse(history(0), h, *self.markets, self.settings)["summary"]
        self.assertAlmostEqual(result["price_pnl"], -900)
        self.assertLess(result["net"],0)

    def test_quantity_mark_rate_not_fixed_notional(self):
        h = history(.001, prices=[100,110,110], count=3)
        result = analyse(history(0,count=3),h,*self.markets,self.settings)["summary"]
        self.assertAlmostEqual(result["funding"],22)
        self.assertAlmostEqual(result["price_pnl"],-1000)

    def test_bundles_and_different_funding_schedules(self):
        left = market(symbol="1000PEPEUSDT", base="PEPE")
        right = market("hyperliquid",2,symbol="kPEPE",base="PEPE")
        self.assertEqual(multiplier(left),1000)
        self.assertEqual(multiplier(right),1000)
        a = history(0,prices=.01,count=4)
        b = history(.001,prices=.01,count=25,freq="1h")
        result=analyse(a,b,left,right,self.settings)["summary"]
        self.assertAlmostEqual(result["funding"],240)
        self.assertAlmostEqual(result["days"],1)

    def test_no_future_or_stale_price_alignment(self):
        a,b=history(),history()
        b.Time += pd.Timedelta(minutes=5)
        with self.assertRaisesRegex(ValueError,"shared mark"):
            analyse(a,b,*self.markets,self.settings)

    def test_missing_price_and_conflicting_duplicate_fail(self):
        h=history();h.loc[2,"Mark price"]=None
        with self.assertRaisesRegex(ValueError,"missing"):
            analyse(h,history(),*self.markets,self.settings)
        h=history(); duplicate=h.iloc[[1]].copy();duplicate["Funding rate"] = .2
        with self.assertRaisesRegex(ValueError,"Conflicting"):
            analyse(pd.concat([h,duplicate]),history(),*self.markets,self.settings)

    def test_gap_visible_not_invented(self):
        h=history().drop(index=[5,6,7])
        result=analyse(h,history(),*self.markets,self.settings)["summary"]
        self.assertTrue(result["notes"])

    def test_walkforward_future_does_not_change_signal_or_entry(self):
        a,b=prepare(history(0),self.markets[0]),prepare(history(.001),self.markets[1])
        prices=shared_prices(a,b)
        before=walk_forward(a,b,prices,self.settings,3)
        b.loc[b.index>pd.Timestamp(before[0]["Entry"]),"Funding rate"]=-.01
        after=walk_forward(a,b,prices,self.settings,3)
        self.assertEqual(before[0]["Entry"],after[0]["Entry"])
        self.assertEqual(before[0]["Signal return %"],after[0]["Signal return %"])
        self.assertLess(after[0]["Net P&L"],0)
        for i in range(1,len(before)):
            self.assertGreaterEqual(before[i]["Entry"],before[i-1]["Exit"])

    def test_cost_and_margin_stress(self):
        normal=analyse(history(0),history(.001),*self.markets,self.settings)["summary"]
        costly=analyse(history(0),history(.001),*self.markets,Assumptions(fee=.01,slippage=.01))["summary"]
        self.assertLess(costly["net"],normal["net"])
        h=history(prices=[100-i*.7 for i in range(91)])
        result=analyse(h,h,*self.markets,self.settings)["summary"]
        self.assertTrue(result["margin_alert"])

    def test_bad_pair(self):
        for m in (dict(self.markets[1],quote_asset="BTC"),dict(self.markets[1],exchange="mexc"),dict(self.markets[1],base_asset="ETH")):
            with self.assertRaises(ValueError):validate_pair(self.markets[0],m)


class ExecutionTests(unittest.TestCase):
    def test_vwap_walks_depth_and_rejects_partial_fill(self):
        self.assertAlmostEqual(vwap([(100,1),(102,1)],2),101)
        with self.assertRaises(ValueError):vwap([(100,1)],2)

    def test_equal_quantity_sizing_and_live_stress(self):
        q,lp,sp=entry(books(),Assumptions())
        self.assertLessEqual(q*max(lp,sp),10000.00001)
        ms=[market(),dict(market("bybit",2),funding_rate_apr={"live":100})]
        result=live_estimate(ms,books(),Assumptions())
        self.assertLess(result["stressed_net"],result["projected_net"])
        self.assertGreater(result["round_trip_cost"],79)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/"journal.sqlite3"
        self.store=Store(self.path)
        self.markets=[market(),market("bybit",2)]

    def tearDown(self):self.tmp.cleanup()

    def test_restart_idempotent_and_immutable(self):
        self.store.put("trade","a",{"x":1})
        self.store.put("trade","a",{"x":2})
        self.assertEqual(Store(self.path).records("trade")[0]["payload"],{"x":1})
        with self.assertRaises(ValueError):self.store.put("trade","b",{"x":float("nan")})

    def test_dedup_and_provider_correction(self):
        h=history(count=3)
        archive_history(self.store,self.markets[0],h)
        archive_history(self.store,self.markets[0],h)
        self.assertEqual(len(self.store.records("funding")),3)
        h.loc[1,"Funding rate"] = .9
        with self.assertRaisesRegex(ValueError,"revised"):
            archive_history(self.store,self.markets[0],h)

    def test_paper_open_refresh_close_and_restart(self):
        t=pd.Timestamp("2026-08-15T00:01:00Z")
        with patch("paper.pair_books",return_value=books()),patch("paper.utc",side_effect=lambda value=None: pd.Timestamp(value) if value else t):
            trade=open_trade(self.store,self.markets,Assumptions(),"Exit after seven days",identifier="test")
        t=pd.Timestamp("2026-08-15T16:01:00Z")
        with patch("paper.pair_books",return_value=books()),patch("paper.load_history",return_value=history(count=3)),patch("paper.utc",side_effect=lambda value=None: pd.Timestamp(value) if value else t):
            first=refresh_trade(self.store,trade)
            second=refresh_trade(self.store,trade)
            self.assertAlmostEqual(first["net"],second["net"])
            self.assertAlmostEqual(first["funding"],0)
            final=refresh_trade(self.store,trade,close=True)
            self.assertTrue(final["closed"])
            with self.assertRaisesRegex(ValueError,"already closed"):refresh_trade(self.store,trade)
        _,rows=trade_rows(Store(self.path))
        self.assertEqual(rows[0]["Status"],"Closed")
        self.assertLess(rows[0]["Net P&L"],-79)

    def test_outage_over_retention_is_flagged(self):
        trade=dict(opened_at="2026-01-01T00:00:00Z",quantity=1,markets=self.markets)
        for m in self.markets:archive_history(self.store,m,history(count=3))
        totals,notes,rows=funding_total(self.store,trade,pd.Timestamp("2026-08-16T00:00:00Z"))
        self.assertTrue(notes)


if __name__ == "__main__":unittest.main()
