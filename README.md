# Booking Data Analyst Lab — QR Demo

**Đề tài:** Ứng dụng Python trong xây dựng quy trình xử lý và phân tích dữ liệu booking xuất khẩu tại Công ty TNHH Đại Quốc Việt.

Web app tương tác theo quy trình **Data Analyst**: khám phá dữ liệu → kiểm tra chất lượng → làm sạch → thống kê → trực quan hóa → giải thích insight. Xây dựng bằng Python, pandas, NumPy, Plotly, Streamlit và SQLite.

> **Chỉ sử dụng dữ liệu GIẢ LẬP.** Bộ demo không chứa dữ liệu booking hay thông tin khách hàng thực tế của công ty. Không đưa dữ liệu nội bộ lên ứng dụng công khai khi chưa được phép.

## Chạy trên máy

```bash
python3 -m venv .venv
source .venv/bin/activate  # macOS / Linux
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

## Triển khai công khai trên Streamlit Community Cloud

1. Đưa **các file này lên thư mục gốc** của một GitHub repository (ví dụ `booking-data-analyst-demo`).
2. Truy cập https://share.streamlit.io/ → Create app → chọn GitHub repository.
3. Chọn branch `main` và main file path **`streamlit_app.py`** → Deploy.
4. Sao chép địa chỉ công khai `https://...streamlit.app` và thử mở bằng điện thoại qua **4G/5G**.
5. Tạo mã QR ngay trong tab **Chia sẻ bằng QR** của app, hoặc:

```bash
python make_qr.py --url https://TEN-APP-THAT.streamlit.app --out qr_bao_cao.png
```

Địa chỉ trên chỉ là ví dụ, phải thay bằng URL thực tế. QR dùng Internet công khai **không phụ thuộc vào cùng Wi-Fi**.

## Kiểm thử

```bash
python -m unittest discover -s tests -v
python -m py_compile streamlit_app.py analysis_core.py sample_data.py sqlite_export.py make_qr.py
```

Xem [README_VI.md](README_VI.md) để hiểu dữ liệu, từng chỉ số thống kê, quy trình và giới hạn phương pháp. Xem [GITHUB_DEPLOY.md](GITHUB_DEPLOY.md) để tải code lên GitHub bằng giao diện hoặc terminal.
