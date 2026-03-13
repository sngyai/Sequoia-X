"""涨停洗盘策略：昨日涨停后今日放量收阴但不破昨收。"""

import pandas as pd

from sequoia_x.core.logger import get_logger
from sequoia_x.strategy.base import BaseStrategy

logger = get_logger(__name__)


class LimitUpShakeoutStrategy(BaseStrategy):
    """涨停洗盘策略。

    选股条件（向量化，严禁 iterrows）：
    1. 昨日涨停：昨日 close >= 前日 close * 1.095
    2. 今日收阴：今日 close < 今日 open
    3. 今日放量：今日 volume > 昨日 volume * 2.0
    4. 支撑不破：今日 low >= 昨日 close

    Attributes:
        webhook_key: 路由到 'shakeout' 专属飞书机器人。
    """

    webhook_key: str = "shakeout"
    _MIN_BARS: int = 3  # 至少需要 3 根 K 线（前日、昨日、今日）

    def run(self) -> list[str]:
        """
        遍历全市场，返回满足涨停洗盘条件的股票代码列表。

        Returns:
            满足条件的股票代码列表。
        """
        symbols = self.engine.get_local_symbols()
        selected: list[str] = []

        for symbol in symbols:
            try:
                df = self.engine.get_ohlcv(symbol)
                if len(df) < self._MIN_BARS:
                    continue

                # 取最近三根 K 线（向量化索引，无 iterrows）
                prev2 = df.iloc[-3]  # 前日
                prev1 = df.iloc[-2]  # 昨日
                today = df.iloc[-1]  # 今日

                # 条件 1：昨日涨停
                limit_up_yesterday = prev1["close"] >= prev2["close"] * 1.095
                # 条件 2：今日收阴
                bearish_today = today["close"] < today["open"]
                # 条件 3：今日放量
                volume_surge = today["volume"] > prev1["volume"] * 2.0
                # 条件 4：支撑不破
                support_hold = today["low"] >= prev1["close"]

                if limit_up_yesterday and bearish_today and volume_surge and support_hold:
                    selected.append(symbol)

            except Exception as exc:
                logger.warning(f"[{symbol}] LimitUpShakeoutStrategy 计算失败：{exc}")
                continue

        logger.info(f"LimitUpShakeoutStrategy 选出 {len(selected)} 只股票")
        return selected
