"""海龟交易策略：20日新高突破 + 成交额过亿 + 动量阳线过滤。"""

import pandas as pd

from sequoia_x.core.logger import get_logger
from sequoia_x.strategy.base import BaseStrategy

logger = get_logger(__name__)


class TurtleTradeStrategy(BaseStrategy):
    """海龟交易策略（A股防诱多改良版）。

    选股条件（向量化，严禁 iterrows）：
    1. 突破新高：今日 close > 前20个交易日 high 的最大值
    2. 流动性：今日 turnover > 100,000,000
    3. 防诱多过滤：今日必须是实体阳线（今日 close > 今日 open），且必须真涨（今日 close > 昨日 close）

    Attributes:
        webhook_key: 路由到 'turtle' 专属飞书机器人。
    """

    webhook_key: str = "turtle"
    _MIN_BARS: int = 21  # 至少需要 21 根 K 线（20日窗口 + 当日）

    def run(self) -> list[str]:
        """
        遍历全市场，返回满足海龟突破条件的股票代码列表。
        """
        symbols = self.engine.get_local_symbols()
        candidates: list[tuple[str, float]] = []  # (symbol, 涨幅%)

        for symbol in symbols:
            try:
                df = self.engine.get_ohlcv(symbol)
                if len(df) < self._MIN_BARS:
                    continue

                # 向量化：前20日 high 的滚动最大值（不含当日，shift(1) 后取 rolling(20)）
                df["high_20"] = df["high"].shift(1).rolling(20).max()

                last = df.iloc[-1]
                prev = df.iloc[-2]  # 获取昨日数据，用于对比

                if pd.isna(last["high_20"]):
                    continue

                # 核心条件 1：突破前 20 天最高点
                breakout = last["close"] > last["high_20"]
                # 核心条件 2：流动性过亿
                liquid = last["turnover"] > 100_000_000

                # 【新增防守条件】拒绝郑州煤电式的高开低走大阴线！
                is_yang = last["close"] > last["open"]   # 实体必须是阳线（红柱）
                is_up = last["close"] > prev["close"]    # 必须是真涨，不能是假阳线

                if breakout and liquid and is_yang and is_up:
                    change_pct = (last["close"] - prev["close"]) / prev["close"] * 100
                    candidates.append((symbol, change_pct))

            except Exception as exc:
                logger.warning(f"[{symbol}] TurtleTradeStrategy 计算失败：{exc}")
                continue

        # 按涨幅从大到小排序
        candidates.sort(key=lambda x: x[1], reverse=True)
        selected = [sym for sym, _ in candidates]

        logger.info(f"TurtleTradeStrategy 选出 {len(selected)} 只股票")
        return selected