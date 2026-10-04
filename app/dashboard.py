# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
import json
import os
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models import Order as OrderModel, OrderStatus, Stock, MenuItem

BASE_DIR = Path(__file__).resolve().parent.parent
MASTER_DATA_PATH = Path(os.getenv("MASTER_DATA_PATH", BASE_DIR / "data" / "business_master_data.json"))


def load_master_data() -> dict:
    if MASTER_DATA_PATH.exists():
        try:
            with open(MASTER_DATA_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "business_name": "Nama Usaha",
        "location": "Lokasi Usaha",
        "fixed_costs": {
            "total_monthly_fixed_cost": 28000000,
            "daily_fixed_cost_allocation": 933333.33,
            "monthly_payroll": 26500000,
            "monthly_electricity_and_water": 1500000
        },
        "historical_hpp_benchmark": {
            "daily_summary": [],
            "rata_rata_pemakaian_harian": 1176687.11,
            "total_pemakaian_bahan": 32947239.00
        },
        "purchasing_summary": {
            "total_purchases": 33152297.0,
            "avg_daily_purchase": 1184010.61,
            "breakdown": {
                "dapur_pasar": {"total": 26038717.0, "percentage": 78.5},
                "minuman": {"total": 3952380.0, "percentage": 11.9},
                "operasional_perlengkapan": {"total": 3161200.0, "percentage": 9.5}
            },
            "top_spending_items": [],
            "daily_purchases": []
        }
    }

def _menu_recommendation(classification: str, cm: float) -> str:
    if classification.startswith("Star"):
        return "Pertahankan kualitas & stok bahan — menu andalan profit."
    if classification.startswith("Puzzle"):
        return "Dorong penjualan lewat paket bundling agar margin optimal."
    return "Evaluasi resep atau harga jual."

def get_top_menu_analytics() -> list[dict]:
    """Analisis menu terlaris paket hemat — 6 bulan (dummy demo).

    Distribusi qty proporsional terhadap omzet bulanan (growth 3-10%),
    margin per menu sesuai food cost masing-masing item.
    """
    # index volume kumulatif (omzet bulanan / omzet April)
    growth = [1.0, 1.065, 1.099, 1.202, 1.260, 1.364]
    menus = [
        # (nama, harga, food_cost_pct, porsi volume, klasifikasi)
        ("Nasi Ayam Penyet", 15000, 0.42, 0.30, "Star (Bintang Profit)"),
        ("Nasi Bebek",       20000, 0.45, 0.26, "Star (Bintang Profit)"),
        ("Nasi Jeroan",      13000, 0.40, 0.19, "Star (Bintang Profit)"),
        ("Nasi Telor Dadar", 12000, 0.38, 0.16, "Star (Bintang Profit)"),
        ("Es Teh",            4000, 0.25, 0.055, "Puzzle (Potensi Tertidur)"),
        ("Es Jeruk",          6000, 0.30, 0.035, "Puzzle (Potensi Tertidur)"),
    ]
    total_index = sum(growth)
    results = []
    for name, price, fc, share, cls in menus:
        qty_total = 0
        revenue_total = 0.0
        cogs_total = 0.0
        for g in growth:
            monthly_rev = 24_000_000 * g * share  # omzet menu bulanan
            qty = int(monthly_rev / price)
            qty_total += qty
            revenue_total += qty * price
            cogs_total += qty * price * fc
        cm = (revenue_total - cogs_total) / revenue_total * 100
        results.append({
            "name": name,
            "sold_qty": qty_total,
            "revenue": round(revenue_total),
            "cogs": round(cogs_total),
            "unit_margin_percent": round(cm, 1),
            "classification": cls,
            "recommendation": _menu_recommendation(cls, cm),
        })
    results.sort(key=lambda r: r["sold_qty"], reverse=True)
    return results


def get_menu_catalog(db: Session) -> list:
    """Return the live active menu catalog for the dashboard price view."""
    items = (
        db.query(MenuItem)
        .filter(MenuItem.is_active == True)
        .order_by(MenuItem.id.asc())
        .all()
    )
    return [
        {
            "id": int(item.id),
            "name": item.name,
            "description": item.description or "",
            "price": float(item.price),
            "is_active": bool(getattr(item, "is_active", True)),
        }
        for item in items
    ]


def get_dashboard_summary_data(db: Session) -> dict:
    master = load_master_data()
    
    # 1. Live Orders Metrics from SQLite DB
    live_sales_scalar = db.query(func.sum(OrderModel.total)).filter(OrderModel.state == OrderStatus.COMPLETED).scalar()
    live_total_sales = round(float(live_sales_scalar) if live_sales_scalar else 0.0, 2)
    live_completed_count = db.query(OrderModel).filter(OrderModel.state == OrderStatus.COMPLETED).count()
    
    # 2. Historical 28-day calculations from Agustus.xlsx data
    hist = master.get("historical_hpp_benchmark", {})
    daily_rows = hist.get("daily_summary", [])
    total_hpp_28d = hist.get("total_pemakaian_bahan", 32947239.0)
    avg_daily_hpp = hist.get("rata_rata_pemakaian_harian", 1176687.11)
    
    daily_fixed_cost = master.get("fixed_costs", {}).get("daily_fixed_cost_allocation", 933333.33)
    
    daily_table_data = []
    total_omzet_28d = 0
    total_net_profit_28d = 0
    
    for row in daily_rows:
        tgl = row.get("tanggal", "")
        hpp = float(row.get("pemakaian_bahan_hpp", 0))
        # Omzet harian eksplisit dari master data; fallback estimasi dari HPP (ratio 0.42)
        est_omzet = float(row.get("omzet", 0)) or (round(hpp / 0.42, 0) if hpp > 0 else 0)
        laba_kotor = est_omzet - hpp
        laba_bersih = laba_kotor - daily_fixed_cost
        margin_pct = round((laba_bersih / est_omzet) * 100, 1) if est_omzet > 0 else 0
        
        total_omzet_28d += est_omzet
        total_net_profit_28d += laba_bersih
        
        daily_table_data.append({
            "tanggal": tgl,
            "stok_tersedia": row.get("total_stok_tersedia", 0),
            "sisa_stok": row.get("sisa_stok_akhir", 0),
            "pemakaian_hpp": hpp,
            "estimasi_omzet": est_omzet,
            "laba_kotor": laba_kotor,
            "beban_tetap": round(daily_fixed_cost, 0),
            "laba_bersih": laba_bersih,
            "margin_persen": margin_pct
        })
        
    avg_daily_omzet = round(total_omzet_28d / len(daily_table_data), 0) if daily_table_data else 2885662
    avg_daily_profit = round(total_net_profit_28d / len(daily_table_data), 0) if daily_table_data else 775641
    avg_margin_pct = round((total_net_profit_28d / total_omzet_28d) * 100, 1) if total_omzet_28d > 0 else 26.9

    # Day of Week Traffic & Revenue Analytics
    from datetime import datetime as dt_mod
    from collections import defaultdict as ddict
    
    days_map = {0: "Senin", 1: "Selasa", 2: "Rabu", 3: "Kamis", 4: "Jumat", 5: "Sabtu", 6: "Minggu"}
    daily_purchases_map = {d["tanggal"]: d for d in master.get("purchasing_summary", {}).get("daily_purchases", [])}
    
    day_stats = ddict(lambda: {
        "count": 0,
        "total_omzet": 0.0,
        "total_hpp": 0.0,
        "total_belanja": 0.0,
        "total_laba_bersih": 0.0,
        "dates": []
    })
    
    for row in daily_table_data:
        tgl = row["tanggal"]
        omzet = row["estimasi_omzet"]
        hpp = row["pemakaian_hpp"]
        laba = row["laba_bersih"]
        try:
            dt_obj = dt_mod.strptime(tgl, "%d.%m.%y")
        except Exception:
            dt_obj = dt_mod.strptime(tgl, "%d.%m.%Y")
        d_name = days_map[dt_obj.weekday()]
        day_stats[d_name]["count"] += 1
        day_stats[d_name]["total_omzet"] += omzet
        day_stats[d_name]["total_hpp"] += hpp
        day_stats[d_name]["total_laba_bersih"] += laba
        day_stats[d_name]["dates"].append(tgl)
        if tgl in daily_purchases_map:
            day_stats[d_name]["total_belanja"] += daily_purchases_map[tgl]["total_belanja"]
            
    ordered_days = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    dow_records = []
    for d in ordered_days:
        st = day_stats[d]
        cnt = st["count"]
        avg_omz = round(st["total_omzet"] / cnt, 0) if cnt else 0
        avg_laba = round(st["total_laba_bersih"] / cnt, 0) if cnt else 0
        avg_hpp = round(st["total_hpp"] / cnt, 0) if cnt else 0
        avg_bel = round(st["total_belanja"] / cnt, 0) if cnt else 0
        margin_pct = round((avg_laba / avg_omz) * 100, 1) if avg_omz else 0
        dow_records.append({
            "day": d,
            "count": cnt,
            "total_omzet": st["total_omzet"],
            "avg_omzet": avg_omz,
            "avg_hpp": avg_hpp,
            "avg_belanja": avg_bel,
            "avg_laba": avg_laba,
            "margin_percent": margin_pct,
            "status": "Puncak Weekend" if d in ["Sabtu", "Minggu"] else ("Awal Weekend" if d == "Jumat" else ("Low-Tide / Sepi" if d == "Kamis" else "Stabil"))
        })
        
    sorted_by_omzet = sorted(dow_records, key=lambda x: x["avg_omzet"], reverse=True)
    peak_day = sorted_by_omzet[0]
    slow_day = sorted_by_omzet[-1]
    weekend_avg = sum(r["avg_omzet"] for r in dow_records if r["day"] in ["Jumat", "Sabtu", "Minggu"]) / 3
    weekday_avg = sum(r["avg_omzet"] for r in dow_records if r["day"] in ["Senin", "Selasa", "Rabu", "Kamis"]) / 4
    weekend_lift_pct = round(((weekend_avg - weekday_avg) / weekday_avg) * 100, 1) if weekday_avg else 0

    dow_analytics = {
        "records": dow_records,
        "peak_day": {
            "day": peak_day["day"],
            "avg_omzet": peak_day["avg_omzet"],
            "avg_laba": peak_day["avg_laba"],
            "badge": "Hari Paling Ramai (Peak Day)"
        },
        "slowest_day": {
            "day": slow_day["day"],
            "avg_omzet": slow_day["avg_omzet"],
            "avg_laba": slow_day["avg_laba"],
            "badge": "Hari Paling Santai (Low-Tide)"
        },
        "weekend_avg_omzet": round(weekend_avg, 0),
        "weekday_avg_omzet": round(weekday_avg, 0),
        "weekend_lift_percent": weekend_lift_pct,
        "recommendations": [
            {
                "title": "Optimasi Shift & Libur Karyawan (Roster Off-Day)",
                "category": "Operasional & SDM",
                "action": "Jadwalkan libur bergilir (off-day) untuk staf operasional di hari Kamis atau Senin saat volume pelanggan terendah (rata-rata Rp 2,34 - 2,58 juta). Wajibkan formasi lengkap (All-Hands On Deck) pada Jumat, Sabtu, dan Minggu saat omzet melonjak tembus Rp 3,1 - 3,46 juta per hari."
            },
            {
                "title": "Jadwal Belanja Pasar Strategis (Procurement Timing)",
                "category": "Belanja & Dapur",
                "action": "Lakukan belanja skala besar (beras, bebek karkas, ayam penyet, cabai, telur) pada Kamis sore atau Jumat pagi. Data membuktikan belanja hari Sabtu melonjak hingga Rp 1,54 juta. Kurangi stok bahan cepat basi pada hari Rabu malam agar tidak menumpuk di hari Kamis."
            },
            {
                "title": "Promo Dongkrak Hari Sepi ('Kamis Manis' Mid-Week Booster)",
                "category": "Pemasaran & Medsos",
                "action": "Hari Kamis merupakan hari paling sepi dengan omzet terendah (Rp 2,34 juta). Luncurkan promo khusus 'Kamis Manis' (contoh: Paket Hemat Nasi Ayam Penyet + Es Teh Jumbo Rp 18.000 khusus dine-in jam 11:00-14:00). Kampanye video TikTok/Reels ditayangkan setiap Rabu sore untuk mengalirkan traffic ke hari Kamis."
            },
            {
                "title": "Maksimalkan Perputaran Meja Akhir Pekan (Weekend Table Turnover)",
                "category": "Layanan & Kasir",
                "action": "Pada hari Minggu (omzet puncak Rp 3,46 juta dan laba Rp 1,29 juta), prioritaskan paket keluarga, porsi rombongan, dan menu margin tinggi (Bebek Bumbu Hitam & Es Teh Jumbo). Percepat durasi saji dapur di bawah 12 menit untuk meningkatkan rotasi meja tamu."
            }
        ]
    }

    # 4. Stock Inventory Catalog & Valuation (katalog opsional di paket hemat)
    cat = master.get("catalog_sample") or {}
    dapur_catalog = cat.get("dapur", []) if isinstance(cat, dict) else []
    minuman_catalog = cat.get("minuman", []) if isinstance(cat, dict) else []
    
    inventory_items = []
    total_inventory_value = 0
    
    for it in dapur_catalog:
        val = it.get("stock_akhir", 0) * it.get("harga_satuan", 0)
        total_inventory_value += val
        inventory_items.append({
            "no": it.get("no"),
            "name": it.get("item"),
            "category": "Bahan Dapur",
            "satuan": it.get("satuan", "Kg"),
            "stock_awal": it.get("stock_awal", 0),
            "masuk": it.get("masuk", 0),
            "total_tersedia": it.get("total_tersedia", 0),
            "harga_satuan": it.get("harga_satuan", 0),
            "stock_akhir": it.get("stock_akhir", 0),
            "total_value": val,
            "status": "Aman" if it.get("stock_akhir", 0) > 1 else ("Kritis" if it.get("stock_akhir", 0) == 0 else "Perlu Restock")
        })
        
    for it in minuman_catalog:
        val = it.get("stock_akhir", 0) * it.get("harga_satuan", 0)
        total_inventory_value += val
        inventory_items.append({
            "no": it.get("no"),
            "name": it.get("item"),
            "category": "Minuman & Ops",
            "satuan": it.get("satuan", "pcs"),
            "stock_awal": it.get("stock_awal", 0),
            "masuk": it.get("masuk", 0),
            "total_tersedia": it.get("total_tersedia", 0),
            "harga_satuan": it.get("harga_satuan", 0),
            "stock_akhir": it.get("stock_akhir", 0),
            "total_value": val,
            "status": "Aman" if it.get("stock_akhir", 0) > 5 else ("Kritis" if it.get("stock_akhir", 0) == 0 else "Perlu Restock")
        })

    # 5. Top Menu Analytics
    top_menus = get_top_menu_analytics()

    # 6. Purchasing & Expenses Summary
    purchasing = master.get("purchasing_summary", {})
    top_spend = purchasing.get("top_spending_items", [])

    # 7. Income Statement (Formal Accounting) — basis bulan terakhir (September)
    fixed = master.get("fixed_costs", {})
    last_month = (master.get("monthly_growth_history") or [{}])[-1]
    is_revenue = float(last_month.get("omzet", total_omzet_28d))
    is_cogs = float(last_month.get("hpp", total_hpp_28d))
    is_gross = is_revenue - is_cogs
    is_net = float(last_month.get("laba_bersih", is_gross - fixed.get("total_monthly_fixed_cost", 0)))
    is_margin = round(is_net / is_revenue * 100, 1) if is_revenue else 0
    income_statement = {
        "revenue": {
            "gross_food_sales": round(is_revenue * 0.85, 0),
            "gross_beverage_sales": round(is_revenue * 0.15, 0),
            "total_revenue": is_revenue
        },
        "cogs": {
            "food_ingredients": round(is_cogs * 0.85, 0),
            "beverage_ingredients": round(is_cogs * 0.15, 0),
            "total_cogs": is_cogs,
            "cogs_percentage": round(is_cogs / is_revenue * 100, 1) if is_revenue else 0
        },
        "gross_profit": is_gross,
        "operating_expenses": {
            "total_payroll": fixed.get("monthly_payroll", 0.0),
            "utilities_water_electricity": fixed.get("monthly_electricity_and_water", 0.0),
            "rent": fixed.get("monthly_rent", 0.0),
            "gas_internet_lain": fixed.get("monthly_gas_internet_lain", 0.0),
            "total_operating_expenses": fixed.get("total_monthly_fixed_cost", 0.0)
        },
        "ebitda": is_gross - fixed.get("total_monthly_fixed_cost", 0),
        "net_profit": is_net,
        "net_margin_percent": is_margin
    }

    monthly_growth = master.get("monthly_growth_history", [])
    six_mo_sum = master.get("six_month_summary", {})

    return {
        "business": {
            "name": master.get("business_name", "Nama Usaha"),
            "location": master.get("location", "Lokasi Usaha"),
            "currency": "IDR",
            "period": hist.get("period", "26.08.26 s/d 24.09.26 (28 hari)")
        },
        "kpi": {
            "total_omzet_period": total_omzet_28d,
            "avg_daily_omzet": avg_daily_omzet,
            "total_hpp_bahan": total_hpp_28d,
            "avg_daily_hpp": avg_daily_hpp,
            "monthly_fixed_cost": master.get("fixed_costs", {}).get("total_monthly_fixed_cost", 0),
            "daily_fixed_cost": daily_fixed_cost,
            "total_net_profit": six_mo_sum.get("total_net_profit", 0.0),
            "avg_daily_profit": avg_daily_profit,
            "avg_margin_percent": avg_margin_pct,
            "total_inventory_value": total_inventory_value,
            "live_sales_db": live_total_sales,
            "live_orders_count": live_completed_count,
            "total_6mo_omzet": six_mo_sum.get("total_revenue", 0.0),
            "total_6mo_net_profit": six_mo_sum.get("total_net_profit", 0.0),
            "avg_mom_growth": six_mo_sum.get("average_monthly_growth", 0.0),
            "total_6mo_orders": live_completed_count
        },
        "income_statement": income_statement,
        "purchasing": purchasing,
        "purchasing_detail": purchasing,
        "fixed_costs_view": master.get("fixed_costs", {}),
        "monthly_growth": monthly_growth,
        "six_month_summary": six_mo_sum,
        "menu_catalog": get_menu_catalog(db),
        "charts": {
            "daily_dates": [d["tanggal"] for d in daily_table_data],
            "daily_omzet": [d["estimasi_omzet"] for d in daily_table_data],
            "daily_hpp": [d["pemakaian_hpp"] for d in daily_table_data],
            "daily_net_profit": [d["laba_bersih"] for d in daily_table_data],
            "monthly_growth": {
                "labels": [m["month_name"] for m in monthly_growth],
                "omzet": [m["omzet"] for m in monthly_growth],
                "hpp": [m["hpp"] for m in monthly_growth],
                "net_profit": [m["laba_bersih"] for m in monthly_growth],
                "growth_rates": [m["growth_percent"] for m in monthly_growth],
                "orders_count": [m.get("total_orders", 0) for m in monthly_growth]
            },
            "cost_breakdown": {
                "labels": ["Gaji & Payroll", "HPP Bahan (Bulanan)", "Sewa Tempat", "Utilitas (Listrik/Air)", "Gas, Internet & Lain-lain"],
                "values": [
                    fixed.get("monthly_payroll", 0.0),
                    round(float(master.get("historical_hpp_benchmark", {}).get("total_pemakaian_bahan", 0)) / 6, 0),
                    fixed.get("monthly_rent", 0.0),
                    fixed.get("monthly_electricity_and_water", 0.0),
                    fixed.get("monthly_gas_internet_lain", 0.0)
                ]
            },
            "purchasing_breakdown": {
                "labels": ["Belanja Bahan Dapur (Pasar)", "Belanja Bahan Minuman", "Operasional & Non-Bahan (Gas, Galon, Tisu, dll)"],
                "values": [
                    round(sum(dp.get("belanja_dapur", 0) for dp in purchasing.get("daily_purchases", [])), 0),
                    round(sum(dp.get("belanja_minuman", 0) for dp in purchasing.get("daily_purchases", [])), 0),
                    round(sum(dp.get("belanja_operasional", 0) for dp in purchasing.get("daily_purchases", [])), 0)
                ]
            },
            "menu_ranking": {
                "names": [m["name"] for m in top_menus[:8]],
                "quantities": [m["sold_qty"] for m in top_menus[:8]],
                "revenues": [m["revenue"] for m in top_menus[:8]]
            }
        },
        "top_menus": top_menus,
        "daily_records": daily_table_data
    }


def get_dashboard_html_page() -> str:
    from pathlib import Path
    from app.auth import is_web_auth_enabled
    html_template_path = Path(os.getenv("DASHBOARD_TEMPLATE_PATH", BASE_DIR / "templates" / "dashboard.html"))
    if html_template_path.exists():
        with open(html_template_path, "r", encoding="utf-8") as f:
            content = f.read()
            if not is_web_auth_enabled():
                content = content.replace('<a href="/logout" title="Kunci Akses" class="px-3 py-1.5 rounded-lg border border-rose-200 bg-rose-50 text-xs font-semibold text-rose-600 hover:bg-rose-100 flex items-center gap-1.5 transition">\n          <i data-lucide="lock" class="w-3.5 h-3.5"></i> <span class="hidden sm:inline">Kunci</span>\n        </a>', "")
            return content
    return "<h1>Template not found</h1>"
