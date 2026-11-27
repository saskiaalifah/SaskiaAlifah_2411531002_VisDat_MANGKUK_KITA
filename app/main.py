"""Interactive seven-module restaurant dashboard for Mangkuk Kita."""
from __future__ import annotations

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
    items["food_cost_total"] = items["qty"] * items["food_cost"]
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
        return f"Rp{value / 1_000_000:,.1f} juta".replace(",", "X").replace(".", ",").replace("X", ".")
    return rupiah(value)


def chart_layout(fig, height=360, **kwargs):
    fig.update_layout(template=CHART_TEMPLATE, height=height, margin=dict(l=18, r=18, t=50, b=18),
                      font=dict(family="Inter, Arial, sans-serif", color="#31413D", size=12),
                      paper_bgcolor=BRAND["surface"], plot_bgcolor=BRAND["surface"], **kwargs)
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor="#E8E0D6", zeroline=False)
    return fig


def create_branch_map(branch_revenue: pd.DataFrame, height=440):
    if branch_revenue.empty:
        fig = go.Figure()
        fig.add_annotation(text="Tidak ada pendapatan pada filter ini", showarrow=False, x=.5, y=.5)
        return chart_layout(fig, height)
    fig = px.scatter_geo(branch_revenue, lat="latitude", lon="longitude", size="revenue", color="kota",
                         hover_name="nama", hover_data={"revenue": ":,.0f", "latitude": False, "longitude": False},
                         projection="mercator", scope="asia", size_max=48,
                         color_discrete_sequence=[BRAND["primary"], BRAND["secondary"], BRAND["warning"]],
                         labels={"revenue": "Pendapatan (Rp)"})
    fig.update_geos(showland=True, landcolor="#F3EBDD", showcountries=True, countrycolor="#D4C8B7",
                    showocean=True, oceancolor="#EAF2F0", showcoastlines=True, coastlinecolor="#B7C5C1",
                    lonaxis_range=[98, 104], lataxis_range=[-2.5, 2.5], center={"lon": 100.7, "lat": 0}, projection_scale=4.2)
    return chart_layout(fig, height)


def kpi_card(label, value, help_text=None):
    st.metric(label, value, help=help_text)


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
        title, reset = st.columns([4, 1])
        with title:
            st.markdown("#### Atur tampilan data")
            st.caption("Pilih filter; grafik dan angka akan langsung menyesuaikan. Gunakan ‘Semua’ untuk gabungan data.")
        with reset:
            st.write("")
            st.button("Reset filter", key="reset_filters", on_click=reset_filters, use_container_width=True)
        if module == "Inventory":
            branch_col = st.container()
            date_col = category_col = channel_col = None
        else:
            branch_col, date_col, category_col, channel_col = st.columns([1, 1.25, 1, 1], gap="small")
        with branch_col:
            branch_value = st.selectbox("Cabang", ["Semua cabang"] + branch_ids, key="filter_branch",
                                         format_func=lambda x: "Semua cabang" if x == "Semua cabang" else branch_names.get(x, x),
                                         help="Pilih satu cabang atau lihat semuanya.")
        selected_branches = branch_ids if branch_value == "Semua cabang" else [branch_value]
        selected_category, selected_channel = "Semua kategori", "Semua channel"
        selected_categories, selected_channels = categories, channels
        date_value = (min_date, max_date)
        if module == "Inventory":
            st.caption("Modul Stok menampilkan ringkasan periode 14 hari. Hanya filter cabang yang berlaku.")
        else:
            with date_col:
                date_value = st.date_input("Periode", value=(min_date, max_date), min_value=min_date,
                                            max_value=max_date, key="filter_dates", help="Pilih tanggal mulai dan tanggal akhir.")
            with category_col:
                selected_category = st.selectbox("Kategori menu", ["Semua kategori"] + categories,
                                                 key="filter_category", help="Pilih satu kategori atau tampilkan semua.")
                selected_categories = categories if selected_category == "Semua kategori" else [selected_category]
            with channel_col:
                selected_channel = st.selectbox("Channel pesanan", ["Semua channel"] + channels,
                                                key="filter_channel", help="Pilih satu channel atau tampilkan semua.")
                selected_channels = channels if selected_channel == "Semua channel" else [selected_channel]
        if isinstance(date_value, tuple):
            start_date, end_date = date_value if len(date_value) == 2 else (date_value[0], date_value[0])
        else:
            start_date = end_date = date_value
        days = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days + 1
        branch_label = "Semua cabang" if branch_value == "Semua cabang" else branch_names[branch_value]
        category_label = selected_category
        channel_label = selected_channel
        if module != "Inventory":
            st.caption(f"Filter aktif: {branch_label} · {category_label} · {channel_label} · {days} hari")
        else:
            st.caption(f"Filter aktif: {branch_label}")
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
                             "occupied_table_minutes": occupied, "occupancy_rate_pct": occupied / denom * 100 if denom else 0})
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
        alerts.append(("🟠", "Limbah Bahan Tinggi", f"{len(high_waste)} bahan memiliki limbah di atas 8% dari nilai pembelian.", "Sesuaikan jumlah pembelian dan persiapan harian."))
    if len(occupancy):
        hourly = occupancy.groupby(["branch_id", "hour"])["occupancy_rate_pct"].mean()
        low_hours = hourly[hourly < 30]
        if len(low_hours):
            alerts.append(("🟡", "Okupansi Rendah", f"Okupansi di bawah 30% pada {len(low_hours)} kombinasi cabang dan jam.", "Uji promo terbatas pada jam sepi."))
        busy_hours = hourly[hourly > 90]
        if len(busy_hours):
            places = [f"{branch} jam {hour:02d}" for branch, hour in busy_hours.index.tolist()]
            alerts.append(("🔴", "Kapasitas Hampir Penuh", f"Okupansi di atas 90% pada {', '.join(places[:5])}.", "Aktifkan reservasi dan siapkan alur antrean."))
    return alerts


def render_insights(alerts):
    if not alerts:
        st.success("Tidak ada peringatan aktif untuk filter yang dipilih.")
        return

    priority = {"Stok Kritis": 0, "Kapasitas Hampir Penuh": 1, "Dapur Melambat": 2,
                "Margin Menu Rendah": 3, "Limbah Bahan Tinggi": 4, "Okupansi Rendah": 5}
    alerts = sorted(alerts, key=lambda item: priority.get(item[1], 99))

    def render_rows(rows):
        for icon, title, message, action in rows:
            severity = "critical" if icon == "🔴" else "caution" if icon == "🟠" else "notice"
            st.markdown(
                f"<div class='alert-card {severity}'><div><b>{icon} {title}</b></div>"
                f"<div>{message}</div><small><b>Saran:</b> {action}</small></div>",
                unsafe_allow_html=True,
            )

    render_rows(alerts[:3])
    if len(alerts) > 3:
        with st.expander(f"Lihat {len(alerts) - 3} peringatan lainnya"):
            render_rows(alerts[3:])


def build_feedback_terms(comments):
    tokens = []
    for comment in comments.dropna().astype(str):
        tokens.extend(w for w in re.findall(r"[a-zA-ZÀ-ÿ]+", comment.lower()) if len(w) > 2 and w not in STOPWORDS)
    counts = Counter(tokens).most_common(12)
    if not counts:
        fig = go.Figure()
        fig.add_annotation(text="Belum ada ulasan", showarrow=False, x=.5, y=.5)
        return chart_layout(fig, 370)
    terms = pd.DataFrame(counts, columns=["kata", "jumlah"]).sort_values("jumlah", ascending=True)
    fig = px.bar(terms, x="jumlah", y="kata", orientation="h", text="jumlah",
                 labels={"kata": "Kata dalam ulasan", "jumlah": "Jumlah penyebutan"},
                 color_discrete_sequence=[BRAND["secondary"]])
    fig.update_traces(textposition="outside", cliponaxis=False, hovertemplate="%{y}: %{x} penyebutan<extra></extra>")
    fig.update_xaxes(rangemode="tozero", title="Jumlah penyebutan")
    return chart_layout(fig, 370, showlegend=False)


def main():
    st.markdown(f"""<style>
    .stApp {{ background: {BRAND['bg']}; }}
    .block-container {{ padding-top: 1.35rem; padding-bottom: 2.5rem; }}
    [data-testid='stSidebar'] {{ background: {BRAND['secondary']}; }}
    [data-testid='stSidebar'] [data-testid='stMarkdownContainer'] p,
    [data-testid='stSidebar'] [data-testid='stMarkdownContainer'] h2,
    [data-testid='stSidebar'] [data-testid='stMarkdownContainer'] h3,
    [data-testid='stSidebar'] label,
    [data-testid='stSidebar'] [data-testid='stCaptionContainer'] * {{ color: #FFFDF9 !important; }}
    h1, h2 {{ color: {BRAND['primary_dark']}; }}
    .alert-card {{ background: {BRAND['surface']}; border: 1px solid #E9DCCB; border-left: 4px solid {BRAND['neutral']}; border-radius: 10px; padding: 10px 12px; margin: 0 0 8px 0; }}
    .alert-card.critical {{ border-left-color: {BRAND['danger']}; }}
    .alert-card.caution {{ border-left-color: {BRAND['warning']}; }}
    .alert-card.notice {{ border-left-color: {BRAND['secondary']}; }}
    .alert-card small {{ color: #56615C; }}
    div[data-testid='stMetric'] {{ background: {BRAND['surface']}; border: 1px solid #E9DCCB; padding: 13px 15px; border-radius: 12px; min-height: 118px; }}
    div[data-testid='stMetricLabel'] p {{ font-size: .9rem; }}
    div[data-testid='stMetricValue'] {{ font-size: 1.35rem; }}
    @media (max-width: 1120px) {{
      [data-testid='stHorizontalBlock'] {{ flex-wrap: wrap; }}
      [data-testid='stHorizontalBlock'] > [data-testid='column'] {{ flex: 1 1 calc(50% - 1rem) !important; min-width: min(100%, 230px); }}
    }}
    </style>""", unsafe_allow_html=True)
    try:
        data = load_data()
    except Exception as exc:
        st.error(str(exc)); st.stop()
    logo = ASSETS / "logo_mangkuk_kita.png"
    modules = ["Overview", "Orders", "Tables", "Kitchen", "Inventory", "Sales / Reports", "Food Cost & Profit"]
    module_labels = {
        "Overview": "Overview · Ikhtisar", "Orders": "Orders · Pesanan",
        "Tables": "Tables · Meja", "Kitchen": "Kitchen · Dapur",
        "Inventory": "Inventory · Stok", "Sales / Reports": "Sales / Reports · Penjualan & Peta",
        "Food Cost & Profit": "Food Cost & Profit · Profitabilitas",
    }
    if "active_module" not in st.session_state or st.session_state["active_module"] not in modules:
        st.session_state["active_module"] = "Overview"
    with st.sidebar:
        if logo.exists():
            st.image(str(logo), width=76)
        st.markdown("### Mangkuk Kita")
        st.caption("SATU MANGKUK, SERIBU CERITA")
        st.divider()
        st.radio("MODUL UTAMA", modules, format_func=lambda value: module_labels[value], key="active_module")
        st.divider()
        st.caption("Proyek Visualisasi Data · DIF61143")
        st.caption("Data sintetis · 3 cabang · 14 hari")

    module = st.session_state["active_module"]
    page_titles = {"Overview": "Ikhtisar", "Orders": "Pesanan", "Tables": "Meja",
                   "Kitchen": "Kitchen · Dapur", "Inventory": "Inventory · Stok", "Sales / Reports": "Sales / Reports · Peta dan Ulasan",
                   "Food Cost & Profit": "Profitabilitas"}
    descriptions = {"Overview": "Ringkasan KPI dan kondisi restoran", "Orders": "Pola penjualan, menu, dan jam sibuk",
                    "Tables": "Okupansi meja dan waktu tunggu", "Kitchen": "Kecepatan dapur dan antrean pesanan",
                    "Inventory": "Stok bahan dan nilai food waste selama 14 hari", "Sales / Reports": "Lokasi cabang, kinerja, dan suara pelanggan",
                    "Food Cost & Profit": "Margin menu dan profit per cabang"}
    st.title(page_titles[module])
    st.caption(descriptions[module])
    filters = get_filters(data, module)
    orders, items = select_data(data, filters)
    occupancy = occupancy_for_selection(data, orders, filters)
    alerts = insights(data, orders, items, occupancy, filters["branches"])
    branches = data["branches"].set_index("branch_id")["nama"].to_dict()
    if module == "Inventory":
        st.caption("Data aktif · ringkasan stok 14 hari · cabang terpilih")
    else:
        st.caption(f"Data aktif · {filters['start'].date()} – {filters['end'].date()} · {orders.order_id.nunique():,} pesanan")
    if module == "Overview":
        revenue = float(items["revenue"].sum()) if len(items) else 0
        food_cost = float(items["food_cost_total"].sum()) if len(items) else 0
        avg_prep = float(orders["durasi_persiapan_menit"].mean()) if len(orders) else 0
        delay_pct = float(orders["durasi_persiapan_menit"].gt(20).mean() * 100) if len(orders) else 0
        occ_avg = float(occupancy["occupied_table_minutes"].sum() / (occupancy["branch_id"].map(data["tables"].groupby("branch_id").size()).sum() * 60) * 100) if len(occupancy) else 0
        waste = data["inventory_metrics"]
        waste = waste[waste.branch_id.isin(filters["branches"])]
        waste_pct = float(waste.waste_value.sum() / waste.purchased_value.sum() * 100) if len(waste) and waste.purchased_value.sum() else 0
        a, b, c, d = st.columns(4)
        with a: kpi_card("Total Pendapatan", rupiah_compact(revenue), "Jumlah nilai pesanan pada filter aktif.")
        with b: kpi_card("Total Pesanan", f"{orders.order_id.nunique():,}")
        with c: kpi_card("Waktu Persiapan", f"{avg_prep:.1f} menit", "Rata-rata dari pesanan masuk sampai selesai disiapkan.")
        with d: kpi_card("Pesanan Terlambat", f"{delay_pct:.1f}%", "Persiapan lebih dari 20 menit.")
        a, b, c = st.columns(3)
        with a: kpi_card("Okupansi Meja", f"{occ_avg:.1f}%", "Bagian dari waktu buka yang meja terisi.")
        with b: kpi_card("Margin Setelah Bahan", f"{((revenue-food_cost)/revenue*100 if revenue else 0):.1f}%", "Pendapatan dikurangi biaya bahan; belum termasuk biaya operasional lain.")
        with c: kpi_card("Limbah Bahan", f"{waste_pct:.1f}%", "Nilai bahan terbuang dibanding nilai pembelian selama 14 hari.")
        left, right = st.columns([1.7, 1], gap="large")
        with left:
            st.subheader("Pendapatan harian per cabang")
            st.caption("Bandingkan perubahan pendapatan dari hari ke hari. Arahkan kursor ke garis untuk melihat nilai.")
            trend = items.groupby(["tanggal", "branch_id"], as_index=False)["revenue"].sum()
            trend["cabang"] = trend.branch_id.map(branches)
            fig = px.line(trend, x="tanggal", y="revenue", color="cabang", markers=True,
                          color_discrete_sequence=[BRAND["primary"], BRAND["secondary"], BRAND["warning"]], labels={"tanggal":"Tanggal", "revenue":"Pendapatan (Rp)", "cabang":"Cabang"})
            st.plotly_chart(chart_layout(fig), use_container_width=True)
        with right:
            st.subheader("Peringatan aktif")
            st.caption("Tiga prioritas teratas ditampilkan; buka daftar untuk melihat sisanya.")
            render_insights(alerts)
        left, right = st.columns([1, 1], gap="large")
        with left:
            st.subheader("Lokasi dan pendapatan cabang")
            st.caption("Ukuran lingkaran mengikuti pendapatan. Arahkan kursor ke titik untuk membandingkan cabang.")
            branch_revenue = items.groupby("branch_id", as_index=False)["revenue"].sum().merge(data["branches"], on="branch_id", how="right")
            branch_revenue["revenue"] = branch_revenue["revenue"].fillna(0)
            st.plotly_chart(create_branch_map(branch_revenue, 390), use_container_width=True)
        with right:
            st.subheader("Okupansi meja menurut jam")
            st.caption("Garis putus-putus menandai kapasitas tinggi (90%). Puncak membantu menentukan kebutuhan staf.")
            occ = occupancy.groupby("hour", as_index=False)["occupancy_rate_pct"].mean()
            fig = px.area(occ, x="hour", y="occupancy_rate_pct", labels={"hour":"Jam", "occupancy_rate_pct":"Meja terisi (%)"}, color_discrete_sequence=[BRAND["secondary"]])
            fig.add_hline(y=90, line_dash="dash", line_color=BRAND["danger"], annotation_text="Ambang tinggi 90%")
            fig.update_yaxes(range=[0, 100], ticksuffix="%")
            st.plotly_chart(chart_layout(fig, 390), use_container_width=True)

    elif module == "Orders":
        left, right = st.columns(2)
        with left:
            st.subheader("Menu terlaris per kategori")
            st.caption("Batang lebih panjang berarti jumlah unit terjual lebih banyak. Warna menunjukkan kategori menu.")
            top = items.groupby(["nama_menu", "kategori"], as_index=False)["qty"].sum().sort_values("qty").tail(18)
            fig = px.bar(top, x="qty", y="nama_menu", color="kategori", orientation="h", labels={"qty":"Unit terjual", "nama_menu":"Menu", "kategori":"Kategori"}, color_discrete_sequence=[BRAND["primary"], BRAND["secondary"], BRAND["warning"], BRAND["success"]])
            st.plotly_chart(chart_layout(fig, 480), use_container_width=True)
        with right:
            st.subheader("Volume pesanan menurut jam dan hari")
            st.caption("Warna lebih pekat menunjukkan lebih banyak pesanan pada jam dan hari tersebut.")
            day_names = {"Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu", "Thursday": "Kamis", "Friday": "Jumat", "Saturday": "Sabtu", "Sunday": "Minggu"}
            heat = orders.assign(hari=orders.waktu_masuk.dt.day_name().map(day_names)).pivot_table(index="hari", columns="jam", values="order_id", aggfunc="count", fill_value=0)
            day_order = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
            heat = heat.reindex([d for d in day_order if d in heat.index])
            fig = px.imshow(heat, aspect="auto", color_continuous_scale=[[0, "#F6EBDD"], [.5, BRAND["warning"]], [1, BRAND["primary"]]], labels=dict(x="Jam", y="Hari", color="Jumlah order"))
            st.plotly_chart(chart_layout(fig, 480), use_container_width=True)
        st.subheader("Detail order")
        order_view = orders.sort_values("waktu_masuk", ascending=False)[["order_id", "tanggal", "branch_id", "channel", "durasi_persiapan_menit", "total_bayar"]].rename(columns={
            "order_id": "ID pesanan", "tanggal": "Tanggal", "branch_id": "ID cabang",
            "channel": "Channel", "durasi_persiapan_menit": "Persiapan (menit)", "total_bayar": "Total bayar (Rp)"
        })
        order_view["Total bayar (Rp)"] = order_view["Total bayar (Rp)"].map(rupiah)
        order_view["Cabang"] = order_view["ID cabang"].map(branches)
        order_view = order_view.drop(columns="ID cabang")
        st.dataframe(order_view, use_container_width=True, hide_index=True)

    elif module == "Tables":
        st.subheader("Okupansi meja menurut jam")
        st.caption("Garis membandingkan rata-rata meja terisi pada setiap cabang; garis putus-putus menandai 90% kapasitas.")
        occ = occupancy.groupby(["hour", "branch_id"], as_index=False)["occupancy_rate_pct"].mean()
        occ["cabang"] = occ.branch_id.map(branches)
        fig = px.line(occ, x="hour", y="occupancy_rate_pct", color="cabang", markers=True, labels={"hour":"Jam", "occupancy_rate_pct":"Meja terisi (%)", "cabang":"Cabang"}, color_discrete_sequence=[BRAND["primary"], BRAND["secondary"], BRAND["warning"]])
        fig.add_hline(y=90, line_dash="dash", line_color=BRAND["danger"], annotation_text="Kapasitas tinggi 90%")
        fig.update_yaxes(range=[0, 100], ticksuffix="%")
        st.plotly_chart(chart_layout(fig, 430), use_container_width=True)
        waits = orders[orders.channel.eq("Dine-in")]
        st.subheader("Waktu tunggu meja")
        if len(waits):
            st.caption("Rata-rata menit menunggu meja untuk pesanan dine-in.")
            wait = waits.groupby("jam", as_index=False)["waktu_tunggu_meja_menit"].mean()
            fig = px.bar(wait, x="jam", y="waktu_tunggu_meja_menit", labels={"jam":"Jam kedatangan", "waktu_tunggu_meja_menit":"Rata-rata tunggu (menit)"}, color_discrete_sequence=[BRAND["secondary"]])
            st.plotly_chart(chart_layout(fig, 330), use_container_width=True)

    elif module == "Kitchen":
        left, right = st.columns(2)
        with left:
            st.subheader("Sebaran waktu persiapan per station")
            st.caption("Garis di tengah kotak = median; kotak merangkum setengah tengah pesanan. Makin rendah, makin cepat.")
            prep = items.sample(min(len(items), 8000), random_state=61143) if len(items) else items
            fig = px.box(prep, x="station", y="waktu_persiapan_menit", color="station", points=False, labels={"station":"Station", "waktu_persiapan_menit":"Menit"}, color_discrete_sequence=[BRAND["primary"], BRAND["secondary"], BRAND["warning"], BRAND["success"]])
            st.plotly_chart(chart_layout(fig), use_container_width=True)
        with right:
            st.subheader("Persentase pesanan terlambat per jam")
            st.caption("Order dianggap terlambat bila persiapan lebih dari 20 menit. Garis menandai batas peringatan 15%.")
            hourly = orders.groupby("jam", as_index=False).agg(delayed=("durasi_persiapan_menit", lambda s: s.gt(20).mean() * 100))
            fig = px.bar(hourly, x="jam", y="delayed", labels={"jam":"Jam", "delayed":"Order terlambat (%)"}, color="delayed", color_continuous_scale=[BRAND["secondary"], BRAND["warning"], BRAND["danger"]])
            fig.add_hline(y=15, line_dash="dash", annotation_text="Alert 15%")
            fig.update_yaxes(ticksuffix="%")
            st.plotly_chart(chart_layout(fig), use_container_width=True)
        st.subheader("Pesanan aktif dan waktu persiapan")
        st.caption("Setiap titik adalah satu pesanan. Sebaran ke kanan-atas dapat menunjukkan dapur yang kewalahan.")
        scatter = orders.sample(min(len(orders), 3500), random_state=61143) if len(orders) else orders
        scatter["cabang"] = scatter.branch_id.map(branches)
        fig = px.scatter(scatter, x="pesanan_aktif", y="durasi_persiapan_menit", color="cabang", opacity=.5, labels={"pesanan_aktif":"Pesanan aktif saat masuk", "durasi_persiapan_menit":"Waktu persiapan (menit)", "cabang":"Cabang"}, color_discrete_sequence=[BRAND["primary"], BRAND["secondary"], BRAND["warning"]])
        if len(scatter) > 1:
            xline = np.linspace(scatter["pesanan_aktif"].min(), scatter["pesanan_aktif"].max(), 50)
            slope, intercept = np.polyfit(scatter["pesanan_aktif"], scatter["durasi_persiapan_menit"], 1)
            fig.add_trace(go.Scatter(x=xline, y=slope*xline+intercept, mode="lines", name="Tren", line=dict(color=BRAND["danger"], dash="dash")))
        st.plotly_chart(chart_layout(fig), use_container_width=True)
        st.subheader("Alur pesanan dari masuk hingga pembayaran")
        st.caption("Lebar alur menunjukkan jumlah pesanan. Percabangan menunjukkan channel yang digunakan.")
        channel_counts = orders.channel.value_counts().to_dict()
        fig = go.Figure(go.Sankey(node=dict(label=["Order masuk", "Dapur", "Siap disajikan", "Dine-in", "Takeaway", "Delivery", "Pembayaran"], color=[BRAND["primary"], BRAND["secondary"], BRAND["success"], BRAND["warning"], BRAND["warning"], BRAND["warning"], BRAND["primary_dark"]], pad=18, thickness=20),
            link=dict(source=[0, 1, 2, 2, 2, 3, 4, 5], target=[1, 2, 3, 4, 5, 6, 6, 6], value=[len(orders), len(orders), channel_counts.get("Dine-in", 0), channel_counts.get("Takeaway", 0), channel_counts.get("Delivery", 0), channel_counts.get("Dine-in", 0), channel_counts.get("Takeaway", 0), channel_counts.get("Delivery", 0)], color="rgba(47,93,80,.25)")))
        st.plotly_chart(chart_layout(fig, 390), use_container_width=True)

    elif module == "Inventory":
        inv = data["inventory_metrics"].copy()
        inv = inv[inv.branch_id.isin(filters["branches"])]
        inv["cabang"] = inv.branch_id.map(branches)
        left, right = st.columns(2)
        with left:
            st.subheader("Stok tersedia dibanding batas minimum")
            st.caption("Setiap pasangan batang membandingkan stok sekarang dengan batas minimum per bahan.")
            stock = inv.sort_values("stok_saat_ini").tail(25)
            long = stock.melt(id_vars=["nama_bahan", "cabang"], value_vars=["stok_saat_ini", "stok_minimum"], var_name="jenis", value_name="jumlah")
            long["jenis"] = long["jenis"].map({"stok_saat_ini": "Stok tersedia", "stok_minimum": "Batas minimum"})
            fig = px.bar(long, x="nama_bahan", y="jumlah", color="jenis", barmode="group", facet_col="cabang", facet_col_wrap=1, labels={"nama_bahan":"Bahan", "jumlah":"Stok (unit bahan)", "jenis":"Jenis stok", "cabang":"Cabang"}, color_discrete_sequence=[BRAND["primary"], BRAND["secondary"]])
            st.plotly_chart(chart_layout(fig, 500), use_container_width=True)
        with right:
            st.subheader("Nilai limbah bahan tertinggi")
            st.caption("Menunjukkan nilai rupiah bahan terbuang selama periode data.")
            inv["waste_value"] = inv["total_terbuang"] * inv["harga_satuan"]
            waste = inv.sort_values("waste_value").tail(15)
            waste["cabang"] = waste.branch_id.map(branches)
            fig = px.bar(waste, x="waste_value", y="nama_bahan", color="kategori", orientation="h", facet_col="cabang", facet_col_wrap=1, labels={"waste_value":"Nilai limbah (Rp)", "nama_bahan":"Bahan", "kategori":"Kategori bahan", "cabang":"Cabang"}, color_discrete_sequence=[BRAND["primary"], BRAND["secondary"]])
            st.plotly_chart(chart_layout(fig, 500), use_container_width=True)
        st.subheader("Daftar stok dan limbah")
        inventory_view = inv[["cabang", "nama_bahan", "kategori", "stok_saat_ini", "stok_minimum", "total_dibeli", "total_terbuang", "stockout_events_14d", "waste_rate_pct"]].sort_values(["cabang", "stok_saat_ini"]).rename(columns={
            "cabang": "Cabang", "nama_bahan": "Bahan", "kategori": "Kategori", "stok_saat_ini": "Stok tersedia",
            "stok_minimum": "Stok minimum", "total_dibeli": "Jumlah dibeli", "total_terbuang": "Jumlah terbuang",
            "stockout_events_14d": "Kejadian kehabisan stok", "waste_rate_pct": "Limbah (%)"
        })
        inventory_view["Limbah (%)"] = inventory_view["Limbah (%)"].map(lambda value: f"{value:.1f}%")
        st.dataframe(inventory_view, use_container_width=True, hide_index=True)

    elif module == "Sales / Reports":
        st.subheader("Peta lokasi dan pendapatan cabang")
        st.caption("Lingkaran lebih besar berarti pendapatan lebih tinggi; arahkan kursor ke titik untuk melihat nilainya.")
        branch_rev = items.groupby("branch_id", as_index=False)["revenue"].sum().merge(data["branches"], on="branch_id", how="right")
        branch_rev["revenue"] = branch_rev["revenue"].fillna(0)
        st.plotly_chart(create_branch_map(branch_rev, 500), use_container_width=True)
        st.caption("Koordinat memakai titik kota dari rancangan, bukan alamat gerai terverifikasi.")
        st.subheader("Topik yang sering disebut pelanggan")
        st.caption("Batang menunjukkan berapa kali kata muncul di komentar yang lolos filter; ini membantu melihat tema ulasan, bukan sentimen otomatis.")
        comments = data["feedback_joined"]
        comments = comments[comments.order_id.isin(orders.order_id)]
        st.plotly_chart(build_feedback_terms(comments["komentar"]), use_container_width=True)
        if len(comments):
            st.caption(f"{len(comments)} ulasan pada filter saat ini; rating rata-rata {comments.rating.mean():.2f}/5.")
        st.subheader("Ringkasan kinerja cabang")
        summary = items.groupby("branch_id", as_index=False).agg(revenue=("revenue", "sum"), food_cost=("food_cost_total", "sum"), units=("qty", "sum"))
        summary["cabang"] = summary.branch_id.map(branches)
        summary["margin_pct"] = (summary.revenue - summary.food_cost) / summary.revenue * 100
        summary_view = summary[["cabang", "revenue", "units", "margin_pct"]].sort_values("revenue", ascending=False).rename(
            columns={"cabang": "Cabang", "revenue": "Pendapatan", "units": "Unit terjual", "margin_pct": "Margin (%)"})
        summary_view["Pendapatan"] = summary_view["Pendapatan"].map(rupiah)
        summary_view["Margin (%)"] = summary_view["Margin (%)"].map(lambda value: f"{value:.1f}%")
        st.dataframe(summary_view, use_container_width=True, hide_index=True)

    elif module == "Food Cost & Profit":
        menu = items.groupby(["menu_id", "nama_menu", "kategori", "harga_satuan", "food_cost"], as_index=False).agg(units=("qty", "sum"), revenue=("revenue", "sum"), food_cost_total=("food_cost_total", "sum"), profit=("profit", "sum"))
        menu["margin_pct"] = (menu.revenue - menu.food_cost_total) / menu.revenue.replace(0, np.nan) * 100
        left, right = st.columns(2)
        with left:
            st.subheader("Harga jual dan margin menu")
            st.caption("Setiap titik = satu menu. Garis 25% menandai margin bahan rendah; titik besar menunjukkan menu lebih laris.")
            fig = px.scatter(menu, x="harga_satuan", y="margin_pct", size="units", color="kategori", hover_name="nama_menu", labels={"harga_satuan":"Harga jual (Rp)", "margin_pct":"Margin menu (%)", "units":"Unit terjual", "kategori":"Kategori"}, color_discrete_sequence=[BRAND["primary"], BRAND["secondary"], BRAND["warning"], BRAND["success"]])
            fig.add_hline(y=25, line_dash="dash", line_color=BRAND["danger"], annotation_text="Ambang margin 25%")
            st.plotly_chart(chart_layout(fig), use_container_width=True)
        with right:
            st.subheader("Profit bahan per cabang dan kategori")
            st.caption("Bandingkan sisa pendapatan setelah biaya bahan; biaya lain seperti gaji dan sewa belum dikurangi.")
            profit = items.groupby(["branch_id", "kategori"], as_index=False)["profit"].sum()
            profit["cabang"] = profit.branch_id.map(branches)
            fig = px.bar(profit, x="cabang", y="profit", color="kategori", barmode="group", labels={"cabang":"Cabang", "profit":"Profit bahan (Rp)", "kategori":"Kategori"}, color_discrete_sequence=[BRAND["primary"], BRAND["secondary"], BRAND["warning"], BRAND["success"]])
            st.plotly_chart(chart_layout(fig), use_container_width=True)
        st.subheader("Rincian profitabilitas menu")
        menu_view = menu[["nama_menu", "kategori", "units", "revenue", "food_cost_total", "profit", "margin_pct"]].sort_values("profit", ascending=False).rename(columns={
            "nama_menu": "Menu", "kategori": "Kategori", "units": "Unit terjual", "revenue": "Pendapatan (Rp)",
            "food_cost_total": "Biaya bahan (Rp)", "profit": "Sisa setelah bahan (Rp)", "margin_pct": "Margin (%)"
        })
        for column in ["Pendapatan (Rp)", "Biaya bahan (Rp)", "Sisa setelah bahan (Rp)"]:
            menu_view[column] = menu_view[column].map(rupiah)
        menu_view["Margin (%)"] = menu_view["Margin (%)"].map(lambda value: f"{value:.1f}%")
        st.dataframe(menu_view, use_container_width=True, hide_index=True)



if __name__ == "__main__":
    main()
