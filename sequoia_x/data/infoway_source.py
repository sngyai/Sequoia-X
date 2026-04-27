import pandas as pd
from infoway import InfowayClient, KlineType
from pydantic import BaseModel


class KlineBar(BaseModel):
    t: int
    o: float
    h: float
    l: float
    c: float
    v: float
    vw: float
    pc: str
    pca: float


class KlineItem(BaseModel):
    s: str
    respList: list[KlineBar]

    def to_dataframe(self) -> pd.DataFrame:
        if not self.respList:
            return pd.DataFrame()
        df = pd.DataFrame(
            [
                {
                    "symbol": self.s.split(".")[0],
                    "date": bar.t,
                    "open": bar.o,
                    "high": bar.h,
                    "low": bar.l,
                    "close": bar.c,
                    "volume": bar.v,
                    "turnover": bar.vw,
                }
                for bar in self.respList
            ]
        )
        # infoway utc时区转换
        df["date"] = (
            pd.to_datetime(df["date"], unit="s", utc=True)
            .dt.tz_convert("Asia/Shanghai")
            .dt.strftime("%Y-%m-%d")
        )
        df = df.sort_values("date").reset_index(drop=True)
        return df


class Infoway:
    def __init__(self, token: str) -> None:
        self.client = InfowayClient(api_key=token)

    @staticmethod
    def load_stock_codes_cn(
        path: str = "./infoway_all_product_code.xlsx",
        sheet_name: str = "A股code（China stock code）",
    ) -> list[str]:
        df = pd.read_excel(
            path,
            sheet_name=sheet_name,
            header=2,
        )

        return df["Code"].dropna().astype(str).str.strip().tolist()

    def get_olhcv(self, symbols: str, count: int = 360) -> pd.DataFrame:
        raw = self.client.stock.get_kline(
            codes=symbols, kline_type=KlineType.DAY, count=count
        )
        # print(f"raw data: {raw}")
        parsed = [KlineItem.model_validate(item) for item in raw]
        if not parsed:
            return pd.DataFrame()
        return parsed[0].to_dataframe()

    def get_olhcv_list(self, symbols: str, count: int = 60) -> list[pd.DataFrame]:
        raw = self.client.stock.get_kline(
            codes=symbols, kline_type=KlineType.DAY, count=count
        )
        # print(f"raw data: {raw}")
        parsed = [KlineItem.model_validate(item) for item in raw]
        return [item.to_dataframe() for item in parsed]
