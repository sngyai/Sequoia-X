"""飞书通知模块：将选股结果通过 Webhook 推送至飞书群。"""

import json
from datetime import date

import requests

from sequoia_x.core.config import Settings
from sequoia_x.core.logger import get_logger

logger = get_logger(__name__)


class FeishuNotifier:
    """飞书 Webhook 推送器。

    根据策略的 webhook_key 路由到对应的飞书机器人。
    若 webhook_key 未在 Settings.strategy_webhooks 中配置，
    则 fallback 到 Settings.feishu_webhook_url。
    """

    def __init__(self, settings: Settings) -> None:
        """
        初始化 FeishuNotifier。

        Args:
            settings: Settings 实例，提供 Webhook URL 配置。
        """
        self.settings = settings

    def _get_xueqiu_mapping(self) -> dict[str, dict[str, str]]:
        """
        调用 akshare 获取雪球热门关注股票，构建代码→名称+前缀的映射字典。

        Returns:
            以6位纯数字代码为 key，value 为 {'prefix_code': 'SH600519', 'name': '贵州茅台'} 的字典。
            若接口调用失败则返回空字典。
        """
        try:
            import akshare as ak
            df = ak.stock_hot_follow_xq(symbol="最热门")
            mapping: dict[str, dict[str, str]] = {}
            for _, row in df.iterrows():
                full_code: str = str(row["股票代码"])          # e.g. "SH600519"
                short_code = full_code[-6:]                    # e.g. "600519"
                mapping[short_code] = {
                    "prefix_code": full_code,
                    "name": str(row["股票简称"]),
                }
            return mapping
        except Exception as exc:
            logger.warning(f"获取雪球映射失败，将使用默认格式：{exc}")
            return {}

    def _build_card(self, symbols: list[str], strategy_name: str) -> dict:
        """
        构造飞书卡片消息 JSON，选股结果以雪球超链接横排展示。

        Args:
            symbols: 选股结果代码列表。
            strategy_name: 策略名称，显示在卡片标题中。

        Returns:
            符合飞书卡片消息格式的字典。
        """
        today = date.today().strftime("%Y-%m-%d")
        xq_map = self._get_xueqiu_mapping()

        links: list[str] = []
        for code in symbols:
            info = xq_map.get(code)
            if info:
                prefix_code = info["prefix_code"]
                name = info["name"]
            else:
                # fallback：按首位数字判断交易所前缀
                if code.startswith("6"):
                    prefix_code = f"SH{code}"
                elif code.startswith(("4", "8")):
                    prefix_code = f"BJ{code}"
                else:
                    prefix_code = f"SZ{code}"
                name = "未知"
            links.append(f"[{name}](https://xueqiu.com/S/{prefix_code})")

        symbol_text = " ".join(links) if links else "（无选股结果）"

        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"📈 Sequoia-X 选股播报 | {strategy_name}",
                    },
                    "template": "blue",
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**日期：** {today}\n**策略：** {strategy_name}\n**选股数量：** {len(symbols)}",
                        },
                    },
                    {"tag": "hr"},
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**选股列表：**\n{symbol_text}",
                        },
                    },
                ],
            },
        }

    def send(
        self,
        symbols: list[str],
        strategy_name: str,
        webhook_key: str = "default",
    ) -> None:
        """
        将选股结果格式化为飞书卡片消息并 POST 至对应 Webhook。

        根据 webhook_key 从 Settings 中查找专属 URL；
        若未配置，则 fallback 到 feishu_webhook_url。

        Args:
            symbols: 选股结果代码列表。
            strategy_name: 策略名称，用于卡片标题。
            webhook_key: 策略标识，用于路由到对应飞书机器人。

        Raises:
            不抛出异常，HTTP 失败时记录 ERROR 日志。
        """
        url = self.settings.get_webhook_url(webhook_key)
        payload = self._build_card(symbols, strategy_name)

        try:
            resp = requests.post(
                url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            # 解析飞书真正的返回体
            resp_json = resp.json()

            # 飞书真正的成功标志是内部的 code == 0
            if resp.status_code != 200 or resp_json.get("code") != 0:
                logger.error(
                    f"飞书推送失败 [{webhook_key}] "
                    f"HTTP状态={resp.status_code} 飞书响应={resp.text}"
                )
            else:
                logger.info(f"飞书推送成功 [{webhook_key}]，共 {len(symbols)} 只股票")

        except requests.RequestException as exc:
            logger.error(f"飞书推送请求异常 [{webhook_key}]：{exc}")
