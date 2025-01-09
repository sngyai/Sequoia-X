# -*- encoding: UTF-8 -*-

import data_fetcher
import settings
import strategy.enter as enter
from strategy import turtle_trade, climax_limitdown
from strategy import backtrace_ma250
from strategy import breakthrough_platform
from strategy import parking_apron
from strategy import low_backtrace_increase
from strategy import keep_increasing
from strategy import high_tight_flag
from strategy import zt_green
import akshare as ak
import push
import logging
import time
from datetime import datetime, timedelta
import holidays


def prepare():
    logging.info("************************ process start ***************************************")
    all_data = ak.stock_hot_follow_xq()
    subset = all_data[['股票代码', '股票简称']]
    stocks = [tuple(x) for x in subset.values]
    # statistics(all_data, stocks)
    lhb()

    strategies = {
        # '放量上涨': enter.check_volume,
        # '均线多头': keep_increasing.check,

        # '回踩年线': backtrace_ma250.check,
        # '突破平台': breakthrough_platform.check,
        # '无大幅回撤': low_backtrace_increase.check,
        # 停机坪
        '8bfca0a4-55fb-495f-87cf-f3c7b410389d': parking_apron.check,
        # 海龟交易法则
        '62dae030-4e77-44b9-9083-e5be60ef9053': turtle_trade.check_enter,
        # 高而窄的旗形
        'af79878f-daba-461c-9b04-d3a0f03800ba': high_tight_flag.check,
        # 放量跌停
        'ae256f7e-b579-4cba-81fd-47c67c975ebb': climax_limitdown.check,
        # '涨停后放量绿': zt_green.check,
    }

    if datetime.now().weekday() == 0:
        strategies['均线多头'] = keep_increasing.check

    process(stocks, strategies)

    logging.info("************************ process   end ***************************************")


def process(stocks, strategies):
    stocks_data = data_fetcher.run(stocks)
    for api_key, strategy_func in strategies.items():
        check(stocks_data, api_key, strategy_func)
        time.sleep(2)


def check(stocks_data, api_key, strategy_func):
    end = settings.config['end_date']
    m_filter = check_enter(end_date=end, strategy_fun=strategy_func)
    results = dict(filter(m_filter, stocks_data.items()))
    if len(results) > 0:
        push.strategy(api_key, list(results.keys()))


def check_enter(end_date=None, strategy_fun=enter.check_volume):
    def end_date_filter(stock_data):
        if end_date is not None:
            if end_date < stock_data[1].iloc[0].日期:  # 该股票在end_date时还未上市
                logging.debug("{}在{}时还未上市".format(stock_data[0], end_date))
                return False
        return strategy_fun(stock_data[0], stock_data[1], end_date=end_date)

    return end_date_filter


# 统计数据
def statistics(all_data, stocks):
    limitup = len(all_data.loc[(all_data['涨跌幅'] >= 9.5)])
    limitdown = len(all_data.loc[(all_data['涨跌幅'] <= -9.5)])

    up5 = len(all_data.loc[(all_data['涨跌幅'] >= 5)])
    down5 = len(all_data.loc[(all_data['涨跌幅'] <= -5)])

    msg = "涨停数：{}   跌停数：{}\n涨幅大于5%数：{}  跌幅大于5%数：{}".format(limitup, limitdown, up5, down5)
    push.statistics(msg)


def get_last_trading_day():
    today = datetime.now()
    cn_holidays = holidays.country_holidays('CN')
    # 判断是否在当天开盘时间之前
    if today.hour < 9 or (today.hour == 9 and today.minute < 30):
        today = today - timedelta(days=1)
    while True:
        weekday = today.weekday()
        if weekday < 5 and today not in cn_holidays:
            return today.strftime('%Y%m%d')
        today = today - timedelta(days=1)


def lhb():
    today = get_last_trading_day()
    df = ak.stock_lhb_jgmmtj_em(start_date=today, end_date=today)
    mask = (df['买方机构数'] > 2)  # 机构买入次数大于1
    df = df.loc[mask]
    result = []
    for index, row in df.iterrows():
        code = row['代码']
        name = row['名称']
        result.append((code, name))
    push.lhb(result)
