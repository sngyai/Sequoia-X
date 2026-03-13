"""Sequoia-X-X V2 主程序入口。

调度顺序：初始化配置 → 初始化日志 → 数据同步 → 策略执行 → 结果推送。
"""

import sys
from dotenv import load_dotenv
load_dotenv()

import socket
socket.setdefaulttimeout(10.0)

from sequoia_x.core.config import get_settings
from sequoia_x.core.logger import get_logger
from sequoia_x.data.engine import DataEngine
from sequoia_x.notify.feishu import FeishuNotifier
from sequoia_x.strategy.base import BaseStrategy
from sequoia_x.strategy.high_tight_flag import HighTightFlagStrategy
from sequoia_x.strategy.limit_up_shakeout import LimitUpShakeoutStrategy
from sequoia_x.strategy.ma_volume import MaVolumeStrategy
from sequoia_x.strategy.turtle_trade import TurtleTradeStrategy
from sequoia_x.strategy.uptrend_limit_down import UptrendLimitDownStrategy


def main() -> None:
    """
    主调度函数，按顺序执行完整的数据同步和选股流程。

    流程：
    1. 加载并校验配置（ValidationError 时终止）
    2. 初始化日志
    3. 初始化数据引擎并执行全市场增量同步
    4. 遍历所有策略依次执行选股
    5. 有选股结果时推送至对应飞书机器人

    Raises:
        SystemExit: 任意阶段发生未捕获异常时，以退出码 1 终止进程。
    """
    try:
        # 1. 初始化配置
        settings = get_settings()

        # 2. 初始化日志
        logger = get_logger(__name__)
        logger.info("Sequoia-X-X V2 启动")

        # 3. 数据同步
        engine = DataEngine(settings)
        all_symbols = engine.get_all_symbols()
        # summary = engine.sync_all(all_symbols[:5])
        summary = engine.sync_all(all_symbols)
        logger.info(
            f"数据同步完成 — 成功: {summary.success} | "
            f"跳过: {summary.skipped} | 失败: {summary.failed}"
        )

        # 4. 策略列表（新增策略在此追加即可）
        strategies: list[BaseStrategy] = [
            MaVolumeStrategy(engine=engine, settings=settings),
            TurtleTradeStrategy(engine=engine, settings=settings),
            HighTightFlagStrategy(engine=engine, settings=settings),
            LimitUpShakeoutStrategy(engine=engine, settings=settings),
            UptrendLimitDownStrategy(engine=engine, settings=settings),
        ]

        notifier = FeishuNotifier(settings)

        # 5. 遍历策略，有结果则推送至对应机器人
        for strategy in strategies:
            strategy_name = type(strategy).__name__
            logger.info(f"执行策略：{strategy_name}")

            selected: list[str] = strategy.run()
            logger.info(f"{strategy_name} 选出 {len(selected)} 只股票")

            if selected:
                notifier.send(
                    symbols=selected,
                    strategy_name=strategy_name,
                    webhook_key=strategy.webhook_key,
                )
            else:
                logger.info(f"{strategy_name} 无选股结果，跳过推送")

    except Exception:
        try:
            _logger = get_logger(__name__)
            _logger.exception("主流程发生未捕获异常，程序终止")
        except Exception:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    logger.info("Sequoia-X-X V2 运行完成")


if __name__ == "__main__":
    main()
