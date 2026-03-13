"""日志模块：基于 rich 库提供带颜色的结构化终端日志输出。"""

import logging
from rich.logging import RichHandler

_FORMAT = "%(name)s - %(message)s"


def get_logger(name: str) -> logging.Logger:
    """
    工厂函数，返回配置了 RichHandler 的 Logger 实例。

    支持 DEBUG/INFO/WARNING/ERROR 四级日志，由 rich 自动以不同颜色渲染。
    每条日志包含时间戳、模块名和日志级别。
    同名 logger 不重复添加 handler（幂等性）。

    Args:
        name: logger 名称，通常传入 __name__。

    Returns:
        logging.Logger: 配置好的 Logger 实例。
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    handler = RichHandler(
        rich_tracebacks=True,
        show_path=False,
        log_time_format="[%Y-%m-%d %H:%M:%S]",
    )
    handler.setFormatter(logging.Formatter(_FORMAT))

    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    return logger
