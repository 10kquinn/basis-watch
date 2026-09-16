"""Offline end-to-end Streamlit checks. Never writes to the real journal."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest
from lab import serial
from research import analyse, Assumptions
from storage import Store
from test_research import history, market, books


class UiTests(unittest.TestCase):
    def test_navigation_research_open_refresh_close_and_locked_ledger(self):
        rows=[dict(base_asset="BTC",apr=40,stability=.9,long_exchange="binance",short_exchange="bybit",long_market_id=1,short_market_id=2)]
        def get(url,**kwargs):
            data={"data":rows,"next_cursor":None}
            if url.endswith("/assets"):data={"data":[{"asset":"BTC","asset_class":"crypto"}]}
            if url.endswith("/exchanges"):data={"data":[{"exchange":v} for v in ["tradexyz","hyperliquid","lighter","binance","bybit","okx","mexc"]]}
            return SimpleNamespace(json=lambda:data,raise_for_status=lambda:None)
        markets=[market(),market("bybit",2)]
        bt=serial(analyse(history(0),history(.001),*markets,Assumptions()))
        run=dict(id="test-run",started_at="2026-09-16T00:00:00Z",finished_at="2026-09-16T00:00:10Z",assumptions=bt["assumptions"],results=[dict(asset="BTC",long="binance",short="bybit",long_id=1,short_id=2,markets=markets,backtest=bt)])
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{"LEDGER_PASSWORD":"test-private-password", "LEDGER_DB_PATH":str(Path(tmp)/"ledger.sqlite3")}), patch("requests.get",side_effect=get), patch("research_ui.scan",return_value=run), patch("paper.pair_books",return_value=books()), patch("paper.load_history",return_value=history(count=3)):
            st.cache_data.clear()
            app=AppTest.from_file(str(Path(__file__).parent/"app.py")).run(timeout=20)
            self.assertFalse(app.exception)
            self.assertEqual(len(app.multiselect(key="selected_exchanges").options),6)
            app.radio(key="workspace_page").set_value("Research lab").run()
            self.assertFalse(app.exception)
            app.text_input(key="journal_password").set_value("test-private-password").run()
            next(b for b in app.button if b.label=="Run research").click().run(timeout=20)
            self.assertFalse(app.exception)
            self.assertTrue(any("0 research candidates" in s.value for s in app.subheader))
            app.text_area[0].set_value("Seven-day paper experiment; close if carry flips").run()
            next(c for c in app.checkbox if "manual paper" in c.label).check().run()
            next(b for b in app.button if b.label=="Open paper trade").click().run()
            self.assertFalse(app.exception)
            store=Store(Path(tmp)/"ledger.sqlite3")
            self.assertEqual(len(store.records("trade")),1)
            app.radio(key="workspace_page").set_value("Paper ledger").run()
            app.text_input(key="journal_password").set_value("test-private-password").run()
            self.assertFalse(app.exception)
            self.assertTrue(app.dataframe)
            next(b for b in app.button if b.label=="Refresh all open trades").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(store.records("valuation")),1)
            # Wrong password must not reveal private tables or exports.
            app.text_input(key="journal_password").set_value("wrong").run()
            self.assertFalse(app.dataframe)
            self.assertFalse(app.get("download_button"))


if __name__ == "__main__":unittest.main()
