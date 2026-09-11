import unittest
import pandas as pd

from market_filters import asset_classes, available_exchanges, exchange_ids, filter_asset_group, TRADFI_CLASSES


class MarketFilterTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({
            "Asset": ["BTC", "TSLA", "XAU", "EURUSD", "SP500", "SPY", "NEW"],
            "_asset_class": ["crypto", "equity", "commodity", "fx", "index", "etf", "unknown"],
            "_long": ["binance"] * 7,
            "_short": ["bybit"] * 6 + ["brand_new_venue"],
        })

    def test_tradfi_includes_each_traditional_class(self):
        actual = filter_asset_group(self.frame, "TradFi", TRADFI_CLASSES)
        self.assertEqual(list(actual.Asset), ["TSLA", "XAU", "EURUSD", "SP500", "SPY"])

    def test_crypto_and_unknown_remain_distinct(self):
        self.assertEqual(list(filter_asset_group(self.frame, "Crypto", []).Asset), ["BTC"])
        self.assertEqual(len(filter_asset_group(self.frame, "All", [])), 7)

    def test_selected_categories_and_empty_selection(self):
        self.assertEqual(list(filter_asset_group(self.frame, "TradFi", ["equity"]).Asset), ["TSLA"])
        self.assertTrue(filter_asset_group(self.frame, "TradFi", []).empty)

    def test_catalogue_classes_do_not_guess_from_tickers(self):
        parsed = asset_classes({"data": [
            {"asset": "spx", "asset_class": "crypto"},
            {"asset": "SP500", "asset_class": "index"},
            {"asset": "NEW", "asset_class": "new_category"}, None,
        ]})
        self.assertEqual(parsed, {"SPX": "crypto", "SP500": "index", "NEW": "unknown"})

    def test_exchange_catalogue_and_feed_are_unioned(self):
        self.assertEqual(available_exchanges(self.frame, ["kraken", "coinbase_intx"]),
                         ["binance", "brand_new_venue", "bybit", "coinbase_intx", "kraken"])
        self.assertIn("brand_new_venue", available_exchanges(self.frame, []))

    def test_exchange_payload_validation(self):
        self.assertEqual(exchange_ids({"data": [{"exchange": "Bybit"}, {"exchange": "bybit"}, None]}), ["bybit"])
        for parser in [asset_classes, exchange_ids]:
            with self.assertRaises(ValueError):
                parser([])


if __name__ == "__main__":
    unittest.main()
