# Mangkuk Kita

Proyek akhir Visualisasi Data (DIF61143): fondasi data sintetis dan persiapan dataset untuk dashboard manajemen restoran.

## Isi proyek

- Generator deterministik ber-seed tetap untuk tujuh tabel relasional. Volume default 9.000 order dipilih agar kapasitas 68 meja dan pola okupansi restoran sibuk lebih masuk akal daripada batas minimum template.
- Dataset mentah dengan pola operasional tiga cabang, puncak jam makan, menu bermargin tipis, keterlambatan dapur, limbah bahan segar, stok kritis, dan ulasan pelanggan.
- Masalah kualitas data yang disengaja agar tahap cleaning dan bukti sebelum/sesudah dapat didokumentasikan.
- Skrip pembersihan, pemeriksaan relasi, ringkasan profil, dan log audit.

Semua data adalah **sintetis** untuk tugas kuliah. Data ini bukan transaksi bisnis nyata. Koordinat saat ini menunjukkan titik tengah kota dari rancangan awal, bukan lokasi gerai yang telah diverifikasi.

## Struktur folder

```text
MANGKUK_KITA/
  data/
    raw/                 # CSV mentah
    clean/               # CSV bersih
  reports/
    cleaning_log.csv     # jumlah sebelum/sesudah dan tindakan cleaning
    data_profile.json    # periode, jumlah baris, nilai kosong, indikator data
    relationship_checks.csv
    data_overview.txt    # info ringkas, describe, dan distribusi kategori
    describe_numeric.csv
    category_distributions.csv
    eda_order_volume_heatmap.png
    menu_metrics.csv
    order_metrics.csv
    occupancy_hourly.csv
    inventory_metrics.csv
    kpi_snapshot.json
  src/
    generate_data.py     # generator tujuh tabel
    clean_data.py        # cleaning, validasi relasi, laporan kualitas
    explore_data.py      # eksplorasi ringkas untuk Bab IV
    metrics.py           # metrik turunan dan KPI awal
  app/
    main.py              # dashboard Streamlit dengan tujuh modul
  requirements.txt
```

## Menjalankan di VS Code

Buka folder proyek ini di VS Code, lalu jalankan di terminal PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python src\generate_data.py
python src\clean_data.py
python src\explore_data.py
python src\metrics.py
streamlit run app\main.py
```

Generator default membuat 9.000 order unik selama 14 hari mulai Senin, 2 November 2026, dengan seed `61143`. Untuk mengubah parameter:

```powershell
python src\generate_data.py --seed 61143 --start-date 2026-11-02 --orders 9000
```

Tanggal mulai harus hari Senin dan jumlah order minimal 500. Seed dan tanggal yang sama akan menghasilkan data yang sama.

## Navigasi dan visualisasi dashboard

Navigasi vertikal di sisi kiri memuat **7 modul** yang memenuhi pilihan pada rancangan: **Overview**, **Orders**, **Tables**, **Kitchen**, **Inventory**, **Sales / Reports**, dan **Food Cost & Profit**. Nama modul mengikuti istilah pada ketentuan proyek dengan padanan Indonesia agar mudah dipahami.

Filter global berada di bagian atas konten. Pilih periode, cabang, kategori menu, dan channel; semua angka dan grafik langsung mengikuti pilihan tersebut. Opsi **Semua** menampilkan gabungan data, sementara **Reset filter** mengembalikan cakupan awal. Pada modul **Inventory**, hanya filter cabang yang berlaku karena data stok berupa ringkasan tetap untuk 14 hari.

Halaman Overview menggabungkan kartu KPI, grafik pendapatan per cabang, peringatan operasional, peta pendapatan cabang, dan okupansi meja. Setiap grafik diberi keterangan singkat tentang cara membacanya. Modul Sales / Reports menyajikan peta lebih besar, frekuensi kata pada ulasan, dan ringkasan kinerja cabang. Koordinat peta menggunakan titik kota dari rancangan, bukan alamat gerai terverifikasi.

Jika virtual environment belum disiapkan:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Skema CSV

| Tabel | Isi dan relasi utama |
|---|---|
| `branches.csv` | 3 cabang, kota, koordinat, jumlah meja; PK `branch_id` |
| `tables.csv` | 68 meja dan kapasitas; PK `table_id`, FK `branch_id` |
| `menu_cost.csv` | 20 menu, kategori, station, harga jual dan food cost; PK `menu_id` |
| `orders.csv` | 9.000 order unik, waktu, channel, meja, cabang, pesanan aktif dan total bayar; PK `order_id` |
| `order_items.csv` | sekitar 30.000 baris menu per order, qty, harga, station dan waktu persiapan; key (`order_id`, `item_line`) |
| `inventory.csv` | 15 bahan per cabang (45 baris), stok, pembelian, pemakaian, waste dan stockout; PK `item_id` |
| `feedback.csv` | sekitar 400 rating/komentar yang terhubung ke order; PK `feedback_id` |

Beberapa kolom tambahan mendukung pertanyaan bisnis pada acuan: `pesanan_aktif`, `waktu_duduk`, dan `waktu_tunggu_meja_menit` pada orders; `item_line` serta biaya bahan per item/cabang (`biaya_bahan_satuan`) pada order_items; serta `stok_awal`, `total_dipakai`, dan `stockout_events_14d` pada inventory. Meja dine-in dijadwalkan agar satu meja tidak digunakan bersamaan. Durasi persiapan order didefinisikan sebagai `waktu_selesai - waktu_masuk`; durasi item tersedia terpisah pada order_items. Waktu tunggu sintetis dibatasi 20 menit dan okupansi efektif per jam dibatasi 95%; margin cabang memakai biaya bahan per item yang berbeda menurut cabang.

## Perlakuan cleaning

- Duplikat order dihapus dengan `order_id`; duplikat item dengan (`order_id`, `item_line`).
- Channel diseragamkan menjadi `Dine-in`, `Takeaway`, atau `Delivery`.
- Timestamp campuran diparse ke datetime.
- Harga berbentuk teks seperti `Rp25.000` dibersihkan menjadi angka.
- Waktu persiapan item yang negatif atau di atas 120 menit diganti median station yang valid.
- `jumlah_tamu` kosong diimputasi memakai median per channel.
- Rating kosong tetap kosong agar nilai subjektif tidak ditebak.
- Foreign key diperiksa dan jika tidak valid proses berhenti dengan pesan error.

> **Catatan laporan:** angka masalah di draft adalah target pola untuk dibangun dalam data sintetis, bukan hasil observasi. Ambil angka akhir dari CSV bersih dan `reports/data_profile.json`.

### Catatan konsistensi target

Template dosen menetapkan minimum 500 transaksi, sedangkan rancangan Mangkuk Kita menyarankan volume sekitar 1.000. Dataset default memakai 9.000 order sebagai peningkatan agar pola sibuk, pembagian channel, dan kapasitas 68 meja dapat dianalisis lebih kuat. Metrik okupansi tetap dihitung dari menit meja terisi yang dijadwalkan, sehingga nilai aktual dilaporkan apa adanya dan tidak dipaksa mencapai target tertentu.
