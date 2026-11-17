"""Dữ liệu booking tổng hợp GIẢ LẬP, không liên quan khách hàng của công ty."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd


def make_demo(n=260, seed=2026):
    rng = np.random.default_rng(seed)
    carriers = ["HÃNG TÀU A", "HÃNG TÀU B", "HÃNG TÀU C", "HÃNG TÀU D"]
    routes = [("CÁT LÁI", "SINGAPORE"), ("CÁT LÁI", "MANILA"),
              ("CÁT LÁI", "BANGKOK"), ("HẢI PHÒNG", "BUSAN"),
              ("HẢI PHÒNG", "HONG KONG"), ("CÁT LÁI", "HONG KONG")]
    # 2024-09 .. 2026-10, có biến động theo mùa, không gợi ý đây là số liệu thật.
    months = pd.period_range("2024-09", "2026-10",freq="M")
    weights = np.array([1+0.15*i/len(months)+0.28*np.sin((i%12)/12*2*np.pi) for i in range(len(months))]); weights/=weights.sum()
    mm = rng.choice(len(months), size=n, p=weights)
    rows=[]
    for i, mid in enumerate(mm):
        m=months[mid]
        booking = m.to_timestamp()+pd.Timedelta(days=int(rng.integers(0,27)))
        lead = max(1,int(rng.normal(17 if mid<12 else 15,6)))
        etd = booking + pd.Timedelta(days=lead)
        eta = etd + pd.Timedelta(days=int(rng.integers(4,24)))
        route=routes[int(rng.choice(len(routes),p=[.31,.19,.12,.18,.11,.09]))]
        containers=int(rng.choice([1,2,3,4],p=[.45,.35,.15,.05]))
        carrier=str(rng.choice(carriers,p=[.39,.28,.21,.12]))
        rows.append({
            "shipment_id":f"DEMO-SHP-{i+1:04d}",
            "booking_no":f"DEMO-BK-{i+1:05d}",
            "booking_date":booking.strftime("%Y-%m-%d"),
            "carrier":carrier,"pol":route[0],"pod":route[1],
            "customer":f"KHÁCH HÀNG {chr(65+int(rng.integers(0,6)))}",
            "etd":etd.strftime("%Y-%m-%d"),"eta":eta.strftime("%Y-%m-%d"),
            "container_count":containers,
            "gross_weight_kg":int(containers*rng.uniform(8000,22000)),
            "cbm":round(containers*rng.uniform(19,58),2),
            "product":str(rng.choice(["HÀNG ĐIỆN TỬ", "NÔNG SẢN", "THỰC PHẨM ĐÓNG GÓI", "DỆT MAY", "HÓA CHẤT CÔNG NGHIỆP"])),
            "status":str(rng.choice(["READY", "IN PROGRESS", "COMPLETED"],p=[.4,.25,.35])),
        })
    df = pd.DataFrame(rows).sort_values("booking_date").reset_index(drop=True)
    df["gross_weight_kg"] = df["gross_weight_kg"].astype("object")
    # Lỗi dữ liệu cố ý để người tham quan trải nghiệm bước profiling/làm sạch.
    df.loc[5,"etd"]="NOT-A-DATE"
    df.loc[11,"etd"] = None
    df.loc[14,"carrier"] = None
    df.loc[25,"booking_date"] = "2025-99-99"
    df.loc[41,"gross_weight_kg"] = "invalid"
    df.loc[52,"pol"] = "CAT LAI"
    df.loc[75,"cbm"] = None
    df.loc[82,"eta"] = None
    df.loc[89,"pod"] = None
    # Cùng shipment/booking lặp để thử sensitivity. Không xóa nếu chưa kiểm tra.
    repeat = df.iloc[[i for i in [3,28,60,103,144] if i < len(df)]].copy()
    repeat.loc[repeat.index[0],"gross_weight_kg"] = 11000 # xung đột từ 2 phiên bản
    df=pd.concat([df,repeat],ignore_index=True)
    return df


if __name__ == "__main__":
    path=Path(__file__).resolve().parent / "data" / "booking_demo.csv"
    path.parent.mkdir(parents=True,exist_ok=True)
    make_demo().to_csv(path,index=False,encoding="utf-8-sig")
    print(path)
