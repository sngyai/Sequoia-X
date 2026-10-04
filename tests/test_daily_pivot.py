"""Daily proxy semantics, causal anchors, invalidation and score boundaries."""

import json

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sequoia_x.strategy.daily_pivot import PivotConfig, analyze_daily_pivot, daily_proxies


def pivot_bars(breakout=True):
    """Synthetic prices only: a shock, rebound, quiet retest and optional breakout."""
    rows = [[100, 102, 98, 100, 1_000_000, 100_000_000] for _ in range(30)]
    rows += [
        [100, 100.5, 89, 90, 2_000_000, 200_000_000],
        [90, 94, 90, 93, 1_000_000, 100_000_000],
        [93, 93.5, 92, 92.5, 1_000_000, 100_000_000],
        [92.5, 93, 92, 92.8, 1_000_000, 100_000_000],
        [92.8, 93, 90, 92.6, 1_000_000, 100_000_000],
        [92.6, 93, 91.5, 92.4, 1_000_000, 100_000_000],
        [92.4, 93, 92, 92.5, 1_000_000, 100_000_000],
        [92.5, 93, 91.8, 92.4, 1_000_000, 100_000_000],
    ]
    if breakout:
        rows += [[92.4, 96, 92.2, 95.5, 1_800_000, 150_000_000]]
    df = pd.DataFrame(
        rows, columns=["open", "high", "low", "close", "volume", "amount"], dtype=float,
    )
    df.insert(0, "date", pd.bdate_range("2026-01-05", periods=len(df)).strftime("%Y-%m-%d"))
    return df


def test_close_return_per_ten_million_proxy_and_frozen_baselines():
    features = daily_proxies(pivot_bars())
    shock = features.iloc[30]
    assert shock["atr_prior"] == pytest.approx(4)
    assert shock["volume_ratio"] == pytest.approx(2)
    assert shock["seller_impact_proxy"] == pytest.approx(0.1 / 20)
    assert shock["buyer_impact_proxy"] == 0
    assert bool(shock["large_negative_shock"])
    assert features.iloc[-1]["buyer_impact_proxy"] == pytest.approx((95.5 / 92.4 - 1) / 15)


def test_retest_candidate_then_compressed_range_breakout():
    candidate = analyze_daily_pivot(pivot_bars(False))
    confirmed = analyze_daily_pivot(pivot_bars())
    assert candidate["status"] == confirmed["status"] == "ok"
    assert candidate["failed_new_low"] and candidate["failed_retest"]
    assert not candidate["hidden_pivot"]
    assert candidate["stage"] == "candidate"
    assert confirmed["stage"] == "confirmed"
    assert confirmed["hidden_pivot"] and confirmed["range_compression"]
    assert confirmed["range_expansion"]
    assert confirmed["pivot_high"] == 93
    assert confirmed["anchor_low"] == 89
    assert confirmed["seller_impact_decay_proxy"] > 0.9
    assert 60 <= confirmed["failure_score"] <= confirmed["hidden_pivot_score"] <= 100
    json.dumps(confirmed, allow_nan=False)


@pytest.mark.parametrize("gate", ["return", "atr", "volume"])
def test_shock_requires_all_three_conditions(gate):
    configs = {
        "return": PivotConfig(shock_min_return=0.15),
        "atr": PivotConfig(shock_atr_multiple=3),
        "volume": PivotConfig(shock_volume_ratio=3),
    }
    result = analyze_daily_pivot(pivot_bars(), config=configs[gate])
    assert not result["large_negative_shock"]
    assert not result["failed_new_low"]
    assert result["failure_score"] == 0


@pytest.mark.parametrize("low, expected", [(89, True), (88.99, False)])
def test_equal_anchor_low_is_allowed_but_any_new_low_invalidates(low, expected):
    bars = pivot_bars(False)
    bars.loc[34, "low"] = low
    result = analyze_daily_pivot(bars)
    assert result["failed_new_low"] is expected
    if not expected:
        assert result["stage"] == "invalidated"
        assert result["failure_score"] == 0


def test_anchor_does_not_move_after_a_lower_low():
    bars = pivot_bars()
    bars.loc[35, "low"] = 88.5
    result = analyze_daily_pivot(bars)
    assert result["anchor_low"] == 89
    assert not result["hidden_pivot"]
    assert result["stage"] == "invalidated"


@pytest.mark.parametrize("age", [1, 2])
def test_new_low_invalidates_immediately_even_before_minimum_observation_age(age):
    bars = pivot_bars(False).iloc[:31 + age].copy()
    bars.loc[30 + age, "low"] = 88.5
    result = analyze_daily_pivot(bars)
    assert result["stage"] == "invalidated"
    assert result["failure_score"] == 0
    assert result["reason"] == "New low below frozen shock anchor"


def test_retest_needs_rebound_volume_control_and_close_recovery():
    bars = pivot_bars(False).iloc[:35].copy()
    for field, value in [("volume", 3_000_000), ("close", 90.1), ("low", 92.5)]:
        changed = bars.copy()
        changed.loc[34, field] = value
        assert not analyze_daily_pivot(changed)["failed_retest"]
    bars.loc[31:33, "close"] = 90
    bars.loc[31:33, "low"] = 89.5
    assert not analyze_daily_pivot(bars)["failed_retest"]


def test_absence_of_down_sessions_is_unknown_decay_not_perfect_decay():
    bars = pivot_bars(False).iloc[:35].copy()
    bars.loc[31:34, "close"] = [91, 91.5, 92, 92.6]
    result = analyze_daily_pivot(bars)
    assert result["seller_impact_decay_proxy"] is None
    assert not result["failed_new_low"]


def test_seller_reacceleration_blocks_candidate_and_penalizes_score():
    bars = pivot_bars(False)
    bars.loc[37, ["open", "high", "low", "close", "amount"]] = [92.5, 93, 90, 90.5, 20_000_000]
    result = analyze_daily_pivot(bars)
    assert result["seller_reacceleration"]
    assert not result["failed_new_low"]
    assert result["score_components"]["reacceleration_penalty"] == -30


@pytest.mark.parametrize("change", ["no_breakout", "no_volume", "no_expansion"])
def test_hidden_pivot_requires_price_volume_and_range_confirmation(change):
    bars = pivot_bars()
    config = PivotConfig()
    if change == "no_breakout":
        bars.loc[38, ["high", "close"]] = [93, 92.8]
    elif change == "no_volume":
        bars.loc[38, "volume"] = 500_000
    else:
        config = PivotConfig(expansion_multiple=10)
    assert not analyze_daily_pivot(bars, config=config)["hidden_pivot"]


def test_latest_shock_restarts_observation_instead_of_reusing_old_retest():
    bars = pivot_bars()
    bars.loc[38, ["open", "high", "low", "close", "volume"]] = [92.4, 93, 82, 83, 2_000_000]
    result = analyze_daily_pivot(bars)
    assert result["shock_date"] == bars.iloc[-1]["date"]
    assert result["stage"] == "observing"
    assert not result["failed_new_low"]


def test_retest_and_shock_expire():
    bars = pivot_bars()
    extra = pd.DataFrame(
        [[96, 97, 95, 96, 1_000_000, 100_000_000]] * 25,
        columns=["open", "high", "low", "close", "volume", "amount"],
    )
    extra.insert(0, "date", pd.bdate_range(pd.Timestamp(bars.iloc[-1]["date"]) + pd.Timedelta(days=1), periods=25).strftime("%Y-%m-%d"))
    assert not analyze_daily_pivot(pd.concat([bars, extra.iloc[:5]], ignore_index=True))["failed_retest"]
    assert not analyze_daily_pivot(pd.concat([bars, extra], ignore_index=True))["large_negative_shock"]


@pytest.mark.parametrize("field, value", [
    ("close", float("nan")), ("amount", 0), ("amount", float("inf")),
    ("volume", 0), ("open", -1), ("low", 200), ("high", 80),
])
def test_invalid_recent_bars_never_produce_a_score(field, value):
    bars = pivot_bars()
    bars.loc[34, field] = value
    result = analyze_daily_pivot(bars)
    assert result["status"] == "invalid_data"
    assert result["failure_score"] is None
    assert not result["hidden_pivot"]
    json.dumps(result, allow_nan=False)


def test_insufficient_history_and_missing_amount_are_explicit():
    assert analyze_daily_pivot(pivot_bars().iloc[:20])["status"] == "insufficient_data"
    result = analyze_daily_pivot(pivot_bars().drop(columns="amount"))
    assert result["status"] == "invalid_data"
    assert "amount" in result["reason"]


@pytest.mark.parametrize("mode", ["duplicate", "unsorted", "bad_date"])
def test_dates_must_be_unique_ordered_and_parseable(mode):
    bars = pivot_bars()
    if mode == "duplicate":
        bars.loc[34, "date"] = bars.loc[33, "date"]
    elif mode == "unsorted":
        bars = bars.iloc[::-1]
    else:
        bars.loc[34, "date"] = "invalid"
    assert analyze_daily_pivot(bars)["status"] == "invalid_data"


def test_as_of_replay_is_equal_to_prefix_and_ignores_future_numeric_data():
    bars = pivot_bars()
    cutoff = bars.loc[37, "date"]
    expected = analyze_daily_pivot(bars.iloc[:38])
    bars.loc[38, "amount"] = float("nan")
    assert analyze_daily_pivot(bars, as_of=cutoff) == expected


@given(scale=st.floats(min_value=0.1, max_value=10, allow_nan=False, allow_infinity=False))
@settings(max_examples=20, deadline=None)
def test_price_scale_invariance_and_score_bounds(scale):
    bars = pivot_bars()
    original = analyze_daily_pivot(bars)
    bars[["open", "high", "low", "close"]] *= scale
    result = analyze_daily_pivot(bars)
    assert result["hidden_pivot"]
    assert result["failure_score"] == pytest.approx(original["failure_score"])
    assert 0 <= result["failure_score"] <= 100


def test_no_liquidity_signal_or_mutation():
    bars = pivot_bars()
    original = bars.copy(deep=True)
    analyze_daily_pivot(bars)
    pd.testing.assert_frame_equal(bars, original)
    bars.loc[38, "amount"] = 1_000_000
    assert not analyze_daily_pivot(bars)["failed_new_low"]


def test_latest_close_must_still_be_above_anchor_recovery_margin():
    bars = pivot_bars(False)
    bars.loc[37, ["open", "high", "low", "close", "amount"]] = [92.5, 93, 89.1, 90, 400_000_000]
    result = analyze_daily_pivot(bars)
    assert result["failed_retest"]
    assert not result["seller_reacceleration"]
    assert not result["failed_new_low"]


@pytest.mark.parametrize("config", [
    {"atr_window": 0}, {"atr_window": 21}, {"min_shock_age": 21},
    {"shock_min_return": float("inf")}, {"min_decay": 1.1}, {"min_score": 101},
])
def test_invalid_configuration_is_rejected(config):
    with pytest.raises(ValueError):
        PivotConfig(**config)
