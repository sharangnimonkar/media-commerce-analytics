"""Charts, the Excel KPI scorecard and the markdown insights report."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

from . import config as C
from .kpis import media_kpis, retailer_scorecard, share_of_search, shelf_kpis

# Validated categorical palette (fixed order) and chart chrome
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"
RETAILER_ORDER = [v["name"] for v in C.RETAILERS.values()]
RETAILER_COLOR = dict(zip(RETAILER_ORDER, SERIES))
AD_COLOR = dict(zip(C.AD_TYPES, SERIES))

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": MUTED, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.axisbelow": True, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "axes.titleweight": "bold", "axes.titlesize": 12, "axes.titlecolor": INK, "axes.titlelocation": "left",
})


def _save(fig, name):
    C.FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(C.FIG_DIR / name, dpi=150)
    plt.close(fig)
    return f"figures/{name}"


def _bar_labels(ax, bars, fmt):
    for b in bars:
        ax.annotate(fmt(b.get_height()), (b.get_x() + b.get_width() / 2, b.get_height()),
                    ha="center", va="bottom", fontsize=8.5, color=INK2, xytext=(0, 2), textcoords="offset points")


def make_figures(t, r) -> dict[str, str]:
    figs = {}
    names = t["dim_retailer"].set_index("retailer_id")["retailer"]

    # 1. ROAS by retailer and ad type
    m = media_kpis(t["fact_media"], ["retailer_id", "ad_type"])
    m["retailer"] = m["retailer_id"].map(names)
    fig, ax = plt.subplots(figsize=(9, 4.2))
    w = 0.26
    x = np.arange(len(RETAILER_ORDER))
    for i, ad in enumerate(C.AD_TYPES):
        vals = [m.loc[(m["retailer"] == rn) & (m["ad_type"] == ad), "roas"].sum() or np.nan for rn in RETAILER_ORDER]
        bars = ax.bar(x + (i - 1) * w, vals, w - 0.03, color=AD_COLOR[ad], label=ad)
        _bar_labels(ax, bars, lambda v: "" if np.isnan(v) else f"{v:.1f}")
    ax.axhline(C.TARGETS["roas"][0], color=INK2, lw=1, ls="--")
    ax.text(len(x) - 0.55, C.TARGETS["roas"][0] + 0.1, "target 3.0", color=INK2, fontsize=8.5, ha="right")
    ax.set_xticks(x, RETAILER_ORDER)
    ax.set_ylabel("ROAS (£ attributed sales per £1)")
    sp_m = m[m["ad_type"] == "Sponsored Products"].set_index("retailer")["roas"]
    dis_m = m[m["ad_type"] == "Display"]["roas"]
    ax.set_title(f"Sponsored Products returns £{sp_m.min():.1f}-£{sp_m.max():.1f} per £1; Display only £{dis_m.min():.1f}-£{dis_m.max():.1f}")
    ax.legend(frameon=False, ncol=3, loc="upper right", bbox_to_anchor=(1, 1.02))
    figs["roas"] = _save(fig, "01_roas_by_retailer_adtype.png")

    # 2. Ad spend wasted on out-of-stock days
    o = r["oos"]["by_retailer"].set_index("retailer").reindex(RETAILER_ORDER)
    avail = r["oos"]["availability_by_retailer"].rename(index=names).reindex(RETAILER_ORDER)
    fig, ax = plt.subplots(figsize=(8, 3.8))
    bars = ax.bar(RETAILER_ORDER, o["spend"], 0.55, color=[RETAILER_COLOR[n] for n in RETAILER_ORDER])
    for b, a in zip(bars, avail):
        ax.annotate(f"£{b.get_height():,.0f}\navailability {a:.1%}", (b.get_x() + b.get_width() / 2, b.get_height()),
                    ha="center", va="bottom", fontsize=8.5, color=INK2, xytext=(0, 2), textcoords="offset points")
    ax.set_ylabel("Ad spend on out-of-stock days (£)")
    ax.set_ylim(0, o["spend"].max() * 1.3)
    ax.set_title("Ad spend kept running while products were out of stock")
    figs["oos"] = _save(fig, "02_oos_wasted_spend.png")

    # 3. Conversion by content band
    cb = r["content"]["bands"]
    fig, ax = plt.subplots(figsize=(6, 3.6))
    bars = ax.bar(cb["content_band"].astype(str), cb["cvr"] * 100, 0.55, color=SERIES[0])
    _bar_labels(ax, bars, lambda v: f"{v:.1f}%")
    ax.set_xlabel("Product page content score")
    ax.set_ylabel("Sponsored Products CVR (%)")
    ax.set_title("Better product pages convert more ad clicks")
    figs["content"] = _save(fig, "03_cvr_by_content_score.png")

    # 4. Units by organic rank bucket
    rk = r["rank"]
    fig, ax = plt.subplots(figsize=(6, 3.6))
    bars = ax.bar(rk["rank_bucket"].astype(str), rk["avg_daily_units"], 0.55, color=SERIES[0])
    _bar_labels(ax, bars, lambda v: f"{v:.0f}")
    ax.set_xlabel("Organic search rank on primary keyword")
    ax.set_ylabel("Avg daily units per SKU")
    lift = rk.loc[rk["rank_bucket"] == "1-3", "index_vs_11plus"].iloc[0]
    ax.set_title(f"Top-3 organic rank sells {lift:.1f}x the units of rank 11+")
    figs["rank"] = _save(fig, "04_units_by_organic_rank.png")

    # 5. Weekly share of search by retailer
    q = share_of_search(t["fact_search"], ["date", "retailer_id"])
    q["retailer"] = q["retailer_id"].map(names)
    fig, ax = plt.subplots(figsize=(9, 3.8))
    for rn in RETAILER_ORDER:
        s = q[q["retailer"] == rn].sort_values("date")
        roll = s["share_of_search"].rolling(4, min_periods=1).mean() * 100
        ax.plot(s["date"], roll, color=RETAILER_COLOR[rn], lw=2, label=rn)
        ax.annotate(rn, (s["date"].iloc[-1], roll.iloc[-1]), xytext=(4, 0), textcoords="offset points",
                    fontsize=8.5, color=INK2, va="center")
    ax.axhline(C.TARGETS["share_of_search"][0] * 100, color=INK2, lw=1, ls="--")
    ax.set_ylabel("Share of Search, top 10 (%)\n4-week rolling")
    q["h2"] = q["date"].dt.month >= 10
    h = q.groupby("h2")["share_of_search"].mean()
    ax.set_title(f"Share of Search rose from {h[False]:.0%} (Jan-Sep) to {h[True]:.0%} in Q4 as ad spend increased")
    ax.legend(frameon=False, ncol=4, loc="upper left")
    ax.set_xlim(right=q["date"].max() + pd.Timedelta(days=45))
    figs["sos"] = _save(fig, "05_share_of_search_trend.png")

    # 6. Budget reallocation
    c = r["curves"].copy()
    c["cell"] = c["retailer"] + " · " + c["ad_type"].str.replace("Sponsored ", "S. ")
    c = c.sort_values("spend_change_pct")
    fig, ax = plt.subplots(figsize=(8, 4.6))
    colors = [SERIES[0] if v > 0 else SERIES[1] for v in c["spend_change_pct"]]
    ax.barh(c["cell"], c["spend_change_pct"] * 100, color=colors, height=0.6)
    for y, (v, mr) in enumerate(zip(c["spend_change_pct"], c["marginal_roas"])):
        ax.annotate(f"{v:+.0%}  (mROAS {mr:.1f})", (v * 100, y), xytext=(4 if v > 0 else -4, 0),
                    textcoords="offset points", ha="left" if v > 0 else "right", va="center", fontsize=8, color=INK2)
    ax.axvline(0, color=MUTED, lw=0.8)
    ax.grid(axis="x", color=GRID)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(-55, 55)
    ax.set_xlabel("Recommended budget change (%), total budget unchanged")
    ax.set_title("Move budget from low to high marginal-ROAS placements")
    figs["realloc"] = _save(fig, "06_budget_reallocation.png")

    # 7. Conversion by price index
    pb = r["price"]
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    bars = ax.bar(pb["price_band"].astype(str), pb["cvr"] * 100, 0.55, color=SERIES[0])
    _bar_labels(ax, bars, lambda v: f"{v:.1f}%")
    ax.set_xlabel("Price index vs competitor average")
    ax.set_ylabel("Sponsored Products CVR (%)")
    ax.set_title(f"CVR drops from {pb['cvr'].iloc[0]:.0%} to {pb['cvr'].iloc[-1]:.0%} as our price rises vs competitors")
    figs["price"] = _save(fig, "07_cvr_by_price_index.png")
    return figs


# ------------------------------------------------------------------ Excel
HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
RAG_FILL = {"Green": PatternFill("solid", fgColor="C6EFCE"), "Amber": PatternFill("solid", fgColor="FFEB9C"),
            "Red": PatternFill("solid", fgColor="FFC7CE")}


def _header(ws, row=1):
    for cell in ws[row]:
        if cell.value is not None:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = HEADER_FILL
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _widths(ws, widths):
    for i, wdt in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = wdt


def _write_df(ws, df, start_row=1, formats=None):
    ws.append(list(df.columns)) if start_row == 1 else None
    for row in df.itertuples(index=False):
        ws.append([None if (isinstance(v, float) and np.isnan(v)) else v for v in row])
    for col, fmt in (formats or {}).items():
        idx = list(df.columns).index(col) + 1
        for cell in ws.iter_rows(min_row=2, min_col=idx, max_col=idx):
            cell[0].number_format = fmt


def write_excel(t, r, path):
    wb = Workbook()

    # Read me
    ws = wb.active
    ws.title = "Read Me"
    lines = [
        ("Brightleaf Retail Media & Digital Shelf Scorecard", True),
        ("Synthetic data for a fictional snack brand across four fictional online retailers, Jan-Dec 2025.", False),
        ("", False),
        ("KPI definitions", True),
        ("CTR = clicks / impressions;  CPC = spend / clicks;  CVR = conversions / clicks", False),
        ("ROAS = attributed ad sales / ad spend;  ACoS = spend / ad sales;  TACoS = spend / total retailer sales", False),
        ("Availability = share of days in stock;  Price index = our price / competitor average price", False),
        ("Share of Search = brand slots / top-10 search slots (paid = positions 1-3, organic = 4-10)", False),
        ("All ratios are ratios of sums at the reporting grain, not averages of daily ratios.", False),
        ("", False),
        ("Sheets", True),
        ("Retailer Scorecard - headline KPIs with RAG status against targets", False),
        ("Summary (formulas) - live SUMIFS summary; pick a month in cell B2", False),
        ("Monthly Media - source table for the formula summary", False),
        ("SKU Shelf Health - availability, rank, content, rating and price index by SKU x retailer, with actions", False),
        ("Budget Reallocation - fitted response curves and recommended budget shifts", False),
        ("Data Quality - every cleaning fix applied to the raw files", False),
    ]
    for text, bold in lines:
        ws.append([text])
        ws.cell(ws.max_row, 1).font = Font(bold=bold, size=14 if ws.max_row == 1 else 11)
    ws.column_dimensions["A"].width = 110

    # Retailer scorecard
    sc = retailer_scorecard(t)
    ws = wb.create_sheet("Retailer Scorecard")
    cols = [("retailer", "Retailer", None), ("revenue", "Total sales (£)", "£#,##0"), ("spend", "Ad spend (£)", "£#,##0"),
            ("tacos", "TACoS", "0.0%"), ("roas", "ROAS", "0.00"), ("ctr", "CTR", "0.00%"), ("cpc", "CPC (£)", "£0.00"),
            ("cvr", "CVR", "0.0%"), ("availability", "Availability", "0.0%"), ("share_of_search", "Share of Search", "0.0%"),
            ("pct_top10", "% days top-10 organic", "0.0%"), ("content_score", "Content score", "0.0"),
            ("avg_rating", "Avg rating", "0.00"), ("price_index", "Price index", "0.000")]
    ws.append([c[1] for c in cols])
    for _, row in sc.iterrows():
        ws.append([row[c[0]] for c in cols])
    _header(ws)
    for j, (key, _, fmt) in enumerate(cols, start=1):
        for i in range(2, ws.max_row + 1):
            cell = ws.cell(i, j)
            if fmt:
                cell.number_format = fmt
            if key in C.TARGETS:
                cell.fill = RAG_FILL.get(sc.iloc[i - 2][f"{key}_rag"], PatternFill())
    tr = ws.max_row + 2
    ws.cell(tr, 1, "Targets").font = Font(bold=True)
    for j, (key, _, fmt) in enumerate(cols, start=1):
        if key in C.TARGETS:
            target, direction = C.TARGETS[key]
            ws.cell(tr, j, target).number_format = fmt
            ws.cell(tr + 1, j, ">= target" if direction == "high" else "<= target")
    ws.cell(tr + 3, 1, "Green = meets target; Amber = within 10%; Red = more than 10% off target.").font = Font(italic=True)
    _widths(ws, [18] + [13] * (len(cols) - 1))
    ws.freeze_panes = "B2"

    # Monthly media source table
    fm = t["fact_media"].merge(t["dim_retailer"], on="retailer_id")
    fm["month"] = fm["date"].dt.strftime("%b")
    fm["month_num"] = fm["date"].dt.month
    mm = (fm.groupby(["month_num", "month", "retailer", "ad_type"])[["impressions", "clicks", "spend", "conversions", "ad_sales"]]
          .sum().reset_index().drop(columns="month_num"))
    ws_m = wb.create_sheet("Monthly Media")
    _write_df(ws_m, mm, formats={"spend": "£#,##0.00", "ad_sales": "£#,##0.00", "impressions": "#,##0", "clicks": "#,##0"})
    ref = f"A1:{get_column_letter(mm.shape[1])}{len(mm) + 1}"
    tbl = Table(displayName="MonthlyMedia", ref=ref)
    tbl.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws_m.add_table(tbl)
    _widths(ws_m, [8, 18, 20, 14, 10, 12, 12, 13])
    ws_m.freeze_panes = "A2"

    # Formula-driven summary
    ws = wb.create_sheet("Summary (formulas)", 2)
    ws["A1"], ws["A2"] = "Live retailer summary (SUMIFS over the Monthly Media table)", "Month:"
    ws["A1"].font = Font(bold=True, size=13)
    ws["B2"] = "All"
    ws["B2"].fill = PatternFill("solid", fgColor="FFF2CC")
    ws["C2"] = "<- choose All or a month"
    dv = DataValidation(type="list", formula1='"All,Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add("B2")
    heads = ["Retailer", "Impressions", "Clicks", "Spend (£)", "Conversions", "Ad sales (£)", "CTR", "CPC (£)", "CVR", "ROAS"]
    ws.append([])
    ws.append(heads)
    _header(ws, 4)
    crit = 'IF($B$2="All","*",$B$2)'
    src = {"Impressions": "MonthlyMedia[impressions]", "Clicks": "MonthlyMedia[clicks]", "Spend (£)": "MonthlyMedia[spend]",
           "Conversions": "MonthlyMedia[conversions]", "Ad sales (£)": "MonthlyMedia[ad_sales]"}
    for i, rn in enumerate(RETAILER_ORDER + ["Total"], start=5):
        ws.cell(i, 1, rn)
        for j, h in enumerate(heads[1:6], start=2):
            col = get_column_letter(j)
            if rn == "Total":
                ws.cell(i, j, f"=SUM({col}5:{col}{i - 1})")
            else:
                ws.cell(i, j, f"=SUMIFS({src[h]},MonthlyMedia[retailer],$A{i},MonthlyMedia[month],{crit})")
        ws.cell(i, 7, f"=IFERROR(C{i}/B{i},0)").number_format = "0.00%"
        ws.cell(i, 8, f"=IFERROR(D{i}/C{i},0)").number_format = "£0.00"
        ws.cell(i, 9, f"=IFERROR(E{i}/C{i},0)").number_format = "0.0%"
        ws.cell(i, 10, f"=IFERROR(F{i}/D{i},0)").number_format = "0.00"
        for j, fmt in zip(range(2, 7), ["#,##0", "#,##0", "£#,##0", "#,##0", "£#,##0"]):
            ws.cell(i, j).number_format = fmt
        if rn == "Total":
            for j in range(1, 11):
                ws.cell(i, j).font = Font(bold=True)
    ws.conditional_formatting.add("J5:J8", ColorScaleRule(start_type="min", start_color="F8696B",
                                                          mid_type="percentile", mid_value=50, mid_color="FFEB84",
                                                          end_type="max", end_color="63BE7B"))
    _widths(ws, [20, 14, 11, 12, 12, 13, 9, 9, 9, 9])

    # SKU shelf health
    s = shelf_kpis(t["fact_shelf"], ["retailer_id", "sku"]).merge(t["dim_retailer"], on="retailer_id") \
        .merge(t["dim_product"][["sku", "product_name", "category"]], on="sku")

    def action(row):
        acts = []
        if row["availability"] < 0.92:
            acts.append("Fix supply / pause ads when OOS")
        if row["content_score"] < 70:
            acts.append("Upgrade product page content")
        if row["price_index"] > 1.05:
            acts.append("Review price vs competitors")
        if row["avg_rating"] < 4.0:
            acts.append("Review ratings & reviews")
        return "; ".join(acts) or "-"
    s["action"] = s.apply(action, axis=1)
    out = s[["retailer", "category", "sku", "product_name", "availability", "avg_organic_rank", "pct_top10",
             "content_score", "avg_rating", "price_index", "action"]].sort_values(["retailer", "sku"])
    ws = wb.create_sheet("SKU Shelf Health")
    _write_df(ws, out, formats={"availability": "0.0%", "pct_top10": "0.0%", "avg_organic_rank": "0.0",
                                "content_score": "0", "avg_rating": "0.00", "price_index": "0.000"})
    _header(ws)
    n = len(out) + 1
    ws.conditional_formatting.add(f"E2:E{n}", ColorScaleRule(start_type="min", start_color="F8696B", end_type="max", end_color="63BE7B"))
    ws.conditional_formatting.add(f"H2:H{n}", ColorScaleRule(start_type="min", start_color="F8696B", end_type="max", end_color="63BE7B"))
    ws.conditional_formatting.add(f"F2:F{n}", ColorScaleRule(start_type="min", start_color="63BE7B", end_type="max", end_color="F8696B"))
    ws.auto_filter.ref = f"A1:K{n}"
    ws.freeze_panes = "E2"
    _widths(ws, [18, 10, 12, 28, 12, 12, 12, 11, 10, 10, 60])

    # Budget reallocation
    c = r["curves"][["retailer", "ad_type", "spend", "ad_sales", "roas", "b", "marginal_roas", "new_spend",
                     "spend_change_pct", "new_ad_sales"]].rename(columns={"b": "saturation_b"})
    ws = wb.create_sheet("Budget Reallocation")
    _write_df(ws, c, formats={"spend": "£#,##0", "ad_sales": "£#,##0", "roas": "0.00", "saturation_b": "0.00",
                              "marginal_roas": "0.00", "new_spend": "£#,##0", "spend_change_pct": "+0%;-0%", "new_ad_sales": "£#,##0"})
    _header(ws)
    ws.append([])
    ws.append(["Total", None, f"=SUM(C2:C{len(c) + 1})", f"=SUM(D2:D{len(c) + 1})", None, None, None,
               f"=SUM(H2:H{len(c) + 1})", None, f"=SUM(J2:J{len(c) + 1})"])
    for j in (3, 4, 8, 10):
        ws.cell(ws.max_row, j).number_format = "£#,##0"
    ws.cell(ws.max_row, 1).font = Font(bold=True)
    ws.append(["Uplift in attributed ad sales", None, None, None, None, None, None, None, None,
               f"=J{ws.max_row}/D{ws.max_row}-1"])
    ws.cell(ws.max_row, 10).number_format = "+0.0%"
    _widths(ws, [18, 20, 12, 12, 8, 12, 13, 12, 14, 13])

    # Data quality
    ws = wb.create_sheet("Data Quality")
    _write_df(ws, t["dq_log"])
    _header(ws)
    _widths(ws, [30, 60, 15])

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


# ------------------------------------------------------------------ Markdown report
def _gbp(v):
    return f"£{v:,.0f}"


def write_insights(t, r, figs, path):
    sc = retailer_scorecard(t).set_index("retailer")
    o, c, rk, d, re_ = r["oos"], r["content"], r["rank"], r["drivers"], r["realloc"]
    curves = r["curves"]
    total_sales, total_spend = sc["revenue"].sum(), sc["spend"].sum()
    mk = media_kpis(t["fact_media"])
    sos = share_of_search(t["fact_search"]).iloc[0]
    best = curves.sort_values("marginal_roas", ascending=False).iloc[0]
    cells = curves.assign(cell=curves["retailer"] + " " + curves["ad_type"])
    ups = ", ".join(f"{x.cell} ({x.spend_change_pct:+.0%})" for x in cells[cells["spend_change_pct"] > 0.05]
                    .sort_values("spend_change_pct", ascending=False).itertuples())
    downs = ", ".join(f"{x.cell} ({x.spend_change_pct:+.0%})" for x in cells[cells["spend_change_pct"] < -0.05]
                      .sort_values("spend_change_pct").itertuples())
    worst = curves.sort_values("marginal_roas").iloc[0]
    top_oos = o["by_retailer"].iloc[0]
    rank_top = rk.loc[rk["rank_bucket"] == "1-3", "index_vs_11plus"].iloc[0]
    coef = d.set_index("term")["effect"]
    pb = r["price"].set_index("price_band")["cvr"]

    scorecard_md = sc[["revenue", "spend", "roas", "availability", "share_of_search", "content_score", "price_index",
                       "roas_rag", "availability_rag", "share_of_search_rag"]].copy()
    rows = ["| Retailer | Sales | Ad spend | ROAS | Availability | Share of Search | Content | Price index |",
            "|---|---:|---:|---:|---:|---:|---:|---:|"]
    icon = {"Green": "🟢", "Amber": "🟠", "Red": "🔴"}
    for rn, x in scorecard_md.iterrows():
        rows.append(f"| {rn} | {_gbp(x.revenue)} | {_gbp(x.spend)} | {icon[x.roas_rag]} {x.roas:.2f} | "
                    f"{icon[x.availability_rag]} {x.availability:.1%} | {icon[x.share_of_search_rag]} {x.share_of_search:.1%} | "
                    f"{x.content_score:.0f} | {x.price_index:.3f} |")

    md = f"""# Brightleaf: Retail Media & Digital Shelf Performance Review (FY2025)

> **Synthetic data.** Brightleaf and all retailers are fictional. The data was generated to
> mirror real retail media and digital shelf exports so the analysis methods can be shown end to end.

## Executive summary

Brightleaf sold **{_gbp(total_sales)}** across four online retailers in 2025 and spent **{_gbp(total_spend)}** on
retail media (TACoS {total_spend / total_sales:.1%}). Blended ROAS was **{mk['roas'].iloc[0]:.2f}** against a 3.0 target,
with CTR {mk['ctr'].iloc[0]:.2%}, CPC £{mk['cpc'].iloc[0]:.2f} and CVR {mk['cvr'].iloc[0]:.1%}.
Share of Search averaged **{sos['share_of_search']:.1%}** (paid {sos['paid_sos']:.1%}, organic {sos['organic_sos']:.1%}),
below the 25% target.

**Five recommendations**

1. **Reallocate media budget at constant spend: about +{re_['uplift_pct']:.0%} attributed sales ({_gbp(re_['uplift'])}).**
   The best marginal return is {best['retailer']} {best['ad_type']} (mROAS {best['marginal_roas']:.1f}); the weakest is
   {worst['retailer']} {worst['ad_type']} (mROAS {worst['marginal_roas']:.1f}). Increase: {ups}. Reduce: {downs}.
2. **Pause ads automatically when a SKU is out of stock: saves {_gbp(o['oos_spend'])} a year ({o['oos_spend_share']:.1%} of spend).**
   ROAS on out-of-stock days was {o['roas_oos']:.2f} vs {o['roas_in_stock']:.2f} in stock. {top_oos['retailer']} wasted the most
   ({_gbp(top_oos['spend'])}); its availability needs a supply fix as well.
3. **Roll out the content upgrade programme.** The {c['n_upgraded']} listings upgraded in July grew sales
   **{c['did_sales_lift']:+.0%}** more than unchanged listings (difference-in-differences), and ad CVR rose
   {c['did_cvr_pts'] * 100:+.1f} pts. Listings scoring under 70 convert at {c['bands']['cvr'].iloc[0]:.1%} vs {c['bands']['cvr'].iloc[2]:.1%} for 85+.
4. **Protect organic rank.** Top-3 organic positions sell **{rank_top:.1f}x** the units of rank 11+. Out-of-stock spells push rank
   down, so fixing availability also protects organic visibility.
5. **Watch price gaps.** Sponsored Products CVR falls from {pb.iloc[0]:.1%} when we are >5% cheaper than competitors to
   {pb.iloc[-1]:.1%} when we are >5% dearer. The driver model gives a price elasticity of {coef['log_price_index']:.1f}.

## Retailer scorecard

{chr(10).join(rows)}

🟢 meets target · 🟠 within 10% · 🔴 more than 10% off. Full detail, a formula-driven summary and SKU-level actions are in
`KPI_Scorecard.xlsx`.

## Findings

### 1. Media effectiveness by retailer and ad type
![ROAS]({figs['roas']})

### 2. Out-of-stock ad waste
![OOS]({figs['oos']})

### 3. Content quality and conversion
![Content]({figs['content']})

### 4. Organic rank and sales
![Rank]({figs['rank']})

### 5. Share of Search
![SoS]({figs['sos']})

### 6. Price competitiveness
![Price]({figs['price']})

### 7. Budget reallocation
![Reallocation]({figs['realloc']})

Each retailer x ad type cell has a fitted response curve, ad sales = a · spend^b, from daily in-stock data. Marginal ROAS
(b x ROAS) is the return on the next £1. A greedy optimiser moves budget from the lowest to the highest marginal ROAS,
keeping total spend fixed and each cell within ±30% of today's spend so it does not extrapolate beyond observed data.

## Sales driver model

OLS on log daily units (in-stock days, n = {d.attrs['n']:,}, R² = {d.attrs['r2']:.2f}), controlling for retailer,
category and month:

| Driver | Effect | Std. error |
|---|---:|---:|
""" + "\n".join(f"| {row.meaning} | {row.effect:+.2f} | {row.se:.3f} |" if row.term.startswith("log_")
                else f"| {row.meaning} | {row.effect:+.0%} | {row.se:.3f} (log scale) |" for row in d.itertuples()) + """

## Method and caveats

- **Pipeline:** 4 retailer media exports with different schemas, a digital shelf export, EPOS sell-out and weekly search
  snapshots, consolidated into a star schema (`data/processed`) that feeds both this report and Power BI.
- **Attributed is not incremental.** Retailer-attributed ad sales overstate true incrementality. Validate the reallocation
  with a geo or retailer-level holdout test before scaling it.
- **Observational model.** The driver coefficients are associations with controls, not causal effects. The content
  difference-in-differences is the strongest causal evidence here.
- **Response curves** use daily variation in spend. Big moves outside the observed spend range need testing.
"""
    path.write_text(md, encoding="utf-8")
