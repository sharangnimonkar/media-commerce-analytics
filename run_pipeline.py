"""Run the full pipeline: generate raw data -> clean -> analyse -> report."""
import argparse
import time

from mca import analysis, clean, config as C, generate, report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-generate", action="store_true", help="reuse existing files in data/raw")
    a = ap.parse_args(argv)
    t0 = time.time()
    if not a.skip_generate:
        generate.write_raw(generate.simulate())
        print("1/4 raw exports generated")
    tables = clean.run()
    print("2/4 cleaned and consolidated:", ", ".join(f"{k} {len(v):,}" for k, v in tables.items() if k != "dq_log"))
    results = analysis.run_all(tables)
    print("3/4 analysis complete")
    figs = report.make_figures(tables, results)
    report.write_excel(tables, results, C.REPORTS_DIR / "KPI_Scorecard.xlsx")
    report.write_insights(tables, results, figs, C.REPORTS_DIR / "insights.md")
    print(f"4/4 reports written to {C.REPORTS_DIR}  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
