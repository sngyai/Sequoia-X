import adata
import pandas as pd


class ADataSource:
    @staticmethod
    def load_stock_codes_cn() -> list[str]:
        df = adata.stock.info.all_code()
        # 去空格
        df["short_name"] = df["short_name"].astype(str).str.strip()

        # 过滤退市股
        df = df[~df["short_name"].str.contains("退", na=False)]
        return df["stock_code"].dropna().astype(str).str.zfill(6).tolist()

    @staticmethod
    def get_ohlcv(
        symbol: str,
        start_date: str = "2020-01-01",
        k_type: int = 1,
    ) -> pd.DataFrame:
        df = adata.stock.market.get_market(
            stock_code=symbol,
            k_type=k_type,
            start_date=start_date,
        )

        if df.empty:
            return pd.DataFrame()

        rename_map = {
            "trade_date": "date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "turnover": "turnover",
        }

        df = df.rename(columns=rename_map)

        df["symbol"] = symbol
        df["date"] = df["date"].astype(str)

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

        return df[[c for c in keep_cols if c in df.columns]]
