"""Public showcase helpers for the original logistics application.

This module contains only deterministic synthetic fixtures and descriptive
statistics. It never contacts third-party services or publishes real records.
"""
from __future__ import annotations

from pathlib import Path
from datetime import timedelta
import io
import random
import re

import pandas as pd


DEMO_SHIPPERS = ["DEMO • Exporter A", "DEMO • Exporter B", "DEMO • Exporter C", "DEMO • Exporter D"]
DEMO_CARRIERS = ["Carrier ALPHA", "Carrier BETA", "Carrier GAMMA"]
DEMO_ROUTES = [
    ("Cat Lai", "Singapore"),
    ("Cat Lai", "Rotterdam"),
    ("Cai Mep", "Los Angeles"),
    ("Cai Mep", "Hamburg"),
]


def safe_upload_filename(name: str) -> str:
    """Take a single filesystem component, regardless of user OS/path separators."""
    basename = Path(str(name).replace("\\", "/")).name
    cleaned = re.sub(r"[^\w. -]+", "_", basename, flags=re.UNICODE)
    cleaned = cleaned.strip(". ")[:120]
    return cleaned or "unnamed_upload"


def make_demo_rows() -> pd.DataFrame:
    """Build repeatable, explicitly artificial export bookings spanning 22 months.

    Dates, parties, carriers, quantities and booking numbers are fabricated.
    There are intentionally missing carriers and two malformed ETD fields.
    """
    rng = random.Random(20261117)
    rows: list[dict] = []
    months = pd.date_range("2025-01-01", "2026-10-01", freq="MS")
    for m_ix, month in enumerate(months):
        volume = 3 + (m_ix // 4) + (m_ix % 3) + rng.randint(0, 2)
        for j in range(volume):
            booking_date = month + pd.Timedelta(days=(j * 3 + rng.randint(0, 5)) % 24)
            lead = rng.randint(8, 34)
            etd = booking_date + timedelta(days=lead)
            eta = etd + timedelta(days=rng.randint(7, 40))
            carrier = DEMO_CARRIERS[(j + m_ix) % len(DEMO_CARRIERS)]
            if (j + m_ix * 7) % 23 == 0:
                carrier = ""  # data-quality illustration
            pol, pod = DEMO_ROUTES[(j * 2 + m_ix) % len(DEMO_ROUTES)]
            booking_id = f"BK-DEMO-{month.year}{month.month:02d}-{j+1:03d}"
            container_count = rng.choice([1, 1, 1, 2, 3])
            for container_no in range(1, container_count + 1):
                rows.append({
                    "Booking ID": booking_id,
                    "Container": str(container_no),
                    "Date of Booking": booking_date.strftime("%Y-%m-%d"),
                    "Shipper": DEMO_SHIPPERS[(j + m_ix) % len(DEMO_SHIPPERS)],
                    "Consignee": "DEMO • Overseas buyer",
                    "Notify": "DEMO • Notification party",
                    "Product": rng.choice(["Textiles", "Furniture", "Machinery", "Home goods"]),
                    "Total Pallet": str(rng.randint(8, 24)),
                    "Packing Details": "SYNTHETIC RECORD — NOT A REAL DOCUMENT",
                    "Quantity": str(rng.randint(100, 2500)),
                    "Marking": "DEMO ONLY",
                    "Source File": "synthetic_example.pdf",
                    "Cargo Type": "NON DG",
                    "Carrier Booking No": f"DEMO-CONF-{month.year}{month.month:02d}-{j+1:03d}",
                    "Carrier": carrier,
                    "Vessel / Voyage": "DEMO VESSEL / 001",
                    "Port of Loading": pol,
                    "Port of Discharge": pod,
                    "ETD": "invalid-date" if (m_ix, j) in {(3, 0), (15, 0)} else etd.strftime("%Y-%m-%d"),
                    "ETA": eta.strftime("%Y-%m-%d"),
                    "Created At": booking_date.strftime("%Y-%m-%d 09:00:00"),
                    "Last Updated": booking_date.strftime("%Y-%m-%d 09:00:00"),
                })
    return pd.DataFrame(rows)


def make_demo_workbook(path: Path) -> Path:
    """Write a workbook readable by the legacy app (one row per container)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = make_demo_rows()
    # This sheet is the original app's normalized read model. The visible
    # sheets serve as fallback for older schema loaders / user exploration.
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="_BookingsData", index=False)
        df.to_excel(writer, sheet_name="Bookings", index=False)
        df.to_excel(writer, sheet_name="Extracted Data", index=False)
        writer.book["_BookingsData"].sheet_state = "hidden"
    return path


def compute_booking_analytics(records: pd.DataFrame) -> dict:
    """Compute defensible descriptives at the *shipment*, not container, level."""
    empty = pd.DataFrame()
    if records is None or records.empty or "Booking ID" not in records.columns:
        return {"shipments": empty, "monthly": empty, "carriers": empty,
                "routes": empty, "lead_times": empty, "quality": {}, "hhi": None}
    df = records.copy()
    df["Booking ID"] = df["Booking ID"].astype("string").fillna("").str.strip()
    df = df[df["Booking ID"].ne("")].copy()
    if df.empty:
        return compute_booking_analytics(pd.DataFrame())
    df["Container"] = df.get("Container", pd.Series("1", index=df.index)).astype(str)
    containers = df.groupby("Booking ID")["Container"].nunique().rename("Container Count")
    shipments = df.drop_duplicates("Booking ID").set_index("Booking ID").join(containers).reset_index()
    for c in ("Date of Booking", "ETD", "ETA"):
        if c not in shipments:
            shipments[c] = ""
        shipments[c + " Parsed"] = pd.to_datetime(shipments[c], errors="coerce")
    shipments["Lead Time Days"] = (
        shipments["ETD Parsed"] - shipments["Date of Booking Parsed"]
    ).dt.days
    shipments["Lead Time Days"] = shipments["Lead Time Days"].where(
        shipments["Lead Time Days"].between(0, 365)
    )
    parsed_booking = shipments["Date of Booking Parsed"]
    valid = shipments.loc[parsed_booking.notna()].copy()
    if valid.empty:
        monthly = pd.DataFrame(columns=["Month", "Bookings", "MoM %", "MA3"])
    else:
        monthly = (valid.groupby(valid["Date of Booking Parsed"].dt.to_period("M"))
                   .size().rename("Bookings").reset_index())
        monthly.columns = ["Month", "Bookings"]
        monthly["Month"] = monthly["Month"].astype(str)
        monthly["MoM %"] = monthly["Bookings"].pct_change(fill_method=None).mul(100)
        monthly["MA3"] = monthly["Bookings"].rolling(3, min_periods=3).mean()
    carrier = shipments.get("Carrier", pd.Series("", index=shipments.index)).fillna("").astype(str).str.strip()
    known = carrier[carrier.ne("")]
    carriers = known.value_counts().rename_axis("Carrier").reset_index(name="Shipments")
    if not carriers.empty:
        carriers["Share %"] = (100 * carriers["Shipments"] / len(known)).round(2)
        hhi = float(((carriers["Shipments"] / len(known)) ** 2).sum())
    else:
        hhi = None
    pol = shipments.get("Port of Loading", pd.Series("", index=shipments.index)).fillna("").astype(str).str.strip()
    pod = shipments.get("Port of Discharge", pd.Series("", index=shipments.index)).fillna("").astype(str).str.strip()
    routes = (pol.where(pol.ne(""), "(Unknown POL)") + " → "
              + pod.where(pod.ne(""), "(Unknown POD)"))
    routes = routes.value_counts().rename_axis("Route").reset_index(name="Shipments")
    lead_times = shipments["Lead Time Days"].dropna().astype(float)
    quality = {
        "shipment_count": int(len(shipments)),
        "container_count": int(containers.sum()),
        "invalid_booking_dates": int(shipments["Date of Booking Parsed"].isna().sum()),
        "invalid_etd": int(shipments["ETD Parsed"].isna().sum()),
        "missing_carrier": int(carrier.eq("").sum()),
        "valid_lead_time": int(lead_times.size),
    }
    return {"shipments": shipments, "monthly": monthly,
            "carriers": carriers, "routes": routes,
            "lead_times": lead_times, "quality": quality, "hhi": hhi}


def render_data_analytics(records: pd.DataFrame) -> None:
    """Analysis follows the report: method -> Python -> chart -> interpretation."""
    import streamlit as st

    st.title("Booking Data Analysis")
    st.caption("Data Analyst workflow: profiling → cleaning checks → descriptive statistics → trends → business interpretation")
    st.warning("Results in the public showcase come from SYNTHETIC data, not Đại Quốc Việt company records. Never treat demo patterns as business findings.")
    if records.empty:
        st.info("Select 'Load synthetic booking sample' in the sidebar to explore analytical charts. Alternatively, create bookings in the original workflow.")
        return
    results = compute_booking_analytics(records)
    quality = results["quality"]
    a,b,c,d = st.columns(4)
    a.metric("Distinct shipments", quality["shipment_count"])
    b.metric("Containers", quality["container_count"])
    c.metric("Invalid ETD", quality["invalid_etd"])
    d.metric("Valid lead-time samples", quality["valid_lead_time"])
    st.markdown("### 1. Data quality — kiểm tra dữ liệu")
    st.dataframe(pd.DataFrame([
        {"Rule": "Missing carrier", "Count": quality["missing_carrier"]},
        {"Rule": "Invalid booking date", "Count": quality["invalid_booking_dates"]},
        {"Rule": "Invalid ETD", "Count": quality["invalid_etd"]},
        {"Rule": "Unusable lead time", "Count": quality["shipment_count"]-quality["valid_lead_time"]},
    ]), hide_index=True, use_container_width=True)
    with st.expander("Method & Python — data-quality rules"):
        st.code('pd.to_datetime(df["ETD"], errors="coerce")\nseries.isna().sum()\ndf.drop_duplicates("Booking ID")', language="python")
        st.latex(r"\mathrm{Validity\ Rate}=\frac{N_{\mathrm{valid}}}{N_{\mathrm{total}}}\times100\%")
        st.write("Insight: thiếu hoặc sai ETD làm mất khả năng phân tích lead time và lịch tàu; cần bổ sung hoặc xác minh chứng từ.")
    st.markdown("### 2. Booking trend — xu hướng theo tháng")
    monthly = results["monthly"]
    if not monthly.empty:
        st.line_chart(monthly.set_index("Month")[["Bookings", "MA3"]], use_container_width=True)
        st.dataframe(monthly, hide_index=True, use_container_width=True)
        if len(monthly) >= 2:
            last = monthly.iloc[-1]
            mom = last["MoM %"]
            mom_text = (f"{mom:+.1f}%" if pd.notna(mom) else "not available")
            st.info(f"Demo observation: month {last['Month']} contains {int(last['Bookings'])} bookings; month-on-month change = {mom_text}. This is an artificial pattern, not a forecast.")
        else:
            st.info("At least two months with valid booking dates are needed for a MoM comparison.")
    else:
        st.info("No usable monthly observations.")
    with st.expander("Method & Python — MoM and moving average"):
        st.latex(r"\mathrm{MoM}_t=\frac{B_t-B_{t-1}}{B_{t-1}}\times100\%")
        st.latex(r"\mathrm{MA3}_t=\frac{B_t+B_{t-1}+B_{t-2}}{3}")
        st.code('monthly["MoM %"] = monthly["Bookings"].pct_change(fill_method=None) * 100\nmonthly["MA3"] = monthly["Bookings"].rolling(3, min_periods=3).mean()', language="python")
        st.write("Interpretation: distinguish seasonal variation from a persistent trend; verify data completeness before asserting increases or decreases.")
    st.markdown("### 3. Carrier mix — cơ cấu hãng tàu")
    carriers = results["carriers"]
    if not carriers.empty:
        st.bar_chart(carriers.set_index("Carrier")["Shipments"], use_container_width=True)
        st.dataframe(carriers, hide_index=True, use_container_width=True)
        st.write(f"HHI across identified carriers = {results['hhi']:.3f}. Missing carriers are excluded from the denominator and reported in quality checks.")
    else:
        st.info("No identified carriers available for share analysis.")
    with st.expander("Method & Python — share and HHI"):
        st.latex(r"p_i=\frac{n_i}{\sum_j n_j};\qquad HHI=\sum_i p_i^2")
        st.code('counts = df["Carrier"].value_counts()\np = counts / counts.sum()\nhhi = (p ** 2).sum()', language="python")
        st.write("Interpretation: larger HHI indicates greater concentration in the observed carrier mix, not automatically a business risk.")
    st.markdown("### 4. Routes — POL to POD")
    if not results["routes"].empty:
        st.bar_chart(results["routes"].set_index("Route")["Shipments"], use_container_width=True)
        st.dataframe(results["routes"], hide_index=True, use_container_width=True)
    st.markdown("### 5. Lead time — Booking Date → ETD")
    lead = results["lead_times"]
    if lead.empty:
        st.info("Lead-time statistics cannot be computed when no valid date pairs exist.")
    else:
        desc = {"Mean": float(lead.mean()), "Median": float(lead.median()),
                "Std": float(lead.std()) if len(lead)>1 else float('nan'),
                "P90": float(lead.quantile(.9)), "Q1": float(lead.quantile(.25)),
                "Q3": float(lead.quantile(.75)), "IQR": float(lead.quantile(.75)-lead.quantile(.25))}
        st.dataframe(pd.DataFrame([desc]).round(2), use_container_width=True, hide_index=True)
        st.bar_chart(lead.round().value_counts().sort_index().rename_axis("Days").rename("Shipments"))
        st.write(f"Demo observation: median lead time = {desc['Median']:.1f} days; P90 = {desc['P90']:.1f} days. These summarize synthetic dates only.")
    with st.expander("Method & Python — duration and percentiles"):
        st.latex(r"L_i=ETD_i-BookingDate_i;\quad IQR=Q_3-Q_1")
        st.code('lead_days = (etd - booking_date).dt.days\nmedian = lead_days.median()\np90 = lead_days.quantile(.90)', language="python")
        st.write("Business use: highlight long lead-time cases for document coordination; do not confuse planned ETD with actual departure.")
    st.divider()
    st.download_button("Download analyzed shipment table (CSV)",
                       data=results["shipments"].drop(columns=[x for x in results["shipments"].columns if x.endswith(" Parsed")]).to_csv(index=False).encode("utf-8-sig"),
                       file_name="synthetic_booking_analysis.csv", mime="text/csv")
    st.caption("Analysis unit: distinct Booking ID. Container rows are aggregated before booking-level counts. This preview is descriptive, not causal or predictive.")
