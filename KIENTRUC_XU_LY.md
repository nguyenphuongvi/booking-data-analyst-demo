# Kiến trúc xử lý chứng từ

## 1. Nguyên tắc

Không dùng AI cho toàn bộ chứng từ. Engine được chọn tự động theo loại file.

```text
Packing List
→ Rule-based parser
→ Validation
→ Human review
→ Save

Booking Confirmation
→ Text extraction
→ Gemini AI
→ Rule-based validation / fallback
→ Human review
→ Save
```

## 2. Điều phối engine

File chính:

```text
core/dieu_phoi_chung_tu.py
```

Class:

```text
BoDieuPhoiXuLyChungTu
```

Hai nhóm cấu hình:

```python
RULE_ONLY_DOCUMENT_TYPES
AI_DOCUMENT_TYPES
```

Packing List nằm trong `RULE_ONLY_DOCUMENT_TYPES`, vì vậy code không gọi API AI
ở workflow này.

Booking Confirmation và DG Information nằm trong `AI_DOCUMENT_TYPES`. Nếu
Gemini khả dụng, AI được gọi tự động. Nếu không, hệ thống fallback.

## 3. Lớp AI

File:

```text
core/phan_tich_ai.py
```

Class:

```text
BoPhanTichAI
```

Lớp này chỉ chịu trách nhiệm giao tiếp Gemini và trả dữ liệu JSON. Không chứa
logic ghi Excel, database hoặc giao diện.

## 4. Business validation

File:

```text
core/kiem_tra_nghiep_vu.py
```

AI không được tự quyết dữ liệu cuối cùng. Kết quả AI tiếp tục đi qua validator
và giao diện review.

## 5. Cấu hình

Local:

```text
.env
```

Biến chính:

```text
GEMINI_API_KEY
GEMINI_MODEL
```

Khi deploy có thể dùng environment variables hoặc Streamlit secrets mà không
cần sửa source code.

## 6. Quy tắc bảo trì

- UI: tiếng Anh.
- Comment nội bộ: ưu tiên tiếng Việt.
- Tên lớp điều phối mới: ưu tiên tiếng Việt không dấu.
- Không thêm parser riêng theo tọa độ cho từng hãng tàu.
- Không để AI ghi thẳng dữ liệu cuối cùng mà không qua validation/review.
- Không hard-code API key trong source code.
