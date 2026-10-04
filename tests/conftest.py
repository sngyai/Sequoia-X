"""Keep the existing notification and entry-point tests offline and deterministic."""

import sys

import pytest

from sequoia_x.notify.feishu import FeishuNotifier


@pytest.fixture(autouse=True)
def offline_test_environment(monkeypatch, request):
    # Existing card tests assert codes/webhooks, not baostock's name service.
    if request.module.__name__.endswith("test_feishu"):
        monkeypatch.setattr(FeishuNotifier, "_get_stock_names", staticmethod(lambda symbols: {}))
    # Otherwise argparse sees pytest's flags and the exception test exits too early.
    if request.module.__name__.endswith("test_main"):
        monkeypatch.setattr(sys, "argv", ["main.py"])
