import sqlite3

import pandas as pd

from sequoia_x.core.logger import get_logger
from sequoia_x.strategy.base import BaseStrategy

logger = get_logger(__name__)


class RpsBreakoutStrategy(BaseStrategy):
    """RPS 极强动量突破策略"""

    webhook_key: str = "rps"
    name: str = "RPS强势突破策略"
    rps_period: int = 120
    rps_threshold: int = 90

    def run(self) -> list[str]:
        try:
            with sqlite3.connect(self.engine.db_path) as conn:
                df = pd.read_sql(
                    "SELECT symbol, date, close, high FROM stock_daily", conn
                )
        except Exception as exc:
            logger.error(f"读取数据库失败: {exc}")
            return []

        if df.empty:
            return []

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values(["symbol", "date"])

        # 纵向计算涨幅
        df["close_shift"] = df.groupby("symbol")["close"].shift(self.rps_period)
        df["pct_change"] = (df["close"] - df["close_shift"]) / df["close_shift"]

        latest_date = df["date"].max()
        latest_df = df[df["date"] == latest_date].copy()
        latest_df = latest_df.dropna(subset=["pct_change"])

        # 横向排位 (RPS)
        latest_df["rps"] = latest_df["pct_change"].rank(pct=True) * 100
        strong_stocks = latest_df[latest_df["rps"] >= self.rps_threshold].copy()

        # 计算滚动最高价
        roll_high = (
            df.groupby("symbol")["high"]
            .rolling(window=self.rps_period, min_periods=self.rps_period // 2)
            .max()
            .reset_index(level=0, drop=True)
        )
        df["roll_high"] = roll_high

        latest_roll_high = df[df["date"] == latest_date][["symbol", "roll_high"]]
        strong_stocks = strong_stocks.merge(latest_roll_high, on="symbol")

        # 突破判定
        breakout_condition = strong_stocks["close"] >= strong_stocks["roll_high"] * 0.90
        selected = strong_stocks[breakout_condition]

        logger.info(f"RpsBreakoutStrategy 选出 {len(selected)} 只股票")
        return selected["symbol"].tolist()

