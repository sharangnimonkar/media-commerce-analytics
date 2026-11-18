import pandas as pd
import pytest

from mca import analysis, clean, generate


def test_parse_money():
    s = pd.Series(["£1,234.50", "99", None, "£0.00"])
    out = clean.parse_money(s)
    assert out.iloc[0] == pytest.approx(1234.5)
    assert out.iloc[1] == 99
    assert pd.isna(out.iloc[2])
    assert out.iloc[3] == 0


@pytest.mark.parametrize("name,rid", [("Shop Mart", "R1"), ("SHOPMART ", "R1"), ("fresh co", "R2"),
                                      ("Quick Basket", "R3"), ("Megastore", "R4"), ("MegaStore Online UK", "R4")])
def test_retailer_aliases(name, rid):
    assert clean.retailer_id(name) == rid


def test_unknown_retailer_raises():
    with pytest.raises(ValueError):
        clean.retailer_id("Some Other Shop")


@pytest.fixture(scope="module")
def tables(tmp_path_factory):
    raw = tmp_path_factory.mktemp("raw")
    out = tmp_path_factory.mktemp("processed")
    generate.write_raw(generate.simulate("2025-01-01", "2025-08-31"), raw)
    return clean.run(raw, out)


def test_clean_removes_injected_problems(tables):
    m, s = tables["fact_media"], tables["fact_shelf"]
    assert not m.duplicated().any()
    assert (m["impressions"] >= 0).all()
    assert m["ad_sales"].notna().all()
    assert set(m["ad_type"]) == {"Sponsored Products", "Sponsored Brands", "Display"}
    assert m["sku"].str.match(r"^BL-[A-Z]{2}-\d{3}$").all()
    assert not s.duplicated(["date", "retailer_id", "sku"]).any()
    assert s["rating"].notna().all()
    issues = " ".join(tables["dq_log"]["issue"])
    assert "duplicate" in issues and "negative impressions" in issues


def test_star_schema_keys_join(tables):
    for f in ["fact_media", "fact_shelf", "fact_sales"]:
        assert tables[f]["sku"].isin(tables["dim_product"]["sku"]).all()
        assert tables[f]["retailer_id"].isin(tables["dim_retailer"]["retailer_id"]).all()
        assert tables[f]["date"].isin(tables["dim_date"]["date"]).all()


def test_analysis_finds_planted_effects(tables):
    r = analysis.run_all(tables)
    assert r["oos"]["roas_oos"] < 0.3 * r["oos"]["roas_in_stock"]       # OOS days waste spend
    bands = r["content"]["bands"]["cvr"].to_numpy()
    assert bands[0] < bands[1] < bands[2]                                 # better content converts more
    assert r["content"]["did_sales_lift"] > 0.10                          # upgrade programme works
    d = r["drivers"].set_index("term")["coef"]
    assert d["log_organic_rank"] < 0 and d["log_price_index"] < -1
    assert r["realloc"]["uplift"] > 0
    assert abs(r["curves"]["new_spend"].sum() - r["curves"]["spend"].sum()) < 1e-6   # budget held constant
