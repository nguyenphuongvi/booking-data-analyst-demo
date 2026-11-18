from __future__ import annotations

import importlib.util
import json
import os
import re


class BoPhanTichAI:
    """
    Bộ phân tích AI dùng Gemini API.

    Nguyên tắc thiết kế:
    - Không có nút bật/tắt AI theo từng file.
    - Nếu GEMINI_API_KEY tồn tại và thư viện google-genai khả dụng,
      những loại chứng từ được cấu hình dùng AI sẽ tự động gọi AI.
    - Nếu thiếu API key, hết quota hoặc API lỗi, lớp điều phối sẽ fallback
      về rule-based/manual review để app không bị dừng.
    - Packing List không đi qua lớp này.
    """

    def __init__(self, model=None):
        self.model = (
            model
            or os.getenv(
                "GEMINI_MODEL",
                "gemini-3.5-flash-lite",
            )
        )

    @staticmethod
    def _co_thu_vien_gemini():
        try:
            return importlib.util.find_spec(
                "google.genai"
            ) is not None
        except (ModuleNotFoundError, ValueError):
            return False

    @staticmethod
    def _lay_api_key():
        return os.getenv(
            "GEMINI_API_KEY",
            "",
        ).strip()

    def co_san(self):
        return bool(
            self._lay_api_key()
            and self._co_thu_vien_gemini()
        )

    def thong_tin_trang_thai(self):
        if not self._lay_api_key():
            return {
                "provider": "Gemini",
                "available": False,
                "mode": "Selective AI fallback unavailable",
                "reason": "GEMINI_API_KEY is not configured.",
                "model": self.model,
            }

        if not self._co_thu_vien_gemini():
            return {
                "provider": "Gemini",
                "available": False,
                "mode": "Selective AI fallback unavailable",
                "reason": (
                    "The google-genai package is not installed. "
                    "Run: pip install google-genai"
                ),
                "model": self.model,
            }

        return {
            "provider": "Gemini",
            "available": True,
            "mode": "Selective AI available",
            "reason": "",
            "model": self.model,
        }

    @staticmethod
    def _tach_json(noi_dung):
        text = str(
            noi_dung
            or ""
        ).strip()

        if not text:
            return {}

        text = re.sub(
            r"^```(?:json)?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\s*```$",
            "",
            text,
        )

        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass

        match = re.search(
            r"\{.*\}",
            text,
            flags=re.DOTALL,
        )

        if not match:
            return {}

        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _goi_model(self, huong_dan, van_ban):
        if not self.co_san():
            return {}

        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError(
                "The google-genai package is not installed."
            ) from exc

        client = genai.Client(
            api_key=self._lay_api_key()
        )

        prompt = (
            huong_dan
            + "\n\nDOCUMENT TEXT:\n"
            + str(van_ban or "")
        )

        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

        return self._tach_json(
            getattr(
                response,
                "text",
                "",
            )
        )

    def doc_booking_confirmation(self, van_ban):
        huong_dan = """
You are a structured information extraction engine for ocean-freight
Booking Confirmations from many different carriers.

Return exactly one JSON object. Do not invent values. If a value is not
supported by the source document, return an empty string.

Required keys:
confirmation_revision
confirmation_date
carrier_booking_no
application_no
vessel_voyage
carrier
on_behalf_of
port_of_receipt
port_of_loading
pol_terminal
cy_cutoff
vgm_cutoff
si_cutoff
documentation_cutoff
pol_eta
etd
port_of_discharge
final_destination
eta
shipper
service_type_mode
stuffing_place
commodity
qty_type
empty_pick_up_at
inland_return_to
service_contract
payment_term
other_deadlines
evidence

The evidence value must be an object. For every extracted business field,
evidence[field] should contain a short verbatim source line or local context.

Interpret labels semantically because carrier wording and layouts can differ.
Do not treat punctuation-only cells, decorative separators or blank table cells
as business values. Distinguish ETA from ETD, POL from POD, carrier from carrier
booking number, service type from service contract, and commodity from cargo
closing/deadline information.
""".strip()

        return self._goi_model(
            huong_dan,
            van_ban,
        )

    def doc_thong_tin_dg(self, van_ban):
        huong_dan = """
You are a structured information extraction engine for dangerous-goods
shipping documents.

Return exactly one JSON object. Do not invent values. If a value is not
supported by the source document, return an empty string.

Required keys:
un_number
proper_shipping_name
technical_name
imo_class
subsidiary_risk
packing_group
marine_pollutant
flash_point
ems
emergency_contact
net_quantity
gross_quantity
packaging
limited_quantity
dg_bl_text
evidence

The evidence value must be an object with short source text for each extracted
field. dg_bl_text must be a concise B/L-ready dangerous-goods description using
only facts that are explicitly supported by the document.
""".strip()

        return self._goi_model(
            huong_dan,
            van_ban,
        )
