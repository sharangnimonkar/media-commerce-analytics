"""Shared settings: fictional brand, retailers, products, keywords and KPI targets.

All names are fictional. The data is synthetic and exists only to demonstrate methods.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
REPORTS_DIR = ROOT / "reports"
FIG_DIR = REPORTS_DIR / "figures"

SEED = 42
START_DATE = "2025-01-01"
END_DATE = "2025-12-31"

BRAND = "Brightleaf"
COMPETITORS = ["Crunchwell", "Nordic Bites", "Golden Acre", "Private Label"]

# traffic: relative shopper traffic; oos: target out-of-stock share;
# cpm: base cost per 1,000 impressions (GBP); cvr_bias: retailer conversion strength;
# saturation: exponent of the diminishing-returns curve (1 = no saturation)
RETAILERS = {
    "R1": dict(name="ShopMart", traffic=1.00, oos=0.03, cpm=2.6, cvr_bias=1.00, price_factor=1.00, saturation=0.65),
    "R2": dict(name="FreshCo", traffic=0.70, oos=0.05, cpm=2.2, cvr_bias=1.20, price_factor=0.98, saturation=0.85),
    "R3": dict(name="QuickBasket", traffic=0.45, oos=0.12, cpm=2.0, cvr_bias=0.95, price_factor=1.03, saturation=0.75),
    "R4": dict(name="MegaStore Online", traffic=0.85, oos=0.04, cpm=3.2, cvr_bias=0.85, price_factor=1.01, saturation=0.60),
}

CATEGORIES = {
    "Crisps": ["crisps", "sea salt crisps", "multipack crisps"],
    "Nuts": ["salted nuts", "mixed nuts", "healthy snacks"],
    "Popcorn": ["popcorn", "sweet popcorn", "lunchbox snacks"],
    "Bars": ["protein bar", "snack bars", "vegan snacks"],
}

# sku, category, product name, RRP (GBP), base daily units per retailer
PRODUCTS = [
    ("BL-CR-001", "Crisps", "Sea Salt Crisps 150g", 1.85, 38),
    ("BL-CR-002", "Crisps", "Cheese & Onion Crisps 150g", 1.85, 30),
    ("BL-CR-003", "Crisps", "Sweet Chilli Crisps 150g", 1.85, 22),
    ("BL-CR-004", "Crisps", "Crisps Multipack 6x25g", 2.75, 26),
    ("BL-NU-001", "Nuts", "Salted Peanuts 200g", 2.10, 18),
    ("BL-NU-002", "Nuts", "Mixed Nuts 200g", 3.25, 14),
    ("BL-NU-003", "Nuts", "Honey Roast Cashews 150g", 3.50, 11),
    ("BL-NU-004", "Nuts", "Nut & Seed Mix 6x30g", 3.40, 9),
    ("BL-PO-001", "Popcorn", "Sea Salt Popcorn 80g", 1.60, 24),
    ("BL-PO-002", "Popcorn", "Sweet & Salty Popcorn 80g", 1.60, 21),
    ("BL-PO-003", "Popcorn", "Popcorn Multipack 6x15g", 2.40, 15),
    ("BL-PO-004", "Popcorn", "Toffee Popcorn 90g", 1.75, 10),
    ("BL-BA-001", "Bars", "Peanut Protein Bar 4x40g", 3.20, 16),
    ("BL-BA-002", "Bars", "Choc Oat Bar 5x30g", 2.20, 19),
    ("BL-BA-003", "Bars", "Berry Fruit Bar 5x30g", 2.20, 12),
    ("BL-BA-004", "Bars", "Vegan Nut Bar 4x35g", 3.00, 8),
]

AD_TYPES = ["Sponsored Products", "Sponsored Brands", "Display"]

# Scorecard targets: (target, direction) where direction "high" means higher is better
TARGETS = {
    "roas": (3.0, "high"),
    "availability": (0.95, "high"),
    "share_of_search": (0.25, "high"),
    "content_score": (80.0, "high"),
    "avg_rating": (4.2, "high"),
    "price_index": (1.05, "low"),
}
AMBER_BAND = 0.10  # within 10% of target -> amber
