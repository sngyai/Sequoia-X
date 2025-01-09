# -*- encoding: UTF-8 -*-
import json
import logging
import requests
import settings


def push(api_key, msg):
    if settings.config['push']['enable']:
        payload = json.dumps(
            {"msg_type": "text", "content": {"text": msg}}
        )
        response = requests.post(settings.config['push']['url'] + api_key, data=payload)
        print(response.text)
    logging.info(msg)


def push_rich(api_key, msg):
    if settings.config['push']['enable']:
        payload = json.dumps(
            {"msg_type": "post", "content": {"post": msg}}
        )
        response = requests.post(settings.config['push']['url'] + api_key, data=payload)
        print(response.text)
    logging.info(msg)


def statistics(msg=None):
    push('27818dfd-bd26-4604-baec-8857748ba1c0', msg)


def strategy(api_key, stock_list=None):
    if stock_list is None or not stock_list:
        stock_list = '今日没有符合条件的股票'
    push_rich(api_key, format_stocks(stock_list))


def lhb(stocks):
    push_rich('27818dfd-bd26-4604-baec-8857748ba1c0', format_lhb(stocks))


def format_stocks(stocks):
    if not isinstance(stocks, list) or not all(isinstance(item, tuple) and len(item) == 2 for item in stocks):
        return stocks
    result = {"zh_cn": {"title": "雪球", "content": [[]]}}
    for code, name in stocks:
        stock_info = {
            "tag": "a",
            "text": name,
            "href": f"https://xueqiu.com/s/{code}"
        }
        result["zh_cn"]["content"][0].append(stock_info)

    return result


def format_lhb(stocks):
    result = {"zh_cn": {"title": "龙虎榜", "content": [[]]}}
    for code, name in stocks:
        stock_info = {
            "tag": "a",
            "text": name,
            "href": f"https://data.eastmoney.com/stock/lhb/{code}.html"
        }
        result["zh_cn"]["content"][0].append(stock_info)

    return result