from __future__ import annotations

from io import BytesIO
from pathlib import Path
import csv
import subprocess
import tempfile

import fitz
import pandas as pd
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation


class BoDocTep:
    """
    Bộ đọc tệp đầu vào.

    Mục tiêu:
    - Chỉ chịu trách nhiệm chuyển file thành văn bản thô.
    - Không suy luận nghiệp vụ tại lớp này.
    - Không gắn logic theo từng hãng tàu.
    """

    DINH_DANG_VAN_BAN = {
        ".txt",
        ".md",
        ".log",
        ".json",
        ".xml",
        ".html",
        ".htm",
    }

    def doc_bytes(
        self,
        ten_tep: str,
        du_lieu: bytes,
    ) -> str:
        duoi_tep = Path(
            ten_tep
        ).suffix.lower()

        if duoi_tep == ".pdf":
            return self._doc_pdf(
                du_lieu
            )

        if duoi_tep == ".docx":
            return self._doc_docx(
                du_lieu
            )

        if duoi_tep == ".doc":
            return self._doc_doc_cu(
                ten_tep,
                du_lieu,
            )

        if duoi_tep in {
            ".xlsx",
            ".xlsm",
        }:
            return self._doc_excel_moi(
                du_lieu
            )

        if duoi_tep == ".xls":
            return self._doc_excel_cu(
                du_lieu
            )

        if duoi_tep in {
            ".csv",
            ".tsv",
        }:
            return self._doc_csv_tsv(
                du_lieu,
                duoi_tep,
            )

        if duoi_tep == ".pptx":
            return self._doc_pptx(
                du_lieu
            )

        if duoi_tep == ".rtf":
            return self._doc_rtf(
                du_lieu
            )

        if duoi_tep in self.DINH_DANG_VAN_BAN:
            return self._doc_text(
                du_lieu
            )

        # Thử đọc như văn bản trước khi báo lỗi.
        try:
            return self._doc_text(
                du_lieu
            )
        except Exception as exc:
            raise ValueError(
                f"Unsupported file type: {duoi_tep or 'unknown'}"
            ) from exc

    def read_bytes(
        self,
        ten_tep: str,
        du_lieu: bytes,
    ) -> str:
        """
        Alias tiếng Anh để tương thích ngược với code cũ.
        """
        return self.doc_bytes(
            ten_tep,
            du_lieu,
        )

    @staticmethod
    def _doc_pdf(
        du_lieu: bytes,
    ) -> str:
        tai_lieu = fitz.open(
            stream=du_lieu,
            filetype="pdf",
        )

        try:
            return "\n".join(
                trang.get_text(
                    "text"
                )
                for trang in tai_lieu
            )
        finally:
            tai_lieu.close()

    @staticmethod
    def _doc_docx(
        du_lieu: bytes,
    ) -> str:
        tai_lieu = Document(
            BytesIO(
                du_lieu
            )
        )

        dong = []

        for doan in tai_lieu.paragraphs:
            noi_dung = (
                doan.text
                or ""
            ).strip()

            if noi_dung:
                dong.append(
                    noi_dung
                )

        for bang in tai_lieu.tables:
            for hang in bang.rows:
                gia_tri = [
                    (
                        o.text
                        or ""
                    ).strip()
                    for o in hang.cells
                ]

                if any(
                    gia_tri
                ):
                    dong.append(
                        " | ".join(
                            gia_tri
                        )
                    )

        return "\n".join(
            dong
        )

    @staticmethod
    def _doc_doc_cu(
        ten_tep: str,
        du_lieu: bytes,
    ) -> str:
        """
        macOS có sẵn textutil; dùng làm đường tương thích cho .doc cũ.
        """

        with tempfile.TemporaryDirectory() as thu_muc:
            thu_muc = Path(
                thu_muc
            )

            tep_nguon = (
                thu_muc
                / ten_tep
            )

            tep_nguon.write_bytes(
                du_lieu
            )

            ket_qua = subprocess.run(
                [
                    "/usr/bin/textutil",
                    "-convert",
                    "txt",
                    "-stdout",
                    str(
                        tep_nguon
                    ),
                ],
                capture_output=True,
                check=False,
            )

            if ket_qua.returncode != 0:
                raise ValueError(
                    "Could not read legacy .doc file."
                )

            return ket_qua.stdout.decode(
                "utf-8",
                errors="replace",
            )

    @staticmethod
    def _doc_excel_moi(
        du_lieu: bytes,
    ) -> str:
        workbook = load_workbook(
            BytesIO(
                du_lieu
            ),
            data_only=True,
            read_only=True,
        )

        dong = []

        try:
            for sheet in workbook.worksheets:
                dong.append(
                    f"[SHEET: {sheet.title}]"
                )

                for hang in sheet.iter_rows(
                    values_only=True
                ):
                    gia_tri = [
                        ""
                        if value is None
                        else str(
                            value
                        )
                        for value in hang
                    ]

                    if any(
                        value.strip()
                        for value in gia_tri
                    ):
                        dong.append(
                            " | ".join(
                                gia_tri
                            )
                        )
        finally:
            workbook.close()

        return "\n".join(
            dong
        )

    @staticmethod
    def _doc_excel_cu(
        du_lieu: bytes,
    ) -> str:
        sheets = pd.read_excel(
            BytesIO(
                du_lieu
            ),
            sheet_name=None,
            header=None,
            dtype=object,
        )

        dong = []

        for ten_sheet, dataframe in sheets.items():
            dong.append(
                f"[SHEET: {ten_sheet}]"
            )

            dataframe = dataframe.fillna(
                ""
            )

            for _, hang in dataframe.iterrows():
                gia_tri = [
                    str(
                        value
                    )
                    for value in hang.tolist()
                ]

                if any(
                    value.strip()
                    for value in gia_tri
                ):
                    dong.append(
                        " | ".join(
                            gia_tri
                        )
                    )

        return "\n".join(
            dong
        )

    @staticmethod
    def _doc_csv_tsv(
        du_lieu: bytes,
        duoi_tep: str,
    ) -> str:
        noi_dung = du_lieu.decode(
            "utf-8-sig",
            errors="replace",
        )

        delimiter = (
            "\t"
            if duoi_tep == ".tsv"
            else ","
        )

        reader = csv.reader(
            noi_dung.splitlines(),
            delimiter=delimiter,
        )

        return "\n".join(
            " | ".join(
                hang
            )
            for hang in reader
        )

    @staticmethod
    def _doc_pptx(
        du_lieu: bytes,
    ) -> str:
        presentation = Presentation(
            BytesIO(
                du_lieu
            )
        )

        dong = []

        for slide_index, slide in enumerate(
            presentation.slides,
            start=1,
        ):
            dong.append(
                f"[SLIDE: {slide_index}]"
            )

            for shape in slide.shapes:
                if not hasattr(
                    shape,
                    "text",
                ):
                    continue

                noi_dung = (
                    shape.text
                    or ""
                ).strip()

                if noi_dung:
                    dong.append(
                        noi_dung
                    )

        return "\n".join(
            dong
        )

    @staticmethod
    def _doc_rtf(
        du_lieu: bytes,
    ) -> str:
        # Import trễ để ứng dụng vẫn khởi động nếu môi trường chưa cài striprtf.
        try:
            from striprtf.striprtf import rtf_to_text
        except ImportError as exc:
            raise RuntimeError(
                "RTF support requires the striprtf package."
            ) from exc

        noi_dung = du_lieu.decode(
            "utf-8",
            errors="replace",
        )

        return rtf_to_text(
            noi_dung
        )

    @staticmethod
    def _doc_text(
        du_lieu: bytes,
    ) -> str:
        for encoding in [
            "utf-8-sig",
            "utf-8",
            "cp1252",
            "latin-1",
        ]:
            try:
                return du_lieu.decode(
                    encoding
                )
            except UnicodeDecodeError:
                continue

        return du_lieu.decode(
            "utf-8",
            errors="replace",
        )
