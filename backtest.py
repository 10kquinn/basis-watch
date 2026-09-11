"""Funding-only replay of published payouts, never a current-APR projection."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import pandas as pd


class HistoryUnavailable(ValueError):
    """History cannot support an unambiguous shared-window funding replay."""


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
    window_start: pd.Timestamp
    window_end: pd.Timestamp

    @property
    def duration_days(self) -> float:
        return (self.window_end - self.window_start).total_seconds() / 86400

    @property
    def notes(self) -> tuple[str, ...]:
        return tuple(f"{side}: {note}" for side, leg in
                     (("Long", self.long), ("Short", self.short)) for note in leg.notes)


def normalize_history(history: pd.DataFrame, end: pd.Timestamp) -> pd.DataFrame:
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
    if len(frame) < 2:
        raise HistoryUnavailable("At least two historical timestamps are needed.")
    return frame


def history_segments(frame: pd.DataFrame) -> list[pd.DataFrame]:
    """Do not bridge multi-day holes with an invented funding rate."""
    breaks = frame["Time"].diff() > pd.Timedelta(hours=24)
    return [part.reset_index(drop=True) for _, part in frame.groupby(breaks.cumsum())
            if len(part) >= 2]


def replay_leg(frame: pd.DataFrame, notional: float, sign: int,
               start: pd.Timestamp, end: pd.Timestamp) -> LegResult:
    # Each APR belongs to the interval ENDING at its timestamp. The API does
    # not provide settlement durations, so infer the first from the next gap.
    hours = frame["Time"].diff().dt.total_seconds().div(3600)
    hours.iloc[0] = hours.iloc[1]
    # Repeated interval changes can be a real schedule change. Isolated gaps
    # are ambiguous, but the user allows a labelled historical approximation:
    # use the APR at the end of each gap for its elapsed duration, not live APR.
    notes = []
    included = (frame["Time"] > start) & (frame["Time"] <= end)
    observed = hours[included].round(6)
    runs = observed.groupby(observed.ne(observed.shift()).cumsum()).size()
    if len(runs) > 1 and (runs < 3).any():
        notes.append(
            "Irregular payout intervals: each gap is estimated using the historical "
            "APR at its ending timestamp. Missing payouts and schedule changes "
            "cannot be distinguished; this may overstate or understate funding."
        )
    payouts = frame.loc[included]
    if payouts.empty:
        raise HistoryUnavailable("No payouts fall within the backtest window.")
    # Sum each venue independently, including full payouts strictly after entry.
    # The record at the coverage start sets timing only; it is not paid at entry.
    # On irregular histories this is an elapsed-time approximation, not verified
    # cash flows.
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
    histories = []
    for side, history in (("Long", long_history), ("Short", short_history)):
        try:
            histories.append(normalize_history(history, end))
        except HistoryUnavailable as error:
            raise HistoryUnavailable(f"{side} side: {error}") from error
    # Intersect coverage ranges, not exact payout timestamps: venues can fund
    # at different frequencies. Prefer the longest continuous shared range;
    # if equally long, choose the more recent range.
    candidates = []
    for long_part in history_segments(histories[0]):
        for short_part in history_segments(histories[1]):
            shared_start = max(start, long_part["Time"].iloc[0], short_part["Time"].iloc[0])
            shared_end = min(end, long_part["Time"].iloc[-1], short_part["Time"].iloc[-1])
            if shared_end > shared_start and all(
                ((part["Time"] > shared_start) & (part["Time"] <= shared_end)).any()
                for part in (long_part, short_part)
            ):
                candidates.append((shared_end - shared_start, shared_end,
                                   shared_start, long_part, short_part))
    if not candidates:
        raise HistoryUnavailable("No usable overlapping history for both markets in the last 30 days.")
    _, actual_end, actual_start, long_part, short_part = max(candidates, key=lambda item: (item[0], item[1]))
    legs = [replay_leg(long_part, notional, -1, actual_start, actual_end),
            replay_leg(short_part, notional, 1, actual_start, actual_end)]
    entry_fee = 2 * notional * 0.002
    exit_fee = 2 * notional * 0.002
    net = legs[0].funding + legs[1].funding - entry_fee - exit_fee
    roi = net / capital * 100
    days = (actual_end - actual_start).total_seconds() / 86400
    return BacktestResult(legs[0], legs[1], notional, entry_fee, exit_fee,
                          net, roi, roi * 365 / days, actual_start, actual_end)
