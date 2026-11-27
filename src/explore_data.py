"""Create report-ready info(), describe(), and categorical distribution summaries."""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean"
REPORTS = ROOT / "reports"
TABLES = ["branches", "tables", "menu_cost", "orders", "order_items", "inventory", "feedback"]


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    overview_lines = ["EKSPLORASI DATA BERSIH — MANGKUK KITA", "" ]
    numeric_rows, category_rows = [], []
    for name in TABLES:
        frame = pd.read_csv(CLEAN / f"{name}.csv", encoding="utf-8-sig")
        overview_lines.extend([f"[{name}]", f"shape: {frame.shape}", "info:"])
        overview_lines.extend(f"  {col}: dtype={frame[col].dtype}, non-null={frame[col].notna().sum()}, null={frame[col].isna().sum()}" for col in frame.columns)
        overview_lines.append("describe numerik:")
        numeric = frame.select_dtypes(include="number")
        if not numeric.empty:
            desc = numeric.describe().T
            for col, row in desc.iterrows():
                record = {"tabel": name, "kolom": col}
                record.update({stat: float(row[stat]) for stat in desc.columns})
                numeric_rows.append(record)
                overview_lines.append(f"  {col}: " + ", ".join(f"{stat}={row[stat]:.3f}" for stat in desc.columns))
        categorical = frame.select_dtypes(include=["object", "string"])
        overview_lines.append("distribusi kategorikal:")
        for col in categorical.columns:
            counts = frame[col].value_counts(dropna=False)
            overview_lines.append(f"  {col}:")
            for value, count in counts.items():
                category_rows.append({"tabel": name, "kolom": col, "nilai": "(kosong)" if pd.isna(value) else str(value), "jumlah": int(count)})
                overview_lines.append(f"    {value}: {count}")
        overview_lines.append("")

    (REPORTS / "data_overview.txt").write_text("\n".join(overview_lines), encoding="utf-8")
    pd.DataFrame(numeric_rows).to_csv(REPORTS / "describe_numeric.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(category_rows).to_csv(REPORTS / "category_distributions.csv", index=False, encoding="utf-8-sig")
    orders = pd.read_csv(CLEAN / "orders.csv", encoding="utf-8-sig", parse_dates=["waktu_masuk"])
    orders["hari"] = orders["waktu_masuk"].dt.day_name()
    orders["jam"] = orders["waktu_masuk"].dt.hour
    pivot = orders.pivot_table(index="hari", columns="jam", values="order_id", aggfunc="count", fill_value=0)
    day_order = [d for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"] if d in pivot.index]
    pivot = pivot.reindex(day_order)
    plt.figure(figsize=(13, 5))
    sns.heatmap(pivot, cmap=sns.blend_palette(["#F6EBDD", "#F2A541", "#C65D3B"], as_cmap=True), linewidths=.25, linecolor="white")
    plt.title("Jumlah order menurut hari dan jam")
    plt.xlabel("Jam masuk")
    plt.ylabel("Hari")
    plt.tight_layout()
    plt.savefig(REPORTS / "eda_order_volume_heatmap.png", dpi=160, bbox_inches="tight")
    plt.close()
    print("Eksplorasi selesai: reports/data_overview.txt, describe_numeric.csv, category_distributions.csv")


if __name__ == "__main__":
    main()
