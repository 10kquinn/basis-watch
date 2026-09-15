import unittest
from unittest.mock import patch
import pandas as pd
import requests

from bend_api import load_opportunities, load_history, load_market_snapshots, normalize_events, request_error_message
from backtest import calculate_backtest


class ApiTests(unittest.TestCase):
    def test_pagination_preserves_query_and_deduplicates(self):
        a = {"long_market_id": 1, "short_market_id": 2}
        b = {"long_market_id": 3, "short_market_id": 4}
        with patch("bend_api.get_json", side_effect=[{"data": [a], "next_cursor": "opaque"}, {"data": [a,b], "next_cursor": None}]) as call:
            self.assertEqual(load_opportunities(), [a,b])
            self.assertEqual(call.call_args_list[1].kwargs["params"],
                             {"limit":500, "window":15, "sort":"apr", "order":"desc", "cursor":"opaque"})

    def test_incomplete_pagination_fails_instead_of_partial_results(self):
        for payload in [{"data":[]}, {"data":[], "next_cursor":"repeat"}, []]:
            with patch("bend_api.get_json", return_value=payload):
                with self.assertRaises(ValueError):
                    load_opportunities()

    def test_later_page_http_failure_is_not_silently_ignored(self):
        with patch("bend_api.get_json", side_effect=[{"data":[], "next_cursor":"a"}, requests.HTTPError("429")]):
            with self.assertRaises(requests.HTTPError):
                load_opportunities()

    def test_explicit_30_day_event_window(self):
        end = pd.Timestamp("2026-09-15T10:00:00Z")
        with patch("bend_api.get_json", return_value={"data":[]}) as call:
            self.assertTrue(load_history(123,end).empty)
            args = call.call_args.args
            self.assertEqual(args[0], "/funding/history/123")
            self.assertEqual(args[1]["resolution"], "event")
            self.assertEqual(pd.Timestamp(args[1]["to"]) - pd.Timestamp(args[1]["from"]), pd.Timedelta(days=30))

    def test_settled_rate_units_and_null_interval(self):
        points = [{"funding_time":f"2026-09-14T{hour:02d}:00:00Z", "funding_rate":"0.0001", "funding_interval":interval}
                  for hour,interval in [(0,8),(8,8),(16,None)]]
        history = normalize_events({"data":points})
        self.assertAlmostEqual(history.APR.iloc[0],10.95)
        self.assertTrue(pd.isna(history.APR.iloc[-1]))
        zero = history.copy(); zero["Funding rate"] = 0
        result = calculate_backtest(zero,history,10000,pd.Timestamp("2026-09-15T00:00Z"))
        self.assertAlmostEqual(result.short.funding,2)  # two payouts at $1 each, no 100x error
        self.assertAlmostEqual(result.net,-78)

    def test_missing_rate_is_not_zero_or_filled(self):
        data = [{"funding_time":f"2026-09-14T{h:02d}:00:00Z", "funding_rate":r, "funding_interval":1}
                for h,r in [(0,"0.0001"),(1,None),(2,"0.0002")]]
        history = normalize_events({"data":data})
        self.assertEqual(len(history),2)
        result = calculate_backtest(history,history,10000,pd.Timestamp("2026-09-15T00:00Z"))
        self.assertAlmostEqual(result.short.funding,2)
        self.assertTrue(result.notes)

    def test_market_envelope_and_ids(self):
        with patch("bend_api.get_json", return_value={"data":{"market_id":123,"open_interest":500}}):
            self.assertEqual(load_market_snapshots([123,123])[123]["open_interest"],500)
            with self.assertRaises(ValueError):
                load_market_snapshots([456])

    def test_http_error_explanation(self):
        response = requests.Response(); response.status_code = 404
        error = requests.HTTPError(response=response)
        self.assertIn("API-address problem",request_error_message(error))
        response.status_code=429
        self.assertIn("rate-limiting",request_error_message(error))


if __name__ == "__main__":
    unittest.main()
