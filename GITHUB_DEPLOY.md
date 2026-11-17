# Hướng dẫn đưa app lên GitHub và tạo QR công khai

## A. Cách không dùng Terminal

1. Mở https://github.com/new và tạo repository tên `booking-data-analyst-demo` với chế độ **Public**. Nên bỏ chọn tạo README tự động vì gói này đã có README.
2. Giải nén `booking_data_analyst_github_ready.zip`. Mở thư mục `booking_data_analyst_github_ready`.
3. Trong repository, chọn **Add file → Upload files**; tải lên **nội dung** thư mục đã giải nén, không tải nguyên tệp ZIP. Đảm bảo các tệp `streamlit_app.py`, `requirements.txt` ở **gốc repo**. `.streamlit/config.toml` chỉ chứa màu giao diện, có thể thêm sau nếu không hiện trong Finder.
4. Nhấn **Commit changes**.
5. Sang https://share.streamlit.io/ → **Create app** → chọn repository, branch `main`, file `streamlit_app.py` → Deploy.
6. Mở link `https://...streamlit.app` trên điện thoại không cùng Wi-Fi. Nếu vào được thì mã QR mới dùng được.
7. Trong app chọn tab **Chia sẻ bằng QR**, dán URL công khai và tải ảnh QR PNG. Có thể chèn ảnh vào báo cáo / slide.

## B. Cách Terminal trên Mac dùng GitHub CLI

Cài GitHub CLI (nếu chưa có):

```bash
brew install gh
gh auth login
```

Giải nén ZIP, vào thư mục đã giải nén và chạy:

```bash
bash publish_to_github_mac.sh booking-data-analyst-demo
```

Script tạo repository **Public** mới và đẩy code lên GitHub của tài khoản mà `gh auth login` đã đăng nhập. Không chạy lại để cập nhật repo đã có. Để cập nhật từ Git về sau, dùng `git add . && git commit -m 'Update' && git push`.

## Các lưu ý bảo mật

- Trước khi public: chỉ giữ code và CSV mẫu `data/booking_demo.csv` trong repo.
- Không commit tệp `.db`, `.env`, `.streamlit/secrets.toml`, chứng từ, tên khách hàng thật.
- Nếu bạn tải dữ liệu riêng lên app public để phân tích, dữ liệu sẽ được xử lý trên máy chủ Streamlit, không phải Mac của bạn.
- Phân tích thống kê của app trên dữ liệu demo không được xem là kết quả kinh doanh thực tế của Đại Quốc Việt.

Trang hướng dẫn chính thức: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
