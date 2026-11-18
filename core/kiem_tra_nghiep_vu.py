from __future__ import annotations

from datetime import datetime
import re


class BoKiemTraNghiepVu:
    """
    Kiểm tra dữ liệu sau khi trích xuất.

    Nguyên tắc:
    - Không tự bịa dữ liệu.
    - Không sửa giá trị của AI một cách âm thầm.
    - Chỉ trả cảnh báo để người dùng review.
    """

    CAC_TRUONG_BC_QUAN_TRONG = [
        "carrier_booking_no",
        "vessel_voyage",
        "port_of_loading",
        "port_of_discharge",
        "etd",
        "eta",
    ]

    CAC_TRUONG_DG_QUAN_TRONG = [
        "un_number",
        "proper_shipping_name",
        "imo_class",
    ]

    @staticmethod
    def _co_gia_tri(
        value,
    ) -> bool:
        return bool(
            str(
                value
                or ""
            ).strip()
        )

    @staticmethod
    def _thu_parse_ngay(
        value,
    ):
        text = str(
            value
            or ""
        ).strip()

        if not text:
            return None

        # Chuẩn hóa nhẹ; validator không thay dữ liệu gốc.
        candidates = [
            text,
            text.replace(
                " AM",
                ""
            ).replace(
                " PM",
                ""
            ),
        ]

        dinh_dang = [
            "%Y/%m/%d %H:%M",
            "%Y-%m-%d %H:%M",
            "%d/%m/%Y %H:%M",
            "%d-%m-%Y %H:%M",
            "%Y/%m/%d",
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%d-%m-%Y",
        ]

        for candidate in candidates:
            candidate = re.sub(
                r"\s+",
                " ",
                candidate,
            ).strip()

            for fmt in dinh_dang:
                try:
                    return datetime.strptime(
                        candidate,
                        fmt,
                    )
                except ValueError:
                    continue

        return None

    def kiem_tra_booking_confirmation(
        self,
        du_lieu,
    ):
        canh_bao = []

        for field in self.CAC_TRUONG_BC_QUAN_TRONG:
            if not self._co_gia_tri(
                du_lieu.get(
                    field,
                    "",
                )
            ):
                canh_bao.append(
                    f"Missing important field: {field}"
                )

        etd = self._thu_parse_ngay(
            du_lieu.get(
                "etd",
                "",
            )
        )

        eta = self._thu_parse_ngay(
            du_lieu.get(
                "eta",
                "",
            )
        )

        if (
            etd is not None
            and eta is not None
            and eta < etd
        ):
            canh_bao.append(
                "ETA is earlier than ETD. Review the extracted schedule."
            )

        return canh_bao

    def kiem_tra_dg(
        self,
        du_lieu,
    ):
        canh_bao = []

        for field in self.CAC_TRUONG_DG_QUAN_TRONG:
            if not self._co_gia_tri(
                du_lieu.get(
                    field,
                    "",
                )
            ):
                canh_bao.append(
                    f"DG field requires review: {field}"
                )

        un_number = str(
            du_lieu.get(
                "un_number",
                "",
            )
            or ""
        ).strip()

        if (
            un_number
            and not re.search(
                r"\bUN\s*\d{4}\b",
                un_number,
                flags=re.IGNORECASE,
            )
        ):
            canh_bao.append(
                "UN Number format is unusual. Review before using it in B/L."
            )

        return canh_bao
