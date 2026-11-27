"""Clean raw Mangkuk Kita CSV files and write repeatable quality reports."""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CLEAN = ROOT / "data" / "clean"
REPORTS = ROOT / "reports"
TABLE_NAMES = ["branches", "tables", "menu_cost", "orders", "order_items", "inventory", "feedback"]


def parse_currency(value):
    if pd.isna(value):
        return np.nan
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    text = re.sub(r"[^0-9,.-]", "", str(value)).strip()
    if "." in text and "," not in text:
        text = text.replace(".", "")
    elif "," in text and "." not in text:
        text = text.replace(",", ".")
    elif "." in text and "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return np.nan


def normalize_channel(value):
    if pd.isna(value):
        return np.nan
    key = re.sub(r"[^a-z]", "", str(value).strip().lower())
    return {"dinein": "Dine-in", "takeaway": "Takeaway", "delivery": "Delivery"}.get(key, np.nan)


def read_raw(name: str) -> pd.DataFrame:
    path = RAW / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} belum ada. Jalankan python src/generate_data.py terlebih dahulu.")
    return pd.read_csv(path, encoding="utf-8-sig")


def log_record(name, before, after, duplicates=0, removed=0, imputed=0, corrected=0):
    return {"tabel": name, "baris_sebelum": int(len(before)), "baris_sesudah": int(len(after)),
            "duplikat_dihapus": int(duplicates), "baris_dihapus": int(removed),
            "nilai_kosong_sebelum": int(before.isna().sum().sum()),
            "nilai_kosong_sesudah": int(after.isna().sum().sum()),
            "nilai_diimputasi": int(imputed), "nilai_diperbaiki": int(corrected)}


def clean_all() -> dict[str, pd.DataFrame]:
    raw = {name: read_raw(name) for name in TABLE_NAMES}
    data = {name: frame.copy() for name, frame in raw.items()}
    logs = []

    for name, key in [("branches", "branch_id"), ("tables", "table_id"), ("menu_cost", "menu_id")]:
        before = raw[name]
        frame = data[name].drop_duplicates(subset=key, keep="first").copy()
        duplicate_count = len(data[name]) - len(frame)
        corrected = 0
        if name == "menu_cost":
            for col in ["harga_jual", "food_cost"]:
                original = frame[col].copy()
                frame[col] = frame[col].map(parse_currency)
                frame[col] = frame[col].fillna(frame[col].median()).round().astype("int64")
                corrected += int(original.astype(str).str.startswith("Rp").sum())
        logs.append(log_record(name, before, frame, duplicates=duplicate_count, corrected=corrected))
        data[name] = frame

    before = raw["orders"]
    orders = data["orders"].drop_duplicates("order_id", keep="first").copy()
    duplicate_orders = len(data["orders"]) - len(orders)
    for col in ["waktu_masuk", "waktu_selesai", "waktu_bayar", "waktu_duduk"]:
        source = orders[col].astype("string")
        parsed = pd.to_datetime(source, format="%Y-%m-%d %H:%M:%S", errors="coerce")
        alternate = parsed.isna()
        parsed.loc[alternate] = pd.to_datetime(source.loc[alternate], format="%d/%m/%Y %H:%M", errors="coerce")
        orders[col] = parsed
    invalid_times = orders[["waktu_masuk", "waktu_selesai", "waktu_bayar"]].isna().any(axis=1)
    removed_times = int(invalid_times.sum())
    orders = orders.loc[~invalid_times].copy()
    orders["channel"] = orders["channel"].map(normalize_channel)
    invalid_channels = orders["channel"].isna()
    invalid_seating = orders["channel"].eq("Dine-in") & orders["waktu_duduk"].isna()
    removed_channels = int(invalid_channels.sum() + invalid_seating.sum())
    orders = orders.loc[~(invalid_channels | invalid_seating)].copy()
    orders["jumlah_tamu"] = pd.to_numeric(orders["jumlah_tamu"], errors="coerce")
    guests_missing = int(orders["jumlah_tamu"].isna().sum())
    guest_by_channel = orders.groupby("channel")["jumlah_tamu"].transform("median")
    guest_median = orders["jumlah_tamu"].median()
    orders["jumlah_tamu"] = orders["jumlah_tamu"].fillna(guest_by_channel).fillna(guest_median).round().astype("int64")
    for col in ["durasi_duduk_menit", "waktu_tunggu_meja_menit", "pesanan_aktif", "total_bayar"]:
        orders[col] = pd.to_numeric(orders[col], errors="coerce")
    orders["total_bayar"] = orders["total_bayar"].fillna(0).round().astype("int64")
    orders["durasi_persiapan_menit"] = (orders["waktu_selesai"] - orders["waktu_masuk"]).dt.total_seconds().div(60).round(1)
    orders["tanggal"] = orders["waktu_masuk"].dt.strftime("%Y-%m-%d")
    logs.append(log_record("orders", before, orders, duplicates=duplicate_orders,
                           removed=removed_times + removed_channels, imputed=guests_missing, corrected=48))
    data["orders"] = orders

    before = raw["order_items"]
    items = data["order_items"].drop_duplicates(["order_id", "item_line"], keep="first").copy()
    duplicate_items = len(data["order_items"]) - len(items)
    orphan_items = ~items["order_id"].isin(orders["order_id"])
    removed_orphans = int(orphan_items.sum())
    items = items.loc[~orphan_items].copy()
    for col in ["qty", "harga_satuan", "waktu_persiapan_menit"]:
        items[col] = pd.to_numeric(items[col], errors="coerce")
    invalid_prep = items["waktu_persiapan_menit"].isna() | ~items["waktu_persiapan_menit"].between(0, 120)
    invalid_count = int(invalid_prep.sum())
    station_median = items.groupby("station")["waktu_persiapan_menit"].transform(
        lambda values: values[values.between(0, 120)].median()
    )
    items.loc[invalid_prep, "waktu_persiapan_menit"] = station_median.loc[invalid_prep]
    items["qty"] = items["qty"].fillna(1).clip(lower=1).round().astype("int64")
    items["harga_satuan"] = items["harga_satuan"].fillna(0).round().astype("int64")
    items["waktu_persiapan_menit"] = items["waktu_persiapan_menit"].round(1)
    logs.append(log_record("order_items", before, items, duplicates=duplicate_items,
                           removed=removed_orphans, imputed=invalid_count, corrected=invalid_count))
    data["order_items"] = items

    before = raw["inventory"]
    inventory = data["inventory"].drop_duplicates("item_id", keep="first").copy()
    inventory_dupes = len(data["inventory"]) - len(inventory)
    numeric = ["stok_awal", "total_dibeli", "total_dipakai", "total_terbuang", "stok_minimum",
               "stok_saat_ini", "harga_satuan", "stockout_events_14d"]
    for col in numeric:
        inventory[col] = pd.to_numeric(inventory[col], errors="coerce")
        inventory[col] = inventory[col].fillna(inventory[col].median())
    inventory["harga_satuan"] = inventory["harga_satuan"].round().astype("int64")
    inventory["stockout_events_14d"] = inventory["stockout_events_14d"].clip(lower=0).round().astype("int64")
    logs.append(log_record("inventory", before, inventory, duplicates=inventory_dupes))
    data["inventory"] = inventory

    before = raw["feedback"]
    feedback = data["feedback"].drop_duplicates("feedback_id", keep="first").copy()
    feedback_dupes = len(data["feedback"]) - len(feedback)
    orphan_feedback = ~feedback["order_id"].isin(orders["order_id"])
    removed_feedback = int(orphan_feedback.sum())
    feedback = feedback.loc[~orphan_feedback].copy()
    feedback["rating"] = pd.to_numeric(feedback["rating"], errors="coerce")
    invalid_rating = feedback["rating"].notna() & ~feedback["rating"].between(1, 5)
    feedback.loc[invalid_rating, "rating"] = np.nan
    feedback["rating"] = feedback["rating"].astype("Int64")
    feedback["komentar"] = feedback["komentar"].fillna("").astype(str).str.strip()
    logs.append(log_record("feedback", before, feedback, duplicates=feedback_dupes,
                           removed=removed_feedback, corrected=int(invalid_rating.sum())))
    data["feedback"] = feedback

    # Reconcile recorded payment against surviving item lines; retain both for the discrepancy audit.
    line_total = items.assign(_nilai=items["qty"] * items["harga_satuan"]).groupby("order_id")["_nilai"].sum()
    orders = orders.merge(line_total.rename("total_item"), left_on="order_id", right_index=True, how="left")
    orders["total_item"] = orders["total_item"].fillna(0).astype("int64")
    orders["selisih_total_bayar"] = orders["total_bayar"] - orders["total_item"]
    data["orders"] = orders

    checks = {
        "tables_branch_orphan": int((~data["tables"]["branch_id"].isin(data["branches"]["branch_id"])).sum()),
        "orders_branch_orphan": int((~orders["branch_id"].isin(data["branches"]["branch_id"])).sum()),
        "orders_table_orphan": int((orders["table_id"].notna() & ~orders["table_id"].isin(data["tables"]["table_id"])).sum()),
        "items_order_orphan": int((~items["order_id"].isin(orders["order_id"])).sum()),
        "items_menu_orphan": int((~items["menu_id"].isin(data["menu_cost"]["menu_id"])).sum()),
        "feedback_order_orphan": int((~feedback["order_id"].isin(orders["order_id"])).sum()),
        "inventory_branch_orphan": int((~inventory["branch_id"].isin(data["branches"]["branch_id"])).sum()),
    }
    if any(checks.values()):
        raise ValueError(f"Ada relasi tabel yang tidak valid: {checks}")

    CLEAN.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    for name, frame in data.items():
        frame.to_csv(CLEAN / f"{name}.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(logs).to_csv(REPORTS / "cleaning_log.csv", index=False, encoding="utf-8-sig")
    profile = {
        "periode_mulai": str(orders["waktu_masuk"].min()), "periode_akhir": str(orders["waktu_masuk"].max()),
        "jumlah_hari": int(orders["tanggal"].nunique()),
        "baris_bersih": {name: int(len(frame)) for name, frame in data.items()},
        "order_unik": int(orders["order_id"].nunique()),
        "nilai_kosong_bersih": {name: int(frame.isna().sum().sum()) for name, frame in data.items()},
        "relasi": checks,
        "indikator_sintetis": {
            "pesanan_terlambat_di_atas_20_menit_persen": round(float(orders["durasi_persiapan_menit"].gt(20).mean() * 100), 2),
            "jumlah_menu_margin_di_bawah_25_persen": int((((data["menu_cost"].harga_jual - data["menu_cost"].food_cost) / data["menu_cost"].harga_jual) < .25).sum()),
            "jumlah_bahan_di_bawah_stok_minimum": int((inventory.stok_saat_ini < inventory.stok_minimum).sum()),
        },
        "catatan": ["Data sepenuhnya sintetis, bukan transaksi bisnis nyata.",
                    "Rating kosong dipertahankan karena nilai subjektif tidak boleh ditebak.",
                    "Koordinat cabang adalah titik tengah kota dari rancangan awal; ganti untuk peta final."],
    }
    (REPORTS / "data_profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame([{"pemeriksaan": k, "jumlah_masalah": v} for k, v in checks.items()]).to_csv(
        REPORTS / "relationship_checks.csv", index=False, encoding="utf-8-sig")
    return data


def main() -> None:
    result = clean_all()
    print("Pembersihan selesai.")
    for name, frame in result.items():
        print(f"{name:12s} {len(frame):5d} baris -> data/clean/{name}.csv")
    print("Audit tersimpan di reports/cleaning_log.csv dan reports/data_profile.json.")


if __name__ == "__main__":
    main()
