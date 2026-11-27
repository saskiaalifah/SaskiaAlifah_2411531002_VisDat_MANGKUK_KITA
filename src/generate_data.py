"""Generate reproducible synthetic operations data for Mangkuk Kita."""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
SEED = 61143
START = "2026-11-02"  # Monday; fourteen days include two weekends.
ORDER_COUNT = 9000

BRANCHES = [
    {"branch_id": "B01", "nama": "Mangkuk Kita Padang", "kota": "Padang", "latitude": -0.9471, "longitude": 100.4172, "jumlah_meja": 28},
    {"branch_id": "B02", "nama": "Mangkuk Kita Bukittinggi", "kota": "Bukittinggi", "latitude": -0.3055, "longitude": 100.3692, "jumlah_meja": 18},
    {"branch_id": "B03", "nama": "Mangkuk Kita Pekanbaru", "kota": "Pekanbaru", "latitude": 0.5071, "longitude": 101.4478, "jumlah_meja": 22},
]

# category, name, station, price, ingredient cost ratio, popularity weight
MENU = [
    ("Rice Bowl", "Ayam Sambal Matah", "Grill", 32000, .78, 1.9),
    ("Rice Bowl", "Beef Teriyaki Bowl", "Grill", 42000, .79, 1.8),
    ("Rice Bowl", "Ayam Geprek Bowl", "Wok", 30000, .77, 1.7),
    ("Rice Bowl", "Chicken Katsu Bowl", "Grill", 35000, .76, 1.6),
    ("Rice Bowl", "Dori Sambal Ijo", "Wok", 36000, .58, 1.2),
    ("Rice Bowl", "Bowl Jamur Crispy", "Wok", 28000, .54, .9),
    ("Rice Bowl", "Beef Rendang Bowl", "Wok", 44000, .62, 1.1),
    ("Rice Bowl", "Tuna Sambal Bowl", "Grill", 38000, .57, .8),
    ("Kopi", "Kopi Susu Kita", "Bar", 22000, .72, 1.8),
    ("Kopi", "Americano", "Bar", 18000, .34, 1.2),
    ("Kopi", "Cafe Latte", "Bar", 25000, .55, 1.1),
    ("Kopi", "Caramel Latte", "Bar", 28000, .59, .8),
    ("Kopi", "Es Kopi Gula Aren", "Bar", 24000, .56, 1.5),
    ("Non-Kopi", "Matcha Latte", "Bar", 27000, .57, 1.0),
    ("Non-Kopi", "Thai Tea", "Bar", 22000, .48, 1.1),
    ("Non-Kopi", "Lemon Tea", "Bar", 18000, .31, .9),
    ("Non-Kopi", "Cokelat Dingin", "Bar", 24000, .52, .8),
    ("Snack", "Kentang Goreng", "Wok", 20000, .45, 1.2),
    ("Snack", "Pisang Cokelat", "Wok", 18000, .43, .8),
    ("Snack", "Salad Buah", "Cold", 22000, .61, .7),
]
INGREDIENTS = [
    ("Beras", "Kering", "kg"), ("Ayam", "Segar", "kg"), ("Daging sapi", "Segar", "kg"),
    ("Ikan dori", "Segar", "kg"), ("Telur", "Segar", "kg"), ("Susu", "Segar", "liter"),
    ("Biji kopi", "Kering", "kg"), ("Gula aren", "Kering", "kg"), ("Sayuran", "Segar", "kg"),
    ("Kentang", "Segar", "kg"), ("Tepung", "Kering", "kg"), ("Minyak goreng", "Kering", "liter"),
    ("Matcha", "Kering", "kg"), ("Buah campur", "Segar", "kg"), ("Roti", "Segar", "kg"),
]


def allocate_daily(rng: np.random.Generator, start: date, total: int) -> list[int]:
    weights = [((1.28 if (start + timedelta(days=i)).weekday() >= 5 else 1.0) * rng.uniform(.94, 1.06)) for i in range(14)]
    exact = np.asarray(weights) / sum(weights) * total
    counts = np.floor(exact).astype(int)
    for i in np.argsort(exact - counts)[::-1][:total - int(counts.sum())]:
        counts[i] += 1
    return counts.tolist()


def make_tables() -> pd.DataFrame:
    rows = []
    for branch in BRANCHES:
        for n in range(1, branch["jumlah_meja"] + 1):
            capacity = 2 if n % 5 in (1, 2) else (6 if n % 11 == 0 else 4)
            rows.append({"table_id": f'{branch["branch_id"]}-T{n:02d}', "branch_id": branch["branch_id"], "kapasitas": capacity})
    return pd.DataFrame(rows)


def make_menu() -> tuple[pd.DataFrame, np.ndarray]:
    frame = pd.DataFrame([
        {"menu_id": f"M{i:02d}", "nama_menu": n, "kategori": c, "station": s,
         "harga_jual": p, "food_cost": round(p * cr), "_popularitas": w}
        for i, (c, n, s, p, cr, w) in enumerate(MENU, 1)
    ])
    weights = frame.pop("_popularitas").to_numpy(float)
    return frame, weights / weights.sum()


def make_inventory(rng: np.random.Generator) -> pd.DataFrame:
    critical = {("B01", "Ayam"), ("B02", "Susu"), ("B03", "Biji kopi")}
    rows = []
    for branch in BRANCHES:
        for i, (name, category, unit) in enumerate(INGREDIENTS, 1):
            initial = rng.uniform(20, 70) if category == "Segar" else rng.uniform(30, 100)
            purchased = rng.uniform(30, 100)
            waste = (initial + purchased) * rng.uniform(.085, .13) if category == "Segar" else (initial + purchased) * rng.uniform(.02, .055)
            used = (initial + purchased) * rng.uniform(.55, .83)
            minimum = rng.uniform(12, 24)
            is_critical = (branch["branch_id"], name) in critical
            on_hand = rng.uniform(1, minimum * .7) if is_critical else max(minimum + 1, initial + purchased - used - waste)
            rows.append({"item_id": f'{branch["branch_id"]}-I{i:02d}', "branch_id": branch["branch_id"],
                         "nama_bahan": name, "kategori": category, "satuan": unit,
                         "stok_awal": round(initial, 2), "total_dibeli": round(purchased, 2),
                         "total_dipakai": round(used, 2), "total_terbuang": round(waste, 2),
                         "stok_minimum": round(minimum, 2), "stok_saat_ini": round(on_hand, 2),
                         "harga_satuan": int(rng.integers(8000, 145000)),
                         "stockout_events_14d": int(rng.integers(2, 5)) if is_critical else int(rng.choice([0, 0, 0, 1]))})
    return pd.DataFrame(rows)


def schedule_tables(orders: pd.DataFrame, tables: pd.DataFrame) -> pd.DataFrame:
    """Assign dine-in tables without simultaneous use of the same table."""
    result = orders.copy()
    result["_arrival"] = pd.to_datetime(result["waktu_masuk"])
    result["_ready"] = pd.to_datetime(result["waktu_selesai"])
    result["waktu_duduk"] = None
    result["waktu_tunggu_meja_menit"] = 0
    table_ids = {branch: group["table_id"].tolist() for branch, group in tables.groupby("branch_id")}
    result["_order_day"] = result["_arrival"].dt.strftime("%Y-%m-%d")
    for (branch_id, day), group in result[result["channel"].eq("Dine-in")].groupby(["branch_id", "_order_day"], sort=True):
        available = {table_id: pd.Timestamp(f"{day} 08:00:00") for table_id in table_ids[branch_id]}
        for idx, row in group.sort_values("_arrival").iterrows():
            table_id = min(available, key=available.get)
            seated = max(row["_arrival"], available[table_id])
            duration = int(row["durasi_duduk_menit"])
            available[table_id] = seated + pd.Timedelta(minutes=duration)
            result.at[idx, "table_id"] = table_id
            result.at[idx, "waktu_duduk"] = seated.strftime("%Y-%m-%d %H:%M:%S")
            result.at[idx, "waktu_tunggu_meja_menit"] = round((seated - row["_arrival"]).total_seconds() / 60, 1)
            paid_at = max(row["_ready"], seated) + pd.Timedelta(minutes=duration)
            result.at[idx, "waktu_bayar"] = paid_at.strftime("%Y-%m-%d %H:%M:%S")
    result["waktu_duduk"] = result["waktu_duduk"].where(result["waktu_duduk"].notna(), "")
    return result.drop(columns=["_arrival", "_ready", "_order_day"])


def generate(seed: int = SEED, start_date: str = START, n_orders: int = ORDER_COUNT) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    start = date.fromisoformat(start_date)
    if start.weekday() != 0:
        raise ValueError(f"{start_date} bukan hari Senin; periode harus dimulai pada hari Senin.")
    if n_orders < 500:
        raise ValueError("Jumlah transaksi minimum sesuai template adalah 500.")

    branches = pd.DataFrame(BRANCHES)
    tables = make_tables()
    menu, menu_probs = make_menu()
    table_lookup = {k: g["table_id"].to_numpy() for k, g in tables.groupby("branch_id")}
    menu_lookup = menu.set_index("menu_id").to_dict("index")
    menu_ids = menu["menu_id"].to_numpy()
    hours = np.arange(8, 22)
    base_hours = np.array([.025, .025, .035, .05, .10, .15, .13, .07, .04, .035, .05, .09, .13, .075])
    order_rows, item_rows = [], []
    order_no = 1
    for day_offset, count in enumerate(allocate_daily(rng, start, n_orders)):
        day = start + timedelta(days=day_offset)
        for _ in range(count):
            branch_probs = [.43, .30, .27] if day.weekday() >= 5 else [.47, .22, .31]
            branch = BRANCHES[int(rng.choice(3, p=branch_probs))]
            channel_probs = {"B01": [.75, .15, .10], "B02": [.82, .10, .08], "B03": [.60, .20, .20]}[branch["branch_id"]]
            channel = str(rng.choice(["Dine-in", "Takeaway", "Delivery"], p=channel_probs))
            hour_weights = base_hours.copy()
            if branch["branch_id"] == "B01": hour_weights[4:7] *= 1.25
            if branch["branch_id"] == "B03": hour_weights[3:6] *= 1.20
            hour = int(rng.choice(hours, p=hour_weights / hour_weights.sum()))
            minute = int(rng.integers(0, 60))
            started = datetime.combine(day, time(hour, minute))
            active = int(np.clip(rng.poisson(7 if hour in [11, 12, 13, 18, 19, 20] else 3), 0, 22))
            n_lines = int(rng.choice([2, 3, 4, 5], p=[.16, .48, .28, .08]))
            chosen = rng.choice(menu_ids, size=n_lines, replace=False, p=menu_probs)
            order_id = f"O{order_no:05d}"
            these_items = []
            for line, menu_id in enumerate(chosen, 1):
                m = menu_lookup[menu_id]
                qty = int(rng.choice([1, 1, 1, 2]))
                base = {"Grill": 11.5, "Wok": 8.5, "Bar": 5.5, "Cold": 6.0}[m["station"]]
                peak = 1.0 if hour in [11, 12, 13, 18, 19, 20] else .25
                prep = max(3, rng.normal(base + active * peak * (.38 if m["station"] == "Grill" else .16), 2.5))
                these_items.append({"order_id": order_id, "item_line": line, "menu_id": menu_id, "qty": qty,
                                    "harga_satuan": int(m["harga_jual"]), "station": m["station"],
                                    "waktu_persiapan_menit": round(float(prep), 1)})
            prep_order = max(x["waktu_persiapan_menit"] for x in these_items) + rng.uniform(1, 4)
            lunch_rush = (hour == 11 and minute >= 30) or hour == 12 or (hour == 13 and minute <= 30)
            if lunch_rush and rng.random() < .22:
                prep_order = max(prep_order, rng.uniform(21, 31))
            finished = started + timedelta(minutes=round(prep_order))
            guests = int(rng.choice([1, 2, 2, 3, 4, 5]))
            sitting = int(rng.integers(65, 101)) if channel == "Dine-in" else 0
            table_id = str(rng.choice(table_lookup[branch["branch_id"]])) if channel == "Dine-in" else None
            revenue = sum(x["qty"] * x["harga_satuan"] for x in these_items)
            order_rows.append({"order_id": order_id, "branch_id": branch["branch_id"], "table_id": table_id,
                               "channel": channel, "waktu_masuk": started.strftime("%Y-%m-%d %H:%M:%S"),
                               "waktu_selesai": finished.strftime("%Y-%m-%d %H:%M:%S"),
                               "waktu_bayar": (finished + timedelta(minutes=sitting)).strftime("%Y-%m-%d %H:%M:%S"),
                               "jumlah_tamu": guests, "durasi_duduk_menit": sitting,
                               "waktu_duduk": "", "waktu_tunggu_meja_menit": 0,
                               "pesanan_aktif": active, "total_bayar": revenue})
            item_rows.extend(these_items)
            order_no += 1

    orders, items = pd.DataFrame(order_rows), pd.DataFrame(item_rows)
    orders = schedule_tables(orders, tables)
    feedback_rows = []
    themes = ["enak", "hangat", "porsi", "ramah", "lama", "gurih", "cepat", "nyaman", "kopi", "sambal"]
    for i, oid in enumerate(rng.choice(orders["order_id"].to_numpy(), size=min(400, n_orders), replace=False), 1):
        if i % 6 == 0:
            comment = f"Pesanan {rng.choice(['lama', 'terlambat'])}, tetapi {rng.choice(themes)}."
            rating = int(rng.choice([2, 3, 4]))
        else:
            comment = f"{rng.choice(['Rasanya', 'Pelayanan', 'Suasananya'])} {rng.choice(themes)}, {rng.choice(['porsinya pas', 'akan kembali', 'cukup memuaskan'])}."
            rating = int(rng.choice([3, 4, 4, 5, 5]))
        feedback_rows.append({"feedback_id": f"F{i:04d}", "order_id": oid, "rating": rating, "komentar": comment})
    feedback = pd.DataFrame(feedback_rows)

    # Intentional data quality issues for the cleaning chapter (36 missing cells).
    orders["jumlah_tamu"] = orders["jumlah_tamu"].astype("float64")
    feedback["rating"] = feedback["rating"].astype("float64")
    menu["harga_jual"] = menu["harga_jual"].astype(object)
    menu["food_cost"] = menu["food_cost"].astype(object)
    orders.loc[rng.choice(orders.index, 18, replace=False), "jumlah_tamu"] = np.nan
    feedback.loc[rng.choice(feedback.index, min(18, len(feedback)), replace=False), "rating"] = np.nan
    for i in rng.choice(orders.index, 24, replace=False):
        orders.at[i, "waktu_masuk"] = pd.Timestamp(orders.at[i, "waktu_masuk"]).strftime("%d/%m/%Y %H:%M")
    for i in rng.choice(menu.index, min(16, len(menu)), replace=False):
        menu.at[i, "harga_jual"] = f'Rp{int(menu.at[i, "harga_jual"]):,}'.replace(",", ".")
        menu.at[i, "food_cost"] = f'Rp{int(menu.at[i, "food_cost"]):,}'.replace(",", ".")
    aliases = {"Dine-in": ["Dine in", "DINE_IN", "dine-in"], "Takeaway": ["take away", "TAKEAWAY", "Take-away"], "Delivery": ["DELIVERY", "delivery ", "Delivery"]}
    for i in rng.choice(orders.index, 24, replace=False):
        orders.at[i, "channel"] = str(rng.choice(aliases[str(orders.at[i, "channel"])]))
    dirty = rng.choice(items.index, 9, replace=False)
    for i in dirty[:5]:
        items.at[i, "waktu_persiapan_menit"] = -float(rng.integers(1, 12))
    for i in dirty[5:]:
        items.at[i, "waktu_persiapan_menit"] = float(rng.integers(125, 181))

    # Twelve duplicate orders and their item rows, with original keys retained for deduplication.
    dup_ids = rng.choice(orders["order_id"].to_numpy(), 12, replace=False)
    orders = pd.concat([orders, orders[orders.order_id.isin(dup_ids)]], ignore_index=True)
    items = pd.concat([items, items[items.order_id.isin(dup_ids)]], ignore_index=True)
    return {"branches": pd.DataFrame(BRANCHES), "tables": tables, "menu_cost": menu,
            "orders": orders, "order_items": items, "inventory": make_inventory(rng), "feedback": feedback}


def main() -> None:
    parser = argparse.ArgumentParser(description="Buat tujuh CSV sintetis Mangkuk Kita di data/raw.")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--start-date", default=START, help="Tanggal Senin dalam format YYYY-MM-DD.")
    parser.add_argument("--orders", type=int, default=ORDER_COUNT)
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    for name, frame in generate(args.seed, args.start_date, args.orders).items():
        frame.to_csv(RAW / f"{name}.csv", index=False, encoding="utf-8-sig")
        print(f"{name:12s} {len(frame):5d} baris -> data/raw/{name}.csv")
    print(f"Seed {args.seed}; periode {args.start_date}–{date.fromisoformat(args.start_date) + timedelta(days=13)}; order unik {args.orders}.")


if __name__ == "__main__":
    main()
