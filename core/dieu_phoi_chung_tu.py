from __future__ import annotations

from copy import deepcopy

from core.booking_confirmation_analyzer import BookingConfirmationAnalyzer
from core.kiem_tra_nghiep_vu import BoKiemTraNghiepVu
from core.phan_tich_ai import BoPhanTichAI


class BoDieuPhoiXuLyChungTu:
    """
    Điều phối engine theo loại chứng từ.

    Thiết kế hiện tại:
    - Packing List: luôn rule-based, KHÔNG gọi AI.
    - Booking Confirmation: AI semantic extraction + rule validation.
      Nếu Gemini không khả dụng thì fallback parser cũ.
    - DG Information: AI + validation; nếu AI không khả dụng thì giữ raw text
      để người dùng review tại bước B/L.
    - SI/VGM/Draft B/L/Final B/L: đánh dấu AI-ready cho các workflow sau.

    Việc chọn engine là tự động theo loại chứng từ, không yêu cầu người dùng
    bật/tắt AI thủ công.
    """

    RULE_ONLY_DOCUMENT_TYPES = {
        "Packing List",
    }

    AI_DOCUMENT_TYPES = {
        "Booking Confirmation",
        "DG Information",
        "Shipping Instruction",
        "VGM",
        "Draft B/L",
        "Final B/L",
    }

    CAC_TRUONG_BOOKING_CONFIRMATION = [
        "confirmation_revision",
        "confirmation_date",
        "carrier_booking_no",
        "application_no",
        "vessel_voyage",
        "carrier",
        "on_behalf_of",
        "port_of_receipt",
        "port_of_loading",
        "pol_terminal",
        "cy_cutoff",
        "vgm_cutoff",
        "si_cutoff",
        "documentation_cutoff",
        "pol_eta",
        "etd",
        "port_of_discharge",
        "final_destination",
        "eta",
        "shipper",
        "service_type_mode",
        "stuffing_place",
        "commodity",
        "qty_type",
        "empty_pick_up_at",
        "inland_return_to",
        "service_contract",
        "payment_term",
        "other_deadlines",
    ]

    def __init__(
        self,
        bo_ai=None,
        bo_rules_booking=None,
        bo_kiem_tra=None,
    ):
        self.bo_ai = bo_ai or BoPhanTichAI()
        self.bo_rules_booking = (
            bo_rules_booking
            or BookingConfirmationAnalyzer()
        )
        self.bo_kiem_tra = (
            bo_kiem_tra
            or BoKiemTraNghiepVu()
        )

    @staticmethod
    def _co_gia_tri(value):
        return bool(
            str(value or "").strip()
        )

    def engine_cho_loai_chung_tu(self, loai_chung_tu):
        loai_chung_tu = str(
            loai_chung_tu
            or ""
        ).strip()

        if loai_chung_tu in self.RULE_ONLY_DOCUMENT_TYPES:
            return {
                "document_type": loai_chung_tu,
                "engine": "Rule-based",
                "ai_required": False,
                "ai_available": self.bo_ai.co_san(),
                "description": (
                    "Rule-based extraction only. AI is intentionally not used."
                ),
            }

        if loai_chung_tu in self.AI_DOCUMENT_TYPES:
            ai_available = self.bo_ai.co_san()
            return {
                "document_type": loai_chung_tu,
                "engine": (
                    "Gemini AI + Business Validation"
                    if ai_available
                    else "Rule-based / Manual Fallback"
                ),
                "ai_required": True,
                "ai_available": ai_available,
                "description": (
                    "AI is selected automatically for this document type."
                    if ai_available
                    else (
                        "AI is intended for this document type, but Gemini is "
                        "not currently available; fallback mode will be used."
                    )
                ),
            }

        return {
            "document_type": loai_chung_tu,
            "engine": "Manual / Registered Document",
            "ai_required": False,
            "ai_available": self.bo_ai.co_san(),
            "description": "No automated extractor is configured yet.",
        }

    def phan_tich_booking_confirmation(self, van_ban):
        # Parser cũ luôn chạy để làm fallback và đối chiếu.
        ket_qua_rules = self.bo_rules_booking.analyze(
            van_ban
        )
        ket_qua = deepcopy(
            ket_qua_rules
        )

        evidence_rules = (
            ket_qua.get("__evidence__", {})
            if isinstance(
                ket_qua.get("__evidence__", {}),
                dict,
            )
            else {}
        )

        ket_qua_ai = {}
        loi_ai = ""

        if self.bo_ai.co_san():
            try:
                ket_qua_ai = self.bo_ai.doc_booking_confirmation(
                    van_ban
                )
            except Exception as exc:
                loi_ai = str(exc)

        evidence_ai = (
            ket_qua_ai.get("evidence", {})
            if isinstance(
                ket_qua_ai.get("evidence", {}),
                dict,
            )
            else {}
        )

        # AI là nguồn semantic chính cho Booking Confirmation.
        # Nếu AI bỏ trống field thì giữ fallback từ parser cũ.
        if ket_qua_ai:
            for field in self.CAC_TRUONG_BOOKING_CONFIRMATION:
                ai_value = ket_qua_ai.get(
                    field,
                    "",
                )

                if self._co_gia_tri(ai_value):
                    ket_qua[field] = ai_value

                    if self._co_gia_tri(
                        evidence_ai.get(field, "")
                    ):
                        evidence_rules[field] = evidence_ai[field]

        ket_qua["__evidence__"] = evidence_rules
        ket_qua["__engine__"] = (
            "Gemini AI + Rule-based validation"
            if ket_qua_ai
            else "Rule-based fallback"
        )
        ket_qua["__ai_provider__"] = (
            "Gemini"
            if ket_qua_ai
            else ""
        )
        ket_qua["__ai_model__"] = (
            self.bo_ai.model
            if ket_qua_ai
            else ""
        )

        canh_bao = self.bo_kiem_tra.kiem_tra_booking_confirmation(
            ket_qua
        )

        review_notes = list(
            ket_qua.get("__review_notes__", [])
            or []
        )

        if loi_ai:
            review_notes.append(
                "Gemini extraction was unavailable for this file; "
                "rule-based fallback was used. "
                f"Technical detail: {loi_ai}"
            )

        for canh_bao_item in canh_bao:
            if canh_bao_item not in review_notes:
                review_notes.append(
                    canh_bao_item
                )

        ket_qua["__review_notes__"] = review_notes
        return ket_qua

    def phan_tich_dg(self, van_ban):
        ket_qua = {
            "un_number": "",
            "proper_shipping_name": "",
            "technical_name": "",
            "imo_class": "",
            "subsidiary_risk": "",
            "packing_group": "",
            "marine_pollutant": "",
            "flash_point": "",
            "ems": "",
            "emergency_contact": "",
            "net_quantity": "",
            "gross_quantity": "",
            "packaging": "",
            "limited_quantity": "",
            "dg_bl_text": "",
            "evidence": {},
        }

        loi_ai = ""

        if self.bo_ai.co_san():
            try:
                ket_qua_ai = self.bo_ai.doc_thong_tin_dg(
                    van_ban
                )

                if isinstance(ket_qua_ai, dict):
                    for key in list(ket_qua.keys()):
                        if key in ket_qua_ai:
                            ket_qua[key] = ket_qua_ai[key]

                    ket_qua["__engine__"] = (
                        "Gemini AI + Rule-based validation"
                    )
                    ket_qua["__ai_provider__"] = "Gemini"
                    ket_qua["__ai_model__"] = self.bo_ai.model
            except Exception as exc:
                loi_ai = str(exc)

        if "__engine__" not in ket_qua:
            ket_qua["__engine__"] = "Manual / raw-text fallback"
            ket_qua["__ai_provider__"] = ""
            ket_qua["__ai_model__"] = ""

        if not self._co_gia_tri(
            ket_qua.get("dg_bl_text", "")
        ):
            ket_qua["dg_bl_text"] = str(
                van_ban
                or ""
            ).strip()

        review_notes = self.bo_kiem_tra.kiem_tra_dg(
            ket_qua
        )

        if loi_ai:
            review_notes.append(
                "Gemini extraction was unavailable for this DG document; "
                "raw-text fallback was retained. "
                f"Technical detail: {loi_ai}"
            )

        ket_qua["__review_notes__"] = review_notes
        return ket_qua

    def thong_tin_ai(self):
        return self.bo_ai.thong_tin_trang_thai()

    def bang_dieu_phoi(self):
        thu_tu = [
            "Packing List",
            "Booking Confirmation",
            "DG Information",
            "Shipping Instruction",
            "VGM",
            "Draft B/L",
            "Final B/L",
        ]

        return [
            self.engine_cho_loai_chung_tu(
                loai_chung_tu
            )
            for loai_chung_tu in thu_tu
        ]
