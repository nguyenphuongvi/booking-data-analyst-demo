# Booking Data Analyst Lab – trải nghiệm bằng QR

**Đề tài:** Ứng dụng Python trong xây dựng quy trình xử lý và phân tích dữ liệu booking xuất khẩu tại Công ty TNHH Đại Quốc Việt.

Đây là một **web app trình diễn độc lập** phục vụ báo cáo tập sự của một Data Analyst. App không sửa code `app.py` hoặc `data/export_master.db` của hệ thống gốc và không tự kết nối database công ty.

## 1. Chạy ngay trên Mac với VS Code

Tải `booking_data_analyst_qr_demo.zip` vào thư mục `~/Downloads`.

```bash
cd ~/Desktop/booking_ai_new
mkdir -p booking_qr_demo
unzip -o ~/Downloads/booking_data_analyst_qr_demo.zip -d booking_qr_demo
source .venv/bin/activate
python -m pip install -r booking_qr_demo/requirements.txt
python -m streamlit run booking_qr_demo/streamlit_app.py --server.port 8503
```

Mở `http://localhost:8503` trên Mac. Bản demo khác cổng `8501` của app chính nên có thể chạy song song.

Nếu không có `.venv`, tạo venv riêng trong `booking_qr_demo` bằng `python3 -m venv .venv` rồi kích hoạt.

## 2. Cho người khác quét QR trong cùng mạng Wi-Fi

Chạy app với địa chỉ lắng nghe toàn bộ card mạng:

```bash
cd ~/Desktop/booking_ai_new
source .venv/bin/activate
python -m streamlit run booking_qr_demo/streamlit_app.py --server.address 0.0.0.0 --server.port 8503
```

Ở **Terminal khác**, xem địa chỉ IP của Mac:

```bash
ipconfig getifaddr en0
```

Giả sử kết quả là `192.168.1.35` (chỉ là ví dụ), thì địa chỉ điện thoại truy cập là `http://192.168.1.35:8503`. Dán **địa chỉ IP thật** vào tab **Chia sẻ bằng QR** trên app để tạo mã. Điện thoại cần ở cùng Wi-Fi, tường lửa Mac cho phép kết nối và tiến trình Streamlit phải đang chạy. Nếu `en0` không có IP, kiểm tra giao diện mạng đang kết nối.

**Không dùng `http://localhost:8503` làm mã QR cho điện thoại**: `localhost` trên điện thoại nghĩa là chính điện thoại.

## 3. Cách dùng QR công khai (người ngoài mạng vẫn quét được)

Streamlit Community Cloud có thể triển khai app từ GitHub:

1. Tạo một repository GitHub **chỉ chứa các file của thư mục app demo** (không upload dữ liệu công ty, `.env`, database nội bộ hay thư mục dự án lớn).
2. Đưa `streamlit_app.py`, `analysis_core.py`, `sqlite_export.py`, `sample_data.py`, `requirements.txt`, `make_qr.py`, `.streamlit/config.toml`, `data/booking_demo.csv`, `README_VI.md`, và thư mục `tests/` lên repository.
3. Vào **https://share.streamlit.io/**, chọn **Create app**, chọn repository/branch và entrypoint **`streamlit_app.py`**, rồi Deploy. Bật chế độ chia sẻ công khai nếu cần cho người xem không có tài khoản.
4. Lấy URL thực tế dạng `https://...streamlit.app` và dán vào tab **Chia sẻ bằng QR** trên app; tải mã QR PNG xuống để đưa vào slide, poster hoặc báo cáo.
5. Thử dùng chế độ ẩn danh trên điện thoại, mạng 4G/5G, để xác nhận người ngoài truy cập được.

Hoặc tạo QR ở Terminal:

```bash
cd ~/Desktop/booking_ai_new/booking_qr_demo
python make_qr.py --url https://URL-THAT-CUA-APP.streamlit.app --out booking_app_qr.png
```

Không có URL chạy thật thì **không thể có QR truy cập công khai hoạt động**. File ZIP này là code triển khai được, không phải trang đã host sẵn.

Tài liệu chính thức:
- https://docs.streamlit.io/deploy/streamlit-community-cloud
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy

## 4. Người trải nghiệm thấy gì?

| Tab | Data Analyst thực hiện | Python / công thức |
| --- | --- | --- |
| Tổng quan | Yêu cầu nghiệp vụ, kiểm kê dữ liệu | pandas, DataFrame |
| Chất lượng & làm sạch | Missing/validity/duplicate, đối soát | `notna()`, `to_datetime()`, `duplicated()`; tỷ lệ = n/N |
| Xu hướng & cơ cấu | Booking theo tháng, tỷ trọng carrier/POL–POD | `groupby()`, `pct_change()`, `rolling()`, `value_counts()`; MoM, YoY, MA3, HHI |
| Quy mô & thời gian | Container/shipment, weight, CBM, lead time | `median()`, `mean()`, `std()`, `quantile()`; IQR, P90 |
| Insight & tải kết quả | Nhận xét có điều kiện, kiểm tra độ vững | CSV, JSON metadata, SQLite relational snapshot |
| QR | Chia sẻ bản demo | QR PNG từ URL đang hoạt động |

Mặc định app dùng 265 dòng **booking giả lập** và cài lỗi cố ý để minh họa data cleaning. Không suy ra từ mẫu demo bất kỳ kết luận thật nào về hoạt động tại Công ty TNHH Đại Quốc Việt.

## 5. Thử CSV/XLSX của mình

Tab sidebar hỗ trợ tệp CSV/XLSX (nếu XLSX có sheet `Shipments` thì ưu tiên sheet đó). Bắt buộc các cột:

```text
shipment_id, booking_date, etd
```

Các cột tùy chọn: `booking_no`, `carrier` (hoặc `shipping_line`), `pol` (hoặc `port_of_loading`), `pod` (hoặc `port_of_discharge`), `customer`, `eta`, `container_count`, `gross_weight_kg` (hoặc `gross_weight`), `cbm`, `product`, `status`.

**Lưu ý:** Các cột trong file CSV/Excel nên phản ánh **1 dòng ở cấp shipment**. Nếu tệp có 1 dòng mỗi container hoặc nhiều dòng mặt hàng thì phải tổng hợp theo shipment trước khi phân tích số booking, tránh đếm trùng/cộng sai weight.

Đối với dữ liệu doanh nghiệp, chỉ chạy trên máy nội bộ theo chính sách bảo mật và chỉ đưa dữ liệu lên máy chủ công khai khi đã được phép. Uploaded data được xử lý trong phiên Streamlit; không được ghi vào DB gốc, nhưng nơi triển khai web vẫn xử lý dữ liệu upload.

## 6. Kiểm tra code

```bash
cd ~/Desktop/booking_ai_new/booking_qr_demo
python -m unittest discover -s tests -v
python -m py_compile streamlit_app.py analysis_core.py sqlite_export.py sample_data.py make_qr.py
```

`streamlit` là package cần cài trên Mac bằng requirements. Dữ liệu demo dùng numpy tạo từ seed cố định để tái lập bài thực nghiệm.

## 7. Các giới hạn học thuật và an toàn dữ liệu

- Chỉ kiểm tra **định dạng** carrier/port; đúng nghiệp vụ phải đối soát chứng từ và danh mục chuẩn.
- Dòng nghi trùng chỉ được đánh dấu; kịch bản “loại tạm” không phải lệnh DELETE, và không tự chọn bản ghi đúng.
- Phân tích “tổng số booking” cần xác nhận business key và kỳ quan sát. Trong app, các chỉ tiêu ban đầu được ghi rõ theo **dòng**.
- ETD/ETA là ngày kế hoạch. Transit time không đại diện thời gian thực tế.
- Tỷ trọng carrier chỉ phản ánh tập dữ liệu đang xem, không phải thị phần.
- Không suy diễn quan hệ nhân quả từ chart hoặc mô tả thống kê.
- `booking_demo.csv` là **dữ liệu giả lập** và được phép dùng trong trình diễn công khai.
