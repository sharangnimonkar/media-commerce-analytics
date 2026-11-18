"""Driver analysis: what moves media efficiency and online sales.

1. Out-of-stock waste: ad spend that ran while the product was unavailable.
2. Content quality: conversion by content band + difference-in-differences on the
   SKU/retailer pairs whose content was upgraded mid-year.
3. Organic rank: sales by rank bucket.
4. Sales driver model: OLS on log units (in-stock days) with retailer/category/month controls.
5. Media response curves: fitted diminishing-returns curves per retailer x ad type,
   marginal ROAS, and a budget reallocation at constant total spend.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .kpis import media_kpis, safe_div

RANK_BINS = [0, 3, 6, 10, 100]
RANK_LABELS = ["1-3", "4-6", "7-10", "11+"]


def media_with_shelf(t) -> pd.DataFrame:
    shelf = t["fact_shelf"][["date", "retailer_id", "sku", "in_stock", "content_score", "price_index", "organic_rank"]]
    return t["fact_media"].merge(shelf, on=["date", "retailer_id", "sku"], how="left")


# 1 --------------------------------------------------------------------------
def oos_waste(t) -> dict:
    m = media_with_shelf(t)
    by_stock = media_kpis(m, ["in_stock"]).set_index("in_stock")
    by_ret = media_kpis(m[~m["in_stock"]], ["retailer_id"]).merge(t["dim_retailer"], on="retailer_id")
    total_spend = m["spend"].sum()
    oos_spend = m.loc[~m["in_stock"], "spend"].sum()
    return {
        "oos_spend": oos_spend,
        "oos_spend_share": oos_spend / total_spend,
        "roas_in_stock": by_stock.loc[True, "roas"],
        "roas_oos": by_stock.loc[False, "roas"],
        "by_retailer": by_ret[["retailer", "spend", "ad_sales", "roas"]].sort_values("spend", ascending=False),
        "availability_by_retailer": t["fact_shelf"].groupby("retailer_id")["in_stock"].mean(),
    }


# 2 --------------------------------------------------------------------------
def content_effect(t) -> dict:
    m = media_with_shelf(t)
    sp = m[(m["ad_type"] == "Sponsored Products") & m["in_stock"]].copy()
    sp["content_band"] = pd.cut(sp["content_score"], [0, 70, 85, 100], labels=["<70", "70-85", "85+"])
    bands = media_kpis(sp, ["content_band"])[["content_band", "clicks", "cvr", "roas"]]

    # Detect upgraded listings: content score up >= 10 points in H2 vs H1
    s = t["fact_shelf"].assign(h2=t["fact_shelf"]["date"].dt.month >= 7)
    pivot = s.groupby(["retailer_id", "sku", "h2"])["content_score"].mean().unstack()
    upgraded = pivot[(pivot[True] - pivot[False]) >= 10].index
    s["treated"] = pd.MultiIndex.from_frame(s[["retailer_id", "sku"]]).isin(upgraded)
    s = s[s["in_stock"]]
    daily = s.merge(t["fact_sales"], on=["date", "retailer_id", "sku"])
    # index each pair's units to its own H1 mean so big and small SKUs weigh equally
    base = daily[~daily["h2"]].groupby(["retailer_id", "sku"])["units"].mean().rename("base")
    daily = daily.join(base, on=["retailer_id", "sku"])
    daily["idx"] = daily["units"] / daily["base"]
    g = daily.groupby(["treated", "h2"])["idx"].mean().unstack()
    did = (g.loc[True, True] - g.loc[True, False]) - (g.loc[False, True] - g.loc[False, False])

    spt = sp.assign(treated=pd.MultiIndex.from_frame(sp[["retailer_id", "sku"]]).isin(upgraded),
                    h2=sp["date"].dt.month >= 7)
    c = media_kpis(spt, ["treated", "h2"]).set_index(["treated", "h2"])["cvr"]
    did_cvr = (c[(True, True)] - c[(True, False)]) - (c[(False, True)] - c[(False, False)])
    return {"bands": bands, "n_upgraded": len(upgraded), "upgraded": list(upgraded),
            "did_sales_lift": did, "did_cvr_pts": did_cvr, "cvr_table": c.unstack()}


# 3 --------------------------------------------------------------------------
def rank_effect(t) -> pd.DataFrame:
    s = t["fact_shelf"][t["fact_shelf"]["in_stock"]].merge(t["fact_sales"], on=["date", "retailer_id", "sku"])
    s["rank_bucket"] = pd.cut(s["organic_rank"], RANK_BINS, labels=RANK_LABELS)
    out = s.groupby("rank_bucket", observed=True).agg(days=("units", "size"), avg_daily_units=("units", "mean"),
                                                      avg_daily_revenue=("revenue", "mean")).reset_index()
    out["index_vs_11plus"] = out["avg_daily_units"] / out.loc[out["rank_bucket"] == "11+", "avg_daily_units"].iloc[0]
    return out


# 4 --------------------------------------------------------------------------
def ols(y: np.ndarray, X: pd.DataFrame) -> pd.DataFrame:
    Xm = np.column_stack([np.ones(len(X)), X.to_numpy(dtype=float)])
    beta, *_ = np.linalg.lstsq(Xm, y, rcond=None)
    resid = y - Xm @ beta
    dof = len(y) - Xm.shape[1]
    sigma2 = resid @ resid / dof
    se = np.sqrt(np.diag(sigma2 * np.linalg.pinv(Xm.T @ Xm)))
    r2 = 1 - (resid @ resid) / ((y - y.mean()) @ (y - y.mean()))
    out = pd.DataFrame({"term": ["intercept", *X.columns], "coef": beta, "se": se})
    out["t"] = out["coef"] / out["se"]
    out.attrs["r2"], out.attrs["n"] = r2, len(y)
    return out


def sales_drivers(t) -> pd.DataFrame:
    d = (t["fact_shelf"][t["fact_shelf"]["in_stock"]]
         .merge(t["fact_sales"], on=["date", "retailer_id", "sku"])
         .merge(t["dim_product"][["sku", "category"]], on="sku"))
    X = pd.DataFrame({
        "log_organic_rank": np.log(d["organic_rank"]),
        "log_price_index": np.log(d["price_index"]),
        "rating": d["rating"],
        "content_score_10pts": d["content_score"] / 10,
    })
    controls = pd.get_dummies(d[["retailer_id", "category"]].assign(month=d["date"].dt.month.astype(str)),
                              drop_first=True, dtype=float)
    res = ols(np.log1p(d["units"].to_numpy(dtype=float)), pd.concat([X, controls], axis=1))
    key = res[res["term"].isin(X.columns)].copy()
    labels = {
        "log_organic_rank": "Organic rank (elasticity: % sales change per 1% worse rank)",
        "log_price_index": "Price index vs competitors (price elasticity)",
        "rating": "Star rating (% sales change per +1 star)",
        "content_score_10pts": "Content score (% sales change per +10 points)",
    }
    key["meaning"] = key["term"].map(labels)
    key["effect"] = np.where(key["term"].str.startswith("log_"), key["coef"], np.expm1(key["coef"]))
    key.attrs = res.attrs
    return key


# 5 --------------------------------------------------------------------------
def response_curves(t) -> pd.DataFrame:
    """Fit log(ad_sales) = a + b*log(spend) on daily data per retailer x ad type (in-stock days)."""
    m = media_with_shelf(t)
    m = m[m["in_stock"] & (m["spend"] > 0)]
    daily = m.groupby(["date", "retailer_id", "ad_type"])[["spend", "ad_sales"]].sum().reset_index()
    daily = daily[daily["ad_sales"] > 0]
    rows = []
    for (rid, ad), g in daily.groupby(["retailer_id", "ad_type"]):
        b, a = np.polyfit(np.log(g["spend"]), np.log(g["ad_sales"]), 1)
        rows.append((rid, ad, len(g), a, b))
    curves = pd.DataFrame(rows, columns=["retailer_id", "ad_type", "days", "a", "b"])
    annual = media_kpis(t["fact_media"], ["retailer_id", "ad_type"])[["retailer_id", "ad_type", "spend", "ad_sales", "roas"]]
    curves = curves.merge(annual, on=["retailer_id", "ad_type"]).merge(t["dim_retailer"], on="retailer_id")
    curves["b"] = curves["b"].clip(0.05, 1.0)
    curves["marginal_roas"] = curves["b"] * curves["roas"]
    return curves


def reallocate(curves: pd.DataFrame, step: float = 0.005, max_change: float = 0.30) -> tuple[pd.DataFrame, dict]:
    """Greedy reallocation at constant total budget: repeatedly move a small slice of budget
    from the cell with the lowest marginal ROAS to the highest, using each cell's fitted
    curve sales(S) = sales0 * (S / S0) ** b, within +/- max_change of today's spend."""
    c = curves.copy()
    s0, r0, b = c["spend"].to_numpy(), c["ad_sales"].to_numpy(), c["b"].to_numpy()
    s = s0.copy()
    chunk = step * s0.sum()
    lo, hi = s0 * (1 - max_change), s0 * (1 + max_change)

    def mroas(sp):
        return b * r0 / s0 * (sp / s0) ** (b - 1)

    for _ in range(2000):
        mr = mroas(s)
        give = np.where(s - chunk >= lo, mr, np.inf).argmin()
        take = np.where(s + chunk <= hi, mr, -np.inf).argmax()
        if mr[take] <= mr[give] * 1.001 or give == take:
            break
        s[give] -= chunk
        s[take] += chunk
    new_sales = r0 * (s / s0) ** b
    c["new_spend"] = s
    c["spend_change_pct"] = s / s0 - 1
    c["new_ad_sales"] = new_sales
    summary = {"total_spend": s0.sum(), "sales_before": r0.sum(), "sales_after": new_sales.sum(),
               "uplift": new_sales.sum() - r0.sum(), "uplift_pct": new_sales.sum() / r0.sum() - 1}
    return c, summary


def price_effect(t) -> pd.DataFrame:
    m = media_with_shelf(t)
    sp = m[(m["ad_type"] == "Sponsored Products") & m["in_stock"]].copy()
    sp["price_band"] = pd.cut(sp["price_index"], [0, 0.95, 1.0, 1.05, 10],
                              labels=["<0.95 (cheaper)", "0.95-1.00", "1.00-1.05", ">1.05 (dearer)"])
    return media_kpis(sp, ["price_band"])[["price_band", "clicks", "cvr", "roas"]]


def run_all(t) -> dict:
    curves = response_curves(t)
    realloc, realloc_summary = reallocate(curves)
    return {
        "oos": oos_waste(t),
        "content": content_effect(t),
        "rank": rank_effect(t),
        "drivers": sales_drivers(t),
        "curves": realloc,
        "realloc": realloc_summary,
        "price": price_effect(t),
    }
