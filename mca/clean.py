"""Consolidate and clean the raw exports into a star schema for Power BI.

Outputs (data/processed):
  dim_date, dim_retailer, dim_product, dim_keyword,
  fact_media (daily, retailer x SKU x ad type), fact_shelf (daily, retailer x SKU),
  fact_sales (daily, retailer x SKU), fact_search (weekly top-10 search results)
Every fix is counted in a data-quality log so the cleaning is auditable.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C
from .generate import MEDIA_SCHEMAS

AD_TYPE_MAP = {"sponsored products": "Sponsored Products", "sponsored brands": "Sponsored Brands", "display": "Display"}


def norm_key(text: str) -> str:
    return re.sub(r"[^a-z]", "", str(text).lower())


RETAILER_ALIASES = {norm_key(r["name"]): rid for rid, r in C.RETAILERS.items()}
RETAILER_ALIASES.update({"megastore": "R4", "megastoreonlineuk": "R4"})


def retailer_id(name: str) -> str:
    key = norm_key(name)
    if key not in RETAILER_ALIASES:
        raise ValueError(f"Unknown retailer name: {name!r}")
    return RETAILER_ALIASES[key]


def parse_money(series: pd.Series) -> pd.Series:
    """'£1,234.50' / '1234.5' / NaN -> float."""
    cleaned = series.astype("string").str.replace(r"[£,\s]", "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce")


class DQLog:
    def __init__(self):
        self.rows: list[tuple[str, str, int]] = []

    def add(self, source: str, issue: str, count: int):
        if count:
            self.rows.append((source, issue, int(count)))

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows, columns=["source", "issue", "rows_affected"])


def clean_media(raw_dir: Path, log: DQLog) -> pd.DataFrame:
    frames = []
    for rid, schema in MEDIA_SCHEMAS.items():
        name = C.RETAILERS[rid]["name"].lower().replace(" ", "_")
        src = f"media_{name}.csv"
        df = pd.read_csv(raw_dir / src)
        cols = {v: k for k, v in schema.items() if not k.startswith("_")}
        df = df.rename(columns=cols)[list(cols.values())]
        df["date"] = pd.to_datetime(df["date"], format=schema["_datefmt"])
        df["retailer_id"] = rid
        df["sku"] = df["sku"].str.upper().str.strip()
        df["ad_type"] = df["ad_type"].str.strip().str.lower().map(AD_TYPE_MAP)
        for c in ["spend", "ad_sales"]:
            df[c] = parse_money(df[c])

        n0 = len(df)
        df = df.drop_duplicates()
        log.add(src, "exact duplicate rows removed", n0 - len(df))
        neg = df["impressions"] < 0
        log.add(src, "negative impressions removed", neg.sum())
        df = df[~neg]
        miss = df["ad_sales"].isna()
        log.add(src, "missing sales set to 0 (no attributed orders)", miss.sum())
        df["ad_sales"] = df["ad_sales"].fillna(0.0)
        log.add(src, "unmapped ad type", df["ad_type"].isna().sum())
        frames.append(df)

    media = pd.concat(frames, ignore_index=True)
    return media[["date", "retailer_id", "sku", "campaign", "ad_type", "impressions", "clicks",
                  "spend", "conversions", "ad_sales"]].sort_values(["date", "retailer_id", "sku", "ad_type"])


def clean_shelf(raw_dir: Path, log: DQLog) -> pd.DataFrame:
    src = "digital_shelf_export.csv"
    df = pd.read_csv(raw_dir / src)
    variants = df["retailer"].nunique()
    df["retailer_id"] = df["retailer"].map(retailer_id)
    canonical = df["retailer_id"].map(lambda r: C.RETAILERS[r]["name"])
    log.add(src, f"retailer names standardised ({variants} spellings -> {df['retailer_id'].nunique()} retailers)",
            (df["retailer"] != canonical).sum())
    df["date"] = pd.to_datetime(df["capture_date"], format="%Y-%m-%d")
    df["in_stock"] = df["availability"].str.strip().str.lower().eq("in stock")

    n0 = len(df)
    df = df.drop_duplicates(subset=["date", "retailer_id", "sku"], keep="last")
    log.add(src, "duplicate daily captures removed", n0 - len(df))

    df = df.sort_values(["retailer_id", "sku", "date"])
    miss = df["rating"].isna()
    log.add(src, "missing ratings filled from previous capture", miss.sum())
    df["rating"] = df.groupby(["retailer_id", "sku"])["rating"].transform(lambda s: s.ffill().bfill())

    df = df.rename(columns={"price_gbp": "price", "rrp_gbp": "rrp", "competitor_avg_price": "competitor_price"})
    df["price_index"] = (df["price"] / df["competitor_price"]).round(4)
    df["on_promo"] = df["price"] < df["rrp"] * 0.95
    return df[["date", "retailer_id", "sku", "in_stock", "price", "rrp", "competitor_price", "price_index",
               "on_promo", "organic_rank", "paid_rank", "content_score", "rating", "review_count"]]


def clean_sales(raw_dir: Path, log: DQLog) -> pd.DataFrame:
    df = pd.read_csv(raw_dir / "epos_sellout.csv")
    df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d")
    df["retailer_id"] = df["retailer_name"].map(retailer_id)
    return df.rename(columns={"units_sold": "units", "gross_sales_gbp": "revenue"})[
        ["date", "retailer_id", "sku", "units", "revenue"]]


def clean_search(raw_dir: Path, log: DQLog) -> pd.DataFrame:
    df = pd.read_csv(raw_dir / "search_rank_snapshots.csv")
    df["date"] = pd.to_datetime(df["snapshot_date"], format="%Y-%m-%d")
    df["retailer_id"] = df["retailer"].map(retailer_id)
    df["sponsored"] = df["sponsored"].eq("Y")
    df["is_brand"] = df["brand"].eq(C.BRAND)
    return df[["date", "retailer_id", "keyword", "position", "brand", "sponsored", "is_brand"]]


def build_dims(start, end) -> dict[str, pd.DataFrame]:
    d = pd.DataFrame({"date": pd.date_range(start, end, freq="D")})
    d["year"] = d["date"].dt.year
    d["quarter"] = "Q" + d["date"].dt.quarter.astype(str)
    d["month_num"] = d["date"].dt.month
    d["month"] = d["date"].dt.strftime("%b")
    d["week_start"] = d["date"] - pd.to_timedelta(d["date"].dt.dayofweek, unit="D")
    d["weekday"] = d["date"].dt.strftime("%a")
    retailers = pd.DataFrame([{"retailer_id": k, "retailer": v["name"]} for k, v in C.RETAILERS.items()])
    products = pd.DataFrame(C.PRODUCTS, columns=["sku", "category", "product_name", "rrp", "_base"]).drop(columns="_base")
    products["brand"] = C.BRAND
    keywords = pd.DataFrame([{"keyword": k, "category": c} for c, ks in C.CATEGORIES.items() for k in ks])
    return {"dim_date": d, "dim_retailer": retailers, "dim_product": products, "dim_keyword": keywords}


def run(raw_dir: Path = C.RAW_DIR, out_dir: Path = C.PROCESSED_DIR) -> dict[str, pd.DataFrame]:
    log = DQLog()
    tables = {
        "fact_media": clean_media(raw_dir, log),
        "fact_shelf": clean_shelf(raw_dir, log),
        "fact_sales": clean_sales(raw_dir, log),
        "fact_search": clean_search(raw_dir, log),
    }
    start = min(t["date"].min() for t in tables.values())
    end = max(t["date"].max() for t in tables.values())
    tables.update(build_dims(start, end))

    # referential integrity: every SKU must exist in dim_product
    known = set(tables["dim_product"]["sku"])
    for name in ["fact_media", "fact_shelf", "fact_sales"]:
        bad = ~tables[name]["sku"].isin(known)
        log.add(name, "rows with unknown SKU dropped", bad.sum())
        tables[name] = tables[name][~bad]

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(out_dir / f"{name}.csv", index=False, date_format="%Y-%m-%d")
    tables["dq_log"] = log.frame()
    tables["dq_log"].to_csv(out_dir / "data_quality_log.csv", index=False)
    return tables


if __name__ == "__main__":
    t = run()
    print(t["dq_log"].to_string(index=False))
    for k, v in t.items():
        print(f"{k:14s} {len(v):>8,d} rows")
