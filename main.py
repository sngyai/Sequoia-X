"""Sequoia-X V2 主程序入口。

运行模式：
  python main.py               # 日常模式：8进程增量补数据 + 跑策略 + 飞书推送（2~3分钟）
  python main.py --backfill    # 回填模式：baostock 拉全市场历史K线（首次/补数据用，约12分钟）
  python main.py --scan-pivots # 本地日K proxy 研究筛选，输出评分 JSON
"""

import argparse
import json
import sys
from contextlib import redirect_stdout
from dotenv import load_dotenv
load_dotenv()

from datetime import date

import socket
socket.setdefaulttimeout(10.0)

from sequoia_x.core.config import Settings, get_settings
from sequoia_x.core.logger import get_logger
from sequoia_x.data.engine import DataEngine
from sequoia_x.notify.feishu import FeishuNotifier
from sequoia_x.strategy.base import BaseStrategy
from sequoia_x.strategy.failed_new_low import FailedNewLowStrategy
from sequoia_x.strategy.hidden_pivot import HiddenPivotStrategy
from sequoia_x.strategy.high_tight_flag import HighTightFlagStrategy
from sequoia_x.strategy.limit_up_shakeout import LimitUpShakeoutStrategy
from sequoia_x.strategy.ma_volume import MaVolumeStrategy
from sequoia_x.strategy.turtle_trade import TurtleTradeStrategy
from sequoia_x.strategy.uptrend_limit_down import UptrendLimitDownStrategy
from sequoia_x.strategy.rps_breakout import RpsBreakoutStrategy
from sequoia_x.strategy.private_placement import PrivatePlacementStrategy


def main() -> None:
    parser = argparse.ArgumentParser(description="Sequoia-X V2 选股系统")
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="回填模式：通过 baostock 拉取全市场历史 K 线（约12分钟）",
    )
    parser.add_argument(
        "--scan-pivots", action="store_true",
        help="仅从本地日K筛选 FailedNewLow/HiddenPivot，输出评分 JSON，不同步或推送",
    )
    parser.add_argument("--as-of", help="本地筛选的历史截止日期 YYYY-MM-DD（需 --scan-pivots）")
    args = parser.parse_args()
    if args.as_of and not args.scan_pivots:
        parser.error("--as-of requires --scan-pivots")
    if args.scan_pivots and args.backfill:
        parser.error("--scan-pivots and --backfill are mutually exclusive")
    if args.as_of:
        try:
            args.as_of = date.fromisoformat(args.as_of).isoformat()
        except ValueError:
            parser.error("--as-of must be YYYY-MM-DD")

    try:
        # 1. 初始化配置
        settings = Settings(feishu_webhook_url="") if args.scan_pivots else get_settings()

        if args.scan_pivots:
            # Preserve the existing logger, while keeping machine-readable stdout pure JSON.
            with redirect_stdout(sys.stderr):
                engine = DataEngine(settings)
                scanners = [
                    FailedNewLowStrategy(engine, settings, as_of=args.as_of),
                    HiddenPivotStrategy(engine, settings, as_of=args.as_of),
                ]
                results = {type(scanner).__name__: scanner.run_scored() for scanner in scanners}
            print(json.dumps({
                "mode": "daily_proxy_research", "as_of": scanners[0].scan_date,
                "strategies": results,
                "diagnostics": scanners[0].diagnostics,
            }, ensure_ascii=False, indent=2, allow_nan=False))
            return

        # 2. 初始化日志
        logger = get_logger(__name__)
        logger.info("Sequoia-X V2 启动")

        # 3. 初始化数据引擎
        engine = DataEngine(settings)

        if args.backfill:
            # ── 回填模式：单线程保守拉历史 K 线，自动多轮重跑 ──
            logger.info("进入回填模式...")
            all_symbols = engine.get_all_symbols()
            engine.backfill(all_symbols)
            logger.info("Sequoia-X V2 回填模式运行完成")
            return

        # ── 日常模式：单次 API 补今天 + 策略 + 推送 ──
        logger.info("开始拉取最新快照...")
        count = engine.sync_today_bulk()
        logger.info(f"快照同步完成，写入 {count} 只股票")

        # 4. 策略列表（新增策略在此追加即可）
        strategies: list[BaseStrategy] = [
            MaVolumeStrategy(engine=engine, settings=settings),
            TurtleTradeStrategy(engine=engine, settings=settings),
            HighTightFlagStrategy(engine=engine, settings=settings),
            LimitUpShakeoutStrategy(engine=engine, settings=settings),
            UptrendLimitDownStrategy(engine=engine, settings=settings),
            RpsBreakoutStrategy(engine=engine, settings=settings),
            PrivatePlacementStrategy(engine=engine, settings=settings),
            FailedNewLowStrategy(engine=engine, settings=settings),
            HiddenPivotStrategy(engine=engine, settings=settings),
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

    logger.info("Sequoia-X V2 运行完成")


if __name__ == "__main__":
    main()
