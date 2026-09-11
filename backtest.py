"""Funding-only replay of published payouts, never a current-APR projection."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import pandas as pd


class HistoryUnavailable(ValueError):
    """History cannot support an unambiguous full-window funding replay."""


@dataclass(frozen=True)
class LegResult:
    funding: float
    payments: int
    first: pd.Timestamp
    last: pd.Timestamp
    intervals_hours: tuple[float, ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class BacktestResult:
    long: LegResult
    short: LegResult
    notional_per_side: float
    entry_fee: float
    exit_fee: float
    net: float
    return_pct: float
    annualised_pct: float

    @property
    def notes(self) -> tuple[str, ...]:
        return tuple(f"{side}: {note}" for side, leg in
                     (("Long", self.long), ("Short", self.short)) for note in leg.notes)


def replay_leg(history: pd.DataFrame, notional: float, sign: int,
               start: pd.Timestamp, end: pd.Timestamp) -> LegResult:
    if history.empty or not {"Time", "APR"}.issubset(history.columns):
        raise HistoryUnavailable("No funding history is available.")
    frame = history[["Time", "APR"]].copy()
    frame["Time"] = pd.to_datetime(frame["Time"], utc=True, errors="coerce")
    frame["APR"] = pd.to_numeric(frame["APR"], errors="coerce")
    if frame["Time"].isna().any() or not frame["APR"].map(isfinite).all():
        raise HistoryUnavailable("History contains invalid timestamps or rates.")
    frame = frame[frame["Time"] <= end].sort_values("Time")
    if (frame.groupby("Time")["APR"].nunique() > 1).any():
        raise HistoryUnavailable("Conflicting rates exist for the same payout time.")
    frame = frame.drop_duplicates("Time").reset_index(drop=True)
    if len(frame) < 3:
        raise HistoryUnavailable("Too few payouts to infer the funding interval.")

    # Each APR belongs to the interval ENDING at its timestamp. The API does
    # not provide settlement durations, so infer the first from the next gap.
    hours = frame["Time"].diff().dt.total_seconds().div(3600)
    hours.iloc[0] = hours.iloc[1]
    if (hours <= 0).any() or (hours > 24).any():
        raise HistoryUnavailable("History contains a gap longer than 24 hours.")
    # Repeated interval changes can be a real schedule change. Isolated gaps
    # are ambiguous, but the user allows a labelled historical approximation:
    # use the APR at the end of each gap for its elapsed duration, not live APR.
    notes = []
    observed = hours.iloc[1:].round(6)
    runs = observed.groupby(observed.ne(observed.shift()).cumsum()).size()
    if len(runs) > 1 and (runs < 3).any():
        notes.append(
            "Irregular payout intervals: each gap is estimated using the historical "
            "APR at its ending timestamp. Missing payouts and schedule changes "
            "cannot be distinguished; this may overstate or understate funding."
        )
    tolerance = pd.Timedelta(minutes=1)
    if frame["Time"].iloc[0] > start + pd.Timedelta(hours=hours.iloc[0]) + tolerance:
        raise HistoryUnavailable("History does not reach the start of the last 30 days.")
    if frame["Time"].iloc[-1] < end - pd.Timedelta(hours=hours.iloc[-1]) - tolerance:
        age = (end - frame["Time"].iloc[-1]).total_seconds() / 3600
        if age > 24:
            raise HistoryUnavailable("The latest payout is more than 24 hours old.")
        notes.append(
            f"Latest available payout is {age:.1f} hours before the window end. "
            "Later payouts may be delayed or missing; no funding is added after "
            "that timestamp. The result may overstate or understate the full 30 days."
        )
    included = (frame["Time"] > start) & (frame["Time"] <= end)
    payouts = frame.loc[included]
    if payouts.empty:
        raise HistoryUnavailable("No payouts fall within the backtest window.")
    # Sum each venue independently, including a full first payout. On irregular
    # histories this is an elapsed-time approximation, not verified cash flows.
    funding = float((payouts["APR"] / 100 * hours[included] / (365 * 24)).sum())
    return LegResult(
        funding=sign * notional * funding,
        payments=len(payouts), first=payouts["Time"].iloc[0],
        last=payouts["Time"].iloc[-1],
        intervals_hours=tuple(sorted(hours[included].round(6).unique())),
        notes=tuple(notes),
    )


def calculate_backtest(long_history: pd.DataFrame, short_history: pd.DataFrame,
                       capital: float, window_end: pd.Timestamp) -> BacktestResult:
    """Total collateral split 50/50, 2x each leg; fees on both notionals."""
    if not isfinite(capital) or capital <= 0:
        raise ValueError("Enter capital greater than zero.")
    end = pd.Timestamp(window_end)
    end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
    start = end - pd.Timedelta(days=30)
    notional = (capital / 2) * 2
    legs = []
    for side, history, sign in (("Long", long_history, -1), ("Short", short_history, 1)):
        try:
            legs.append(replay_leg(history, notional, sign, start, end))
        except HistoryUnavailable as error:
            raise HistoryUnavailable(f"{side} side: {error}") from error
    entry_fee = 2 * notional * 0.002
    exit_fee = 2 * notional * 0.002
    net = legs[0].funding + legs[1].funding - entry_fee - exit_fee
    roi = net / capital * 100
    return BacktestResult(legs[0], legs[1], notional, entry_fee, exit_fee,
                          net, roi, roi * 365 / 30)
