import numpy as np
import pandas as pd
import pytest

from mca import kpis


def test_ratios_are_ratio_of_sums_not_mean_of_ratios():
    df = pd.DataFrame({"g": ["a", "a"], "impressions": [1000, 10], "clicks": [10, 5],
                       "spend": [100.0, 1.0], "conversions": [2, 1], "ad_sales": [400.0, 10.0]})
    out = kpis.media_kpis(df, ["g"]).iloc[0]
    assert out["roas"] == pytest.approx(410 / 101)      # not mean(4.0, 10.0) = 7.0
    assert out["ctr"] == pytest.approx(15 / 1010)
    assert out["cpc"] == pytest.approx(101 / 15)
    assert out["cvr"] == pytest.approx(3 / 15)
    assert out["acos"] == pytest.approx(101 / 410)


def test_zero_denominator_gives_nan_not_error():
    df = pd.DataFrame({"impressions": [0], "clicks": [0], "spend": [0.0], "conversions": [0], "ad_sales": [0.0]})
    out = kpis.media_kpis(df).iloc[0]
    assert np.isnan(out["ctr"]) and np.isnan(out["roas"])


def test_share_of_search_split():
    df = pd.DataFrame({"r": ["x"] * 10, "position": range(1, 11),
                       "sponsored": [True] * 3 + [False] * 7,
                       "is_brand": [True, False, False, True, True, False, False, False, False, False]})
    out = kpis.share_of_search(df, ["r"]).iloc[0]
    assert out["share_of_search"] == pytest.approx(0.3)
    assert out["paid_sos"] == pytest.approx(1 / 3)
    assert out["organic_sos"] == pytest.approx(2 / 7)


@pytest.mark.parametrize("value,metric,expected", [
    (3.2, "roas", "Green"), (2.8, "roas", "Amber"), (2.0, "roas", "Red"),
    (1.00, "price_index", "Green"), (1.10, "price_index", "Amber"), (1.20, "price_index", "Red"),
    (np.nan, "roas", "n/a"),
])
def test_rag(value, metric, expected):
    assert kpis.rag(value, metric) == expected
