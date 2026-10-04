"""Causal daily-bar research proxies; no order-flow or win-rate interpretation.

Prices must share one adjustment basis. `amount` is traded CNY, never turnover
rate. Impact is close-to-close fractional return per CNY 10 million of total
daily trading, so opposite-direction intraday activity cannot be recovered.
"""

from dataclasses import dataclass
from datetime import date
from math import isfinite

import pandas as pd


@dataclass(frozen=True)
class PivotConfig:
    atr_window: int = 14
    baseline_window: int = 20
    shock_lookback: int = 20
    shock_min_return: float = 0.04
    shock_atr_multiple: float = 1.5
    shock_volume_ratio: float = 1.2
    min_shock_age: int = 3
    impact_window: int = 5
    min_decay: float = 0.3
    retest_lookback: int = 5
    retest_tolerance_atr: float = 0.5
    rebound_atr: float = 0.5
    min_close_location: float = 0.6
    max_retest_volume_ratio: float = 1.5
    reacceleration_multiple: float = 1.5
    reacceleration_anchor_ratio: float = 0.8
    compression_window: int = 5
    compression_ratio: float = 0.65
    expansion_multiple: float = 1.5
    expansion_volume_ratio: float = 1.2
    min_amount: float = 20_000_000
    min_score: float = 60

    def __post_init__(self) -> None:
        windows = (
            self.atr_window, self.baseline_window, self.shock_lookback,
            self.min_shock_age, self.impact_window, self.retest_lookback,
            self.compression_window,
        )
        if any(type(value) is not int or value < 1 for value in windows):
            raise ValueError("Windows and minimum shock age must be positive integers")
        if self.atr_window > self.baseline_window or self.min_shock_age > self.shock_lookback:
            raise ValueError("ATR/age windows exceed their baseline/lookback")
        ratios = (
            self.shock_min_return, self.shock_atr_multiple, self.shock_volume_ratio,
            self.retest_tolerance_atr, self.rebound_atr, self.max_retest_volume_ratio,
            self.reacceleration_multiple, self.reacceleration_anchor_ratio,
            self.compression_ratio, self.expansion_multiple, self.expansion_volume_ratio,
            self.min_amount,
        )
        if any(not isfinite(value) or value <= 0 for value in ratios):
            raise ValueError("Thresholds must be finite and positive")
        if not (0 <= self.min_decay <= 1 and 0 <= self.min_close_location <= 1
                and 0 <= self.min_score <= 100):
            raise ValueError("Decay, close location or score outside its bounds")


def _prepare(df: pd.DataFrame, config: PivotConfig, as_of: str | None) -> pd.DataFrame:
    columns = ["date", "open", "high", "low", "close", "volume", "amount"]
    missing = set(columns) - set(df.columns)
    if missing:
        raise ValueError(f"Missing fields: {', '.join(sorted(missing))}")
    frame = df[columns].copy()
    dates = pd.to_datetime(frame["date"], format="%Y-%m-%d", errors="coerce")
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError("Dates must be parseable, unique and ascending")
    frame["date"] = dates.dt.strftime("%Y-%m-%d")
    if as_of is not None:
        cutoff = date.fromisoformat(as_of).isoformat()
        frame = frame.loc[frame["date"] <= cutoff]
    # Bound work and validation to all bars that can affect the latest decision.
    history = config.baseline_window + config.shock_lookback + config.compression_window + 2
    frame = frame.tail(history).reset_index(drop=True)
    values = frame[columns[1:]].apply(pd.to_numeric, errors="coerce")
    if not values.apply(lambda col: col.map(isfinite)).all().all() or (values <= 0).any().any():
        raise ValueError("Recent OHLC, volume and amount must be finite and positive")
    if ((values["low"] > values[["open", "close", "high"]].min(axis=1)).any()
            or (values["high"] < values[["open", "close", "low"]].max(axis=1)).any()):
        raise ValueError("Inconsistent OHLC bounds")
    frame[columns[1:]] = values
    return frame


def _proxies(frame: pd.DataFrame, config: PivotConfig) -> pd.DataFrame:
    features = frame.copy()
    previous_close = features["close"].shift(1)
    features["close_return"] = features["close"] / previous_close - 1
    features["true_range"] = pd.concat([
        features["high"] - features["low"],
        (features["high"] - previous_close).abs(),
        (features["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    features["atr_prior"] = features["true_range"].shift(1).rolling(config.atr_window).mean()
    features["volume_ratio"] = (
        features["volume"] / features["volume"].shift(1).rolling(config.baseline_window).mean()
    )
    notional = features["amount"] / 10_000_000
    features["seller_impact_proxy"] = (-features["close_return"]).clip(lower=0) / notional
    features["buyer_impact_proxy"] = features["close_return"].clip(lower=0) / notional
    spread = features["high"] - features["low"]
    features["close_location"] = (
        (features["close"] - features["low"]) / spread.where(spread > 0)
    )
    features["large_negative_shock"] = (
        (features["close_return"] <= -config.shock_min_return)
        & (previous_close - features["close"] >= config.shock_atr_multiple * features["atr_prior"])
        & (features["volume_ratio"] >= config.shock_volume_ratio)
        & (features["atr_prior"] > 0)
    )
    return features


def daily_proxies(df: pd.DataFrame, config: PivotConfig | None = None) -> pd.DataFrame:
    """Validated per-bar proxies with strictly prior ATR/volume baselines."""
    config = config or PivotConfig()
    return _proxies(_prepare(df, config, None), config)


def _empty_result(status="ok", reason="", as_of=None) -> dict:
    return {
        "version": "daily-pivot-proxy-v1", "status": status, "reason": reason,
        "as_of": as_of, "stage": "no_shock", "shock_date": None, "retest_date": None,
        "anchor_low": None, "anchor_atr": None, "pivot_high": None,
        "large_negative_shock": False, "seller_impact_proxy": None,
        "buyer_impact_proxy": None, "seller_impact_decay_proxy": None,
        "seller_reacceleration_proxy": None, "seller_reacceleration": False,
        "failed_retest": False, "failed_new_low": False, "range_compression": False,
        "compression_ratio": None, "range_expansion": False, "hidden_pivot": False,
        "failure_score": 0.0 if status == "ok" else None, "hidden_pivot_score": None,
        "score_components": {},
        "impact_unit": "fractional close return per CNY 10 million total daily amount",
    }


def analyze_daily_pivot(
    df: pd.DataFrame, config: PivotConfig | None = None, as_of: str | None = None,
) -> dict:
    """Evaluate the latest completed daily bar; an as-of cutoff never uses future prices.

    FailureScore measures evidence of seller failure, not a trading probability.
    A strict new low after the frozen shock invalidates the whole setup. A newer
    shock starts a fresh observation; missing sell samples leave decay unknown.
    """
    config = config or PivotConfig()
    try:
        frame = _prepare(df, config, as_of)
    except ValueError as exc:
        return _empty_result("invalid_data", str(exc))
    cutoff = frame.iloc[-1]["date"] if not frame.empty else None
    if len(frame) < config.baseline_window + 1:
        return _empty_result("insufficient_data", "Need prior baseline plus current bar", cutoff)
    features = _proxies(frame, config)
    result = _empty_result(as_of=cutoff)
    last = features.iloc[-1]
    result.update(seller_impact_proxy=float(last["seller_impact_proxy"]),
                  buyer_impact_proxy=float(last["buyer_impact_proxy"]))
    shocks = features.index[
        features["large_negative_shock"]
        & (features.index >= len(features) - config.shock_lookback - 1)
    ]
    if len(shocks) == 0:
        return result
    anchor_index = int(shocks[-1])
    anchor = features.iloc[anchor_index]
    age = len(features) - 1 - anchor_index
    low, atr = float(anchor["low"]), float(anchor["atr_prior"])
    anchor_impact = float(anchor["seller_impact_proxy"])
    result.update(large_negative_shock=True, shock_date=anchor["date"],
                  anchor_low=low, anchor_atr=atr, stage="observing")
    post = features.iloc[anchor_index + 1:]
    if (post["low"] < low).any():
        result.update(stage="invalidated", reason="New low below frozen shock anchor")
        return result
    if age < config.min_shock_age:
        return result

    recent = post.tail(config.impact_window)
    sellers = recent.loc[recent["seller_impact_proxy"] > 0, "seller_impact_proxy"]
    decay = None if sellers.empty else 1 - float(sellers.mean()) / anchor_impact
    previous_sellers = post.iloc[:-1].tail(config.impact_window)
    previous_sellers = previous_sellers.loc[
        previous_sellers["seller_impact_proxy"] > 0, "seller_impact_proxy"
    ]
    previous_mean = None if previous_sellers.empty else float(previous_sellers.mean())
    seller = float(last["seller_impact_proxy"])
    acceleration = seller / previous_mean if previous_mean is not None else None
    reaccelerating = (
        seller >= anchor_impact * config.reacceleration_anchor_ratio
        and (acceleration is None or acceleration >= config.reacceleration_multiple)
    )
    result.update(seller_impact_decay_proxy=decay, seller_reacceleration_proxy=acceleration,
                  seller_reacceleration=bool(reaccelerating))

    # Retest needs an earlier rebound, so the retest bar cannot prove its own rebound.
    for index in range(max(anchor_index + 2, len(features) - config.retest_lookback), len(features)):
        bar = features.iloc[index]
        rebound = features.iloc[anchor_index + 1:index]["close"].max() >= low + config.rebound_atr * atr
        retest = (
            rebound and low <= bar["low"] <= low + config.retest_tolerance_atr * atr
            and bar["close"] >= low + config.rebound_atr * atr
            and bar["close_location"] >= config.min_close_location
            and bar["volume_ratio"] <= config.max_retest_volume_ratio
        )
        if retest:
            result.update(failed_retest=True, retest_date=bar["date"])

    prior = features.iloc[-config.compression_window - 1:-1]
    baseline = features["true_range"].shift(config.compression_window + 1).rolling(
        config.baseline_window
    ).mean().iloc[-1]
    quiet_range = float(prior["true_range"].mean())
    compression = quiet_range / baseline if pd.notna(baseline) and baseline > 0 else None
    compressed = compression is not None and compression <= config.compression_ratio
    pivot_high = float(prior["high"].max())
    expansion = (
        compressed and quiet_range > 0
        and last["true_range"] >= quiet_range * config.expansion_multiple
        and last["close"] > pivot_high and last["close"] > last["open"]
        and last["volume_ratio"] >= config.expansion_volume_ratio
        and not sellers.empty and last["buyer_impact_proxy"] > sellers.mean()
    )
    result.update(compression_ratio=float(compression) if compression is not None else None,
                  range_compression=bool(compressed), range_expansion=bool(expansion),
                  pivot_high=pivot_high)
    close_location = float(last["close_location"]) if pd.notna(last["close_location"]) else 0
    components = {
        "shock": 20.0,
        "decay": 25 * max(0, min(1, decay)) if decay is not None else 0.0,
        "retest": 25.0 if result["failed_retest"] else 0.0,
        "close_recovery": 15 * close_location,
        "compression": 15.0 if compressed else 0.0,
        "reacceleration_penalty": -30.0 if reaccelerating else 0.0,
    }
    score = round(max(0, min(100, sum(components.values()))), 2)
    candidate = (
        result["failed_retest"] and decay is not None and decay >= config.min_decay
        and not reaccelerating and last["amount"] >= config.min_amount
        and last["close"] >= low + config.rebound_atr * atr
        and score >= config.min_score
    )
    hidden = candidate and expansion
    result.update(score_components=components, failure_score=score,
                  failed_new_low=bool(candidate), hidden_pivot=bool(hidden),
                  hidden_pivot_score=min(100.0, score + 10) if hidden else None,
                  stage="confirmed" if hidden else "candidate" if candidate else "observing")
    return result
