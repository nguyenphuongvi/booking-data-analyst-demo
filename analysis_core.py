"""Thuật toán phân tích booking cho app demo Data Analyst.

Không sửa DB hoặc file dữ liệu nguồn. Hàm thuần pandas để dễ kiểm thử.
Không tự coi các bản ghi nghi trùng là sai; chỉ đánh dấu, so sánh kịch bản.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any

import numpy as np
import pandas as pd

REQUIRED = ("shipment_id", "booking_date", "etd")
CORE_COLUMNS = (
    "shipment_id", "booking_no", "booking_date", "carrier", "pol", "pod",
    "customer", "etd", "eta", "container_count", "gross_weight_kg", "cbm",
    "product", "status"
)
COLUMN_ALIASES = {
    "shipping_line": "carrier", "carrier_name": "carrier",
    "port_of_loading": "pol", "pol_name": "pol", "pol_port": "pol",
    "port_of_discharge": "pod", "pod_name": "pod", "pod_port": "pod",
    "shipper": "customer", "consignee": "customer",
    "gross_weight": "gross_weight_kg", "weight_kg": "gross_weight_kg",
    "total_cbm": "cbm", "product_names": "product",
    "container_rows": "container_count", "numbered_containers": "container_count",
}
DATE_FIELDS = ("booking_date", "etd", "eta")
NUMBER_FIELDS = ("container_count", "gross_weight_kg", "cbm")
CATEGORICAL_FIELDS = ("carrier", "pol", "pod", "customer", "status")
PORT_ALIASES = {
    "CAT LAI": "CÁT LÁI", "CATLAI": "CÁT LÁI", "CAT LAI PORT": "CÁT LÁI",
    "HO CHI MINH CITY": "TP. HỒ CHÍ MINH", "HCMC": "TP. HỒ CHÍ MINH",
    "HPH": "HẢI PHÒNG", "HAI PHONG": "HẢI PHÒNG",
    "SGN": "TP. HỒ CHÍ MINH", "SINGAPORE PORT": "SINGAPORE",
}


def _clean_text(s: pd.Series) -> pd.Series:
    out = s.astype("string").str.strip().str.replace(r"\s+", " ", regex=True)
    return out.mask(out.str.lower().isin({"", "none", "nan", "null", "n/a", "na", "-"}))


def _dates(s: pd.Series) -> pd.Series:
    # ISO trước; ngày VN dd/mm/yyyy; không suy diễn giờ hoặc timezone từ ngày.
    def parse(v: Any):
        if pd.isna(v) or str(v).strip().lower() in {"", "none", "nan", "nat"}:
            return pd.NaT
        if isinstance(v, (pd.Timestamp,)):
            return v.tz_localize(None) if v.tzinfo else v
        raw = str(v).strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[ T].*)?", raw):
            parsed = pd.to_datetime(raw, errors="coerce", yearfirst=True, utc=True)
        else:
            parsed = pd.to_datetime(raw, errors="coerce", dayfirst=True, utc=True)
        if pd.isna(parsed):
            return pd.NaT
        return parsed.tz_localize(None)
    return pd.to_datetime(s.map(parse), errors="coerce")


def prepare_bookings(raw: pd.DataFrame) -> pd.DataFrame:
    """Làm sạch nhưng giữ 100% dòng gốc; đánh dấu thay vì xóa."""
    if raw is None or raw.empty:
        raise ValueError("Không có dòng dữ liệu để phân tích.")
    df = raw.copy(deep=True)
    df.columns = [str(x).strip().lower().replace(" ", "_") for x in df.columns]
    # Cột chuẩn ưu tiên hơn cột alias nếu cùng tồn tại.
    for old, new in COLUMN_ALIASES.items():
        if old in df.columns and new not in df.columns:
            df = df.rename(columns={old: new})
    if df.columns.duplicated().any():
        raise ValueError("Tên cột bị lặp sau chuẩn hóa. Hãy sửa file nguồn.")
    missing = [x for x in REQUIRED if x not in df.columns]
    if missing:
        raise ValueError("Thiếu cột bắt buộc: " + ", ".join(missing))
    for c in CORE_COLUMNS:
        if c not in df.columns:
            df[c] = pd.NA
    df = df[list(CORE_COLUMNS)].copy()
    df["_source_row"] = np.arange(2, len(df) + 2)
    for field in ("shipment_id", "booking_no", "carrier", "pol", "pod", "customer", "product", "status"):
        df[field] = _clean_text(df[field])
    for field in CATEGORICAL_FIELDS:
        df[field] = df[field].str.upper()
    for field in ("pol", "pod"):
        df[field] = df[field].replace(PORT_ALIASES)
    for field in DATE_FIELDS:
        df[field + "_parsed"] = _dates(df[field])
        df[field + "_valid"] = df[field + "_parsed"].notna()
    for field in NUMBER_FIELDS:
        df["_raw_present_"+field] = _clean_text(df[field]).notna()
        # Không đổi kg sang tấn vì chưa có chuẩn đơn vị nguồn.
        original = df[field].astype("string").str.strip().str.replace(",", "", regex=False)
        df[field] = pd.to_numeric(original, errors="coerce")
        df.loc[df[field] < 0, field] = np.nan

    # Đánh dấu toàn bộ các dòng nghi trùng, kể cả dòng đầu (keep=False).
    df["duplicate_id"] = df["shipment_id"].notna() & df["shipment_id"].duplicated(keep=False)
    normalized_booking = df["booking_no"].str.replace(r"\s+", "", regex=True).str.upper()
    business_key = df["carrier"].fillna("") + "|" + normalized_booking.fillna("")
    good_key = df["carrier"].notna() & normalized_booking.notna()
    df["duplicate_booking"] = good_key & business_key.duplicated(keep=False)
    df["suspected_duplicate"] = df["duplicate_id"] | df["duplicate_booking"]

    df["lead_days"] = (df["etd_parsed"] - df["booking_date_parsed"]).dt.days
    df["transit_days"] = (df["eta_parsed"] - df["etd_parsed"]).dt.days
    df["lead_anomaly"] = df["lead_days"].notna() & (df["lead_days"] < 0)
    df["transit_anomaly"] = df["transit_days"].notna() & (df["transit_days"] < 0)
    df.loc[df["lead_days"] < 0, "lead_days"] = np.nan
    df.loc[df["transit_days"] < 0, "transit_days"] = np.nan
    df["route"] = df["pol"].fillna("") + " → " + df["pod"].fillna("")
    df.loc[df["pol"].isna() | df["pod"].isna(), "route"] = pd.NA
    df["booking_month"] = df["booking_date_parsed"].dt.to_period("M")
    return df


def analysis_sample(prepared: pd.DataFrame, exclude_suspected: bool = True) -> pd.DataFrame:
    """Mặc định tạm loại toàn bộ nhóm nghi trùng; KHÔNG thay đổi dữ liệu nguồn."""
    return prepared.loc[~prepared["suspected_duplicate"]].copy() if exclude_suspected else prepared.copy()


def profile(prepared: pd.DataFrame) -> pd.DataFrame:
    cols = ["shipment_id", "booking_no", "booking_date", "carrier", "pol", "pod", "customer", "etd", "eta", "container_count", "gross_weight_kg", "cbm", "product"]
    rows = []
    n = len(prepared)
    for field in cols:
        if field in DATE_FIELDS:
            present = int(prepared[field].notna().sum())
            valid = int(prepared[field + "_valid"].sum())
        elif field in NUMBER_FIELDS:
            present = int(prepared["_raw_present_"+field].sum())
            valid = int(prepared[field].notna().sum())
        else:
            present = int(prepared[field].notna().sum())
            valid = present  # Chưa xác minh ngữ nghĩa danh mục từ chứng từ gốc.
        rows.append({"Trường dữ liệu": field, "Có giá trị": present,
                     "Hợp lệ định dạng": valid, "Tổng dòng": n,
                     "Tỷ lệ hiện diện (%)": round(100 * present / n, 1) if n else np.nan,
                     "Tỷ lệ hợp lệ định dạng (%)": round(100 * valid / n, 1) if n else np.nan})
    return pd.DataFrame(rows)


def monthly_trend(sample: pd.DataFrame) -> pd.DataFrame:
    valid = sample["booking_month"].dropna()
    if valid.empty:
        return pd.DataFrame(columns=["month", "bookings", "mom_pct", "yoy_pct", "ma3"])
    count = valid.value_counts().sort_index()
    all_months = pd.period_range(count.index.min(), count.index.max(), freq="M")
    count = count.reindex(all_months, fill_value=0)
    trend = pd.DataFrame({"month": [str(p) for p in count.index], "bookings": count.to_numpy()})
    denominator = trend["bookings"].shift(1).replace(0, np.nan)
    trend["mom_pct"] = 100 * (trend["bookings"] - trend["bookings"].shift(1)) / denominator
    yoybase = trend["bookings"].shift(12).replace(0, np.nan)
    trend["yoy_pct"] = 100 * (trend["bookings"] - trend["bookings"].shift(12)) / yoybase
    trend["ma3"] = trend["bookings"].rolling(3, min_periods=3).mean()
    return trend


def category_breakdown(sample: pd.DataFrame, field: str, max_rows: int = 25) -> pd.DataFrame:
    if field not in {"carrier", "route", "customer", "status", "pol", "pod"}:
        raise ValueError(f"Không hỗ trợ nhóm {field}.")
    known = sample[field].dropna()
    if known.empty:
        return pd.DataFrame(columns=[field, "shipments", "share_pct"])
    counts = known.value_counts().head(max_rows)
    return pd.DataFrame({field: counts.index.astype(str), "shipments": counts.to_numpy(),
                         "share_pct": (counts.to_numpy() / len(known) * 100).round(2)})


def numeric_summary(sample: pd.DataFrame, field: str) -> dict[str, float | int | None]:
    if field not in {"container_count", "gross_weight_kg", "cbm", "lead_days", "transit_days"}:
        raise ValueError("Tên biến thống kê không hợp lệ.")
    values = pd.to_numeric(sample[field], errors="coerce").dropna()
    if len(values) == 0:
        return {"n": 0, "mean": None, "median": None, "std": None,
                "q1": None, "q3": None, "iqr": None, "p90": None, "min": None, "max": None}
    q1 = float(values.quantile(0.25))
    q3 = float(values.quantile(0.75))
    return {"n": len(values), "mean": float(values.mean()),
            "median": float(values.median()), "std": float(values.std(ddof=1)) if len(values)>1 else None,
            "q1": q1, "q3": q3, "iqr": q3-q1, "p90": float(values.quantile(0.90)),
            "min": float(values.min()), "max": float(values.max())}


def hhi(sample: pd.DataFrame, field: str = "carrier") -> float | None:
    known = sample[field].dropna()
    if known.empty:
        return None
    weights = known.value_counts(normalize=True)
    return float((weights**2).sum()*10000)


def quality_metrics(prepared: pd.DataFrame, sample: pd.DataFrame) -> dict[str, int | float]:
    n = len(prepared)
    return {
        "total_rows": n,
        "distinct_ids": int(prepared["shipment_id"].nunique(dropna=True)),
        "suspected_rows": int(prepared["suspected_duplicate"].sum()),
        "included_rows": len(sample),
        "valid_booking_dates": int(prepared["booking_date_valid"].sum()),
        "valid_etds": int(prepared["etd_valid"].sum()),
        "valid_etas": int(prepared["eta_valid"].sum()),
        "negative_leads": int(prepared["lead_anomaly"].sum()),
        "negative_transits": int(prepared["transit_anomaly"].sum()),
        "carrier_present": int(prepared["carrier"].notna().sum()),
        "coverage_etd_pct": round(100*prepared["etd_valid"].sum()/n,1) if n else 0.0,
    }


def insights(prepared: pd.DataFrame, sample: pd.DataFrame) -> list[dict[str, str]]:
    """Diễn giải thống kê thận trọng, không suy ra quan hệ nhân quả."""
    out = []
    q = quality_metrics(prepared, sample)
    out.append({"title":"Chất lượng và mẫu phân tích", "finding":
        f"Có {q['total_rows']} dòng đầu vào; {q['suspected_rows']} dòng nghi trùng. "
        f"Có {q['valid_etds']} ETD đúng định dạng ({q['coverage_etd_pct']}%). "
        f"Kịch bản hiện tại dùng {q['included_rows']} dòng.",
        "action":"Đối soát dòng nghi trùng với chứng từ, chuẩn hóa ETD và xem lại tỷ lệ hợp lệ trước khi báo cáo chính thức."})
    trend = monthly_trend(sample)
    eligible = sample["booking_month"].dropna().nunique()
    if len(trend) >= 6 and eligible >= 6:
        last = trend["bookings"].iloc[-3:].sum()
        prev = trend["bookings"].iloc[-6:-3].sum()
        direction = "cao hơn" if last > prev else "thấp hơn" if last < prev else "bằng"
        out.append({"title":"Diễn biến booking theo tháng", "finding":
            f"Tổng số dòng trong 3 tháng cuối ({int(last)}) {direction} 3 tháng liền trước ({int(prev)}). "
            "Đây là so sánh mô tả trong phạm vi dữ liệu, không phải dự báo.",
            "action":"Kiểm tra tính đầy đủ của từng tháng và nguyên nhân nghiệp vụ trước khi kết luận xu hướng dài hạn."})
    else:
        out.append({"title":"Xu hướng booking", "finding":
            "Chưa đủ tối thiểu 6 tháng có dữ liệu booking hợp lệ để nhận xét xu hướng đáng tin cậy.",
            "action":"Bổ sung dữ liệu lịch sử đồng nhất và xác minh kỳ quan sát."})
    b = category_breakdown(sample, "carrier")
    if not b.empty:
        top = b.iloc[0]
        out.append({"title":"Cơ cấu hãng tàu", "finding":
            f"Nhóm {top['carrier']} có {int(top['shipments'])} dòng, chiếm {top['share_pct']:.1f}% "
            "trên số dòng có carrier; không đại diện thị phần thị trường.",
            "action":"Theo dõi cơ cấu theo tháng và xem nhóm carrier chưa xác minh trước khi điều chỉnh vận hành."})
    lead = numeric_summary(sample,"lead_days")
    if lead["n"] >= 5:
        out.append({"title":"Booking-to-ETD lead time", "finding":
            f"Tập ngày hợp lệ có n={lead['n']}, trung vị {lead['median']:.1f} ngày và P90 {lead['p90']:.1f} ngày.",
            "action":"Xem nhóm lead time dài, đối chiếu lịch tàu và rà soát phân phối theo tuyến."})
    else:
        out.append({"title":"Lead time", "finding":
            f"Chỉ có {lead['n']} cặp ngày hợp lệ; chưa đủ mẫu để nhận xét về phân phối lead time.",
            "action":"Kiểm tra booking date và ETD, mở rộng tập quan sát."})
    return out


def safe_export_csv(df: pd.DataFrame) -> bytes:
    """Giảm rủi ro CSV formula injection khi mở bằng Excel."""
    out = df.copy()
    for col in out.select_dtypes(include=["object","string"]).columns:
        out[col] = out[col].map(lambda x: "'"+x if isinstance(x,str) and x.lstrip().startswith(("=", "+", "-", "@")) else x)
    return out.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
