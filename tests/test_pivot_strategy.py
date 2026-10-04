"""Strategy contract, SQLite alias compatibility and local JSON entry point."""

import json
import sqlite3
from unittest.mock import Mock

import pytest

import main as main_module
from sequoia_x.core.config import Settings
from sequoia_x.data.engine import DataEngine
from sequoia_x.strategy.failed_new_low import FailedNewLowStrategy
from sequoia_x.strategy.hidden_pivot import HiddenPivotStrategy
from tests.test_daily_pivot import pivot_bars


def local_engine(tmp_path):
    settings = Settings(db_path=str(tmp_path / "market.db"), feishu_webhook_url="")
    return DataEngine(settings), settings


def write_bars(engine, symbol, bars):
    stored = bars.rename(columns={"amount": "turnover"}).assign(symbol=symbol)
    with sqlite3.connect(engine.db_path) as conn:
        stored.to_sql("stock_daily", conn, if_exists="append", index=False)


def test_amount_alias_preserves_old_schema_rows_and_strategy_field(tmp_path):
    engine, _ = local_engine(tmp_path)
    write_bars(engine, "000001", pivot_bars())
    read = engine.get_ohlcv("000001")
    assert read["amount"].tolist() == read["turnover"].tolist()
    with sqlite3.connect(engine.db_path) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(stock_daily)")]
        assert "turnover" in columns and "amount" not in columns
        assert conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0] == 39
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_strategies_return_codes_and_scored_results_without_network(tmp_path):
    engine, settings = local_engine(tmp_path)
    write_bars(engine, "000002", pivot_bars())
    write_bars(engine, "000001", pivot_bars())
    write_bars(engine, "600000", pivot_bars().iloc[:20])
    for strategy_cls in [FailedNewLowStrategy, HiddenPivotStrategy]:
        strategy = strategy_cls(engine, settings)
        assert strategy.run() == ["000001", "000002"]
        scored = strategy.run_scored()
        assert [row["symbol"] for row in scored] == ["000001", "000002"]
        assert all(row["score"] >= 60 for row in scored)
        assert strategy.diagnostics["600000"]["status"] == "insufficient_data"
        json.dumps(scored, allow_nan=False)


def test_global_scan_date_blocks_stale_symbol_and_as_of_does_not_leak(tmp_path):
    engine, settings = local_engine(tmp_path)
    write_bars(engine, "000001", pivot_bars())
    write_bars(engine, "000002", pivot_bars(False))
    strategy = FailedNewLowStrategy(engine, settings)
    assert strategy.run() == ["000001"]
    assert strategy.diagnostics["000002"]["status"] == "stale_data"
    cutoff = pivot_bars(False).iloc[-1]["date"]
    replay = FailedNewLowStrategy(engine, settings, as_of=cutoff)
    assert replay.run() == ["000001", "000002"]
    assert HiddenPivotStrategy(engine, settings, as_of=cutoff).run() == []


def test_one_corrupt_symbol_does_not_abort_scan(tmp_path):
    engine, settings = local_engine(tmp_path)
    write_bars(engine, "000001", pivot_bars())
    bad = pivot_bars()
    bad.loc[34, "amount"] = 0
    write_bars(engine, "000002", bad)
    strategy = HiddenPivotStrategy(engine, settings)
    assert strategy.run() == ["000001"]
    assert strategy.diagnostics["000002"]["status"] == "invalid_data"


def test_offline_cli_prints_scores_without_sync_or_notifier(tmp_path, monkeypatch, capsys):
    engine, settings = local_engine(tmp_path)
    write_bars(engine, "000001", pivot_bars())
    monkeypatch.setenv("DB_PATH", settings.db_path)
    monkeypatch.setattr("sys.argv", ["main.py", "--scan-pivots"])
    sync = Mock(side_effect=AssertionError("offline mode must not update data"))
    notify = Mock(side_effect=AssertionError("offline mode must not construct a notifier"))
    monkeypatch.setattr(DataEngine, "sync_today_bulk", sync)
    monkeypatch.setattr(main_module, "FeishuNotifier", notify)
    capsys.readouterr()  # Discard fixture setup logging before testing CLI stdout.
    main_module.main()
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "daily_proxy_research"
    assert output["as_of"] == pivot_bars().iloc[-1]["date"]
    assert output["strategies"]["HiddenPivotStrategy"][0]["symbol"] == "000001"
    assert output["strategies"]["HiddenPivotStrategy"][0]["hidden_pivot"]
    sync.assert_not_called()
    notify.assert_not_called()


def test_daily_mode_keeps_old_registration_and_adds_both_strategies(tmp_path, monkeypatch):
    engine, settings = local_engine(tmp_path)
    monkeypatch.setattr("sys.argv", ["main.py"])
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "DataEngine", lambda _: engine)
    monkeypatch.setattr(engine, "sync_today_bulk", lambda: 0)
    calls = []
    classes = [
        "MaVolumeStrategy", "TurtleTradeStrategy", "HighTightFlagStrategy",
        "LimitUpShakeoutStrategy", "UptrendLimitDownStrategy", "RpsBreakoutStrategy",
        "PrivatePlacementStrategy", "FailedNewLowStrategy", "HiddenPivotStrategy",
    ]
    for name in classes:
        def run(self, _name=name):
            calls.append(_name)
            return []
        monkeypatch.setattr(getattr(main_module, name), "run", run)
    main_module.main()
    assert calls == classes


@pytest.mark.parametrize("args", [
    ["--as-of", "2026-01-01"], ["--scan-pivots", "--backfill"],
    ["--scan-pivots", "--as-of", "not-a-date"],
])
def test_cli_rejects_ambiguous_or_invalid_modes(args, monkeypatch):
    monkeypatch.setattr("sys.argv", ["main.py", *args])
    with pytest.raises(SystemExit) as exc:
        main_module.main()
    assert exc.value.code == 2
