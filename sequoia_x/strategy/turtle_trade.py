"""海龟交易策略：20日新高突破 + 成交额过亿。"""

import pandas as pd

from sequoia_x.core.logger import get_logger
from sequoia_x.strategy.base import BaseStrategy

logger = get_logger(__name__)


class TurtleTradeStrategy(BaseStrategy):
    """海龟交易策略。

    选股条件（向量化，严禁 iterrows）：
    1. 今日 close > 前20个交易日 high 的最大值（突破20日新高）
    2. 今日 turnover > 100,000,000（成交额过亿，流动性过滤）

    Attributes:
        webhook_key: 路由到 'turtle' 专属飞书机器人。
    """

    webhook_key: str = "turtle"
    _MIN_BARS: int = 21  # 至少需要 21 根 K 线（20日窗口 + 当日）

    def run(self) -> list[str]:
        """
        遍历全市场，返回满足海龟突破条件的股票代码列表。

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

                # 向量化：前20日 high 的滚动最大值（不含当日，shift(1) 后取 rolling(20)）
                df["high_20"] = df["high"].shift(1).rolling(20).max()

                last = df.iloc[-1]
                if pd.isna(last["high_20"]):
                    continue

                breakout = last["close"] > last["high_20"]
                liquid = last["turnover"] > 100_000_000

                if breakout and liquid:
                    selected.append(symbol)

            except Exception as exc:
                logger.warning(f"[{symbol}] TurtleTradeStrategy 计算失败：{exc}")
                continue

        logger.info(f"TurtleTradeStrategy 选出 {len(selected)} 只股票")
        return selected
