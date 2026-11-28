"""Build reportable derived metrics from the cleaned Mangkuk Kita tables."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean"
REPORTS = ROOT / "reports"


def load(name: str) -> pd.DataFrame:
    return pd.read_csv(CLEAN / f"{name}.csv", encoding="utf-8-sig")


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    orders = load("orders")
    items = load("order_items")
    menu = load("menu_cost")
    inventory = load("inventory")
    tables = load("tables")

    orders["waktu_masuk"] = pd.to_datetime(orders["waktu_masuk"])
    orders["waktu_selesai"] = pd.to_datetime(orders["waktu_selesai"])
    orders["waktu_duduk"] = pd.to_datetime(orders["waktu_duduk"], errors="coerce")
    items = items.merge(menu[["menu_id", "nama_menu", "kategori", "food_cost"]], on="menu_id", how="left", validate="many_to_one")
    items["revenue_item"] = items["qty"] * items["harga_satuan"]
    item_cost = items["biaya_bahan_satuan"].fillna(items["food_cost"]) if "biaya_bahan_satuan" in items else items["food_cost"]
    items["food_cost_total"] = items["qty"] * item_cost
    items["profit_item"] = items["revenue_item"] - items["food_cost_total"]
    menu_metrics = items.groupby(["menu_id", "nama_menu", "kategori"], as_index=False).agg(
        units_sold=("qty", "sum"), revenue=("revenue_item", "sum"),
        food_cost_total=("food_cost_total", "sum"), profit=("profit_item", "sum"))
    menu_metrics["margin_pct"] = (menu_metrics["revenue"] - menu_metrics["food_cost_total"]) / menu_metrics["revenue"] * 100
    menu_metrics.to_csv(REPORTS / "menu_metrics.csv", index=False, encoding="utf-8-sig")

    order_metrics = orders[["order_id", "branch_id", "channel", "waktu_masuk", "tanggal", "total_bayar", "durasi_persiapan_menit", "waktu_tunggu_meja_menit"]].copy()
    order_metrics["delayed_20m"] = order_metrics["durasi_persiapan_menit"].gt(20)
    order_metrics["hour"] = order_metrics["waktu_masuk"].dt.hour
    order_metrics.to_csv(REPORTS / "order_metrics.csv", index=False, encoding="utf-8-sig", date_format="%Y-%m-%d %H:%M:%S")

    # Hourly occupancy = occupied table-minutes / available table-minutes.
    # Seat time is modeled from order entry for dine-in orders and clipped to 08:00-22:00.
    table_counts = tables.groupby("branch_id").size().to_dict()
    dates = sorted(orders["tanggal"].unique())
    occupancy_rows = []
    dine_in = orders.loc[orders["channel"].eq("Dine-in") & orders["durasi_duduk_menit"].gt(0)]
    occupied: dict[tuple[str, str, int], float] = {}
    for row in dine_in.itertuples(index=False):
        start = row.waktu_duduk
        if pd.isna(start):
            continue
        end = start + pd.Timedelta(minutes=float(row.durasi_duduk_menit))
        cursor = start
        while cursor < end:
            hour = cursor.hour
            hour_start = cursor.normalize() + pd.Timedelta(hours=hour)
            hour_end = hour_start + pd.Timedelta(hours=1)
            segment_end = min(end, hour_end)
            if 8 <= hour < 22:
                key = (row.branch_id, row.tanggal, hour)
                occupied[key] = occupied.get(key, 0.0) + (segment_end - cursor).total_seconds() / 60
            cursor = segment_end
    for day in dates:
        for branch_id, capacity in table_counts.items():
            for hour in range(8, 22):
                minutes = occupied.get((branch_id, day, hour), 0.0)
                denominator = int(capacity) * 60
                occupancy_rows.append({"tanggal": day, "branch_id": branch_id, "hour": hour,
                                       "occupied_table_minutes": round(minutes, 2),
                                       "available_table_minutes": denominator,
                                       "occupancy_rate_pct": round(min(minutes / denominator * 100, 95), 2)})
    occupancy = pd.DataFrame(occupancy_rows)
    occupancy.to_csv(REPORTS / "occupancy_hourly.csv", index=False, encoding="utf-8-sig")

    inventory["waste_value"] = inventory["total_terbuang"] * inventory["harga_satuan"]
    inventory["purchased_value"] = inventory["total_dibeli"] * inventory["harga_satuan"]
    inventory["waste_rate_pct"] = inventory["waste_value"] / inventory["purchased_value"].replace(0, pd.NA) * 100
    inventory.to_csv(REPORTS / "inventory_metrics.csv", index=False, encoding="utf-8-sig")

    revenue = int(orders["total_bayar"].sum())
    total_food_cost = int(items["food_cost_total"].sum())
    profile = {
        "period_start": str(orders["waktu_masuk"].min()), "period_end": str(orders["waktu_masuk"].max()),
        "total_revenue_idr": revenue, "total_orders": int(orders["order_id"].nunique()),
        "average_preparation_minutes": round(float(orders["durasi_persiapan_menit"].mean()), 2),
        "delayed_orders_over_20m_pct": round(float(orders["durasi_persiapan_menit"].gt(20).mean() * 100), 2),
        "average_occupancy_pct": round(float(occupancy["occupied_table_minutes"].sum() / occupancy["available_table_minutes"].sum() * 100), 2),
        "peak_hourly_occupancy_pct": round(float(occupancy["occupancy_rate_pct"].max()), 2),
        "food_cost_margin_pct": round((revenue - total_food_cost) / revenue * 100, 2) if revenue else None,
        "food_waste_pct_of_purchases_by_value": round(float(inventory["waste_value"].sum() / inventory["purchased_value"].sum() * 100), 2),
        "food_waste_value_idr": round(float(inventory["waste_value"].sum()), 2),
        "definitions": {
            "delayed_order": "durasi_persiapan_menit > 20 menit",
            "occupancy": "meja-menit terisi / meja-menit tersedia; jam operasional 08.00–22.00; nilai per jam dibatasi 95% untuk mensimulasikan utilisasi efektif",
            "food_cost_margin": "(revenue - food cost menu) / revenue; belum memasukkan biaya tenaga kerja/sewa/overhead",
            "food_waste": "nilai bahan terbuang / nilai total pembelian bahan",
        },
        "data_limitations": [
            "Seluruh order, jadwal duduk, rating, dan komentar adalah simulasi sintetis, bukan pengukuran cabang nyata.",
            "Okupansi per jam dibatasi maksimal 95% sebagai utilisasi efektif agar lonjakan sintetis tidak mengesankan seluruh meja selalu penuh. Waktu tunggu meja disimulasikan terpisah dengan batas 20 menit.",
        ],
    }
    (REPORTS / "kpi_snapshot.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Metrik turunan selesai: menu, order terlambat, okupansi per jam, food waste, dan KPI snapshot.")
    print(json.dumps({k: v for k, v in profile.items() if not isinstance(v, dict)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
