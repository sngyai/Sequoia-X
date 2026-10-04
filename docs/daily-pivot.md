# 日K隐秘轴心 / 拒绝新低 V1

本版复用 SQLite、`get_ohlcv()`、`BaseStrategy.run()` 和 `main.py` 的手工注册方式。
新增策略为 `FailedNewLowStrategy` 和 `HiddenPivotStrategy`，原有 7 个策略仍按原顺序执行。
没有新增依赖、数据库、数据源或数据库迁移。

## 数据与 proxy 语义

使用同一复权口径的 `date/open/high/low/close/volume/amount`。
baostock 的 `amount` 是人民币成交额，原数据库误命名为 `turnover`；本版保留旧列，
`DataEngine.get_ohlcv()` 通过 SQL 增加 `amount` 同值别名。新指标只接受 `amount`，
不把缺失成交额替换成换手率或 `close × volume`。

设 `r = close / previous_close - 1`，`a = amount / 10,000,000`：

```text
SellerImpactProxy = max(-r, 0) / a
BuyerImpactProxy  = max( r, 0) / a
```

单位为“每一千万元总成交额对应的收盘收益率小数”。例如下跌 10%，成交额 2 亿元，
SellerImpactProxy 为 `0.1 / 20 = 0.005`。
这些是收盘价格路径 proxy，不能识别主动买卖、真实订单流、筹码归属或盘中承接。
平收会得到零，不能据此推断日内没有买卖压力。日K顺序不足以证明真实的“应该创新低”；
本版用冲击、反弹、接近冻结低点的回踩和恢复收盘作为可复核的形态条件。

## 六组逻辑和默认阈值

| 逻辑 | V1 定义 |
|---|---|
| Large Negative Shock | 收盘跌幅至少 4%；跌去的价格至少为前 14 根完整日K平均 TR 的 1.5 倍；成交量至少为前 20 日均量的 1.2 倍，三者同时满足。TR 包含前收盘跳空。 |
| Seller / Buyer Impact | 使用上述收盘收益率 / 成交额 proxy。ATR 和成交量基准均不含判定当日。 |
| Seller Impact Decay | 最近 5 个冲击后交易日里，仅对实际负收盘收益的 SellerImpactProxy 取均值；`1 - 均值 / 冲击日 proxy`。无下跌样本为 `null`，衰减可为负值。候选要求至少 30% 衰减。 |
| Failed Retest | 最近 5 日内，先有一根更早的收盘反弹到 `冻结低点 + 0.5 × 冻结ATR`；随后回踩低点在 `[冻结低点, 冻结低点 + 0.5 × 冻结ATR]`，收盘恢复至该上边界，收盘位置至少为当日区间的 60%，成交量不超过前 20 日均量 1.5 倍。 |
| FailureScore / Re-acceleration | 评分见下式。若当日卖方 proxy 达到冲击日的 80%，且至少为此前最近 5 日内下跌样本均值的 1.5 倍，则标记卖方重新加速；没有可比的此前下跌样本时，达到冲击日 80% 也保守否决。扣 30 分并禁止候选。 |
| Compression → Expansion | 当日前 5 日平均 TR / 更早 20 日平均 TR ≤ 0.65 为压缩。随后当日 TR ≥ 这 5 日均值的 1.5 倍，收盘严格超过这 5 日最高价且收阳，成交量 / 前 20 日均量 ≥ 1.2，BuyerImpactProxy 高于最近下跌样本的卖方均值。 |

冲击日的低点和前 14 日 ATR 冻结。最少观察 3 根冲击后日K，冲击最多保留 20 根日K；
任一后续日K出现严格更低的低点，整轮形态失效并清零评分。等于冻结低点允许。
新的合格负向冲击会开启新的观察轮次，不能沿用旧回踩。

```text
FailureScore = clip(
    20 × 已确认冲击
  + 25 × clip(SellerImpactDecayProxy, 0, 1)
  + 25 × 有近期合格回踩
  + 15 × 当前收盘在当日高低区间的位置
  + 15 × 压缩成立
  - 30 × 卖方重新加速,
  0, 100)
```

未观测到衰减时，该项计 0 分且禁止候选；没有权重重分配。
数据有效但没有近期冲击、观察期未满或锚点失效时，评分为 0；数据不合格时评分为 `null`。

- `FailedNewLow`：近期合格回踩 + 至少 30% proxy 衰减 + 未重新加速 + 无更低低点；
  当前成交额至少 2000 万元，当前收盘仍在 `冻结低点 + 0.5 × 冻结ATR` 以上，
  FailureScore 至少 60 分。选出的阶段可为 `candidate` 或 `confirmed`。
- `HiddenPivot`：满足全部 FailedNewLow 条件，进一步要求压缩后的扩张确认。
  `HiddenPivotScore = min(100, FailureScore + 10)`；阶段为 `confirmed`。

两个结果集合允许重叠，分别代表候选证据和突破确认。结果按评分降序、代码升序排列。
阈值集中在不可变 `PivotConfig`，可在 Python 初始化策略时调整；V1 没有自动优化或回测调参。

## 数据门槛和因果性

- 至少需要前 20 根基准日K和当前日K。完整压缩比较还需前 5 日和更早 20 日。
- 日期须可解析、严格递增且唯一。计算相关窗口内 OHLC、成交量、成交额须为有限正数；
  OHLC 须符合区间边界。零成交量、零成交额、缺字段、NaN、Infinity 均阻断评分。
- `as_of` 在计算价格、量和成交额之前截断；不使用未来价格，不事后移动锚点。
- 扫描日期为整个本地数据库截至所选日期的最大行情日期。
  单个股票若比该日期旧则标为 `stale_data`，不进入结果；其它无效数据原因保留在 diagnostics。
  这个日期只证明本地数据的相对新旧，不能证明缓存已追上真实市场。
- 回填/增量路径本来过滤掉了零成交量日。没有交易日历、ST/退市状态或停牌字段，
  V1 不能判定所有漏日、停牌和证券状态，也不能确认实时覆盖。只应使用已完成的收盘日K。
- 不使用固定 9.5% 跌幅判断跌停，因此不依赖主板、创业板、科创板或 ST 的不同跌停比例。
  原有 UptrendLimitDown 策略本版未修改。

## 运行命令

Python 3.10+，在仓库根目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q

# 已有本地库：直接扫描，不要求飞书凭据、不联网、不推送。
.venv/bin/python main.py --scan-pivots > pivot-results.json
.venv/bin/python main.py --scan-pivots --as-of 2026-02-26 > replay-results.json

# 原有流程：首次回填 / 日常同步与全部策略（使用原有 .env 配置）。
.venv/bin/python main.py --backfill
.venv/bin/python main.py
```

`--as-of` 只能与 `--scan-pivots` 搭配；`--scan-pivots` 和 `--backfill` 互斥。
本地模式日志到 stderr，stdout 只输出 JSON，包括所有证券的数据门槛 diagnostics。
日常模式会记录新策略的评分；`run()` 仍返回 `list[str]`，飞书仍使用原有代码列表卡片。
如需专属机器人，使用已有配置机制设置 `STRATEGY_WEBHOOK_FAILED_NEW_LOW` / `STRATEGY_WEBHOOK_HIDDEN_PIVOT`。

Python 接口：

```python
from sequoia_x.core.config import Settings
from sequoia_x.data.engine import DataEngine
from sequoia_x.strategy.daily_pivot import PivotConfig
from sequoia_x.strategy.hidden_pivot import HiddenPivotStrategy

settings = Settings(feishu_webhook_url="")
engine = DataEngine(settings)
strategy = HiddenPivotStrategy(engine, settings, config=PivotConfig(min_score=65))
scored = strategy.run_scored()  # score、anchor、proxy、score_components 等
codes = strategy.run()         # 保持旧接口
diagnostics = strategy.diagnostics
```

## 示例与验证边界

以下是测试合成日K的输出节选，代码仅为测试标识，不是对该证券真实行情的分析：

```json
{
  "symbol": "000001",
  "as_of": "2026-02-26",
  "stage": "confirmed",
  "anchor_low": 89.0,
  "pivot_high": 93.0,
  "failure_score": 97.13,
  "hidden_pivot_score": 100.0,
  "seller_impact_decay_proxy": 0.9640261286086865,
  "failed_new_low": true,
  "hidden_pivot": true
}
```

测试覆盖 proxy 单位、三个冲击门槛、冻结锚点、新低失效、回踩的顺序与量价条件、
未知衰减、重新加速、压缩扩张、冲击与回踩过期、日期与数值数据门槛、历史前缀一致性、
价格尺度不变性、旧库字段兼容、策略排序、过期证券、本地 CLI 和原策略注册顺序。
现有通知测试只替换 baostock 的名称查找，现有入口测试隔离 pytest 参数，生产通知逻辑未改。
测试和合成示例证明程序语义及接入流程；本版没有真实全市场回填、自然跨日验证或胜率证据。
