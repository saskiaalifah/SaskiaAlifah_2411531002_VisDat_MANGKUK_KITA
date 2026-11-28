"""Interactive seven-module restaurant dashboard for Mangkuk Kita."""
from __future__ import annotations

import base64
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean"
REPORTS = ROOT / "reports"
ASSETS = ROOT / "assets"
BRAND = {"primary": "#C65D3B", "primary_dark": "#9E4125", "secondary": "#2F5D50",
         "success": "#3A9D5D", "warning": "#F2A541", "danger": "#D64545",
         "neutral": "#5F6368", "bg": "#F6EBDD", "surface": "#FFFDF9"}
COLOR_CABANG = {"Mangkuk Kita Padang": "#C65D3B", "Mangkuk Kita Bukittinggi": "#2F5D50", "Mangkuk Kita Pekanbaru": "#D99527"}
ORDER_CABANG = list(COLOR_CABANG)
COLOR_KATEGORI = {"Rice Bowl": "#2F5D50", "Kopi": "#C65D3B", "Non-Kopi": "#D99527", "Snack": "#718A76"}
ORDER_KATEGORI = list(COLOR_KATEGORI)
COLOR_CHANNEL = {"Dine-in": "#2F5D50", "Takeaway": "#D99527", "Delivery": "#C65D3B"}
ORDER_STATION = {"Grill": "Panggang", "Wok": "Wok", "Cold": "Dingin", "Bar": "Bar"}
CHART_TEMPLATE = "plotly_white"
STOPWORDS = set("dan yang di ke dari untuk dengan ini itu ada adalah atau tapi tetapi saya kami aku nya the a an of to in is it this that sangat cukup akan juga pada saat agar karena jadi".split())

st.set_page_config(page_title="Mangkuk Kita | Dashboard", page_icon="🍲", layout="wide", initial_sidebar_state="expanded")


def load_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(CLEAN / f"{name}.csv", encoding="utf-8-sig")


@st.cache_data(show_spinner="Memuat data restoran…")
def load_data() -> dict[str, pd.DataFrame]:
    if not (CLEAN / "orders.csv").exists():
        raise FileNotFoundError("Data bersih belum ada. Jalankan src/generate_data.py lalu src/clean_data.py.")
    data = {name: load_csv(name) for name in ["branches", "tables", "menu_cost", "orders", "order_items", "inventory", "feedback"]}
    for col in ["waktu_masuk", "waktu_selesai", "waktu_bayar", "waktu_duduk"]:
        data["orders"][col] = pd.to_datetime(data["orders"][col], errors="coerce")
    data["orders"]["tanggal_dt"] = pd.to_datetime(data["orders"]["tanggal"], errors="coerce")
    data["orders"]["jam"] = data["orders"]["waktu_masuk"].dt.hour
    data["menu_cost"]["margin_pct"] = (data["menu_cost"]["harga_jual"] - data["menu_cost"]["food_cost"]) / data["menu_cost"]["harga_jual"] * 100
    items = data["order_items"].merge(data["menu_cost"], on="menu_id", how="left", validate="many_to_one")
    items = items.merge(data["orders"][["order_id", "branch_id", "channel", "tanggal", "tanggal_dt", "waktu_masuk"]], on="order_id", how="left", validate="many_to_one")
    if "station_x" in items.columns:
        items["station"] = items["station_x"].fillna(items["station_y"])
        items = items.drop(columns=["station_x", "station_y"])
    items["revenue"] = items["qty"] * items["harga_satuan"]
    item_cost = items["biaya_bahan_satuan"].fillna(items["food_cost"]) if "biaya_bahan_satuan" in items else items["food_cost"]
    items["food_cost_total"] = items["qty"] * item_cost
    items["profit"] = items["revenue"] - items["food_cost_total"]
    data["items"] = items
    data["occupancy_hourly"] = pd.read_csv(REPORTS / "occupancy_hourly.csv", encoding="utf-8-sig")
    data["inventory_metrics"] = pd.read_csv(REPORTS / "inventory_metrics.csv", encoding="utf-8-sig")
    feedback = data["feedback"].merge(data["orders"][["order_id", "branch_id", "channel", "tanggal", "tanggal_dt"]], on="order_id", how="left", validate="many_to_one")
    data["feedback_joined"] = feedback
    return data


def rupiah(value: float) -> str:
    return f"Rp{value:,.0f}".replace(",", ".")


def rupiah_compact(value: float) -> str:
    if abs(value) >= 1_000_000_000:
        return f"Rp{value / 1_000_000_000:,.2f} miliar".replace(",", "X").replace(".", ",").replace("X", ".")
    if abs(value) >= 1_000_000:
        return f"Rp{value / 1_000_000:,.1f} jt".replace(",", "X").replace(".", ",").replace("X", ".")
    return rupiah(value)


def chart_layout(fig, height=360, **kwargs):
    options = dict(template=CHART_TEMPLATE, height=height, separators=",.", margin=dict(l=18, r=18, t=50, b=18),
                   font=dict(family="Inter, Arial, sans-serif", color="#31413D", size=13),
                   paper_bgcolor=BRAND["surface"], plot_bgcolor=BRAND["surface"])
    options.update(kwargs)
    fig.update_layout(**options)
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor="#E8E0D6", zeroline=False)
    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1].replace("Mangkuk Kita ", "")))
    return fig


def angka_id(value, decimals=0):
    return f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def short_branch(name):
    return str(name).replace("Mangkuk Kita ", "")


def tanggal_id(value, year=False):
    stamp = pd.Timestamp(value)
    months = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
    return f"{stamp.day} {months[stamp.month - 1]}{f' {stamp.year}' if year else ''}"


def rentang_jam(hours):
    vals = sorted(set(int(hour) for hour in hours))
    ranges = []
    start = previous = vals[0]
    for hour in vals[1:]:
        if hour != previous + 1:
            ranges.append(f"{start:02d}–{previous:02d}" if start != previous else f"{start:02d}")
            start = hour
        previous = hour
    ranges.append(f"{start:02d}–{previous:02d}" if start != previous else f"{start:02d}")
    return ", ".join(ranges)


def money_axis(fig, axis="y"):
    """Show monetary chart axes in millions of rupiah, with Indonesian units."""
    fn = fig.update_yaxes if axis == "y" else fig.update_xaxes
    fn(tickformat=",.0f", ticksuffix=" jt", title_text="Pendapatan (juta Rp)" if axis == "y" else "Nilai (juta Rp)")
    return fig


def create_branch_map(branch_revenue: pd.DataFrame, height=440):
    """Offline schematic map: uses only local vector traces, never external map tiles."""
    map_data = branch_revenue.dropna(subset=["latitude", "longitude"]).copy()
    fig = go.Figure()
    # A restrained local outline of Sumatra's western coast keeps the map visible offline.
    coastline_x = [99.02, 99.15, 99.28, 99.42, 99.50, 99.46, 99.55, 99.70, 99.82, 100.02, 100.25, 100.55, 100.92, 101.28, 101.66, 101.92, 101.96, 101.78, 101.35, 100.92, 100.48, 100.08, 99.72, 99.40, 99.16, 99.02]
    coastline_y = [-1.48, -1.24, -.92, -.62, -.28, .06, .38, .69, 1.03, 1.30, 1.48, 1.63, 1.78, 1.90, 1.99, 2.07, -1.48, -1.48, -1.48, -1.48, -1.48, -1.48, -1.48, -1.48, -1.48, -1.48]
    fig.add_trace(go.Scatter(x=coastline_x, y=coastline_y, mode="lines", fill="toself", fillcolor="#E6E9D9",
        line=dict(color="#CCD2C1", width=1.3), hoverinfo="skip", showlegend=False, name="Daratan"))
    if map_data.empty:
        fig.add_annotation(text="Koordinat cabang belum tersedia", showarrow=False, x=100.5, y=0)
        fig.update_xaxes(range=[98.9, 102.0], title="Bujur (°BT)", dtick=.5, ticksuffix="°")
        fig.update_yaxes(range=[-1.55, 1.65], title="Lintang (°)", dtick=.5, ticksuffix="°", scaleanchor="x", scaleratio=1)
        return chart_layout(fig, height, margin=dict(l=25, r=20, t=16, b=38), showlegend=False)
    map_data["label_cabang"] = map_data["nama"].map(short_branch)
    map_data["pendapatan_tampilan"] = map_data["revenue"].map(rupiah)
    max_revenue = max(float(map_data["revenue"].max()), 1)
    label_positions = {"Padang": "bottom left", "Bukittinggi": "top left", "Pekanbaru": "middle right"}
    for row in map_data.itertuples(index=False):
        color = COLOR_CABANG.get(row.nama, BRAND["primary"])
        size = 19 + 23 * np.sqrt(max(float(row.revenue), 0) / max_revenue)
        fig.add_trace(go.Scatter(x=[row.longitude], y=[row.latitude], mode="markers+text", name=short_branch(row.nama),
            text=[row.kota], textposition=label_positions.get(row.kota, "top center"), textfont=dict(size=12, color="#244C43", family="Inter, Arial, sans-serif"),
            marker=dict(size=size, color=color, line=dict(color="#FFFDF9", width=3), opacity=.96),
            customdata=[[row.pendapatan_tampilan]],
            hovertemplate="<b>%{text}</b><br>Pendapatan: %{customdata[0]}<br>Koordinat: %{x:.3f}° BT, %{y:.3f}°<extra></extra>"))
    fig.add_annotation(x=99.35, y=-.05, text="SAMUDRA HINDIA", showarrow=False,
                       font=dict(size=10, color="#82999C", family="Inter, Arial, sans-serif"))
    fig.add_annotation(x=101.65, y=1.05, text="RIAU", showarrow=False,
                       font=dict(size=10, color="#718A76", family="Inter, Arial, sans-serif"))
    fig.update_xaxes(range=[98.95, 102.02], title="Bujur (°BT)", dtick=.5, ticksuffix="°", gridcolor="#DAE2DE", zeroline=False)
    fig.update_yaxes(range=[-1.55, 1.7], title="Lintang (°)", dtick=.5, ticksuffix="°", gridcolor="#DAE2DE", zeroline=False, scaleanchor="x", scaleratio=1)
    fig.update_layout(showlegend=False, plot_bgcolor="#EAF2F0", paper_bgcolor=BRAND["surface"])
    fig = chart_layout(fig, height, margin=dict(l=42, r=16, t=18, b=42), showlegend=False)
    fig.update_xaxes(showgrid=True, gridcolor="#DAE2DE")
    fig.update_yaxes(showgrid=True, gridcolor="#DAE2DE")
    return fig


def create_table_plan(tables: pd.DataFrame, selected_orders: pd.DataFrame, height=480):
    """Schematic table layout; table positions are generated for visualization only."""
    if tables.empty:
        fig = go.Figure()
        fig.add_annotation(text="Data meja tidak tersedia untuk cabang ini", showarrow=False, x=.5, y=.5)
        return chart_layout(fig, height)

    table_data = tables.sort_values("table_id").copy().reset_index(drop=True)
    visits = selected_orders.loc[
        selected_orders.channel.eq("Dine-in") & selected_orders.table_id.notna()
    ].groupby("table_id").size()
    table_data["kunjungan"] = table_data.table_id.map(visits).fillna(0).astype(int)
    positive = table_data.loc[table_data.kunjungan.gt(0), "kunjungan"]
    low_cut = float(positive.quantile(.33)) if len(positive) else 0
    high_cut = float(positive.quantile(.67)) if len(positive) else 0
    table_data["kelompok"] = np.select(
        [table_data.kunjungan.eq(0), table_data.kunjungan.le(low_cut), table_data.kunjungan.le(high_cut)],
        ["0 pesanan dine-in", "Frekuensi rendah", "Frekuensi sedang"],
        default="Frekuensi tinggi",
    )

    columns = [.58, 1.48, 2.38, 4.05, 4.95, 5.85, 6.75]
    rows = []
    for index in range(len(table_data)):
        row, col = divmod(index, len(columns))
        y = row * 1.08
        rows.append((columns[col], y))
    table_data["x"] = [point[0] for point in rows]
    table_data["y"] = [point[1] for point in rows]

    palette = {"0 pesanan dine-in": "#D8D4CE", "Frekuensi rendah": "#D99527",
               "Frekuensi sedang": "#789384", "Frekuensi tinggi": "#2F5D50"}
    fig = go.Figure()
    for label in palette:
        part = table_data[table_data.kelompok.eq(label)]
        if part.empty:
            continue
        fig.add_trace(go.Scatter(
            x=part.x, y=part.y, mode="markers+text", name=label,
            text=part.table_id.str[-3:], textposition="middle center",
            textfont=dict(size=10, color="#FFFDF9" if label != "0 pesanan dine-in" else "#31413D"),
            marker=dict(symbol="square", size=39, color=palette[label],
                        line=dict(color="#FFFDF9", width=2)),
            customdata=np.column_stack([part.table_id, part.kapasitas, part.kunjungan]),
            hovertemplate="Meja %{customdata[0]}<br>Kapasitas: %{customdata[1]} orang<br>Pesanan dine-in pada periode: %{customdata[2]}<extra></extra>"))

    max_y = float(table_data.y.max()) if len(table_data) else 1
    fig.add_shape(type="rect", x0=.12, y0=-.62, x1=7.18, y1=max_y + 1.38,
                  line=dict(color="#CFC4B6", width=2), fillcolor="#FAF7F1", layer="below")
    fig.add_shape(type="rect", x0=3.18, y0=-.58, x1=3.78, y1=max_y + 1.32,
                  line=dict(width=0), fillcolor="#EEE9DF", layer="below")
    fig.add_annotation(x=1.48, y=max_y + .92, text="AREA A · 3 KOLOM MEJA", showarrow=False,
                       font=dict(size=11, color="#6A6258"), bgcolor="#F3EBDD", borderpad=4)
    fig.add_annotation(x=5.42, y=max_y + .92, text="AREA B · 4 KOLOM MEJA", showarrow=False,
                       font=dict(size=11, color="#6A6258"), bgcolor="#F3EBDD", borderpad=4)
    fig.add_annotation(x=3.48, y=max_y / 2, text="JALUR", textangle=-90,
                       showarrow=False, font=dict(size=9, color="#776E63"))
    fig.update_xaxes(visible=False, range=[-.12, 7.42], fixedrange=True)
    fig.update_yaxes(visible=False, range=[max_y + 1.62, -.88], fixedrange=True)
    return chart_layout(fig, height, margin=dict(l=10, r=10, t=18, b=58),
                        legend=dict(title="Pesanan dine-in", orientation="h", y=-.16, x=0))


def kpi_card(label, value, help_text=None, delta=None, target=None, status=None):
    st.metric(label, value, delta=delta, help=help_text)
    if target or status:
        status_class = "good" if status in {"Di atas target", "Sesuai target", "Sesuai data"} else "watch"
        st.markdown(f"<div class='kpi-context'><span>{target or ''}</span><b class='{status_class}'>{status or ''}</b></div>", unsafe_allow_html=True)


def get_filters(data, module):
    orders = data["orders"]
    min_date = orders["tanggal_dt"].min().date()
    max_date = orders["tanggal_dt"].max().date()
    branch_ids = data["branches"]["branch_id"].tolist()
    branch_names = data["branches"].set_index("branch_id")["nama"].to_dict()
    categories = sorted(data["menu_cost"]["kategori"].dropna().unique().tolist())
    channels = ["Dine-in", "Takeaway", "Delivery"]

    def reset_filters():
        st.session_state["filter_dates"] = (min_date, max_date)
        st.session_state["filter_branch"] = "Semua cabang"
        st.session_state["filter_category"] = "Semua kategori"
        st.session_state["filter_channel"] = "Semua channel"

    with st.container(border=True):
        kicker_col, branch_col, date_col, category_col, channel_col, reset_col = st.columns([.72, 1.15, 1.55, 1.08, 1.08, .62], gap="small", vertical_alignment="bottom")
        with kicker_col:
            st.markdown("<div class='filter-kicker'>FILTER<br>DATA</div>", unsafe_allow_html=True)
        with branch_col:
            branch_value = st.selectbox("Cabang", ["Semua cabang"] + branch_ids, key="filter_branch",
                                         format_func=lambda x: "Semua cabang" if x == "Semua cabang" else branch_names.get(x, x))
        selected_branches = branch_ids if branch_value == "Semua cabang" else [branch_value]
        selected_category, selected_channel = "Semua kategori", "Semua channel"
        selected_categories, selected_channels = categories, channels
        date_value = (min_date, max_date)
        if module == "Inventory":
            with date_col: st.text_input("Periode", "Ringkasan tetap · 14 hari", disabled=True, key="inventory_period_display")
            with category_col: st.text_input("Kategori", "Tidak berlaku", disabled=True, key="inventory_category_display")
            with channel_col: st.text_input("Channel", "Tidak berlaku", disabled=True, key="inventory_channel_display")
        else:
            with date_col:
                date_value = st.date_input("Tanggal", value=(min_date, max_date), min_value=min_date,
                                            max_value=max_date, key="filter_dates")
            with category_col:
                selected_category = st.selectbox("Kategori menu", ["Semua kategori"] + categories,
                                                 key="filter_category")
                selected_categories = categories if selected_category == "Semua kategori" else [selected_category]
            with channel_col:
                selected_channel = st.selectbox("Channel pesanan", ["Semua channel"] + channels,
                                                key="filter_channel")
                selected_channels = channels if selected_channel == "Semua channel" else [selected_channel]
        if isinstance(date_value, tuple):
            start_date, end_date = date_value if len(date_value) == 2 else (date_value[0], date_value[0])
        else:
            start_date = end_date = date_value
        with reset_col:
            st.button("Reset", key="reset_filters", on_click=reset_filters, use_container_width=True)
    return {"start": pd.Timestamp(start_date), "end": pd.Timestamp(end_date), "branches": selected_branches,
            "categories": selected_categories, "channels": selected_channels}


def select_data(data, filters):
    orders = data["orders"]
    mask = (orders["tanggal_dt"] >= filters["start"]) & (orders["tanggal_dt"] <= filters["end"])
    mask &= orders["branch_id"].isin(filters["branches"]) & orders["channel"].isin(filters["channels"])
    selected_ids = set(orders.loc[mask, "order_id"])
    items = data["items"]
    if filters["categories"]:
        selected_ids &= set(items.loc[items["kategori"].isin(filters["categories"]), "order_id"])
        items = items[items["kategori"].isin(filters["categories"])].copy()
    else:
        selected_ids = set()
    filtered_orders = orders[orders["order_id"].isin(selected_ids)].copy()
    filtered_items = items[items["order_id"].isin(selected_ids)].copy()
    return filtered_orders, filtered_items


def occupancy_for_selection(data, selected_orders, filters):
    dine = selected_orders[selected_orders["channel"].eq("Dine-in") & selected_orders["waktu_duduk"].notna()]
    table_counts = data["tables"].groupby("branch_id").size().to_dict()
    available = {}
    for row in dine.itertuples(index=False):
        cursor = row.waktu_duduk
        end = cursor + pd.Timedelta(minutes=float(row.durasi_duduk_menit))
        while cursor < end:
            hour = cursor.hour
            next_hour = cursor.normalize() + pd.Timedelta(hours=hour + 1)
            segment_end = min(end, next_hour)
            if 8 <= hour < 22:
                key = (row.branch_id, row.tanggal, hour)
                available[key] = available.get(key, 0.0) + (segment_end - cursor).total_seconds() / 60
            cursor = segment_end
    dates = pd.date_range(filters["start"], filters["end"], freq="D")
    rows = []
    for day in dates:
        for branch in filters["branches"]:
            for hour in range(8, 22):
                denom = table_counts.get(branch, 0) * 60
                occupied = available.get((branch, day.strftime("%Y-%m-%d"), hour), 0.0)
                rows.append({"tanggal": day.strftime("%Y-%m-%d"), "branch_id": branch, "hour": hour,
                             "occupied_table_minutes": occupied, "available_table_minutes": denom,
                             "occupancy_rate_pct": min(occupied / denom * 100, 95) if denom else 0})
    return pd.DataFrame(rows)


def insights(data, orders, items, occupancy, selected_branches):
    alerts = []
    if len(items):
        low = items.groupby("nama_menu").agg(revenue=("revenue", "sum"), cost=("food_cost_total", "sum"))
        low["margin"] = (low["revenue"] - low["cost"]) / low["revenue"].replace(0, np.nan) * 100
        names = low.index[low["margin"] < 25].tolist()
        if names:
            alerts.append(("🔴", "Margin Menu Rendah", f"{len(names)} menu di bawah margin 25%.", "Tinjau harga jual atau biaya bahan."))
    if len(orders):
        by_hour = orders.groupby("jam")["durasi_persiapan_menit"].apply(lambda s: s.gt(20).mean() * 100)
        slow = by_hour[by_hour > 15]
        if len(slow):
            alerts.append(("🟠", "Dapur Melambat", f"Pesanan terlambat di atas 15% pada jam {', '.join(map(str, slow.index.tolist()))}.", "Atur staf dan alur kerja dapur pada jam tersebut."))
    stock = data["inventory_metrics"]
    stock = stock[stock["branch_id"].isin(selected_branches)]
    critical = stock[stock["stok_saat_ini"] < stock["stok_minimum"]]
    if len(critical):
        alerts.append(("🔴", "Stok Kritis", f"{len(critical)} bahan di bawah stok minimum.", "Jadwalkan pengadaan bahan kritis."))
    waste = data["inventory_metrics"]
    waste = waste[waste["branch_id"].isin(selected_branches)]
    high_waste = waste[waste["waste_rate_pct"] > 8]
    if len(high_waste):
        alerts.append(("🟠", "Limbah Bahan Tinggi", f"{len(high_waste)} bahan memiliki limbah di atas target 8% dari nilai pembelian.", "Sesuaikan jumlah pembelian dan persiapan harian."))
    if len(occupancy):
        hourly = occupancy.groupby(["branch_id", "hour"])["occupancy_rate_pct"].mean()
        overall_occupancy = occupancy.occupied_table_minutes.sum() / occupancy.available_table_minutes.sum() * 100 if occupancy.available_table_minutes.sum() else 0
        if overall_occupancy < 30:
            alerts.append(("🟠", "Okupansi Rendah", f"Okupansi rata-rata hanya {angka_id(overall_occupancy, 1)}%.", "Uji promo terbatas pada jam sepi."))
        busy_hours = hourly[hourly > 95]
        if len(busy_hours):
            branch_names = data["branches"].set_index("branch_id")["nama"].to_dict()
            by_branch = {}
            for branch, hour in busy_hours.index.tolist():
                by_branch.setdefault(short_branch(branch_names.get(branch, branch)), []).append(int(hour))
            places = [f"{name}, jam {rentang_jam(hours)}" for name, hours in by_branch.items()]
            alerts.append(("🟠", "Kapasitas Hampir Penuh", f"Okupansi di atas 95% pada {'; '.join(places[:5])}.", "Aktifkan reservasi dan siapkan alur antrean."))
    return alerts


def render_insights(alerts):
    if not alerts:
        st.success("Tidak ada peringatan aktif untuk filter yang dipilih.")
        return

    priority = {"Stok Kritis": 0, "Margin Menu Rendah": 1, "Kapasitas Hampir Penuh": 2,
                "Dapur Melambat": 3, "Limbah Bahan Tinggi": 4, "Okupansi Rendah": 5}
    alerts = sorted(alerts, key=lambda item: priority.get(item[1], 99))[:4]

    def render_rows(rows):
        for icon, title, message, action in rows:
            severity, level = ("critical", "Kritis") if icon == "🔴" else ("caution", "Sedang")
            st.markdown(
                f"<div class='alert-card {severity}'><div class='alert-title'><b>{icon} {level} · {title}</b></div>"
                f"<div class='alert-message'>{message}</div><small><b>Saran:</b> {action}</small></div>",
                unsafe_allow_html=True,
            )

    columns = st.columns(3, gap="small")
    for index, alert in enumerate(alerts):
        with columns[index % 3]:
            render_rows([alert])


def normalize_word(word):
    # Keep complete words; stemming made Indonesian words such as “nyaman” unreadable.
    return {"enakkk": "enak", "mantapp": "mantap", "porsii": "porsi"}.get(word.lower(), word.lower())


def build_feedback_terms(feedback):
    counts = Counter()
    if not feedback.empty:
        for row in feedback.dropna(subset=["komentar"]).itertuples(index=False):
            words = {normalize_word(w) for w in re.findall(r"[a-zA-ZÀ-ÿ]+", str(row.komentar).lower())}
            counts.update(word for word in words if len(word) > 2 and word not in STOPWORDS)
    terms = pd.DataFrame(counts.most_common(24), columns=["kata", "jumlah"])
    if terms.empty:
        fig = go.Figure()
        fig.add_annotation(text="Belum ada ulasan", showarrow=False, x=.5, y=.5)
        return chart_layout(fig, 340)
    terms = terms.sort_values("jumlah", ascending=False).reset_index(drop=True)
    max_count = max(int(terms.jumlah.max()), 1)
    sizes = 14 + 20 * np.sqrt(terms.jumlah / max_count)
    # A fixed, wrapped row layout leaves room for the longest full word on smaller screens.
    row_widths = [max(.075, min(.22, len(word) * float(sizes[i]) * .00072)) for i, word in enumerate(terms.kata)]
    rows, current, used = [], [], 0.0
    for idx, width in enumerate(row_widths):
        if current and used + width + .025 > .88:
            rows.append(current); current, used = [], 0.0
        current.append(idx); used += width + (.025 if len(current) > 1 else 0)
    if current: rows.append(current)
    rows = rows[:6]
    keep = [idx for row in rows for idx in row]
    terms, sizes, row_widths = terms.iloc[keep].reset_index(drop=True), sizes[keep], [row_widths[i] for i in keep]
    xs, ys = [0.0] * len(terms), [0.0] * len(terms)
    for row_idx, row in enumerate(rows):
        width = sum(row_widths[i] for i in row) + .025 * (len(row) - 1)
        cursor = .5 - width / 2
        for idx in row:
            xs[idx] = cursor + row_widths[idx] / 2
            ys[idx] = .88 - row_idx * (.76 / max(len(rows) - 1, 1))
            cursor += row_widths[idx] + .025
    fig = go.Figure(go.Scatter(x=xs, y=ys, mode="text", text=terms.kata,
        textfont={"size": sizes, "color": ["#2F5D50" if i % 2 == 0 else "#C65D3B" for i in range(len(terms))], "family": "Inter, Arial, sans-serif"},
        customdata=terms.jumlah, hovertemplate="%{text}<br>Disebut di %{customdata} ulasan<extra></extra>", showlegend=False))
    fig.update_xaxes(visible=False, range=[0, 1]); fig.update_yaxes(visible=False, range=[0, 1])
    return chart_layout(fig, 340, margin=dict(l=12, r=12, t=25, b=28))


def build_sentiment_words(feedback, minimum_rating, maximum_rating, color):
    subset = feedback[feedback.rating.notna() & feedback.rating.ge(minimum_rating) & feedback.rating.le(maximum_rating)]
    counts = Counter()
    for comment in subset.komentar.dropna():
        words = {normalize_word(w) for w in re.findall(r"[a-zA-ZÀ-ÿ]+", str(comment).lower())}
        counts.update(word for word in words if len(word) > 2 and word not in STOPWORDS)
    terms = pd.DataFrame(counts.most_common(10), columns=["Kata", "Jumlah ulasan"])
    if terms.empty:
        terms = pd.DataFrame([{"Kata": "Belum ada kata", "Jumlah ulasan": 0}])
    terms = terms.sort_values("Jumlah ulasan", ascending=True)
    fig = px.bar(terms, x="Jumlah ulasan", y="Kata", orientation="h", text="Jumlah ulasan",
                 color_discrete_sequence=[color], labels={"Jumlah ulasan": "Jumlah ulasan", "Kata": "Kata utuh"})
    fig.update_traces(textposition="outside", cliponaxis=False, hovertemplate="%{y}: %{x} ulasan<extra></extra>")
    fig.update_yaxes(dtick=1, automargin=True)
    return chart_layout(fig, max(300, 30 * len(terms) + 80), margin=dict(l=12, r=42, t=25, b=25), showlegend=False)

def main():
    st.markdown(f"""<style>
    .stApp {{ background: {BRAND['bg']}; }}
    .block-container {{ max-width: 1680px; padding: 1.05rem 1.45rem 2.5rem; }}
    [data-testid='stAppViewContainer'] {{ background: {BRAND['bg']}; }}
    [data-testid='stAppViewContainer'] > .main {{ background: {BRAND['bg']}; }}
    [data-testid='stSidebar'] {{ background: #244C43; border-right: 1px solid #1C4038; min-width: 252px !important; }}
    [data-testid='stSidebar'] > div:first-child {{ min-height: 100vh; padding: .8rem .8rem 1.1rem; }}
    [data-testid='stSidebarContent'] {{ min-height: 100vh; background: #244C43; }}
    [data-testid='stSidebarUserContent'] {{ height: calc(100vh - 5.6rem); min-height: calc(100vh - 5.6rem); display: flex; flex-direction: column; overflow-y: auto; }}
    [data-testid='stSidebarUserContent'] > div {{ height: 100%; }}
    [data-testid='stSidebarUserContent'] [data-testid='stVerticalBlock']:has(.sidebar-footer) {{ height: 100%; min-height: 100%; }}
    [data-testid='stSidebar'] [data-testid='stMarkdownContainer'] p,
    [data-testid='stSidebar'] [data-testid='stMarkdownContainer'] h2,
    [data-testid='stSidebar'] [data-testid='stMarkdownContainer'] h3,
    [data-testid='stSidebar'] label,
    [data-testid='stSidebar'] [data-testid='stCaptionContainer'] * {{ color: #FFFDF9 !important; }}
    [data-testid='stSidebar'] [data-testid='stHorizontalBlock'] {{ align-items: center; }}
    [data-testid='stSidebar'] [data-testid='stMarkdownContainer'] h3 {{ font-size: 1.15rem; margin: 0 0 .1rem; letter-spacing: -.02em; }}
    [data-testid='stSidebar'] .brand-lockup {{ display: flex; align-items: center; gap: .62rem; margin: .25rem .12rem .9rem; }}
    [data-testid='stSidebar'] .brand-lockup img {{ display: block; width: 46px; height: 46px; object-fit: contain; flex: 0 0 46px; border-radius: 10px; }}
    [data-testid='stSidebar'] .brand-lockup b {{ display: block; color: #FFFDF9; font-size: 1.08rem; line-height: 1.2; letter-spacing: -.025em; }}
    [data-testid='stSidebar'] .brand-lockup small {{ display: block; color: #C8DAD2; font-size: .57rem; line-height: 1.3; letter-spacing: .12em; font-weight: 750; margin-top: .22rem; }}
    [data-testid='stSidebar'] [data-testid='stMarkdownContainer'] .brand-tag {{ color: #C8DAD2; font-size: .7rem; letter-spacing: .11em; font-weight: 650; }}
    [data-testid='stSidebar'] [data-testid='stMarkdownContainer'] .sidebar-kicker {{ color: #C8DAD2; font-size: .68rem; letter-spacing: .12em; font-weight: 700; margin: .25rem 0 .65rem; }}
    [data-testid='stSidebar'] .stRadio,
    [data-testid='stSidebar'] [data-testid='stRadioGroup'] {{ box-sizing: border-box; width: 100% !important; }}
    [data-testid='stSidebar'] .st-key-active_module {{ box-sizing: border-box; width: 100% !important; max-width: none !important; }}
    [data-testid='stSidebar'] [data-testid='stRadioGroup'] {{ align-items: stretch; gap: .28rem; }}
    [data-testid='stSidebar'] [data-testid='stRadioGroup'] > div {{ box-sizing: border-box; width: 100% !important; }}
    [data-testid='stSidebar'] [data-testid='stRadioOption'] {{ box-sizing: border-box; width: 100% !important; min-height: 42px; display: flex; align-items: center; background: transparent; border: 1px solid transparent; border-radius: 9px; padding: .48rem .62rem; cursor: pointer; transition: background-color .15s ease, border-color .15s ease; }}
    [data-testid='stSidebar'] [data-testid='stRadioOption'] > span {{ display: none !important; }}
    [data-testid='stSidebar'] [data-testid='stRadioOption'] > div > div:first-child {{ display: none !important; }}
    [data-testid='stSidebar'] [data-testid='stRadioOption'] [data-testid='stMarkdownContainer'] p {{ display: flex; align-items: center; gap: .62rem; margin: 0; font-size: .88rem; font-weight: 650; }}
    [data-testid='stSidebar'] [data-testid='stRadioGroup'] > div:nth-child(1) [data-testid='stMarkdownContainer'] p::before {{ content: '▦'; }}
    [data-testid='stSidebar'] [data-testid='stRadioGroup'] > div:nth-child(2) [data-testid='stMarkdownContainer'] p::before {{ content: '▤'; }}
    [data-testid='stSidebar'] [data-testid='stRadioGroup'] > div:nth-child(3) [data-testid='stMarkdownContainer'] p::before {{ content: '▦'; }}
    [data-testid='stSidebar'] [data-testid='stRadioGroup'] > div:nth-child(4) [data-testid='stMarkdownContainer'] p::before {{ content: '♨'; }}
    [data-testid='stSidebar'] [data-testid='stRadioGroup'] > div:nth-child(5) [data-testid='stMarkdownContainer'] p::before {{ content: '▤'; }}
    [data-testid='stSidebar'] [data-testid='stRadioGroup'] > div:nth-child(6) [data-testid='stMarkdownContainer'] p::before {{ content: '▧'; }}
    [data-testid='stSidebar'] [data-testid='stRadioGroup'] > div:nth-child(7) [data-testid='stMarkdownContainer'] p::before {{ content: '↗'; }}
    [data-testid='stSidebar'] [data-testid='stRadioOption'] [data-testid='stMarkdownContainer'] p::before {{ display: inline-flex; justify-content: center; width: 1rem; font-size: .88rem; }}
    [data-testid='stSidebar'] [data-testid='stRadioOption']:hover:not(:has(input:checked)) {{ background: rgba(255,255,255,.10); border-color: rgba(255,255,255,.12); }}
    [data-testid='stSidebar'] [data-testid='stRadioOption']:has(input:checked),
    [data-testid='stSidebar'] [data-testid='stRadioOption']:has(input:checked):hover {{ background: #C65D3B; border-color: #D46D4B; box-shadow: 0 2px 8px rgba(0,0,0,.12); }}
    [data-testid='stSidebar'] [data-testid='stRadioOption']:has(input:checked) * {{ color: #FFFDF9 !important; font-weight: 700; }}
    [data-testid='stSidebar'] [data-testid='stRadioOption']:focus-within {{ outline: 2px solid #F6EBDD; outline-offset: 2px; }}
    [data-testid='stSidebar'] .sidebar-footer {{ position: fixed; left: .9rem; bottom: .7rem; z-index: 5; width: 222px; box-sizing: border-box; border-top: 1px solid rgba(255,255,255,.18); margin: 0; padding: .68rem .12rem .12rem; background: #244C43; color: #D5E2DC; font-size: .76rem; line-height: 1.5; }}
    .page-kicker {{ color: {BRAND['primary']}; font-size: .68rem; font-weight: 800; letter-spacing: .14em; margin: 0 0 .1rem; }}
    .page-status {{ display: flex; justify-content: flex-end; align-items: center; gap: .5rem; flex-wrap: wrap; padding-top: .45rem; }}
    .page-status span {{ display: inline-flex; align-items: center; border: 1px solid #E8D8C7; border-radius: 7px; background: #FBF3EA; color: {BRAND['primary_dark']}; padding: .38rem .58rem; font-size: .67rem; font-weight: 750; letter-spacing: .045em; white-space: nowrap; }}
    .page-status .period {{ background: {BRAND['surface']}; color: #5E655F; font-weight: 550; letter-spacing: 0; }}
    .filter-kicker {{ color: #6C6258; font-size: .67rem; line-height: 1.2; font-weight: 800; letter-spacing: .12em; padding: 0 0 .62rem .12rem; }}
    [data-testid='stVerticalBlockBorderWrapper'] {{ border: 1px solid #E9DCCB !important; border-radius: 12px !important; background: {BRAND['surface']}; box-shadow: 0 4px 14px rgba(69,49,31,.035); }}
    [data-testid='stVerticalBlockBorderWrapper'] > div {{ border-radius: 12px; }}
    [data-testid='stHorizontalBlock'] {{ gap: .72rem; }}
    div[data-testid='stColumn']:has([data-testid='stPlotlyChart']) {{ background: {BRAND['surface']}; border: 1px solid #E9DCCB; border-radius: 12px; padding: .62rem .68rem .38rem; box-shadow: 0 4px 14px rgba(69,49,31,.035); }}
    div[data-testid='stColumn']:has([data-testid='stPlotlyChart']) [data-testid='stVerticalBlock'] {{ gap: .25rem; }}
    [data-testid='stMainBlockContainer'] > [data-testid='stVerticalBlock'] > [data-testid='stElementContainer']:has([data-testid='stPlotlyChart']) {{ background: {BRAND['surface']}; border: 1px solid #E9DCCB; border-radius: 12px; padding: .35rem .55rem .15rem; box-shadow: 0 4px 14px rgba(69,49,31,.035); }}
    [data-testid='stPlotlyChart'] {{ border-radius: 9px; overflow: hidden; }}
    [data-testid='stPlotlyChart'] iframe {{ border-radius: 9px; }}
    [data-testid='stSelectbox'] label, [data-testid='stDateInput'] label {{ font-size: .73rem; font-weight: 650; color: #51483F; margin-bottom: .22rem; }}
    [data-testid='stSelectbox'] [data-baseweb='select'] > div, [data-testid='stDateInput'] input {{ border-color: #E5D7C7; border-radius: 7px; background: #FFFDF9; min-height: 2.35rem; }}
    [data-testid='stButton'] button {{ min-height: 2.35rem; border: 1px solid #EBCAB8; border-radius: 7px; color: {BRAND['primary_dark']}; background: #FBF3EA; font-weight: 700; transition: background-color .15s ease, color .15s ease; }}
    [data-testid='stButton'] button:hover {{ border-color: {BRAND['primary']}; background: {BRAND['primary']}; color: white; }}
    [data-testid='stCaptionContainer'], [data-testid='stCaptionContainer'] p {{ color: #51483F !important; }}
    h1, h2 {{ color: {BRAND['primary_dark']}; }}
    h1 {{ font-size: clamp(1.65rem, 2vw, 2rem); letter-spacing: -.035em; margin: 0 0 .65rem; }}
    h2 {{ font-size: 1.06rem; letter-spacing: -.015em; margin-bottom: .15rem; }}
    .alert-card {{ box-sizing: border-box; height: 144px; min-height: 144px; max-height: 144px; overflow: hidden; display: flex; flex-direction: column; gap: 5px; background: {BRAND['surface']}; border: 1px solid #E9DCCB; border-left: 4px solid {BRAND['neutral']}; border-radius: 10px; padding: 10px 12px; margin: 0 0 8px 0; }}
    .alert-card.critical {{ border-left-color: {BRAND['danger']}; }}
    .alert-card.caution {{ border-left-color: {BRAND['warning']}; }}
    .alert-card.notice {{ border-left-color: {BRAND['secondary']}; }}
    .alert-card .alert-title {{ min-height: 2.2em; font-size: .79rem; line-height: 1.3; }}
    .alert-card .alert-message {{ display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; min-height: 2.45em; color: #303B36; font-size: .79rem; line-height: 1.3; }}
    .alert-card small {{ display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; min-height: 2.45em; margin-top: auto; color: #56615C; font-size: .73rem; line-height: 1.3; }}
    div[data-testid='stMetric'] {{ background: {BRAND['surface']}; border: 1px solid #E9DCCB; border-top: 3px solid {BRAND['primary']}; padding: 12px 10px; border-radius: 12px; min-height: 116px; box-shadow: 0 3px 12px rgba(69,49,31,.04); text-align: center; align-items: center; }}
    div[data-testid='stHorizontalBlock']:has(div[data-testid='stMetric']) > div[data-testid='stColumn']:nth-child(4n + 2) div[data-testid='stMetric'] {{ border-top-color: {BRAND['secondary']}; }}
    div[data-testid='stHorizontalBlock']:has(div[data-testid='stMetric']) > div[data-testid='stColumn']:nth-child(4n + 3) div[data-testid='stMetric'] {{ border-top-color: {BRAND['warning']}; }}
    div[data-testid='stHorizontalBlock']:has(div[data-testid='stMetric']) > div[data-testid='stColumn']:nth-child(4n) div[data-testid='stMetric'] {{ border-top-color: #718A9B; }}
    div[data-testid='stMetricLabel'] {{ justify-content: center; }}
    div[data-testid='stMetricLabel'] p {{ font-size: .9rem; font-weight: 650; text-align: center; }}
    div[data-testid='stMetricValue'] {{ justify-content: center; font-size: 1.55rem; line-height: 1.15; font-weight: 800; }}
    div[data-testid='stMetricDelta'] {{ font-size: .82rem; }}
    [data-testid='stCaptionContainer'] p {{ font-size: .88rem; line-height: 1.45; }}
    .kpi-context {{ margin-top: -10px; min-height: 36px; padding: 0 10px 9px; border: 1px solid #E9DCCB; border-top: 0; border-radius: 0 0 12px 12px; background: {BRAND['surface']}; display:flex; justify-content:space-between; align-items:center; gap:8px; color:#626761; font-size:.68rem; line-height:1.25; }}
    .kpi-context .good {{ color:#28744A; }} .kpi-context .watch {{ color:#A6502E; }}
    .order-flow {{ display:flex; align-items:stretch; gap:9px; margin:.25rem 0 .15rem; }}
    .flow-step {{ flex:1; min-width:0; display:flex; flex-direction:column; justify-content:center; gap:4px; background:#F9F5EF; border:1px solid #E9DCCB; border-radius:10px; padding:12px 14px; }}
    .flow-step small {{ color:{BRAND['primary']}; font-size:.66rem; font-weight:800; letter-spacing:.1em; }}
    .flow-step b {{ color:#244C43; font-size:.9rem; }} .flow-step span {{ color:#626761; font-size:.74rem; }}
    .flow-step.bottleneck {{ background:#FFF1E8; border:2px solid {BRAND['primary']}; }}
    .order-flow > i {{ align-self:center; color:#C6A78D; font-size:1.5rem; font-style:normal; }}
    [data-testid='stHeadingWithActionElements'] a, [data-testid='stHeadingWithActionElements'] button {{ visibility:hidden !important; }}
    .chart-insight {{ background: #F7F1E8; border-left: 3px solid {BRAND['primary']}; border-radius: 0 8px 8px 0; padding: 8px 10px; color: #51483F; font-size: .83rem; line-height: 1.4; margin: 5px 0 8px; }}
    [data-testid='stDataFrame'] {{ border: 1px solid #E9DCCB; border-radius: 9px; overflow: hidden; background: {BRAND['surface']}; }}
    [data-testid='stDataFrame'] [role='columnheader'] {{ background: #F7F1E8; font-weight: 750; }}
    .alert-grid .alert-card {{ height: 144px; }}
    @media (max-width: 780px) {{ .order-flow {{ flex-wrap:wrap; }} .flow-step {{ flex-basis:42%; }} .order-flow > i {{ display:none; }} }}
    @media (max-width: 1120px) {{
      [data-testid='stMain'] [data-testid='stHorizontalBlock'] {{ flex-wrap: wrap; }}
      [data-testid='stMain'] [data-testid='stHorizontalBlock'] > [data-testid='stColumn'] {{ flex: 1 1 calc(50% - 1rem) !important; min-width: min(100%, 230px); }}
    }}
    </style>""", unsafe_allow_html=True)
    try:
        data = load_data()
    except Exception as exc:
        st.error(str(exc)); st.stop()
    logo = ASSETS / "logo_mark.png"
    modules = ["Overview", "Orders", "Tables", "Kitchen", "Inventory", "Sales / Reports", "Food Cost & Profit"]
    module_labels = {
        "Overview": "Ikhtisar", "Orders": "Pesanan",
        "Tables": "Meja", "Kitchen": "Dapur",
        "Inventory": "Stok", "Sales / Reports": "Penjualan & Laporan",
        "Food Cost & Profit": "Profitabilitas",
    }
    if "active_module" not in st.session_state or st.session_state["active_module"] not in modules:
        st.session_state["active_module"] = "Overview"
    with st.sidebar:
        logo_html = ""
        if logo.exists():
            encoded_logo = base64.b64encode(logo.read_bytes()).decode("ascii")
            logo_html = f"<img src='data:image/png;base64,{encoded_logo}' alt='Logo Mangkuk Kita'>"
        st.markdown(f"<div class='brand-lockup'>{logo_html}<div><b>Mangkuk Kita</b><small>SATU MANGKUK, SERIBU CERITA</small></div></div>", unsafe_allow_html=True)
        st.divider()
        st.markdown("<div class='sidebar-kicker'>MODUL UTAMA</div>", unsafe_allow_html=True)
        st.radio("Modul utama", modules, format_func=lambda value: module_labels[value], key="active_module", label_visibility="collapsed")
        st.divider()
        st.markdown("<div class='sidebar-footer'><b>Proyek Visualisasi Data · DIF61143</b><br>Data sintetis · 3 cabang · 14 hari</div>", unsafe_allow_html=True)

    module = st.session_state["active_module"]
    page_titles = {"Overview": "Ikhtisar", "Orders": "Pesanan", "Tables": "Meja",
                   "Kitchen": "Dapur", "Inventory": "Stok", "Sales / Reports": "Penjualan & Laporan",
                   "Food Cost & Profit": "Profitabilitas"}
    title_col, status_col = st.columns([3.1, 1.4], vertical_alignment="center")
    with title_col:
        st.markdown("<div class='page-kicker'>RESTAURANT MANAGEMENT DASHBOARD</div>", unsafe_allow_html=True)
        st.title(page_titles[module])
    with status_col:
        st.markdown("<div class='page-status'><span>● MODE PRATINJAU · DATA SINTETIS</span><span class='period'>Filter berlaku di semua halaman</span></div>", unsafe_allow_html=True)
    filters = get_filters(data, module)
    orders, items = select_data(data, filters)
    occupancy = occupancy_for_selection(data, orders, filters)
    alerts = insights(data, orders, items, occupancy, filters["branches"])
    branches = data["branches"].set_index("branch_id")["nama"].to_dict()
    if module == "Overview":
        revenue = float(items["revenue"].sum()) if len(items) else 0
        food_cost = float(items["food_cost_total"].sum()) if len(items) else 0
        profit_after_food = revenue - food_cost
        margin_pct = profit_after_food / revenue * 100 if revenue else 0
        order_count = int(orders.order_id.nunique())
        average_order = revenue / order_count if order_count else 0
        span_days = max(1, (filters["end"] - filters["start"]).days + 1)
        split_date = filters["start"] + pd.Timedelta(days=span_days // 2)
        first_half = items[items.tanggal_dt < split_date].revenue.sum()
        second_half = items[items.tanggal_dt >= split_date].revenue.sum()
        revenue_delta = ((second_half - first_half) / first_half * 100) if first_half else None
        delta_label = (("+" if revenue_delta >= 0 else "−") + angka_id(abs(revenue_delta), 1) + "% · paruh akhir vs awal") if revenue_delta is not None else None
        branch_sales = items.groupby("branch_id").revenue.sum().sort_values(ascending=False)
        best_branch_id = branch_sales.index[0] if len(branch_sales) else None
        menu_sales = items.groupby("nama_menu").qty.sum().sort_values(ascending=False)
        best_menu = menu_sales.index[0] if len(menu_sales) else None
        prep_avg = float(orders.durasi_persiapan_menit.mean()) if len(orders) else 0
        late_pct = float(orders.durasi_persiapan_menit.gt(20).mean() * 100) if len(orders) else 0
        occ_pct = float(occupancy.occupied_table_minutes.sum() / occupancy.available_table_minutes.sum() * 100) if len(occupancy) and occupancy.available_table_minutes.sum() else 0
        target_revenue = len(filters["branches"]) * span_days * 25_000_000
        target_orders = 9000 * span_days / 14 * len(filters["branches"]) / max(len(data["branches"]), 1)
        kpis = [
            ("Total Pendapatan", rupiah_compact(revenue), "Nilai seluruh item dalam cakupan filter.", None,
             f"Target: {rupiah_compact(target_revenue)} · semua kategori/channel", "Di atas target" if revenue >= target_revenue else "Perlu perhatian"),
            ("Total Pesanan", angka_id(order_count), "Jumlah pesanan unik setelah filter.", None,
             f"Target acuan: {angka_id(target_orders)} untuk periode/cabang terpilih", "Di atas target" if order_count >= target_orders else "Perlu perhatian"),
            ("Margin Setelah Bahan", f"{angka_id(margin_pct, 1)}%", "Profit setelah biaya bahan dibagi pendapatan.", None,
             "Target: ≥ 35%", "Di atas target" if margin_pct >= 35 else "Perlu perhatian"),
            ("Waktu Persiapan Rata-rata", f"{angka_id(prep_avg, 1)} menit", "Selisih waktu selesai dan waktu masuk.", None,
             "Target: ≤ 15 menit", "Di atas target" if prep_avg <= 15 else "Perlu perhatian"),
            ("Pesanan Terlambat", f"{angka_id(late_pct, 1)}%", "Persiapan lebih dari 20 menit.", None,
             "Target: < 10%", "Di atas target" if late_pct < 10 else "Perlu perhatian"),
            ("Okupansi Rata-rata", f"{angka_id(occ_pct, 1)}%", "Meja-menit terisi dibandingkan kapasitas waktu tersedia.", None,
             "Target: 60–75%", "Sesuai target" if 60 <= occ_pct <= 75 else "Perlu perhatian"),
        ]
        for row_index in range(2):
            kpi_cols = st.columns(3, gap="small")
            for column, (label, value, help_text, delta, target, status) in zip(kpi_cols, kpis[row_index * 3:(row_index + 1) * 3]):
                with column: kpi_card(label, value, help_text, delta, target, status)
        best_branch_name = short_branch(branches.get(best_branch_id, best_branch_id)) if best_branch_id else "belum tersedia"
        best_menu_units = int(menu_sales.iloc[0]) if len(menu_sales) else 0
        st.markdown(f"<div class='chart-insight'><b>Ringkasan bisnis:</b> cabang dengan pendapatan tertinggi adalah {best_branch_name} ({rupiah_compact(branch_sales.iloc[0]) if len(branch_sales) else '—'}); menu terlaris {best_menu or '—'} ({angka_id(best_menu_units)} unit). Profit setelah bahan {rupiah_compact(profit_after_food)} dari {angka_id(order_count)} pesanan; rata-rata nilai pesanan {rupiah_compact(average_order)}.</div>", unsafe_allow_html=True)
        left, right = st.columns([1.15, 1], gap="large")
        with left:
            st.subheader("Tren Pendapatan Harian per Cabang")
            st.caption("Perubahan nilai transaksi harian untuk membandingkan pola dan kontribusi penjualan tiap cabang.")
            trend = items.groupby(["tanggal", "branch_id"], as_index=False)["revenue"].sum()
            trend["cabang"] = trend.branch_id.map(branches)
            trend["pendapatan_jt"] = trend.revenue / 1_000_000
            trend["tanggal_label"] = pd.to_datetime(trend.tanggal).map(tanggal_id)
            fig = px.line(trend, x="tanggal_label", y="pendapatan_jt", color="cabang", markers=True,
                          color_discrete_map=COLOR_CABANG, category_orders={"cabang": ORDER_CABANG}, labels={"tanggal_label":"Tanggal", "pendapatan_jt":"Pendapatan (juta Rp)", "cabang":"Cabang"})
            fig.update_yaxes(tickformat=",.0f", ticksuffix=" jt")
            st.plotly_chart(chart_layout(fig), use_container_width=True)
            if len(trend):
                totals = trend.groupby("cabang").revenue.sum().sort_values(ascending=False)
                st.markdown(f"<div class='chart-insight'><b>Temuan:</b> {totals.index[0]} mencatat pendapatan tertinggi ({rupiah_compact(totals.iloc[0])}). Gunakan pola hari yang turun untuk mengevaluasi promosi dan aktivitas penjualan.</div>", unsafe_allow_html=True)
        with right:
            st.subheader("Peta Kinerja Cabang")
            st.caption("Peta skematis offline; titik menunjukkan pusat kota cabang, sedangkan ukuran lingkaran membandingkan pendapatan.")
            branch_revenue = items.groupby("branch_id", as_index=False)["revenue"].sum().merge(data["branches"], on="branch_id", how="right")
            branch_revenue["revenue"] = branch_revenue["revenue"].fillna(0)
            st.plotly_chart(create_branch_map(branch_revenue, 420), use_container_width=True)
        st.subheader("Peringatan Aktif")
        st.caption(f"{len(alerts)} kondisi operasional melewati ambang pemantauan pada filter saat ini.")
        render_insights(alerts)

    elif module == "Orders":
        channel_counts = orders.channel.value_counts()
        channel_cols = st.columns(3)
        for column, channel in zip(channel_cols, ["Dine-in", "Takeaway", "Delivery"]):
            with column:
                kpi_card(f"Pesanan · {channel}", angka_id(int(channel_counts.get(channel, 0))), "Jumlah pesanan pada channel ini setelah filter aktif.")
        if len(orders):
            busiest_hour = int(orders.jam.value_counts().idxmax())
            weekdays = {"Monday":"Senin", "Tuesday":"Selasa", "Wednesday":"Rabu", "Thursday":"Kamis", "Friday":"Jumat", "Saturday":"Sabtu", "Sunday":"Minggu"}
            busiest_day = weekdays[orders.waktu_masuk.dt.day_name().value_counts().idxmax()]
            st.caption(f"Puncak pesanan: {busiest_day} sekitar pukul {busiest_hour:02d}. Gunakan jam ini untuk menyesuaikan kesiapan staf dan persediaan.")
        left, right = st.columns(2)
        with left:
            st.subheader("Menu terlaris per kategori")
            st.caption("Batang lebih panjang berarti jumlah unit terjual lebih banyak. Warna menunjukkan kategori menu.")
            top = items.groupby(["nama_menu", "kategori"], as_index=False)["qty"].sum().nlargest(10, "qty").sort_values("qty", ascending=False)
            display_order = top.sort_values("qty", ascending=True).nama_menu.tolist()
            fig = px.bar(top, x="qty", y="nama_menu", color="kategori", orientation="h", labels={"qty":"Unit terjual", "nama_menu":"Menu", "kategori":"Kategori"}, color_discrete_map=COLOR_KATEGORI, category_orders={"nama_menu": display_order, "kategori": ORDER_KATEGORI})
            fig.update_traces(hovertemplate="%{y}<br>Unit terjual: %{x:,.0f}<extra></extra>")
            st.plotly_chart(chart_layout(fig, 420), use_container_width=True)
            if len(top):
                best_seller = top.nlargest(1, "qty").iloc[0]
                st.markdown(f"<div class='chart-insight'><b>Temuan:</b> {best_seller.nama_menu} paling banyak terjual ({angka_id(best_seller.qty)} unit). Prioritaskan ketersediaan bahan menu ini pada jam ramai.</div>", unsafe_allow_html=True)
        with right:
            st.subheader("Volume pesanan menurut jam dan hari")
            st.caption("Warna lebih pekat menunjukkan lebih banyak pesanan pada jam dan hari tersebut.")
            day_names = {"Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu", "Thursday": "Kamis", "Friday": "Jumat", "Saturday": "Sabtu", "Sunday": "Minggu"}
            heat = orders.assign(hari=orders.waktu_masuk.dt.day_name().map(day_names)).pivot_table(index="hari", columns="jam", values="order_id", aggfunc="count", fill_value=0)
            day_order = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
            heat = heat.reindex([d for d in day_order if d in heat.index])
            fig = px.imshow(heat, aspect="auto", color_continuous_scale=[[0, "#F6EBDD"], [.5, BRAND["warning"]], [1, BRAND["primary"]]], labels=dict(x="Jam", y="Hari", color="Jumlah pesanan"))
            st.plotly_chart(chart_layout(fig, 480), use_container_width=True)
        st.subheader("Rincian pesanan")
        st.caption("Hijau = selesai · merah = terlambat (>20 menit) · kuning = masih diproses. Total bayar tetap mencakup seluruh item dalam pesanan, meski filter kategori menu aktif.")
        order_source = orders.sort_values("waktu_masuk", ascending=False).copy()
        is_late = order_source.durasi_persiapan_menit.gt(20)
        is_open = order_source.waktu_selesai.isna()
        order_source["status"] = np.select(
            [is_late, is_open], ["Terlambat", "Diproses"], default="Selesai")
        order_view = order_source[["order_id", "waktu_masuk", "branch_id", "channel", "status", "durasi_persiapan_menit", "total_bayar"]].rename(columns={
            "order_id": "ID pesanan", "waktu_masuk": "Waktu masuk", "branch_id": "ID cabang",
            "channel": "Channel pesanan", "status": "Status", "durasi_persiapan_menit": "Persiapan (menit)", "total_bayar": "Total bayar (Rp)"
        })
        order_view["Persiapan (menit)"] = order_view["Persiapan (menit)"].map(lambda value: angka_id(value, 1))
        order_view["Total bayar (Rp)"] = order_view["Total bayar (Rp)"].map(rupiah)
        order_view["Cabang"] = order_view["ID cabang"].map(branches)
        order_view = order_view.drop(columns="ID cabang")
        styled_orders = order_view.style.map(
            lambda value: "background-color:#E7F1EB;color:#285E47;font-weight:700" if value == "Selesai"
            else "background-color:#FBE8E4;color:#982F24;font-weight:700" if value == "Terlambat"
            else "background-color:#FFF2D8;color:#805514;font-weight:700" if value == "Diproses" else "",
            subset=["Status"])
        st.dataframe(styled_orders, use_container_width=True, hide_index=True)

    elif module == "Tables":
        table_counts = data["tables"].groupby("branch_id").size().to_dict()
        total_tables = sum(table_counts.get(branch, 0) for branch in filters["branches"])
        peak_occupancy = occupancy.groupby("hour").occupancy_rate_pct.mean() if len(occupancy) else pd.Series(dtype=float)
        peak_hour = int(peak_occupancy.idxmax()) if len(peak_occupancy) else None
        peak_value = float(peak_occupancy.max()) if len(peak_occupancy) else 0.0
        avg_occupancy = float(occupancy.occupied_table_minutes.sum() / occupancy.available_table_minutes.sum() * 100) if len(occupancy) and occupancy.available_table_minutes.sum() else 0
        cols = st.columns(3)
        with cols[0]: kpi_card("Kapasitas meja", angka_id(total_tables), "Jumlah meja pada cabang yang dipilih.", target="Meja terdaftar di sistem", status="Sesuai data")
        with cols[1]: kpi_card("Okupansi rata-rata", f"{angka_id(avg_occupancy, 1)}%", "Meja-menit terisi dibanding meja-menit yang tersedia.", target="Target: 60–75%", status="Sesuai target" if 60 <= avg_occupancy <= 75 else "Perlu perhatian")
        with cols[2]: kpi_card("Jam okupansi tertinggi", f"{peak_hour:02d}.00 · {angka_id(peak_value, 1)}%" if peak_hour is not None else "—", "Jam dengan rata-rata okupansi tertinggi pada data terpilih.", target="Batas perhatian: 90%", status="Sesuai target" if peak_value <= 90 else "Perlu perhatian")
        st.caption("Ringkasan kapasitas dan okupansi di atas menunjukkan gambaran agregat cabang terpilih.")
        st.subheader("Denah meja cabang")
        st.caption("Denah skematis: posisi meja dan jalur dibuat untuk membantu orientasi, bukan berdasarkan layout bangunan. Warna menunjukkan frekuensi pesanan dine-in pada data yang lolos filter, bukan status meja saat ini. Jika channel Dine-in tidak dipilih, jumlah pesanan per meja akan nol. Arahkan kursor ke meja untuk melihat kapasitas dan jumlah pesanan.")
        selected_table_branches = filters["branches"]
        if len(selected_table_branches) > 1:
            branch_tabs = st.tabs([short_branch(branches[branch]) for branch in selected_table_branches])
            for tab, branch_id in zip(branch_tabs, selected_table_branches):
                with tab:
                    branch_tables = data["tables"][data["tables"].branch_id.eq(branch_id)]
                    branch_orders = orders[orders.branch_id.eq(branch_id)]
                    st.plotly_chart(create_table_plan(branch_tables, branch_orders), use_container_width=True)
        elif selected_table_branches:
            branch_id = selected_table_branches[0]
            branch_tables = data["tables"][data["tables"].branch_id.eq(branch_id)]
            branch_orders = orders[orders.branch_id.eq(branch_id)]
            st.plotly_chart(create_table_plan(branch_tables, branch_orders), use_container_width=True)
        st.subheader("Okupansi meja menurut jam")
        st.caption("Garis membandingkan rata-rata okupansi cabang; garis putus-putus menandai batas perhatian 90% kapasitas.")
        occ = occupancy.groupby(["hour", "branch_id"], as_index=False)["occupancy_rate_pct"].mean()
        occ["cabang"] = occ.branch_id.map(branches)
        fig = px.line(occ, x="hour", y="occupancy_rate_pct", color="cabang", markers=True, labels={"hour":"Jam", "occupancy_rate_pct":"Meja terisi (%)", "cabang":"Cabang"}, color_discrete_map=COLOR_CABANG, category_orders={"cabang": ORDER_CABANG})
        fig.add_hline(y=90, line_dash="dash", line_color=BRAND["danger"], annotation_text="Batas perhatian 90%", annotation_position="bottom left")
        fig.update_yaxes(range=[0, 100], ticksuffix="%")
        st.plotly_chart(chart_layout(fig, 430), use_container_width=True)
        if peak_hour is not None:
            st.markdown(f"<div class='chart-insight'><b>Temuan:</b> penggunaan meja tertinggi terjadi sekitar pukul {peak_hour:02d}.00 ({angka_id(peak_value, 1)}%). Pertimbangkan penjadwalan staf dan pengelolaan reservasi di rentang ini.</div>", unsafe_allow_html=True)
        waits = orders[orders.channel.eq("Dine-in")]
        st.subheader("Waktu tunggu meja")
        if len(waits):
            st.caption("Rata-rata menit menunggu meja dine-in. Garis putus-putus menandai target maksimum 15 menit.")
            wait = waits.groupby("jam", as_index=False)["waktu_tunggu_meja_menit"].mean()
            fig = px.bar(wait, x="jam", y="waktu_tunggu_meja_menit", labels={"jam":"Jam kedatangan", "waktu_tunggu_meja_menit":"Rata-rata tunggu (menit)"}, color_discrete_sequence=[BRAND["secondary"]])
            fig.add_hline(y=15, line_dash="dash", line_color=BRAND["danger"], annotation_text="Target 15 menit", annotation_position="top left")
            st.plotly_chart(chart_layout(fig, 330), use_container_width=True)
            max_wait = float(wait.waktu_tunggu_meja_menit.max())
            peak_wait = wait.loc[wait.waktu_tunggu_meja_menit.idxmax()]
            st.markdown(f"<div class='chart-insight'><b>Temuan:</b> waktu tunggu rata-rata tertinggi {angka_id(max_wait, 1)} menit pada pukul {int(peak_wait.jam):02d}.00; {'masih dalam' if max_wait <= 15 else 'melewati'} target 15 menit.</div>", unsafe_allow_html=True)

    elif module == "Kitchen":
        avg_order_prep = float(orders.durasi_persiapan_menit.mean()) if len(orders) else 0
        delayed_count = int(orders.durasi_persiapan_menit.gt(20).sum()) if len(orders) else 0
        station_summary = items.groupby("station", as_index=False).agg(rata_persiapan=("waktu_persiapan_menit", "mean"), jumlah_item=("waktu_persiapan_menit", "count")) if len(items) else pd.DataFrame(columns=["station", "rata_persiapan", "jumlah_item"])
        slow_station = station_summary.sort_values("rata_persiapan", ascending=False).head(1)
        slow_station_label = f"{ORDER_STATION.get(slow_station.iloc[0].station, slow_station.iloc[0].station)} · {angka_id(slow_station.iloc[0].rata_persiapan, 1)} mnt" if len(slow_station) else "—"
        cols = st.columns(3)
        with cols[0]: kpi_card("Rata-rata persiapan pesanan", f"{angka_id(avg_order_prep, 1)} menit", "Dihitung dari waktu pesanan masuk sampai selesai disiapkan.", target="Target: ≤ 15 menit", status="Sesuai target" if avg_order_prep <= 15 else "Perlu perhatian")
        delayed_pct = delayed_count / len(orders) * 100 if len(orders) else 0
        with cols[1]: kpi_card("Pesanan terlambat", f"{angka_id(delayed_count)} ({angka_id(delayed_pct, 1)}%)", "Jumlah dan persentase pesanan dengan waktu persiapan lebih dari 20 menit.", target="Target: < 10%", status="Di atas target" if delayed_pct < 10 else "Perlu perhatian")
        with cols[2]: kpi_card("Pos dengan rata-rata terlama", slow_station_label, "Rata-rata waktu persiapan per item menu yang tercatat pada setiap pos dapur.", target="Tinjau bila rata-rata > 15 menit", status="Sesuai target" if len(slow_station) and slow_station.iloc[0].rata_persiapan <= 15 else "Perlu perhatian")
        st.subheader("Alur pesanan")
        bottleneck = ORDER_STATION.get(slow_station.iloc[0].station, slow_station.iloc[0].station) if len(slow_station) else "Masak"
        st.markdown(f"<div class='order-flow'><div class='flow-step'><small>01 · PESAN</small><b>Pesanan diterima</b><span>Waktu masuk tercatat</span></div><i>›</i><div class='flow-step bottleneck'><small>02 · MASAK</small><b>Persiapan dapur</b><span>Hambatan: {bottleneck} · {angka_id(float(slow_station.iloc[0].rata_persiapan), 1) if len(slow_station) else '—'} menit</span></div><i>›</i><div class='flow-step'><small>03 · SAJI</small><b>Pesanan selesai</b><span>Waktu siap tercatat</span></div><i>›</i><div class='flow-step'><small>04 · BAYAR</small><b>Transaksi dicatat</b><span>Nilai pembayaran</span></div></div>", unsafe_allow_html=True)
        st.caption("Titik hambatan ditandai dari pos dengan rata-rata waktu persiapan tertinggi. Dataset mengukur tahap persiapan, bukan durasi penyajian atau pembayaran.")
        left, right = st.columns(2)
        with left:
            st.subheader("Sebaran waktu persiapan per pos dapur")
            st.caption("Garis di tengah kotak = median; kotak merangkum setengah tengah pesanan. Makin rendah, makin cepat.")
            prep = items.sample(min(len(items), 8000), random_state=61143) if len(items) else items
            prep["pos_dapur"] = prep.station.map(ORDER_STATION).fillna(prep.station)
            fig = px.box(prep, x="pos_dapur", y="waktu_persiapan_menit", points=False, labels={"pos_dapur":"Pos dapur", "waktu_persiapan_menit":"Waktu persiapan (menit)"}, color_discrete_sequence=[BRAND["secondary"]])
            st.plotly_chart(chart_layout(fig), use_container_width=True)
            if len(station_summary):
                station_view = station_summary.copy()
                station_view["Pos dapur"] = station_view.station.map(ORDER_STATION).fillna(station_view.station)
                station_view["Rata-rata persiapan (menit)"] = station_view.rata_persiapan.map(lambda value: angka_id(value, 1))
                st.caption("Ringkasan rata-rata persiapan per pos dapur:")
                st.dataframe(station_view.sort_values("rata_persiapan", ascending=False)[["Pos dapur", "Rata-rata persiapan (menit)"]], use_container_width=True, hide_index=True)
        with right:
            st.subheader("Persentase pesanan terlambat per jam")
            st.caption("Pesanan terlambat berarti persiapan lebih dari 20 menit. Garis menunjukkan batas pemantauan 15%.")
            hourly = orders.groupby("jam", as_index=False).agg(delayed=("durasi_persiapan_menit", lambda s: s.gt(20).mean() * 100))
            fig = go.Figure(go.Bar(x=hourly.jam, y=hourly.delayed, marker_color=[BRAND["danger"] if v > 15 else BRAND["secondary"] for v in hourly.delayed], hovertemplate="Jam %{x}: %{y:.1f}% pesanan terlambat<extra></extra>"))
            fig.add_hline(y=15, line_dash="dash", line_color=BRAND["danger"], annotation_text="Batas 15%", annotation_position="top left")
            fig.update_xaxes(dtick=1, title="Jam")
            fig.update_yaxes(ticksuffix="%")
            st.plotly_chart(chart_layout(fig), use_container_width=True)
            if len(hourly):
                peak_delay = hourly.loc[hourly.delayed.idxmax()]
                st.markdown(f"<div class='chart-insight'><b>Temuan:</b> keterlambatan tertinggi terjadi pukul {int(peak_delay.jam):02d}.00 ({angka_id(peak_delay.delayed, 1)}%). Atur kesiapan kru dan bahan sebelum jam tersebut.</div>", unsafe_allow_html=True)
        st.subheader("Waktu persiapan menurut jumlah pesanan aktif")
        st.caption("Kotak membandingkan median dan rentang tengah waktu persiapan pada tiap tingkat beban dapur.")
        prep_groups = orders.copy()
        prep_groups["kelompok_aktif"] = pd.cut(prep_groups.pesanan_aktif, bins=[-1, 2, 5, 8, 11, np.inf], labels=["0–2", "3–5", "6–8", "9–11", "12+"])
        fig = px.box(prep_groups, x="kelompok_aktif", y="durasi_persiapan_menit", points=False,
                     labels={"kelompok_aktif":"Pesanan aktif saat masuk", "durasi_persiapan_menit":"Waktu persiapan (menit)"}, color_discrete_sequence=[BRAND["secondary"]])
        st.plotly_chart(chart_layout(fig, 380, showlegend=False), use_container_width=True)
    elif module == "Inventory":
        inv = data["inventory_metrics"].copy()
        inv = inv[inv.branch_id.isin(filters["branches"])]
        inv["cabang"] = inv.branch_id.map(branches)
        inv["rasio_stok"] = inv.stok_saat_ini / inv.stok_minimum.replace(0, np.nan)
        inv["status_stok"] = np.select([inv.stok_saat_ini.le(0), inv.stok_saat_ini.lt(inv.stok_minimum)], ["Habis", "Menipis"], default="Aman")
        status_rank = {"Habis": 0, "Menipis": 1, "Aman": 2}
        inv["urutan_status"] = inv.status_stok.map(status_rank)
        low_count = int(inv.status_stok.isin(["Habis", "Menipis"]).sum())
        empty_count = int(inv.status_stok.eq("Habis").sum())
        cols = st.columns(3)
        with cols[0]: kpi_card("Bahan di bawah minimum", angka_id(low_count), "Termasuk bahan habis dan stok yang kurang dari batas minimum.")
        with cols[1]: kpi_card("Bahan tanpa stok saat ini", angka_id(empty_count), "Jumlah bahan yang stok fisiknya nol atau kurang.")
        with cols[2]: kpi_card("Bahan aman", angka_id(int(inv.status_stok.eq('Aman').sum())), "Stok saat ini sama dengan atau melebihi minimum.")
        left, right = st.columns(2)
        with left:
            st.subheader("Ketersediaan stok terhadap minimum")
            st.caption("Rasio 1,00 berarti stok tepat di batas minimum; merah menunjukkan stok di bawah batas.")
            heat = inv.pivot_table(index="nama_bahan", columns="cabang", values="rasio_stok", aggfunc="mean").reindex(columns=[branches[b] for b in filters["branches"] if b in branches])
            heat.columns = [short_branch(c) for c in heat.columns]
            heat_text = np.vectorize(lambda value: angka_id(value, 2))(heat.values)
            fig = go.Figure(go.Heatmap(z=heat.values, x=heat.columns, y=heat.index, zmin=0, zmax=3, zmid=1,
                colorscale=[[0, "#B74736"], [1 / 3, "#F2C66D"], [1, "#2F5D50"]], text=heat_text, texttemplate="%{text}",
                colorbar=dict(title="Rasio"), hovertemplate="%{y}<br>%{x}: %{z:.2f}× minimum<extra></extra>"))
            fig.add_annotation(x=.5, y=-.14, xref="paper", yref="paper", text="Batas minimum stok: rasio 1,00×", showarrow=False, font=dict(size=11, color="#805514"))
            st.plotly_chart(chart_layout(fig, max(420, min(760, 28 * len(heat))), showlegend=False), use_container_width=True)
        with right:
            st.subheader("Persentase bahan terbuang")
            st.caption("Limbah dihitung sebagai nilai bahan terbuang ÷ nilai pembelian. Garis putus-putus menunjukkan target 8%.")
            waste = inv.nlargest(15, "waste_rate_pct").copy()
            waste["cabang"] = waste.branch_id.map(branches).map(short_branch)
            fig = px.bar(waste.sort_values("waste_rate_pct"), x="waste_rate_pct", y="nama_bahan", color="cabang", orientation="h", barmode="group",
                labels={"waste_rate_pct":"Bahan terbuang (%)", "nama_bahan":"Bahan", "cabang":"Cabang"}, color_discrete_map={short_branch(k): v for k, v in COLOR_CABANG.items()},
                category_orders={"cabang": [short_branch(x) for x in ORDER_CABANG]})
            fig.add_vline(x=8, line_dash="dash", line_color=BRAND["danger"], annotation_text="Target limbah 8%", annotation_position="top")
            fig.update_xaxes(ticksuffix="%")
            st.plotly_chart(chart_layout(fig, max(420, min(760, 28 * len(waste)))), use_container_width=True)
            if len(waste):
                top_waste = waste.loc[waste.waste_rate_pct.idxmax()]
                over_waste = int(inv.waste_rate_pct.gt(8).sum())
                st.markdown(f"<div class='chart-insight'><b>Temuan:</b> {top_waste.nama_bahan} di {short_branch(branches[top_waste.branch_id])} memiliki limbah tertinggi ({angka_id(top_waste.waste_rate_pct, 1)}%); {over_waste} catatan bahan-cabang melewati 8%. Periksa pembelian dan persiapan bahan tersebut.</div>", unsafe_allow_html=True)
        st.subheader("Daftar stok dan limbah")
        inv["saran_stok"] = inv.apply(lambda row: " · ".join(
            (["Tambah pembelian"] if row.stok_saat_ini < row.stok_minimum else []) +
            (["Kurangi pembelian"] if row.waste_rate_pct > 8 else [])
        ) or "Pantau", axis=1)
        st.caption("Baris prioritas muncul lebih dahulu. Limbah ditampilkan sebagai persentase dari nilai pembelian; angka stok tetap memakai satuan bahan.")
        inventory_view = inv.sort_values(["urutan_status", "rasio_stok", "cabang"])[["cabang", "nama_bahan", "satuan", "status_stok", "stok_saat_ini", "stok_minimum", "total_dibeli", "total_terbuang", "stockout_events_14d", "waste_rate_pct", "saran_stok"]].rename(columns={
            "cabang": "Cabang", "nama_bahan": "Bahan", "satuan": "Satuan", "stok_saat_ini": "Stok tersedia",
            "stok_minimum": "Stok minimum", "total_dibeli": "Dibeli (14 hari)", "total_terbuang": "Terbuang (14 hari)",
            "stockout_events_14d": "Kejadian kehabisan stok (14 hari)", "waste_rate_pct": "Limbah (%)", "status_stok": "Status stok", "saran_stok": "Tindak lanjut"
        }).reset_index(drop=True)
        inventory_view["Status stok"] = inventory_view["Status stok"].map({"Habis": "🔴 Habis", "Menipis": "🟠 Menipis", "Aman": "🟢 Aman"})
        for column in ["Stok tersedia", "Stok minimum", "Dibeli (14 hari)", "Terbuang (14 hari)"]:
            inventory_view[column] = inventory_view[column].map(lambda value: angka_id(value, 1))
        inventory_view["Limbah (%)"] = inventory_view["Limbah (%)"].map(lambda value: f"{angka_id(value, 1)}%")
        inventory_view["Kejadian kehabisan stok (14 hari)"] = inventory_view["Kejadian kehabisan stok (14 hari)"].map(angka_id)
        inventory_view = inventory_view.sort_values(["Status stok", "Cabang"], kind="stable")
        st.dataframe(inventory_view, use_container_width=True, hide_index=True, height=520)

    elif module == "Sales / Reports":
        comments = data["feedback_joined"]
        comments = comments[comments.order_id.isin(orders.order_id)]
        export = items.copy()
        if len(export):
            export["nama_cabang"] = export.branch_id.map(branches)
            export["tanggal"] = export.tanggal_dt.dt.strftime("%Y-%m-%d")
            export = export[["order_id", "tanggal", "nama_cabang", "channel", "nama_menu", "kategori", "qty", "harga_satuan", "revenue", "food_cost_total", "profit"]]
        st.download_button("Unduh CSV data terfilter", data=export.to_csv(index=False, encoding="utf-8-sig"),
                           file_name="mangkuk_kita_penjualan_terfilter.csv", mime="text/csv",
                           help="Mengunduh rincian item pesanan untuk periode, cabang, kategori, dan channel terpilih.")
        st.subheader("Pendapatan menurut channel pesanan")
        st.caption("Bandingkan kontribusi setiap channel selama periode dan cabang terpilih.")
        by_channel = items.groupby(["channel", "branch_id"], as_index=False).revenue.sum()
        by_channel["cabang"] = by_channel.branch_id.map(branches).map(short_branch)
        by_channel["pendapatan_jt"] = by_channel.revenue / 1_000_000
        channel_total = by_channel.groupby("channel").revenue.sum().sort_values(ascending=False)
        total_channel_revenue = channel_total.sum()
        top_channel = channel_total.index[0] if len(channel_total) else "—"
        top_share = float(channel_total.iloc[0] / total_channel_revenue * 100) if total_channel_revenue else 0
        summary_cols = st.columns(3)
        with summary_cols[0]: kpi_card("Channel dengan pendapatan terbesar", f"{top_channel} · {angka_id(top_share, 1)}%", "Bagian pendapatan dari channel terbesar di antara channel terpilih.")
        with summary_cols[1]: kpi_card("Jumlah ulasan", angka_id(len(comments)), "Ulasan yang terhubung dengan pesanan dalam filter saat ini.")
        with summary_cols[2]: kpi_card("Rating rata-rata", f"{angka_id(comments.rating.mean(), 2)}/5" if len(comments) else "—", "Rata-rata rating pada ulasan yang terhubung dengan pesanan terpilih.")
        fig = px.bar(by_channel, x="channel", y="pendapatan_jt", color="cabang", barmode="group",
            labels={"channel":"Channel pesanan", "pendapatan_jt":"Pendapatan (juta Rp)", "cabang":"Cabang"},
            color_discrete_map={short_branch(k): v for k, v in COLOR_CABANG.items()}, category_orders={"cabang": [short_branch(x) for x in ORDER_CABANG]})
        fig.update_yaxes(tickformat=",.0f", ticksuffix=" jt")
        st.plotly_chart(chart_layout(fig, 390), use_container_width=True)
        st.subheader("Topik yang sering disebut pelanggan")
        st.caption("Word cloud merangkum kata yang disebut pada ulasan. Grafik di bawah memisahkan kata utuh pada pujian (rating ≥ 4) dan keluhan (rating ≤ 2); jumlah menunjukkan banyak ulasan yang memuat kata tersebut.")
        st.plotly_chart(build_feedback_terms(comments), use_container_width=True)
        praise, complaint = st.columns(2, gap="large")
        with praise:
            st.subheader("Pujian · rating ≥ 4")
            st.plotly_chart(build_sentiment_words(comments, 4, 5, BRAND["secondary"]), use_container_width=True)
        with complaint:
            st.subheader("Keluhan · rating ≤ 2")
            st.plotly_chart(build_sentiment_words(comments, 1, 2, BRAND["danger"]), use_container_width=True)
        if len(comments):
            st.caption(f"{angka_id(len(comments))} ulasan pada filter saat ini; rating rata-rata {angka_id(comments.rating.mean(), 2)}/5.")
        st.subheader("Ringkasan kinerja cabang")
        summary = items.groupby("branch_id", as_index=False).agg(revenue=("revenue", "sum"), food_cost=("food_cost_total", "sum"), units=("qty", "sum"))
        summary["cabang"] = summary.branch_id.map(branches)
        summary["margin_pct"] = (summary.revenue - summary.food_cost) / summary.revenue * 100
        st.caption("Pendapatan dan unit terjual dibandingkan dengan margin setelah biaya bahan; gunakan hasil ini untuk menentukan cabang yang perlu ditinjau lebih lanjut.")
        summary_view = summary[["cabang", "revenue", "units", "margin_pct"]].sort_values("revenue", ascending=False).rename(
            columns={"cabang": "Cabang", "revenue": "Pendapatan", "units": "Unit terjual", "margin_pct": "Margin setelah bahan (%)"})
        summary_view["Pendapatan"] = summary_view["Pendapatan"].map(rupiah)
        summary_view["Unit terjual"] = summary_view["Unit terjual"].map(angka_id)
        summary_view["Margin setelah bahan (%)"] = summary_view["Margin setelah bahan (%)"].map(lambda value: f"{angka_id(value, 1)}%")
        st.dataframe(summary_view, use_container_width=True, hide_index=True)

    elif module == "Food Cost & Profit":
        menu = items.groupby(["menu_id", "nama_menu", "kategori", "harga_satuan", "food_cost"], as_index=False).agg(units=("qty", "sum"), revenue=("revenue", "sum"), food_cost_total=("food_cost_total", "sum"), profit=("profit", "sum"))
        menu["margin_pct"] = (menu.revenue - menu.food_cost_total) / menu.revenue.replace(0, np.nan) * 100
        best = menu.loc[menu.margin_pct.idxmax()] if len(menu) else None
        lowest = menu.loc[menu.margin_pct.idxmin()] if len(menu) else None
        cols = st.columns(3)
        with cols[0]: kpi_card("Margin tertinggi", f"{angka_id(best.margin_pct, 1)}%" if best is not None else "—", f"Menu: {best.nama_menu}. Margin tertinggi setelah bahan pada filter saat ini." if best is not None else "Tidak ada data menu.")
        with cols[1]: kpi_card("Margin terendah", f"{angka_id(lowest.margin_pct, 1)}%" if lowest is not None else "—", f"Menu: {lowest.nama_menu}. Margin terendah setelah bahan pada filter saat ini." if lowest is not None else "Tidak ada data menu.")
        with cols[2]: kpi_card("Menu di bawah target", angka_id(int(menu.margin_pct.lt(25).sum())), "Jumlah menu dengan margin setelah bahan di bawah 25%.")
        left, right = st.columns(2)
        with left:
            st.subheader("Margin Setelah Bahan per Menu")
            below_threshold = int(menu.margin_pct.lt(25).sum())
            st.caption(f"Batang membandingkan margin setiap menu. Garis 25% adalah target evaluasi; {below_threshold} menu berada di bawahnya.")
            menu["status_margin"] = np.where(menu.margin_pct.lt(25), "Di bawah 25%", "Memenuhi 25%")
            margin_order = menu.sort_values("margin_pct")
            fig = px.bar(margin_order, x="margin_pct", y="nama_menu", orientation="h", color="status_margin",
                color_discrete_map={"Di bawah 25%": BRAND["danger"], "Memenuhi 25%": BRAND["secondary"]},
                category_orders={"status_margin": ["Di bawah 25%", "Memenuhi 25%"]},
                labels={"margin_pct":"Margin setelah bahan (%)", "nama_menu":"Menu", "status_margin":"Status margin"})
            fig.add_vline(x=25, line_dash="dash", line_color=BRAND["neutral"], annotation_text="Target 25%", annotation_position="top")
            fig.update_xaxes(ticksuffix="%")
            fig.update_layout(legend_title_text="")
            fig.update_yaxes(dtick=1, automargin=True, categoryorder="array", categoryarray=margin_order.nama_menu.tolist())
            st.plotly_chart(chart_layout(fig, max(680, 28 * len(menu) + 160), margin=dict(l=110, r=22, t=50, b=30)), use_container_width=True)
            if best is not None and lowest is not None:
                st.markdown(f"<div class='chart-insight'><b>Insight:</b> {below_threshold} menu perlu ditinjau; mulai dari {lowest.nama_menu} ({angka_id(lowest.margin_pct, 1)}%). Evaluasi harga jual atau biaya bahan sebelum mengubah menu.</div>", unsafe_allow_html=True)
        with right:
            st.subheader("Margin setelah bahan per cabang dan kategori")
            st.caption("Nilai pendapatan setelah biaya bahan; biaya gaji, sewa, dan operasional lain belum dikurangi.")
            profit = items.groupby(["branch_id", "kategori"], as_index=False)["profit"].sum()
            profit["cabang"] = profit.branch_id.map(branches).map(short_branch)
            profit["margin_setelah_bahan_jt"] = profit.profit / 1_000_000
            fig = px.bar(profit, x="cabang", y="margin_setelah_bahan_jt", color="kategori", barmode="group", labels={"cabang":"Cabang", "margin_setelah_bahan_jt":"Margin setelah bahan (juta Rp)", "kategori":"Kategori"}, color_discrete_map=COLOR_KATEGORI, category_orders={"kategori": ORDER_KATEGORI, "cabang": [short_branch(x) for x in ORDER_CABANG]})
            fig.update_yaxes(tickformat=",.0f", ticksuffix=" jt")
            st.plotly_chart(chart_layout(fig), use_container_width=True)
        st.subheader("Rincian profitabilitas menu")
        st.caption("Menu diurutkan berdasarkan unit terjual terbanyak. Status warna menunjukkan menu yang di bawah atau memenuhi target margin 25%.")
        menu_view = menu[["nama_menu", "kategori", "units", "revenue", "food_cost_total", "profit", "margin_pct"]].sort_values("units", ascending=False).rename(columns={
            "nama_menu": "Menu", "kategori": "Kategori", "units": "Unit terjual", "revenue": "Pendapatan (Rp)",
            "food_cost_total": "Biaya bahan (Rp)", "profit": "Margin setelah bahan (Rp)", "margin_pct": "Margin setelah bahan (%)"
        })
        menu_view["Status margin"] = np.where(menu_view["Margin setelah bahan (%)"] < 25, "Perlu ditinjau", "Memenuhi target")
        menu_view["Unit terjual"] = menu_view["Unit terjual"].map(angka_id)
        for column in ["Pendapatan (Rp)", "Biaya bahan (Rp)", "Margin setelah bahan (Rp)"]:
            menu_view[column] = menu_view[column].map(rupiah)
        menu_view["Margin setelah bahan (%)"] = menu_view["Margin setelah bahan (%)"].map(lambda value: f"{angka_id(value, 1)}%")
        styled_menu = menu_view.style.map(
            lambda value: "background-color:#FBE8E4;color:#982F24;font-weight:700" if value == "Perlu ditinjau" else "background-color:#E7F1EB;color:#285E47;font-weight:700",
            subset=["Status margin"])
        st.dataframe(styled_menu, use_container_width=True, hide_index=True)



if __name__ == "__main__":
    main()
