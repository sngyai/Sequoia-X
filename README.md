# Sequoia-X: 王者回归 | The King Returns

> A 股量化选股系统 V2 | A-Share Quantitative Stock Selection System V2

---

## 简介 | Introduction

**中文：**
Sequoia-X V2 是面向 A 股市场的量化选股系统，基于 2026 年现代 Python 工程化标准从零重构。
系统以 OOP 架构、向量化计算和增量数据更新为核心设计原则，相较 V1 版本在性能、可维护性和可扩展性上实现全面飞跃。

**English:**
Sequoia-X V2 is a quantitative stock selection system for the A-share market, rebuilt from scratch
following modern Python engineering standards. It adopts OOP architecture, vectorized computation,
and incremental data updates as core design principles, achieving a comprehensive leap over V1 in
performance, maintainability, and extensibility.

---

## V1 vs V2 对比 | Comparison

| 特性 / Feature | V1 | V2 |
|---|---|---|
| 数据计算 / Computation | 逐行迭代 `iterrows()` | 向量化 `pandas` 批量操作 |
| 数据更新 / Data Update | 全量重新下载 | 增量同步，仅拉取缺失区间 |
| 代码架构 / Architecture | 过程式脚本 | OOP 分层架构 |
| 配置管理 / Config | 硬编码常量 | Pydantic-settings + `.env` 文件 |
| 日志输出 / Logging | `print()` | `rich` 彩色结构化日志 |

---

## 快速开始 | Quick Start

### 1. 安装依赖 | Install Dependencies

```bash
pip install akshare "pydantic-settings>=2.0" "rich>=13.0" "pandas>=2.0" "requests>=2.31"
```

### 2. 配置环境变量 | Configure Environment

```bash
cp .env.example .env
# 编辑 .env，填写飞书 Webhook URL
# Edit .env and fill in your Feishu Webhook URL
```

`.env` 示例：

```env
DB_PATH=data/sequoia_v2.db
START_DATE=2024-01-01
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/your-token-here
```

### 3. 运行 | Run

```bash
python main.py
```

---

## 目录结构 | Project Structure

```
sequoia-x-v2/
├── main.py                    # 唯一程序入口 / Single entry point
├── pyproject.toml             # 依赖声明 + ruff 配置 / Dependencies + ruff config
├── .env.example               # 环境变量示例 / Environment variable template
├── .gitignore
├── README.md
├── data/                      # 运行时生成，存放 SQLite DB / Runtime-generated SQLite DB
└── sequoia_x/
    ├── __init__.py
    ├── core/
    │   ├── __init__.py
    │   ├── config.py          # 配置管理 / Config manager (Pydantic-settings)
    │   └── logger.py          # 日志工厂 / Logger factory (rich)
    ├── data/
    │   ├── __init__.py
    │   └── engine.py          # 数据引擎 / Data engine (akshare + SQLite)
    ├── strategy/
    │   ├── __init__.py
    │   ├── base.py            # 策略抽象基类 / Abstract base strategy
    │   └── ma_volume.py       # 均线+成交量策略示例 / MA+Volume strategy example
    └── notify/
        ├── __init__.py
        └── feishu.py          # 飞书推送 / Feishu Webhook notifier
```

---

## 许可证 | License

MIT
