from pathlib import Path
import os


TEN_UNG_DUNG = "Export Documentation Intelligence"
MO_TA_UNG_DUNG = (
    "Logistics document extraction, storage, process tracking and analytics"
)

THU_MUC_GOC = Path(__file__).resolve().parent
THU_MUC_DU_LIEU = THU_MUC_GOC / "data"
THU_MUC_UPLOAD = THU_MUC_GOC / "uploads"
DUONG_DAN_DATABASE = THU_MUC_DU_LIEU / "tracking.db"
TEP_CAU_HINH_LUU_TRU = THU_MUC_DU_LIEU / "storage_settings.json"

# Gemini chỉ được dùng cho nhóm chứng từ cần hiểu ngữ nghĩa nhiều form.
# Packing List được giữ rule-based và không gọi AI.
AI_PROVIDER = os.getenv(
    "AI_PROVIDER",
    "gemini",
).strip().lower()

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.5-flash-lite",
)
