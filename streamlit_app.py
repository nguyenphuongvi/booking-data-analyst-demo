"""Booking Data Analyst Experience — QR-friendly public demo.

Chạy: python -m streamlit run streamlit_app.py --server.port 8503
Không nhập khóa API. Không kết nối/sửa DB nội bộ.
"""
from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import re
from urllib.parse import urlparse

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import qrcode
import streamlit as st

from analysis_core import (
    analysis_sample, category_breakdown, hhi, insights, monthly_trend,
    numeric_summary, prepare_bookings, profile, quality_metrics, safe_export_csv,
)
from sample_data import make_demo
from sqlite_export import export_sqlite_bytes

BASE = Path(__file__).resolve().parent

st.set_page_config(
    page_title="Booking Data Lab • Đại Quốc Việt | Demo",
    page_icon="📊", layout="wide", initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  .block-container {padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1180px}
  .big-title {font-weight:780; font-size:clamp(1.45rem,3vw,2.35rem); letter-spacing:-.035em; color:#123450}
  .subline {color:#516475; line-height:1.65; margin:.45rem 0 1rem}
  .eyebrow {font-size:.72rem; text-transform:uppercase; font-weight:700; color:#1b6d7d; letter-spacing:.10em}
  .note {background:#eef4f7;padding:.78rem 1rem;border-left:3px solid #4d8795;border-radius:5px;line-height:1.55;color:#314657}
  .mini {font-size:.82rem; color:#617482}
  div[data-testid="stMetric"] {border:1px solid #dde5eb; border-radius:10px;padding:12px;background:#ffffff}
  @media (max-width: 650px) {.block-container {padding:.6rem .8rem;} }
</style>
""", unsafe_allow_html=True)


def qr_image(url: str) -> BytesIO:
    im = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=8, border=3)
    im.add_data(url); im.make(fit=True)
    buff = BytesIO(); im.make_image(fill_color="#173953", back_color="white").save(buff, format="PNG")
    buff.seek(0)
    return buff


def is_shareable_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in {"http","https"} and bool(parsed.netloc) and " " not in url
    except Exception:
        return False


def as_number(x, decimals=1):
    return "Chưa có" if x is None or pd.isna(x) else f"{x:,.{decimals}f}"


def make_plot_template(fig, height=340):
    fig.update_layout(
        height=height, margin=dict(l=8,r=8,t=28,b=24),
        font=dict(family="Arial",size=12,color="#283c4b"),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend_title_text="", legend_orientation="h", legend_y=-.25,
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#e8edf1", zeroline=False)
    return fig


def label_box(title, formula, code, reading):
    with st.expander(f"ℹ️ Cách tính: {title}"):
        st.markdown(f"**Công thức:** {formula}")
        st.code(code, language="python")
        st.caption(reading)


def nice_header(title, desc=""):
    st.subheader(title)
    if desc: st.caption(desc)


def get_data():
    file = st.session_state.get("booking_uploaded")
    if file is None:
        return make_demo(), "DỮ LIỆU DEMO GIẢ LẬP"
    name = file.name.lower()
    try:
        file.seek(0)
        if name.endswith(".csv"):
            raw = pd.read_csv(file, dtype={"shipment_id":"string", "booking_no":"string"},low_memory=False)
        elif name.endswith(".xlsx"):
            xls = pd.ExcelFile(file)
            sheet = "Shipments" if "Shipments" in xls.sheet_names else xls.sheet_names[0]
            raw = pd.read_excel(xls,sheet_name=sheet,dtype={"shipment_id":"string", "booking_no":"string"})
        else:
            raise ValueError("Chỉ hỗ trợ CSV và XLSX.")
        if len(raw) > 30000:
            raise ValueError("Giới hạn bản trải nghiệm: tối đa 30.000 dòng.")
        return raw, f"TỆP CÁ NHÂN: {file.name}"
    except Exception as exc:
        st.error(f"Không đọc được file: {exc}")
        st.stop()


with st.sidebar:
    st.markdown("### 📊 Booking Data Lab")
    st.caption("Bản demo nghiên cứu • Vai trò Data Analyst")
    st.info("Dữ liệu mặc định là **giả lập 100%**, không phải dữ liệu của Công ty TNHH Đại Quốc Việt.")
    st.file_uploader("Thử phân tích file của bạn (CSV/XLSX)", type=["csv","xlsx"],
                     key="booking_uploaded",help="Chỉ tải dữ liệu được phép chia sẻ lên dịch vụ đang chạy app.")
    st.caption("Không tải dữ liệu nội bộ hoặc thông tin khách hàng lên bản công khai khi chưa được phép.")
    scenario = st.radio("Kịch bản chọn mẫu", ["Loại tạm dòng nghi trùng", "Giữ tất cả dòng để đối chiếu"], index=0)
    remove_suspected = scenario.startswith("Loại")
    st.divider()
    st.markdown("**Luồng trải nghiệm**")
    st.markdown("01 · Thu thập\n\n02 · Data profiling\n\n03 · Làm sạch & đối soát\n\n04 · Phân tích & biểu đồ\n\n05 · Insight & đề xuất")
    st.caption("Công cụ: Python · pandas · NumPy · Plotly · SQLite")

st.markdown('<div class="eyebrow">CÔNG TY TNHH ĐẠI QUỐC VIỆT • ĐỀ TÀI TẬP SỰ</div>', unsafe_allow_html=True)
st.markdown('<div class="big-title">Ứng dụng Python trong quy trình xử lý và phân tích dữ liệu booking xuất khẩu</div>', unsafe_allow_html=True)
st.markdown('<div class="subline">Một trải nghiệm tương tác theo công việc Data Analyst: kiểm tra nguồn dữ liệu → làm sạch và chọn mẫu → tính chỉ tiêu Toán–Thống kê → trực quan hóa → diễn giải kết quả.</div>', unsafe_allow_html=True)

raw, source_label = get_data()
try:
    cleaned = prepare_bookings(raw)
except ValueError as exc:
    st.error(str(exc))
    st.code("shipment_id,booking_no,booking_date,carrier,pol,pod,customer,etd,eta,container_count,gross_weight_kg,cbm,product,status",language="text")
    st.stop()
sample = analysis_sample(cleaned, exclude_suspected=remove_suspected)
q = quality_metrics(cleaned,sample)
trend = monthly_trend(sample)

st.caption(f"**Nguồn đang xem:** {source_label} · **Kịch bản:** {scenario} · **Đơn vị phân tích:** 1 dòng dữ liệu cấp shipment (chỉ coi là một shipment sau khi ID được xác minh)")

m1,m2,m3,m4 = st.columns(4)
m1.metric("Dòng đầu vào", f"{q['total_rows']:,}")
m2.metric("Dòng đang phân tích",f"{q['included_rows']:,}")
m3.metric("Dòng nghi trùng",f"{q['suspected_rows']:,}")
m4.metric("ETD hợp lệ",f"{q['coverage_etd_pct']:.1f}%")

# Tab navigation works on mobile. All pages use the same in-memory clean sample.
tabs = st.tabs(["🏁 Tổng quan", "🔍 Chất lượng & làm sạch", "📈 Xu hướng & cơ cấu", "📦 Quy mô & thời gian", "💡 Insight & xuất báo cáo", "📱 Chia sẻ bằng QR"])

with tabs[0]:
    nice_header("Trải nghiệm công việc Data Analyst", "Mục tiêu là tìm thông tin có ích từ dữ liệu booking — Python giúp thực hiện và tái lập phép phân tích.")
    a,b,c = st.columns(3)
    with a:
        st.markdown("**1. Business understanding**")
        st.write("Tìm hiểu lượng booking, hãng tàu, tuyến và chất lượng ngày ETD.")
        st.markdown("**2. Data profiling**")
        st.write("Đo trường thiếu, sai định dạng và bản ghi nghi trùng.")
    with b:
        st.markdown("**3. Data cleaning**")
        st.write("Chuẩn hóa nhãn, ngày tháng và khóa; giữ dấu vết lỗi.")
        st.markdown("**4. EDA & thống kê**")
        st.write("Nhóm, tính mean/median/P90/MoM/YoY, so sánh các phân phối.")
    with c:
        st.markdown("**5. Visualization**")
        st.write("Biểu đồ đường, cột, histogram và boxplot.")
        st.markdown("**6. Insights & action**")
        st.write("Nhận xét có điều kiện, nêu rủi ro và hướng xác minh.")
    st.markdown('<div class="note">Bản demo không phân loại lỗi ngữ nghĩa bằng AI và không tự xác nhận booking nào là bản ghi chính thức. Dữ liệu nghi trùng chỉ được đánh dấu để đối soát; lựa chọn loại tạm chỉ áp dụng cho phép phân tích hiện tại.</div>',unsafe_allow_html=True)
    st.markdown("#### Dữ liệu đầu vào (10 dòng đầu)")
    st.dataframe(raw.head(10),hide_index=True,use_container_width=True,height=240)
    with st.expander("Cấu trúc dữ liệu & quan hệ"):
        st.code("""SHIPMENT (shipment_id)
   ├── carrier → Danh mục hãng tàu
   ├── POL/POD → Danh mục cảng
   ├── booking_date, ETD, ETA → Biến thời gian
   └── container_count / weight / CBM → Chỉ tiêu quy mô

Demo này hiển thị các chỉ tiêu ở cấp shipment.
Khi phân tích dữ liệu container thực, cần JOIN theo shipment_id,
không nhân đôi gross weight ở cả hai cấp.""",language="text")

with tabs[1]:
    nice_header("Khảo sát chất lượng dữ liệu", "Phân biệt giá trị có mặt với giá trị hợp lệ định dạng; còn tính đúng nghiệp vụ phải đối chiếu chứng từ.")
    prof = profile(cleaned)
    left,right = st.columns([1.15,0.85])
    with left:
        st.dataframe(prof, hide_index=True, use_container_width=True, height=380)
    with right:
        view = prof[prof["Trường dữ liệu"].isin(["booking_date","etd","eta","carrier","pol","pod"])].copy()
        melted = view.melt(id_vars="Trường dữ liệu", value_vars=["Tỷ lệ hiện diện (%)","Tỷ lệ hợp lệ định dạng (%)"], var_name="Nhóm kiểm tra",value_name="Tỷ lệ (%)")
        fig = px.bar(melted,x="Tỷ lệ (%)",y="Trường dữ liệu",color="Nhóm kiểm tra",orientation="h",barmode="group",color_discrete_sequence=["#164c63","#50a5a1"],title="Độ bao phủ và độ hợp lệ định dạng")
        st.plotly_chart(make_plot_template(fig,height=365),use_container_width=True)
    label_box("Tỷ lệ hợp lệ", "validity_j = n_{valid,j} / N × 100%", "pd.to_datetime(df['etd'], errors='coerce').notna().mean()*100", "Ngày có nội dung chưa chắc là ngày hợp lệ. Danh mục carrier/POL/POD cần đối soát ngữ nghĩa riêng.")
    st.markdown("#### Xem các dòng cần đối soát")
    errors = cleaned.loc[cleaned["suspected_duplicate"] | ~cleaned["booking_date_valid"] | ~cleaned["etd_valid"] | cleaned["lead_anomaly"]].copy()
    columns = ["_source_row","shipment_id","booking_no","booking_date","etd","carrier","duplicate_id","duplicate_booking","lead_anomaly"]
    st.dataframe(errors[columns], hide_index=True,use_container_width=True,height=255)
    st.caption("Không có lệnh DELETE/UPDATE. Những dòng lỗi được giữ để theo dõi.")
    st.markdown("#### Sau chuẩn hóa (10 dòng đầu)")
    st.dataframe(cleaned[["shipment_id","booking_no","carrier","pol","pod","booking_date_parsed","etd_parsed","lead_days","suspected_duplicate"]].head(10),hide_index=True,use_container_width=True)

with tabs[2]:
    nice_header("RQ1 · Biến động booking theo thời gian")
    month_valid = int(sample["booking_month"].dropna().nunique())
    if month_valid < 3:
        st.warning("Ít hơn 3 tháng có dữ liệu: chưa đủ cơ sở để trình bày xu hướng ổn định.")
    elif month_valid < 6:
        st.warning("Mẫu chỉ có dưới 6 tháng có booking: xem như mô tả sơ bộ, không suy diễn xu hướng dài hạn.")
    if trend.empty:
        st.info("Không có ngày booking hợp lệ để dựng biểu đồ.")
    else:
        fig = go.Figure()
        fig.add_scatter(x=trend["month"],y=trend["bookings"],mode="lines+markers",name="Dòng booking/tháng",line=dict(color="#16506c",width=2.8))
        fig.add_scatter(x=trend["month"],y=trend["ma3"],mode="lines",name="Trung bình trượt 3 tháng",line=dict(color="#df8e38",dash="dash",width=2.4))
        fig.update_layout(title="Chuỗi tháng booking (dòng phân tích, không đồng nhất với booking đã đối soát)",xaxis_title="Tháng",yaxis_title="Số dòng")
        st.plotly_chart(make_plot_template(fig,height=390),use_container_width=True)
        st.dataframe(trend.tail(12).rename(columns={"month":"Tháng","bookings":"Số dòng","mom_pct":"MoM (%)","yoy_pct":"YoY (%)","ma3":"MA3"}),hide_index=True,use_container_width=True)
    label_box("MoM, YoY và MA3", "MoM_t=(B_t-B_{t-1})/B_{t-1} × 100%;  YoY_t=(B_t-B_{t-12})/B_{t-12} × 100%; MA3=Σ(B_{t-2}...B_t)/3", "trend['bookings'].pct_change(fill_method=None)*100\ntrend['bookings'].rolling(3,min_periods=3).mean()", "Không tính tăng trưởng nếu kỳ gốc bằng 0. Ngày booking chưa đủ coverage có thể gây xu hướng giả.")
    st.divider()
    nice_header("RQ2 · Cơ cấu hãng tàu và tuyến vận chuyển")
    group_label = st.selectbox("Chọn chiều phân tích",["Hãng tàu","Tuyến POL–POD","Khách hàng"],index=0)
    field = {"Hãng tàu":"carrier","Tuyến POL–POD":"route","Khách hàng":"customer"}[group_label]
    breakdown=category_breakdown(sample,field)
    if breakdown.empty:
        st.info("Không có danh mục hợp lệ để phân nhóm.")
    else:
        tab1,tab2=st.columns([1.4,.8])
        with tab1:
            fig=px.bar(breakdown.head(12).iloc[::-1],x="shipments",y=field,orientation="h",text="share_pct",title=f"Cơ cấu theo {group_label.lower()} · số dòng có danh mục",color_discrete_sequence=["#1b6980"])
            fig.update_traces(texttemplate="%{text:.1f}%",textposition="outside")
            fig.update_layout(xaxis_title="Số dòng",yaxis_title="")
            st.plotly_chart(make_plot_template(fig,height=385),use_container_width=True)
        with tab2:
            st.dataframe(breakdown,hide_index=True,use_container_width=True,height=320)
            known = int(sample[field].notna().sum())
            st.metric("Số dòng có danh mục",f"{known}/{len(sample)}")
            if field == "carrier":
                st.metric("HHI nội bộ (0–10.000)",as_number(hhi(sample),0))
    label_box("Tỷ trọng & HHI", "p_g = n_g / N_known × 100%;  HHI=10.000 × Σ(p_g/100)^2", "df['carrier'].value_counts(normalize=True)*100\n(df['carrier'].value_counts(normalize=True)**2).sum()*10000", "Mẫu số chỉ gồm dòng có danh mục; HHI là mức tập trung nội bộ mẫu, không phải thị phần ngành.")

with tabs[3]:
    nice_header("RQ3 · Quy mô lô hàng")
    measure_names={"Số container/shipment":"container_count","Gross weight (kg)":"gross_weight_kg","CBM (m³)":"cbm"}
    measure_name=st.selectbox("Chỉ tiêu",list(measure_names),index=0)
    measure=measure_names[measure_name]
    summary=numeric_summary(sample,measure)
    cc=st.columns(5)
    for c,(label,val) in zip(cc,[("n",summary["n"]),("Trung bình",summary["mean"]),("Trung vị",summary["median"]),("Q3",summary["q3"]),("P90",summary["p90"])]):
        c.metric(label, str(val) if label=="n" else as_number(val))
    points=sample[measure].dropna()
    if len(points) >= 5:
        l,r=st.columns(2)
        with l:
            fig=px.histogram(points,x=measure,nbins=min(20,max(5,int(len(points)**.5))),title=f"Phân phối {measure_name}",color_discrete_sequence=["#1e6882"])
            fig.update_layout(xaxis_title=measure_name,yaxis_title="Số dòng")
            st.plotly_chart(make_plot_template(fig),use_container_width=True)
        with r:
            fig=px.box(points,x=measure,points="outliers",title="Boxplot, ngoại lệ chỉ để rà soát",color_discrete_sequence=["#47a49f"])
            st.plotly_chart(make_plot_template(fig),use_container_width=True)
    else: st.info("Số giá trị hợp lệ < 5: không vẽ biểu đồ phân phối.")
    label_box("Trung bình, trung vị, phương sai, Q1/Q3/P90", "x̄=Σx_i/n; s²=Σ(x_i-x̄)²/(n−1); IQR=Q3−Q1; P90=quantile(x, 0.9)",
              "x.mean(); x.median(); x.std(ddof=1)\nx.quantile([0.25, 0.75, 0.90])", "Ngoại lệ trong thống kê chưa chắc là dữ liệu sai. Không tự loại khỏi mẫu.")
    st.divider()
    nice_header("RQ4 · Lead time và thời gian vận chuyển dự kiến")
    lead_names={"Booking → ETD (ngày)":"lead_days","ETD → ETA dự kiến (ngày)":"transit_days"}
    lt_label=st.selectbox("Loại thời gian",list(lead_names),index=0)
    lt_key=lead_names[lt_label]
    lead_summary=numeric_summary(sample,lt_key)
    k1,k2,k3=st.columns(3)
    k1.metric("Số cặp ngày hợp lệ",str(lead_summary["n"]))
    k2.metric("Trung vị (ngày)",as_number(lead_summary["median"]))
    k3.metric("P90 (ngày)",as_number(lead_summary["p90"]))
    if lead_summary["n"]>=5:
        fig=px.histogram(sample.loc[sample[lt_key].notna()],x=lt_key,nbins=min(24,max(6,int(lead_summary["n"]**.5))),color_discrete_sequence=["#d99d4e"],title=f"Phân phối {lt_label}")
        st.plotly_chart(make_plot_template(fig),use_container_width=True)
        by=sample[["carrier",lt_key]].dropna().groupby("carrier")[lt_key].agg(n="size",median="median",p90=lambda v:v.quantile(.9)).reset_index()
        st.dataframe(by,hide_index=True,use_container_width=True)
        st.caption("So sánh carrier chỉ là mô tả. Không suy ra carrier gây ra sự khác biệt khi chưa kiểm soát các yếu tố khác.")
    else: st.warning("Chưa đủ 5 cặp ngày hợp lệ để thể hiện phân phối; cần kiểm tra chất lượng booking date/ETD/ETA.")
    label_box("Lead time và transit time", "L_i=(ETD_i−BookingDate_i) (ngày); T_i=(ETA_i−ETD_i) (ngày)",
              "(df['etd_parsed']-df['booking_date_parsed']).dt.days\nx.median(); x.quantile(0.9)","Ngày âm đánh dấu cần đối soát, không dùng để tính phân phối; đây là lịch dự kiến, không phải thực tế tàu đến.")

with tabs[4]:
    nice_header("RQ5 · Insight → diễn giải → kiến nghị", "Nhận xét được sinh từ số liệu đang xem, luôn kèm điều kiện và giới hạn của kết luận.")
    for j,item in enumerate(insights(cleaned,sample),start=1):
        with st.container(border=True):
            st.markdown(f"**{j}. {item['title']}**")
            st.write(item["finding"])
            st.caption("**Gợi ý hành động:** "+item["action"])
    st.divider()
    st.markdown("#### Xuất tập phân tích (có ghi rõ nguồn và kịch bản)")
    export_df=sample.copy()
    for field in ("booking_date","etd","eta"):
        export_df[field+"_normalized"] = export_df[field+"_parsed"].dt.strftime("%Y-%m-%d")
    export_cols=[c for c in export_df.columns if not c.endswith("_parsed") and not c.startswith("_raw_present_")]
    st.download_button("⬇️ CSV dữ liệu đã chuẩn hóa",data=safe_export_csv(export_df[export_cols]),
                       file_name="booking_analysis_cleaned.csv",mime="text/csv")
    st.download_button("⬇️ CSV chất lượng dữ liệu",data=safe_export_csv(profile(cleaned)),
                       file_name="booking_data_quality.csv",mime="text/csv")
    st.download_button("⬇️ CSV chuỗi thời gian",data=safe_export_csv(trend),
                       file_name="booking_monthly_trend.csv",mime="text/csv")
    st.download_button("⬇️ SQLite relational (bản sao phân tích)",
                       data=export_sqlite_bytes(sample),file_name="booking_analysis_copy.db",
                       mime="application/vnd.sqlite3",help="Tạo database SQLite mới, không sửa database chính.")
    meta={"data_source":source_label,"scenario":scenario, "generated_for":"interactive demo - not official business statistics",
          "metrics":quality_metrics(cleaned,sample),"n_months_with_data":int(sample["booking_month"].dropna().nunique()),
          "meanings":"The counts represent data rows; duplicates need business verification."}
    st.download_button("⬇️ Metadata và mẫu số (JSON)",json.dumps(meta,ensure_ascii=False,indent=2).encode("utf-8"),
                       file_name="booking_analysis_metadata.json",mime="application/json")
    st.info("Kết quả demo không được dùng làm kết luận chính thức cho Công ty TNHH Đại Quốc Việt.")

with tabs[5]:
    nice_header("Quét mã QR để mở app trên điện thoại", "QR chỉ là đường dẫn. Người khác truy cập được khi app đang chạy trên địa chỉ mà điện thoại kết nối tới.")
    default_url=os.environ.get("APP_PUBLIC_URL","")
    user_url=st.text_input("URL của app (sau khi deploy hoặc IP nội bộ)",value=default_url,
                           placeholder="https://ten-app-cua-ban.streamlit.app/")
    if user_url:
        if is_shareable_url(user_url):
            a,b=st.columns([1,2])
            with a:
                st.image(qr_image(user_url),width=225,caption="Quét bằng camera điện thoại")
                st.download_button("⬇️ Tải mã QR PNG",data=qr_image(user_url).getvalue(),file_name="booking_data_lab_qr.png",mime="image/png")
            with b:
                st.markdown(f"**Địa chỉ chia sẻ:** [{user_url}]({user_url})")
                if re.search(r"(?:localhost|127\.0\.0\.1)",user_url):
                    st.warning("localhost chỉ mở trên chính máy đang chạy, không dùng để chia sẻ cho điện thoại khác.")
                elif user_url.startswith("http://"):
                    st.caption("Với địa chỉ IP Wi-Fi, điện thoại phải cùng mạng và Mac phải đang chạy app. Nếu dùng website công khai, nên dùng HTTPS.")
                st.markdown("**Cách tạo link công khai:** đưa các file project lên GitHub → Deploy qua Streamlit Community Cloud → sao chép URL `.streamlit.app` → dán vào đây.")
        else:
            st.error("URL không hợp lệ. Nhập địa chỉ http:// hoặc https:// đầy đủ.")
    else:
        st.info("Chưa có link triển khai. Hãy deploy app hoặc dùng địa chỉ IP Wi-Fi của Mac rồi dán link vào ô trên để tạo mã QR thật.")
    with st.expander("Quét QR trong cùng Wi-Fi (không cần GitHub)"):
        st.code("""cd ~/Desktop/booking_ai_new/booking_qr_demo
source ../.venv/bin/activate
python -m streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port 8503
# Ở Terminal khác:
ipconfig getifaddr en0""",language="bash")
        st.write("Ví dụ Mac có IP `192.168.1.35`: nhập `http://192.168.1.35:8503` vào ô URL để tạo QR. Ví dụ IP không phải IP thật của m.")

st.markdown("---")
st.caption("Dự án trải nghiệm Data Analyst · Python hỗ trợ quy trình xử lý & phân tích dữ liệu booking xuất khẩu · Bản demo độc lập, không thay đổi app hay database nội bộ.")
