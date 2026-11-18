# Power BI dashboard: build guide

The Python pipeline writes a star schema to `data/processed/`. This guide turns it into a
5-page Power BI report. A `.pbix` file is not included: build it once in Power BI Desktop
(about 1-2 hours), then save it as `powerbi/Brightleaf_Dashboard.pbix` and add page screenshots
to `powerbi/screenshots/` for the GitHub README.

## 1. Load the data

*Get Data → Text/CSV*, load each file from `data/processed/`:

| Table | Grain | Key columns |
|---|---|---|
| `fact_media` | day x retailer x SKU x ad type | date, retailer_id, sku, ad_type |
| `fact_shelf` | day x retailer x SKU | date, retailer_id, sku |
| `fact_sales` | day x retailer x SKU | date, retailer_id, sku |
| `fact_search` | week x retailer x keyword x position | date, retailer_id, keyword |
| `dim_date` | day | date |
| `dim_retailer` | retailer | retailer_id |
| `dim_product` | SKU | sku |
| `dim_keyword` | keyword | keyword |

In Power Query, set `date` columns to **Date**, `in_stock` / `on_promo` / `sponsored` / `is_brand`
to **True/False**, and money columns to **Fixed decimal**. Mark `dim_date` as the date table.

## 2. Relationships (single direction, one-to-many)

```
dim_date[date]            1 ─── * fact_media[date], fact_shelf[date], fact_sales[date], fact_search[date]
dim_retailer[retailer_id] 1 ─── * fact_media, fact_shelf, fact_sales, fact_search
dim_product[sku]          1 ─── * fact_media, fact_shelf, fact_sales
dim_keyword[keyword]      1 ─── * fact_search
```

Sort `dim_date[month]` by `dim_date[month_num]`.

## 3. Measures

Create a blank table `_Measures` and paste the measures from [`measures.dax`](measures.dax).
Format: CTR/CVR/ACoS/TACoS/Availability/SoS as %, CPC/Spend/Sales as £, ROAS as 0.00.

## 4. Report pages

Shared slicer row at the top of every page: **Date range** (`dim_date[date]`), **Retailer**, **Category**.
Sync slicers across pages.

| Page | Visuals |
|---|---|
| **1. Executive Overview** | KPI cards: Total Sales, Ad Spend, ROAS, TACoS, Availability %, Share of Search. Line chart: Total Sales and Ad Spend by month (two separate charts, not a dual axis). Table: retailer scorecard with RAG colours (conditional formatting → Field value → `RAG Colour …` measures). |
| **2. Media Performance** | Clustered bar: ROAS by retailer and ad type, with a constant line at 3.0. Matrix: retailer × ad type with Impressions, CTR, CPC, CVR, ROAS. Scatter: Ad Spend vs ROAS by SKU (size = Ad Sales). Card: OOS Ad Spend and OOS Spend %. |
| **3. Digital Shelf Health** | Matrix: SKU × retailer, showing Availability % (red-to-green background), Avg Organic Rank, Avg Content Score, Avg Rating, Price Index. Line: Availability % by week per retailer. Column: Total Units by organic-rank bucket (calculated column on `fact_shelf`). |
| **4. Share of Search** | Line: Share of Search by week per retailer, with a constant line at 25%. Stacked bar: Paid SoS vs Organic SoS by keyword. Table: keyword × brand slot counts (all brands, so competitors are visible). |
| **5. SKU Drill-through** | Drill-through on `dim_product[sku]`: daily units, price vs competitor price, organic rank, in-stock flag and ad spend for one SKU. |

## 5. Optional: rank bucket column

```DAX
Rank Bucket =
SWITCH ( TRUE (),
    fact_shelf[organic_rank] <= 3, "1-3",
    fact_shelf[organic_rank] <= 6, "4-6",
    fact_shelf[organic_rank] <= 10, "7-10",
    "11+" )
```

## 6. Check your numbers

Your Power BI totals should match the Python outputs in `reports/insights.md` and
`reports/KPI_Scorecard.xlsx` (for example, total ROAS and each retailer's availability).
