"""KPI definitions for media, digital shelf and share of search.

Ratios are always computed as a ratio of sums at the chosen grain (e.g. ROAS =
total sales / total spend), never as an average of daily ratios, which would
over-weight low-volume days.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C


def safe_div(num, den):
    num = np.asarray(num, dtype="float64")
    den = np.asarray(den, dtype="float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(den == 0, np.nan, num / den)
    return out


def media_kpis(df: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    sums = ["impressions", "clicks", "spend", "conversions", "ad_sales"]
    g = df.groupby(by, observed=True)[sums].sum().reset_index() if by else df[sums].sum().to_frame().T
    g["ctr"] = safe_div(g["clicks"], g["impressions"])
    g["cpc"] = safe_div(g["spend"], g["clicks"])
    g["cpm"] = safe_div(g["spend"], g["impressions"]) * 1000
    g["cvr"] = safe_div(g["conversions"], g["clicks"])
    g["roas"] = safe_div(g["ad_sales"], g["spend"])
    g["acos"] = safe_div(g["spend"], g["ad_sales"])
    return g


def shelf_kpis(df: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    d = df.assign(top10=df["organic_rank"] <= 10, top3=df["organic_rank"] <= 3)
    agg = dict(availability=("in_stock", "mean"), avg_organic_rank=("organic_rank", "mean"),
               pct_top10=("top10", "mean"), pct_top3=("top3", "mean"), avg_paid_rank=("paid_rank", "mean"),
               content_score=("content_score", "mean"), avg_rating=("rating", "mean"),
               price_index=("price_index", "mean"), promo_share=("on_promo", "mean"))
    if by:
        return d.groupby(by, observed=True).agg(**agg).reset_index()
    return pd.DataFrame({k: [d[col].agg(fn)] for k, (col, fn) in agg.items()})


def share_of_search(df: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    d = df.assign(brand_paid=df["is_brand"] & df["sponsored"], brand_org=df["is_brand"] & ~df["sponsored"],
                  paid_slot=df["sponsored"], org_slot=~df["sponsored"], slot=1)
    cols = ["is_brand", "brand_paid", "brand_org", "paid_slot", "org_slot", "slot"]
    g = d.groupby(by, observed=True)[cols].sum().reset_index() if by else d[cols].sum().to_frame().T
    g["share_of_search"] = safe_div(g["is_brand"], g["slot"])
    g["paid_sos"] = safe_div(g["brand_paid"], g["paid_slot"])
    g["organic_sos"] = safe_div(g["brand_org"], g["org_slot"])
    return g.drop(columns=cols)


def rag(value: float, metric: str) -> str:
    """Red / Amber / Green status against the target in config.TARGETS."""
    if pd.isna(value):
        return "n/a"
    target, direction = C.TARGETS[metric]
    if direction == "high":
        if value >= target:
            return "Green"
        return "Amber" if value >= target * (1 - C.AMBER_BAND) else "Red"
    if value <= target:
        return "Green"
    return "Amber" if value <= target * (1 + C.AMBER_BAND) else "Red"


def retailer_scorecard(t: dict[str, pd.DataFrame], period: pd.Series | None = None) -> pd.DataFrame:
    """One row per retailer with the headline KPIs and RAG status."""
    m = media_kpis(t["fact_media"], ["retailer_id"])
    s = shelf_kpis(t["fact_shelf"], ["retailer_id"])
    q = share_of_search(t["fact_search"], ["retailer_id"])
    sales = t["fact_sales"].groupby("retailer_id")[["units", "revenue"]].sum().reset_index()
    sc = (t["dim_retailer"].merge(sales, on="retailer_id").merge(m, on="retailer_id")
          .merge(s, on="retailer_id").merge(q, on="retailer_id"))
    sc["tacos"] = safe_div(sc["spend"], sc["revenue"])  # total ad cost of sale
    for metric in C.TARGETS:
        sc[f"{metric}_rag"] = sc[metric].map(lambda v, m=metric: rag(v, m))
    return sc
