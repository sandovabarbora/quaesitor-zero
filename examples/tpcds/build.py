"""Build the TPC-DS warehouse this example runs against.

DuckDB generates it locally in seconds, so the worked example needs no
warehouse of your own and downloads no data from us.

    python build.py            # ~0.01 scale factor, a few hundred thousand rows
"""

import argparse
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale", type=float, default=0.01)
    parser.add_argument("--out", type=Path, default=HERE / "tpcds.duckdb")
    args = parser.parse_args()

    if args.out.exists():
        args.out.unlink()
    con = duckdb.connect(str(args.out))
    con.execute("INSTALL tpcds; LOAD tpcds;")
    con.execute(f"CALL dsdgen(sf={args.scale})")
    tables = con.execute(
        "SELECT COUNT(*) FROM duckdb_tables() WHERE NOT internal"
    ).fetchone()[0]
    rows = con.execute("SELECT COUNT(*) FROM store_sales").fetchone()[0]
    span = con.execute("SELECT MIN(d_date), MAX(d_date) FROM date_dim").fetchone()
    con.close()
    print(f"{args.out}: {tables} tables, {rows:,} store_sales rows, "
          f"date_dim spans {span[0]}–{span[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
