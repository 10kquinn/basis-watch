import unittest

import pandas as pd

from backtest import HistoryUnavailable, calculate_backtest


END = pd.Timestamp("2026-09-10T00:30:00Z")


def history(apr, hours=1):
    return pd.DataFrame({
        "Time": pd.date_range("2026-08-11", "2026-09-10", freq=f"{hours}h", tz="UTC"),
        "APR": float(apr),
    })


class BacktestTests(unittest.TestCase):
    def test_known_return_and_fees(self):
        result = calculate_backtest(history(10), history(30, 4), 10000, END)
        self.assertAlmostEqual(result.net, 10000 * .2 * 30 / 365 - 80)
        self.assertEqual(result.entry_fee, 40)
        self.assertEqual(result.exit_fee, 40)
        self.assertEqual(result.notional_per_side, 10000)
        self.assertAlmostEqual(result.return_pct, .843835616438356)
        self.assertAlmostEqual(result.annualised_pct, 10.2666666666667)
        self.assertEqual(result.long.payments, 720)
        self.assertEqual(result.short.payments, 180)

    def test_equal_rates_different_cadences(self):
        result = calculate_backtest(history(20), history(20, 8), 10000, END)
        self.assertAlmostEqual(result.net, -80)
        self.assertAlmostEqual(result.return_pct, -.8)

    def test_negative_rates_reverse_cashflows_and_scale(self):
        result = calculate_backtest(history(-20), history(-10, 4), 10000, END)
        doubled = calculate_backtest(history(-20), history(-10, 4), 20000, END)
        self.assertGreater(result.long.funding, 0)
        self.assertLess(result.short.funding, 0)
        self.assertAlmostEqual(doubled.net, result.net * 2)
        self.assertAlmostEqual(doubled.return_pct, result.return_pct)

    def test_sort_and_exact_duplicates(self):
        original = history(10)
        shuffled = pd.concat([original.iloc[::-1], original.iloc[10:11]])
        self.assertEqual(calculate_backtest(original, history(20), 10000, END),
                         calculate_backtest(shuffled, history(20), 10000, END))

    def test_future_and_start_boundary_excluded(self):
        end = END.floor("h")
        original = history(10)
        modified = original.copy()
        modified.loc[0, "APR"] = 999999  # exactly at entry, excluded
        modified.loc[len(modified)] = [end + pd.Timedelta(hours=1), 999999]
        self.assertEqual(calculate_backtest(original, history(20), 10000, end),
                         calculate_backtest(modified, history(20), 10000, end))

    def test_variable_rates_use_each_payout(self):
        short = history(0, 4)
        short.loc[len(short) - 1, "APR"] = 876  # 0.4% at this 4h event
        result = calculate_backtest(history(0), short, 10000, END)
        self.assertAlmostEqual(result.short.funding, 40)
        self.assertAlmostEqual(result.net, -40)

    def test_repeated_schedule_change_uses_preceding_interval(self):
        times = pd.date_range("2026-08-11", "2026-08-26", freq="8h", tz="UTC")
        times = times.append(pd.date_range("2026-08-26T04:00Z", "2026-09-10T00:00Z", freq="4h"))
        short = pd.DataFrame({"Time": times, "APR": 0.0})
        short.loc[45, "APR"] = 876  # last 8h payout, NOT next 4h interval
        result = calculate_backtest(history(0), short, 10000, END)
        self.assertAlmostEqual(result.short.funding, 80)

    def test_unusable_histories_withhold_result(self):
        bad_rate = history(20)
        bad_rate.loc[10, "APR"] = float("inf")
        bad_time = history(20)
        bad_time.loc[10, "Time"] = pd.NaT
        conflict = pd.concat([history(20), history(21).iloc[10:11]])
        cases = [pd.DataFrame(), history(20).iloc[20:], history(20).iloc[:-30],
                 history(20).drop(index=range(100, 130)), bad_rate, bad_time, conflict]
        for frame in cases:
            with self.subTest(rows=len(frame)):
                with self.assertRaises(HistoryUnavailable):
                    calculate_backtest(frame, history(20), 10000, END)

    def test_irregular_gap_returns_labelled_rough_estimate(self):
        short = history(0).drop(index=[100, 101])
        short.loc[102, "APR"] = 876  # 3h gap: use its ending historic rate
        result = calculate_backtest(history(0), short, 10000, END)
        self.assertAlmostEqual(result.short.funding, 30)
        self.assertAlmostEqual(result.net, -50)
        self.assertTrue(any("Short: Irregular" in note for note in result.notes))

    def test_recently_stale_history_omits_tail_and_warns(self):
        result = calculate_backtest(history(0), history(876).iloc[:-2], 10000, END)
        self.assertAlmostEqual(result.short.funding, 718 * 10)
        self.assertTrue(any("no funding is added" in note for note in result.notes))

    def test_regular_history_is_not_marked_rough(self):
        result = calculate_backtest(history(10), history(20, 4), 10000, END)
        self.assertEqual(result.notes, ())

    def test_invalid_capital(self):
        for capital in (0, -10, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                calculate_backtest(history(10), history(20), capital, END)


if __name__ == "__main__":
    unittest.main()
