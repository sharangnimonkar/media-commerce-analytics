"""Generate synthetic retail media, digital shelf, sell-out and search-rank data.

The generator builds one "true" daily dataset with known relationships (out-of-stock
days waste ad spend, better content lifts conversion, better organic rank lifts sales)
and then writes it out as messy raw exports, the way real files arrive: one media
file per retailer with its own column names and formats, a digital shelf tool export,
an EPOS sell-out file and weekly search-rank snapshots.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C


def _season(dates: pd.DatetimeIndex, category: str) -> np.ndarray:
    weekday = np.array([0.92, 0.90, 0.93, 0.97, 1.08, 1.15, 1.05])[dates.dayofweek]
    month = np.array([0.90, 0.88, 0.95, 0.98, 1.02, 1.05, 1.08, 1.07, 0.98, 1.00, 1.08, 1.30])[dates.month - 1]
    if category == "Popcorn":  # summer and movie-night lift
        month = month * np.where(dates.month.isin([6, 7, 8, 12]), 1.10, 1.0)
    if category == "Bars":  # January health kick
        month = month * np.where(dates.month == 1, 1.25, 1.0)
    return weekday * month


def _promo_weeks(rng, n_days: int) -> np.ndarray:
    """1-week promotions roughly every 6-8 weeks."""
    promo = np.zeros(n_days, dtype=bool)
    day = int(rng.integers(5, 30))
    while day < n_days:
        promo[day:day + 7] = True
        day += int(rng.integers(42, 57))
    return promo


def simulate(start: str = C.START_DATE, end: str = C.END_DATE, seed: int = C.SEED) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, end, freq="D")
    n = len(dates)
    july = dates >= pd.Timestamp("2025-07-01")

    # Pick 6 sku-retailer pairs that get a content optimisation project from 1 July
    pairs = [(r, p[0]) for r in C.RETAILERS for p in C.PRODUCTS]
    treated = {pairs[i] for i in rng.choice(len(pairs), size=6, replace=False)}

    shelf_rows, media_rows = [], []
    for rid, rcfg in C.RETAILERS.items():
        promo = _promo_weeks(rng, n)
        for sku, cat, name, rrp, base_units in C.PRODUCTS:
            # --- content score, with a step change for treated pairs
            content = np.full(n, rng.uniform(55, 88))
            if (rid, sku) in treated:
                content = np.where(july, np.minimum(content + rng.uniform(14, 20), 97), content)
            content = np.clip(content + rng.normal(0, 1.0, n), 30, 100).round(0)

            # --- rating: slow random walk around a product-level mean
            rating = np.clip(rng.normal(4.2, 0.25) + np.cumsum(rng.normal(0, 0.004, n)), 3.2, 4.9).round(2)

            # --- availability: two-state Markov chain (mean out-of-stock spell = 3 days)
            p_out, p_back = rcfg["oos"] / 3 * rng.uniform(0.6, 1.6), 1 / 3
            in_stock = np.ones(n, dtype=bool)
            for t in range(1, n):
                in_stock[t] = (rng.random() > p_out) if in_stock[t - 1] else (rng.random() < p_back)

            # --- price and competitor price
            price = np.round(rrp * rcfg["price_factor"] * np.where(promo, 0.80, 1.0), 2)
            comp_price = np.round(rrp * rng.uniform(0.90, 1.06) * (1 + rng.normal(0, 0.01, n)), 2)
            price_index = price / comp_price

            # --- organic rank: AR(1) towards a target that depends on content; drops when out of stock
            target = 3 + 14 * (1 - content / 100) + rng.uniform(-1, 4)
            rank = np.empty(n)
            rank[0] = target[0]
            for t in range(1, n):
                penalty = 8 if not in_stock[t] else 0
                rank[t] = 0.85 * rank[t - 1] + 0.15 * (target[t] + penalty) + rng.normal(0, 0.8)
            organic_rank = np.clip(np.round(rank), 1, 40).astype(int)

            # --- organic demand
            mu = (base_units * rcfg["traffic"] * _season(dates, cat)
                  * 1.8 * organic_rank ** -0.45
                  * price_index ** -2.0
                  * np.exp(1.2 * (rating - 4.2))
                  * (1 + 0.004 * (content - 75))
                  * np.where(in_stock, 1.0, 0.03)
                  * rng.lognormal(0, 0.15, n))
            organic_units = rng.poisson(mu)

            # --- media: planned budgets do NOT react to stock outs (that is the waste we want to find)
            ad_conv_total = np.zeros(n, dtype=int)
            paid_rank = np.full(n, np.nan)
            for ad_type in C.AD_TYPES:
                if ad_type == "Sponsored Brands" and sku[-3:] not in ("001", "002"):
                    continue  # brand campaigns only run on hero SKUs
                if ad_type == "Display" and rid == "R3":
                    continue  # QuickBasket has no display inventory
                base_budget = {"Sponsored Products": 4.0, "Sponsored Brands": 3.0, "Display": 4.0}[ad_type]
                budget = base_budget * (base_units / 20) ** 0.6 * rcfg["traffic"] ** 0.5
                q4 = np.where(dates.month >= 10, 1.35, 1.0)
                on = np.ones(n, dtype=bool)
                if ad_type == "Display":  # flighted: 4 weeks on, 4 weeks off
                    on = ((np.arange(n) // 28) % 2) == 0
                spend = np.round(budget * q4 * rng.lognormal(0, 0.25, n) * on, 2)

                cpm = rcfg["cpm"] * {"Sponsored Products": 1.0, "Sponsored Brands": 0.9, "Display": 0.6}[ad_type]
                # diminishing returns: impressions grow with spend^saturation around the base budget
                impressions = rng.poisson(budget / cpm * 1000 * (spend / budget) ** rcfg["saturation"])
                ctr = ({"Sponsored Products": 0.0060, "Sponsored Brands": 0.0045, "Display": 0.0030}[ad_type]
                       * (1 + 0.5 * (rating - 4.2)) * (1 + 0.006 * (content - 75)))
                clicks = rng.binomial(impressions, np.clip(ctr, 0, 1))
                cvr = ({"Sponsored Products": 0.28, "Sponsored Brands": 0.20, "Display": 0.10}[ad_type]
                       * rcfg["cvr_bias"] * price_index ** -2.5 * (1 + 0.012 * (content - 75))
                       * np.where(in_stock, 1.0, 0.05))
                conversions = rng.binomial(clicks, np.clip(cvr, 0, 1))
                ad_units = np.round(conversions * rng.uniform(2.0, 3.5, n)).astype(int)  # units per order
                ad_sales = np.round(ad_units * price, 2)
                ad_conv_total += ad_units
                if ad_type == "Sponsored Products":
                    rel = spend / max(np.median(spend[spend > 0]), 0.01)
                    paid_rank = np.where(spend > 0, np.clip(np.round(4 - 2 * np.log1p(rel) + rng.normal(0, 0.7, n)), 1, 8), np.nan)

                media_rows.append(pd.DataFrame({
                    "date": dates, "retailer_id": rid, "sku": sku, "category": cat, "ad_type": ad_type,
                    "campaign": f"{C.BRAND}_{rcfg['name'].replace(' ', '')}_{''.join(w[0] for w in ad_type.split())}_{cat}",
                    "impressions": impressions, "clicks": clicks, "spend": spend,
                    "conversions": conversions, "ad_sales": ad_sales,
                })[on])

            units = organic_units + ad_conv_total
            shelf_rows.append(pd.DataFrame({
                "date": dates, "retailer_id": rid, "sku": sku, "category": cat, "product_name": name,
                "in_stock": in_stock, "price": price, "rrp": rrp, "competitor_price": comp_price,
                "organic_rank": organic_rank, "paid_rank": paid_rank, "content_score": content,
                "rating": rating, "units": units, "revenue": np.round(units * price, 2),
                "content_project": (rid, sku) in treated,
            }))

    shelf = pd.concat(shelf_rows, ignore_index=True)
    shelf["review_count"] = (shelf.groupby(["retailer_id", "sku"])["units"].cumsum() * 0.02 + 40).astype(int)
    media = pd.concat(media_rows, ignore_index=True)
    search = _search_snapshots(rng, shelf, media)
    return {"shelf": shelf, "media": media, "search": search}


def _search_snapshots(rng, shelf: pd.DataFrame, media: pd.DataFrame) -> pd.DataFrame:
    """Weekly top-10 search results per keyword: positions 1-3 sponsored, 4-10 organic."""
    mondays = shelf["date"][shelf["date"].dt.dayofweek == 0].unique()
    sp = media[media["ad_type"] == "Sponsored Products"].groupby(["date", "retailer_id", "category"])["spend"].sum()
    sp_ref = sp.groupby(["retailer_id", "category"]).median()
    top = shelf.assign(top7=shelf["organic_rank"] <= 7).groupby(["date", "retailer_id", "category"])["top7"].sum()
    rows = []
    for d in mondays:
        for rid in C.RETAILERS:
            for cat, keywords in C.CATEGORIES.items():
                spend = sp.get((d, rid, cat), 0.0)
                p_paid = min(0.85, 0.35 * spend / max(sp_ref.get((rid, cat), 1.0), 0.01))
                for kw in keywords:
                    n_paid = rng.binomial(3, p_paid)
                    n_org = int(np.clip(top.get((d, rid, cat), 0) + rng.integers(-1, 2), 0, 4))
                    paid = [C.BRAND] * n_paid + list(rng.choice(C.COMPETITORS, 3 - n_paid))
                    org = [C.BRAND] * n_org + list(rng.choice(C.COMPETITORS, 7 - n_org))
                    rng.shuffle(paid)
                    rng.shuffle(org)
                    for pos, brand in enumerate(paid + org, start=1):
                        rows.append((d, rid, kw, pos, brand, pos <= 3))
    return pd.DataFrame(rows, columns=["date", "retailer_id", "keyword", "position", "brand", "sponsored"])


# ---------------------------------------------------------------- raw exports
MEDIA_SCHEMAS = {
    "R1": {"date": "Date", "campaign": "Campaign Name", "ad_type": "Ad Type", "sku": "SKU", "impressions": "Impressions",
           "clicks": "Clicks", "spend": "Spend (GBP)", "conversions": "Orders", "ad_sales": "Sales (GBP)", "_datefmt": "%Y-%m-%d"},
    "R2": {"date": "date", "campaign": "campaign", "ad_type": "format", "sku": "product_code", "impressions": "impr",
           "clicks": "clicks", "spend": "cost", "conversions": "conversions", "ad_sales": "revenue", "_datefmt": "%d/%m/%Y"},
    "R3": {"date": "Day", "campaign": "Campaign", "ad_type": "Placement", "sku": "Item ID", "impressions": "Views",
           "clicks": "Taps", "spend": "Spend", "conversions": "Purchases", "ad_sales": "Attributed Revenue", "_datefmt": "%d-%b-%Y"},
    "R4": {"date": "Date", "campaign": "Campaign Name", "ad_type": "Ad Type", "sku": "SKU", "impressions": "Impressions",
           "clicks": "Clicks", "spend": "Spend (GBP)", "conversions": "Orders", "ad_sales": "Sales (GBP)", "_datefmt": "%Y-%m-%d"},
}
RETAILER_VARIANTS = {
    "R1": ["ShopMart", "shopmart", "Shop Mart", "SHOPMART "],
    "R2": ["FreshCo", "Freshco", "fresh co"],
    "R3": ["QuickBasket", "Quick Basket", "quickbasket"],
    "R4": ["MegaStore Online", "Megastore", "MegaStore Online UK"],
}


def write_raw(data: dict[str, pd.DataFrame], out: Path = C.RAW_DIR, seed: int = C.SEED) -> None:
    rng = np.random.default_rng(seed + 1)
    out.mkdir(parents=True, exist_ok=True)

    for rid, schema in MEDIA_SCHEMAS.items():
        m = data["media"][data["media"]["retailer_id"] == rid].copy()
        m["date"] = m["date"].dt.strftime(schema["_datefmt"])
        if rid == "R2":  # currency strings and lower-case ad formats
            m["spend"] = m["spend"].map(lambda v: f"£{v:,.2f}")
            m["ad_type"] = m["ad_type"].str.lower()
        if rid == "R3":  # lower-case item ids
            m["sku"] = m["sku"].str.lower()
        if rid == "R4":  # duplicated rows, negative impressions, missing sales
            m = pd.concat([m, m.sample(frac=0.01, random_state=1)])
            bad = m.sample(n=12, random_state=2).index
            m.loc[bad, "impressions"] = -m.loc[bad, "impressions"]
            m["ad_sales"] = m["ad_sales"].astype("float64")
            m.loc[m.sample(n=30, random_state=3).index, "ad_sales"] = np.nan
        cols = {k: v for k, v in schema.items() if not k.startswith("_")}
        m = m[list(cols)].rename(columns=cols)
        name = C.RETAILERS[rid]["name"].lower().replace(" ", "_")
        m.to_csv(out / f"media_{name}.csv", index=False)

    s = data["shelf"].copy()
    s["retailer"] = [rng.choice(RETAILER_VARIANTS[r]) for r in s["retailer_id"]]
    s["availability"] = np.where(s["in_stock"], "In Stock", rng.choice(["Out of Stock", "OOS"], len(s)))
    s.loc[s.sample(frac=0.02, random_state=4).index, "rating"] = np.nan
    s = pd.concat([s, s.sample(frac=0.005, random_state=5)])
    s["capture_date"] = s["date"].dt.strftime("%Y-%m-%d")
    s[["capture_date", "retailer", "sku", "product_name", "availability", "price", "rrp", "competitor_price",
       "organic_rank", "paid_rank", "content_score", "rating", "review_count"]].rename(columns={
        "price": "price_gbp", "rrp": "rrp_gbp", "competitor_price": "competitor_avg_price"}
    ).to_csv(out / "digital_shelf_export.csv", index=False)

    e = data["shelf"][["date", "retailer_id", "sku", "units", "revenue"]].copy()
    e["retailer_name"] = e["retailer_id"].map(lambda r: C.RETAILERS[r]["name"])
    e["date"] = e["date"].dt.strftime("%Y-%m-%d")
    e.rename(columns={"units": "units_sold", "revenue": "gross_sales_gbp"})[
        ["date", "retailer_name", "sku", "units_sold", "gross_sales_gbp"]].to_csv(out / "epos_sellout.csv", index=False)

    q = data["search"].copy()
    q["retailer"] = q["retailer_id"].map(lambda r: C.RETAILERS[r]["name"])
    q["snapshot_date"] = q["date"].dt.strftime("%Y-%m-%d")
    q["sponsored"] = np.where(q["sponsored"], "Y", "N")
    q[["snapshot_date", "retailer", "keyword", "position", "brand", "sponsored"]].to_csv(out / "search_rank_snapshots.csv", index=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default=C.START_DATE)
    ap.add_argument("--end", default=C.END_DATE)
    ap.add_argument("--out", type=Path, default=C.RAW_DIR)
    a = ap.parse_args(argv)
    write_raw(simulate(a.start, a.end), a.out)
    print(f"Raw files written to {a.out}")


if __name__ == "__main__":
    main()
