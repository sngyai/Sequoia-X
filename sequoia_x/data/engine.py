"""数据引擎模块：负责 SQLite 行情数据存储与 akshare 增量同步。"""

import random
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import akshare as ak
import pandas as pd

from sequoia_x.core.config import Settings
from sequoia_x.core.logger import get_logger
from sequoia_x.data.adata_source import ADataSource
from sequoia_x.data.infoway_source import Infoway

logger = get_logger(__name__)


@dataclass
class SyncResult:
    """单个 symbol 同步结果。"""

    symbol: str
    status: Literal["success", "skip", "fail"]
    rows_added: int = 0


@dataclass
class SyncSummary:
    """全市场同步汇总统计。"""

    success: int = 0
    skipped: int = 0
    failed: int = 0


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS stock_daily (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol   TEXT    NOT NULL,
    date     TEXT    NOT NULL,
    open     REAL,
    high     REAL,
    low      REAL,
    close    REAL,
    volume   REAL,
    turnover REAL,
    UNIQUE (symbol, date)
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_symbol_date ON stock_daily (symbol, date);
"""


class DataEngine:
    """行情数据引擎，负责 SQLite 存储和 akshare 增量同步。"""

    def __init__(self, settings: Settings) -> None:
        """
        初始化 DataEngine。

        Args:
            settings: 系统配置实例，提供 db_path 和 start_date。
        """
        self.db_path: str = settings.db_path
        self.start_date: str = settings.start_date
        self.range: int = settings.range
        self.source: str = settings.source
        self.infoway = Infoway(token=settings.infoway_token)
        self._init_db()

    def _init_db(self) -> None:
        """
        初始化数据库：创建 data/ 目录、建表、建唯一索引。
        若表和索引已存在则跳过（幂等）。
        """
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(_CREATE_TABLE_SQL)
            conn.execute(_CREATE_INDEX_SQL)
            conn.commit()
        logger.info(f"数据库初始化完成：{self.db_path}")

    def _get_last_date(self, symbol: str) -> str | None:
        """
        查询某 symbol 在本地数据库中的最新日期。

        Args:
            symbol: 股票代码，如 '000001'。

        Returns:
            最新日期字符串（格式 YYYY-MM-DD），无数据时返回 None。
        """
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT MAX(date) FROM stock_daily WHERE symbol = ?",
                (symbol,),
            ).fetchone()
        return row[0] if row and row[0] else None

    def get_ohlcv(self, symbol: str) -> pd.DataFrame:
        """
        读取某 symbol 的全量 OHLCV 数据，供策略层调用。

        Args:
            symbol: 股票代码。

        Returns:
            包含 date/open/high/low/close/volume/turnover 列的 DataFrame。
        """
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql(
                "SELECT * FROM stock_daily WHERE symbol = ? ORDER BY date",
                conn,
                params=(symbol,),
            )
        return df

    def sync_symbol_ak(self, symbol: str) -> SyncResult:
        last_date = self._get_last_date(symbol)
        today_date = date.today()
        today_str = today_date.strftime("%Y%m%d")

        if last_date is None:
            start = self.start_date.replace("-", "")
        else:
            last_date_obj = date.fromisoformat(last_date)
            # 👇 核心优化：如果本地数据已经是今天（或更晚），直接跳过，物理阻断网络请求！
            if last_date_obj >= today_date:
                return SyncResult(symbol=symbol, status="skip")

            start = (last_date_obj + timedelta(days=1)).strftime("%Y%m%d")

        # ==========================================
        # 🛡️ 核心防反爬装甲：随机休眠 + 遇断连重试
        # ==========================================
        df = None
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 伪装人类：每次请求前随机休眠 0.1 到 0.4 秒，打乱机械节奏
                # time.sleep(random.uniform(0.1, 0.4))
                time.sleep(random.uniform(0.8, 2.0))

                df = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start,
                    end_date=today_str,
                    adjust="qfq",
                )
                logger.info(f"拉取{symbol}成功")
                break  # 只要成功拉取，立刻跳出重试循环

            except Exception as exc:
                error_str = str(exc)
                # 识别被拔网线的特征
                if (
                    "RemoteDisconnected" in error_str
                    or "Connection aborted" in error_str
                ):
                    if attempt < max_retries - 1:
                        # sleep_time = (attempt + 1) * 3  # 第一次被封睡3秒，第二次睡6秒
                        sleep_time = (2**attempt) + random.uniform(0, 1)
                        logger.warning(
                            f"[{symbol}] 触发反爬，蛰伏 {sleep_time} 秒后第 {attempt + 2} 次重试..."
                        )
                        time.sleep(sleep_time)
                        continue

                # 如果是其他莫名其妙的错误，或者 3 次重试机会都用光了，认输跳过
                logger.warning(f"[{symbol}] akshare 拉取最终失败：{error_str}")
                return SyncResult(symbol=symbol, status="fail")
        # ==========================================

        if df is None or df.empty:
            return SyncResult(symbol=symbol, status="skip")

        # 列名标准化（akshare 返回中文列名）
        col_map = {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "turnover",
        }
        df = df.rename(columns=col_map)
        df["symbol"] = symbol

        # 只保留需要的列，向量化操作，严禁 iterrows()
        keep_cols = [
            "symbol",
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover",
        ]
        df = df[[c for c in keep_cols if c in df.columns]]
        df["date"] = df["date"].astype(str)

        rows = len(df)
        try:
            with sqlite3.connect(self.db_path) as conn:
                df.to_sql(
                    "stock_daily",
                    conn,
                    if_exists="append",
                    index=False,
                    method="multi",
                )
        except sqlite3.IntegrityError as exc:
            logger.warning(f"[{symbol}] 写入时遇到重复数据，已跳过：{exc}")

        return SyncResult(symbol=symbol, status="success", rows_added=rows)

    def sync_symbol_iw(self, symbol: str) -> SyncResult:
        last_date = self._get_last_date(symbol)
        today_date = date.today()
        count = self.range

        if last_date is None:
            count = self.range
        else:
            if date.fromisoformat(last_date) >= today_date:
                return SyncResult(symbol=symbol, status="skip")
            last_date_obj = date.fromisoformat(last_date)
            diff_days = (today_date - last_date_obj).days
            count = max(diff_days + 5, 10)

        time.sleep(1)
        df = self.infoway.get_olhcv(symbol, count)

        if df is None or df.empty:
            return SyncResult(symbol=symbol, status="skip")

        rows = len(df)
        try:
            with sqlite3.connect(self.db_path) as conn:
                df.to_sql(
                    "stock_daily",
                    conn,
                    if_exists="append",
                    index=False,
                    method="multi",
                )
        except sqlite3.IntegrityError as exc:
            logger.warning(f"[{symbol}] 写入时遇到重复数据，已跳过：{exc}")

        return SyncResult(symbol=symbol, status="success", rows_added=rows)

    def sync_symbol_adata(self, symbol: str):
        last_date = self._get_last_date(symbol)
        today_date = date.today()

        if last_date is not None and date.fromisoformat(last_date) >= today_date:
            return SyncResult(symbol=symbol, status="skip")

        df = ADataSource.get_ohlcv(symbol, start_date=self.start_date)

        if df.empty:
            return SyncResult(symbol=symbol, status="skip")

        rows = len(df)
        try:
            with sqlite3.connect(self.db_path) as conn:
                df.to_sql(
                    "stock_daily",
                    conn,
                    if_exists="append",
                    index=False,
                    method="multi",
                )
        except sqlite3.IntegrityError as exc:
            logger.warning(f"[{symbol}] 写入时遇到重复数据，已跳过：{exc}")

        return SyncResult(symbol=symbol, status="success", rows_added=rows)

    def sync_symbol(self, symbol: str) -> SyncResult:
        match self.source:
            case "adata":
                return self.sync_symbol_adata(symbol)
            case "infoway":
                return self.sync_symbol_iw(symbol)
            case _:
                return self.sync_symbol_ak(symbol)

    def get_all_symbols_ak(self) -> list[str]:
        """
        从 akshare 获取全市场 A 股 symbol 列表（轻量接口）。
        包含网络重试机制，防止服务器掐断连接。

        Returns:
            股票代码字符串列表，如 ['000001', '000002', ...]。
        """
        max_retries = 5
        for attempt in range(max_retries):
            try:
                logger.info(
                    f"正在获取全市场股票列表 (第 {attempt + 1}/{max_retries} 次尝试)..."
                )
                df = ak.stock_info_a_code_name()
                logger.info(f"成功获取股票列表，共 {len(df)} 只股票。")
                return df["code"].astype(str).tolist()
            except Exception as e:
                logger.warning(f"获取全市场列表失败: {e}。3秒后重试...")
                time.sleep(3)

        logger.error("获取全市场列表最终失败！请检查网络连接。")
        return []

    def get_all_symbols_iw(self) -> list[str]:
        return Infoway.load_stock_codes_cn()

    def get_all_symbols_adata(self) -> list[str]:
        return ADataSource.load_stock_codes_cn()

    def get_all_symbols(self) -> list[str]:
        match self.source:
            case "adata":
                return self.get_all_symbols_adata()
            case "infoway":
                return self.get_all_symbols_iw()
            case _:
                return self.get_all_symbols_ak()

    def get_local_symbols(self) -> list[str]:
        """
        从本地 SQLite 数据库获取已有数据的股票代码列表，无需网络请求。

        Returns:
            本地已存在数据的股票代码列表。
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT DISTINCT symbol FROM stock_daily").fetchall()
        return [row[0] for row in rows]

    def sync_all(self, symbols: list[str]) -> SyncSummary:
        """
        批量增量同步全市场，展示 rich 进度条。

        Args:
            symbols: 股票代码列表，通常由 get_all_symbols() 提供。

        Returns:
            SyncSummary，包含 success / skipped / failed 计数。
        """
        from rich.progress import (
            BarColumn,
            MofNCompleteColumn,
            Progress,
            SpinnerColumn,
            TextColumn,
            TimeElapsedColumn,
        )

        summary = SyncSummary()

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]同步中[/bold cyan]"),
            BarColumn(bar_width=40),
            MofNCompleteColumn(),
            TextColumn("[yellow]{task.fields[symbol]}[/yellow]"),
            TimeElapsedColumn(),
        ) as progress:
            task = progress.add_task("sync", total=len(symbols), symbol="")

            for symbol in symbols:
                f"正在同步: {symbol} "
                progress.update(task, symbol=symbol)
                result = self.sync_symbol(symbol)

                if result.status == "success":
                    summary.success += 1
                elif result.status == "skip":
                    summary.skipped += 1
                else:
                    summary.failed += 1

                progress.advance(task)

        logger.info(
            f"同步完成 — 成功: {summary.success} | "
            f"跳过: {summary.skipped} | "
            f"失败: {summary.failed}"
        )
        return summary
