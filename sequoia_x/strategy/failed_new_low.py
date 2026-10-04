"""Local daily-bar FailedNewLow screening with auditable research scores."""

from datetime import date

import pandas as pd

from sequoia_x.core.config import Settings
from sequoia_x.core.logger import get_logger
from sequoia_x.data.engine import DataEngine
from sequoia_x.strategy.base import BaseStrategy
from sequoia_x.strategy.daily_pivot import PivotConfig, analyze_daily_pivot

logger = get_logger(__name__)


class FailedNewLowStrategy(BaseStrategy):
    """Preserve run()->list[str]; run_scored() exposes scores and evidence.

    The scan uses the latest available local market date (or the requested
    as-of date's latest available session). Older per-symbol data is skipped.
    `diagnostics` includes all symbols, including explicit data-gate failures.
    """

    webhook_key = "failed_new_low"
    signal_key = "failed_new_low"
    score_key = "failure_score"

    def __init__(
        self, engine: DataEngine, settings: Settings, config: PivotConfig | None = None,
        as_of: str | None = None,
    ) -> None:
        super().__init__(engine, settings)
        self.config = config or PivotConfig()
        self.as_of = date.fromisoformat(as_of).isoformat() if as_of is not None else None
        self.scan_date: str | None = None
        self.diagnostics: dict[str, dict] = {}

    def run_scored(self) -> list[dict]:
        self.diagnostics = {}
        # Reuse the existing data path; do not create a cache or a second provider.
        self.scan_date = self.engine.get_latest_date(self.as_of)
        if self.scan_date is None:
            return []
        results = []
        for symbol in sorted(self.engine.get_local_symbols()):
            try:
                bars = self.engine.get_ohlcv(symbol)
                analysis = analyze_daily_pivot(bars, self.config, self.as_of)
                if analysis["status"] == "ok" and analysis["as_of"] != self.scan_date:
                    analysis.update(status="stale_data", reason="Symbol is older than scan date",
                                    failure_score=None, hidden_pivot_score=None,
                                    failed_new_low=False, hidden_pivot=False)
                self.diagnostics[symbol] = analysis
                if analysis["status"] == "ok" and analysis[self.signal_key]:
                    results.append({"symbol": symbol, "score": analysis[self.score_key], **analysis})
            except (ValueError, TypeError, KeyError, pd.errors.DatabaseError) as exc:
                self.diagnostics[symbol] = {
                    "status": "invalid_data", "reason": str(exc), "failure_score": None,
                }
                logger.warning(f"[{symbol}] {type(self).__name__} 数据不可用：{exc}")
        results.sort(key=lambda row: (-row["score"], row["symbol"]))
        return results

    def run(self) -> list[str]:
        results = self.run_scored()
        for row in results:
            logger.info(
                f"{type(self).__name__} {row['symbol']} as_of={row['as_of']} "
                f"score={row['score']:.2f} stage={row['stage']} "
                f"seller_impact_decay_proxy={row['seller_impact_decay_proxy']:.4f}"
            )
        return [row["symbol"] for row in results]
