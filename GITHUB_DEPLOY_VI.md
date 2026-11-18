# HƯỚNG DẪN ĐƯA APP GỐC LÊN GITHUB VÀ STREAMLIT CLOUD

## 1. Đưa code gốc lên GitHub (thay repo demo cũ)

Sau khi giải nén file ZIP vào Downloads, mở Terminal VS Code trên Mac:

```bash
brew install gh
# Nếu đã đăng nhập GitHub CLI thì không cần chạy lại:
gh auth status
cd ~/Downloads/booking_goc_streamlit_cloud
bash publish_to_github_mac.sh booking-data-analyst-demo
```

Script sẽ tìm repo `booking-data-analyst-demo` trong tài khoản GitHub hiện tại. Nếu chưa có, script tạo một repository **Public**. Nếu đã có, script thay code demo cũ bằng **code app gốc trong gói này** sau khi bạn xác nhận `y`. Không sửa thư mục gốc trên Desktop. Hãy đọc danh sách các file đổi trước khi xác nhận.

**Quan trọng:** nếu repo đã từng chứa dữ liệu bí mật, việc xóa file trong commit mới không loại bỏ bản sao trong lịch sử Git. Phải xử lý lịch sử repo riêng.

## 2. Deploy Streamlit Cloud

Vào https://share.streamlit.io, đăng nhập bằng GitHub, chọn **Create app / Deploy from GitHub**:

- Repository: `<ten-GitHub-cua-ban>/booking-data-analyst-demo`
- Branch: `main`
- **Main file path: `app.py`** (không phải `streamlit_app.py`)
- Nhấn Deploy.

Nếu đã deploy demo cũ với `streamlit_app.py`, hãy chỉnh entrypoint sang `app.py` nếu giao diện cho phép, hoặc tạo deployment mới từ repo và file đúng.

## 3. Trải nghiệm và tạo QR

Trên app công khai, chọn **Load synthetic booking sample**, rồi vào **Data Analysis** để xem xu hướng, carrier, POL–POD, lead time, KPI và công thức. Đây là dữ liệu giả lập được tạo tự động.

Sau khi nhận URL thật `https://....streamlit.app`, chạy trên Mac:

```bash
python3 -m pip install 'qrcode[pil]'
python3 - <<'PY'
import qrcode
url = input('Dán URL Streamlit thật: ').strip()
if not (url.startswith('https://') and '.streamlit.app' in url):
    raise SystemExit('Hãy nhập link công khai đúng của app, không phải localhost.')
qrcode.make(url).save('QR_APP_GOC.png')
print('Tạo xong QR_APP_GOC.png')
PY
open QR_APP_GOC.png
```

**Không cần chung Wi-Fi.** Người quét QR truy cập link qua Internet bằng Chrome/Safari/4G/5G khi app cloud đang hoạt động.

## 4. Các thay đổi dành riêng cho bản cloud

- Chỉ dùng dữ liệu demo, không gửi database, Excel hoặc chứng từ thật của doanh nghiệp.
- Giữ lại các trang cũ; bổ sung tab **Data Analysis** theo đề tài báo cáo.
- SQLite, workbook và file được tải lên lưu trong thư mục tạm **riêng theo phiên Streamlit**, không dùng chung như ứng dụng desktop cũ.
- Đổi các thao tác chọn thư mục bằng Finder thành thư mục tạm theo phiên.
- Tắt API AI ở bản public, vẫn giữ fallback rule-based và kiểm tra thủ công.
- Người dùng có thể bấm **Reset my demo data** để làm sạch phiên của mình.

### Lưu ý về bảo mật và giới hạn

Mã đã tách thư mục lưu tạm theo phiên nhưng đây **không phải** hệ thống được chứng nhận bảo mật dữ liệu khách hàng. Không tải lên dữ liệu riêng tư hay chứng từ thật. Dữ liệu phiên có thể biến mất nếu Streamlit Cloud restart/redeploy. Các tính năng cần lưu dài hạn hoặc AI API nên chạy trong một hệ thống nội bộ có xác thực.
