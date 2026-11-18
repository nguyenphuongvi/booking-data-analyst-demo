"""
Export Documentation Intelligence
=================================

Kiến trúc xử lý:
1. Đọc tệp / text extraction.
2. Chọn engine tự động theo loại chứng từ.
3. Packing List dùng rules; Booking Confirmation/DG dùng AI + validation.
4. Human review.
5. Lưu trữ Shipment / Documents / Events / Deadlines / Field History.
6. Analytics cho quy trình chứng từ xuất khẩu.

Giao diện hiển thị bằng tiếng Anh.
Comment và lớp điều phối mới dùng tiếng Việt để thuận tiện bảo trì.
"""

from pathlib import Path
from datetime import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from cloud_demo import (make_demo_workbook, render_data_analytics, safe_upload_filename)
import zipfile

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from core.document_analyzer import DocumentAnalyzer
from core.doc_tep import BoDocTep
from core.dieu_phoi_chung_tu import BoDieuPhoiXuLyChungTu
from core.tracking import TrackingService
from core.process_repository import ProcessRepository


# ==========================================================
# CẤU HÌNH TRANG
# ==========================================================

st.set_page_config(
    page_title="Export Documentation Intelligence",
    page_icon="🚢",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ==========================================================
# ĐƯỜNG DẪN
# ==========================================================

BASE_DIR = Path(__file__).resolve().parent

# This distribution is expressly for public presentation. Do not store actual
# company records here; each browser session receives an isolated workspace.
PUBLIC_DEMO_MODE = True
if PUBLIC_DEMO_MODE:
    if "public_demo_workspace" not in st.session_state:
        st.session_state.public_demo_workspace = tempfile.mkdtemp(
            prefix="booking_public_demo_"
        )
    PUBLIC_WORKSPACE = Path(st.session_state.public_demo_workspace)
    PUBLIC_STORAGE_FOLDER = PUBLIC_WORKSPACE / "booking_store"
    PUBLIC_STORAGE_FOLDER.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR = PUBLIC_WORKSPACE / "uploads"
    DATA_DIR = PUBLIC_WORKSPACE / "data"
    # Never submit visitor documents to third-party AI from a public demo.
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("OPENAI_API_KEY", None)
else:
    PUBLIC_STORAGE_FOLDER = None
    UPLOAD_DIR = BASE_DIR / "uploads"
    DATA_DIR = BASE_DIR / "data"

TRACKING_DB = (
    DATA_DIR
    / "tracking.db"
)

STORAGE_SETTINGS_FILE = (
    DATA_DIR
    / "storage_settings.json"
)

UPLOAD_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# Tự động đọc cấu hình cục bộ. File .env đã được .gitignore bảo vệ.
# Khi deploy, có thể dùng environment variables / platform secrets thay thế.
if not PUBLIC_DEMO_MODE:
    load_dotenv(BASE_DIR / ".env", override=False)

# Khi deploy Streamlit, cho phép cấu hình bằng st.secrets thay vì file .env.
# Không ghi secret ra giao diện hay log.
try:
    if not PUBLIC_DEMO_MODE and not os.getenv(
        "GEMINI_API_KEY",
        "",
    ).strip():
        secret_key = str(
            st.secrets.get(
                "GEMINI_API_KEY",
                "",
            )
            or ""
        ).strip()

        if secret_key:
            os.environ[
                "GEMINI_API_KEY"
            ] = secret_key

    if not os.getenv(
        "GEMINI_MODEL",
        "",
    ).strip():
        secret_model = str(
            st.secrets.get(
                "GEMINI_MODEL",
                "",
            )
            or ""
        ).strip()

        if secret_model:
            os.environ[
                "GEMINI_MODEL"
            ] = secret_model
except Exception:
    # Local development không bắt buộc phải có Streamlit secrets.
    pass


if PUBLIC_DEMO_MODE:
    st.info("🚢 Original booking-management app • Public presentation mode • Data is synthetic and temporary per browser session.")

# ==========================================================
# DỊCH VỤ
# ==========================================================

# Bộ dịch vụ nghiệp vụ.
# Tên nội bộ ưu tiên tiếng Việt để thuận tiện kiểm tra và bảo trì.
bo_doc_tep = BoDocTep()
bo_phan_tich_packing = DocumentAnalyzer()
bo_dieu_phoi_chung_tu = BoDieuPhoiXuLyChungTu()

tracker = TrackingService(
    TRACKING_DB
)

process_repo = ProcessRepository(
    TRACKING_DB
)


# ==========================================================
# HÀM HỖ TRỢ
# ==========================================================

def normalize_compare_value(value):
    """
    Normalize values only for comparison.

    Example:
    ABC COMPANY
    abc   company

    -> considered identical.
    """

    if value is None:
        return ""

    return " ".join(
        str(value)
        .strip()
        .upper()
        .split()
    )


def merge_booking_data(results):
    """
    Merge data from multiple Packing Lists.

    Common fields:
        If every Packing List contains the same value,
        show it once under Booking Information.

    Container fields:
        Always keep separately for each container.
    """

    if not results:
        return {}, []

    # ------------------------------------------
    # Fields that MAY become common
    # ------------------------------------------

    common_fields = [
        "date_of_booking",
        "shipper",
        "consignee",
        "notify",
        "product",
    ]

    # ------------------------------------------
    # Fields that ALWAYS stay per container
    # ------------------------------------------

    container_fields = [
        "total_pallet",
        "packing_details",
        "quantity",
        "marking",
    ]

    common_data = {}
    different_common_fields = []

    # ------------------------------------------
    # Detect common values
    # ------------------------------------------

    for field in common_fields:

        values = []

        for row in results:

            value = row.get(
                field,
                "",
            )

            normalized = normalize_compare_value(
                value
            )

            if normalized:
                values.append(
                    normalized
                )

        unique_values = set(values)

        # Must exist in every PL AND be identical
        if (
            len(unique_values) == 1
            and len(values) == len(results)
        ):

            for row in results:

                original_value = row.get(
                    field,
                    "",
                )

                if str(
                    original_value
                ).strip():

                    common_data[field] = (
                        original_value
                    )

                    break

        else:

            different_common_fields.append(
                field
            )

    # ------------------------------------------
    # Build container rows
    # ------------------------------------------

    container_rows = []

    for row in results:

        container_row = {
            "Container":
                row.get(
                    "container_no",
                    "",
                ),

            "Source File":
                row.get(
                    "source_file",
                    "",
                ),

            "Presentation Segment Sizes":
                json.dumps(
                    row.get(
                        "presentation_segment_sizes",
                        [],
                    ),
                    ensure_ascii=False,
                ),
        }

        # Common-type fields that differ
        # between Packing Lists.
        for field in different_common_fields:

            container_row[field] = (
                row.get(
                    field,
                    "",
                )
            )

        # Always container-specific.
        for field in container_fields:

            container_row[field] = (
                row.get(
                    field,
                    "",
                )
            )

        container_rows.append(
            container_row
        )

    return common_data, container_rows



BOOKING_CONFIRMATION_FIELD_MAP = {
    "confirmation_revision": "BC Revision",
    "confirmation_date": "BC Confirmation Date",
    "carrier_booking_no": "Carrier Booking No",
    "application_no": "Application No",
    "vessel_voyage": "Vessel / Voyage",
    "carrier": "Carrier",
    "on_behalf_of": "On Behalf Of",
    "port_of_receipt": "Port of Receipt",
    "port_of_loading": "Port of Loading",
    "pol_terminal": "POL Terminal",
    "cy_cutoff": "CY Cut-off",
    "vgm_cutoff": "VGM Cut-off",
    "si_cutoff": "SI Cut-off",
    "documentation_cutoff": "Documentation Cut-off",
    "pol_eta": "POL ETA",
    "etd": "ETD",
    "port_of_discharge": "Port of Discharge",
    "final_destination": "Final Destination",
    "eta": "ETA",
    "shipper": "BC Shipper",
    "service_type_mode": "Service Type / Mode",
    "stuffing_place": "Stuffing Place",
    "commodity": "BC Commodity",
    "qty_type": "BC QTY / Type",
    "empty_pick_up_at": "Empty Pick Up At",
    "inland_return_to": "Inland Return To",
    "service_contract": "Service Contract",
    "payment_term": "Payment Term",
    "other_deadlines": "Other Deadlines",
}

BOOKING_CONFIRMATION_FIELDS = list(
    BOOKING_CONFIRMATION_FIELD_MAP.values()
) + [
    "Booking Confirmation File",
]

DEADLINE_FIELDS = [
    "CY Cut-off",
    "VGM Cut-off",
    "SI Cut-off",
    "Documentation Cut-off",
    "POL ETA",
    "ETD",
    "ETA",
    "Other Deadlines",
]

AUDIT_FIELDS = [
    "Date of Booking",
    "Shipper",
    "Consignee",
    "Notify",
    "Product",
    "Total Pallet",
    "Packing Details",
    "Quantity",
    "Marking",
    "Source File",
    "Cargo Type",
    "DG Information File",
    "DG B/L Text",
] + BOOKING_CONFIRMATION_FIELDS

COMMON_AUDIT_FIELDS = {
    "Date of Booking",
    "Shipper",
    "Consignee",
    "Notify",
    "Product",
    "Cargo Type",
    "DG Information File",
    "DG B/L Text",
    *BOOKING_CONFIRMATION_FIELDS,
}


def ensure_text_columns(
    dataframe,
    columns,
):
    """
    Return a copy whose requested columns can safely store text.

    Pandas may infer an all-blank Excel column as float64 (NaN). Assigning
    a Booking No. such as "235600650088" into that float column raises:
        TypeError: Invalid value ... for dtype 'float64'

    Booking/document fields are text by business meaning, even when they
    contain only digits, so they must stay object/string-safe.
    """

    if dataframe is None:
        return dataframe

    result = dataframe.copy()

    for column in columns:

        if column not in result.columns:

            result[
                column
            ] = pd.Series(
                "",
                index=result.index,
                dtype="object",
            )

        else:

            # object preserves exact textual identifiers and also accepts
            # existing numbers / NaN without coercing Booking No. to float.
            result[
                column
            ] = result[
                column
            ].astype(
                "object"
            )

    return result


def clean_data_value(value):
    """Return a safe string value for comparison and Excel."""

    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    return str(value).strip()



def sync_process_model_from_booking_df(
    booking_df,
):
    """
    Keep the process-oriented SQLite model synchronized with the
    normalized booking workbook.

    Safe to run repeatedly.
    """

    if (
        booking_df is None
        or booking_df.empty
    ):
        return

    records = []

    for _, row in booking_df.iterrows():

        records.append(
            {
                str(column):
                    clean_data_value(
                        value
                    )
                for column, value
                in row.to_dict().items()
            }
        )

    process_repo.sync_from_booking_records(
        records
    )



def file_excel_hop_le(
    excel_file,
):
    """
    Kiểm tra nhanh cấu trúc .xlsx trước khi openpyxl/pandas mở file.

    .xlsx thực chất là ZIP và bắt buộc phải có [Content_Types].xml
    cùng xl/workbook.xml.
    """
    excel_file = Path(
        excel_file
    )

    if (
        not excel_file.exists()
        or not excel_file.is_file()
        or excel_file.stat().st_size == 0
    ):
        return False

    try:
        if not zipfile.is_zipfile(
            excel_file
        ):
            return False

        with zipfile.ZipFile(
            excel_file,
            "r",
        ) as archive:

            names = set(
                archive.namelist()
            )

            return (
                "[Content_Types].xml"
                in names
                and "xl/workbook.xml"
                in names
            )

    except Exception:
        return False


def sao_luu_file_excel_loi(
    excel_file,
):
    """
    Không xóa file Excel lỗi.

    Đổi tên file lỗi thành bản backup để:
    - không mất dữ liệu cũ nếu còn khả năng phục hồi;
    - app có thể tạo booking_data.xlsx mới sạch.
    """
    excel_file = Path(
        excel_file
    )

    if not excel_file.exists():
        return None

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    backup_file = excel_file.with_name(
        f"{excel_file.stem}_corrupted_{timestamp}"
        f"{excel_file.suffix}"
    )

    counter = 1

    while backup_file.exists():
        backup_file = excel_file.with_name(
            f"{excel_file.stem}_corrupted_{timestamp}_{counter}"
            f"{excel_file.suffix}"
        )
        counter += 1

    excel_file.replace(
        backup_file
    )

    return backup_file


def chuan_bi_file_excel_truoc_khi_ghi(
    excel_file,
):
    """
    Nếu booking_data.xlsx đang tồn tại nhưng không còn là workbook hợp lệ,
    giữ lại một bản backup và để luồng ghi tạo file mới.
    """
    excel_file = Path(
        excel_file
    )

    if not excel_file.exists():
        return None

    if file_excel_hop_le(
        excel_file
    ):
        return None

    return sao_luu_file_excel_loi(
        excel_file
    )


def luu_workbook_an_toan(
    workbook,
    excel_file,
):
    """
    Ghi workbook theo kiểu atomic save.

    Không ghi trực tiếp đè booking_data.xlsx vì nếu openpyxl lỗi giữa chừng,
    file gốc có thể bị biến thành ZIP không hoàn chỉnh và thiếu
    [Content_Types].xml.

    Quy trình:
    1. Save sang file tạm cùng thư mục.
    2. Kiểm tra file tạm là .xlsx hợp lệ.
    3. Chỉ khi hợp lệ mới replace file chính.
    """
    excel_file = Path(
        excel_file
    )

    excel_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_handle = tempfile.NamedTemporaryFile(
        prefix=f".{excel_file.stem}_",
        suffix=".xlsx",
        dir=excel_file.parent,
        delete=False,
    )

    temp_file = Path(
        temp_handle.name
    )

    temp_handle.close()

    try:
        workbook.save(
            temp_file
        )

        if not file_excel_hop_le(
            temp_file
        ):
            raise ValueError(
                "The generated Excel workbook is incomplete."
            )

        os.replace(
            temp_file,
            excel_file,
        )

    finally:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass


def build_process_excel_sheets(
    excel_file,
):
    """
    Export process-model tables into visible Excel sheets for review
    and internship analysis.
    """

    excel_file = Path(
        excel_file
    )

    if not excel_file.exists():
        return

    process_repo.sync_legacy_events()

    workbook = load_workbook(
        excel_file
    )

    sheet_specs = [
        (
            "Process Documents",
            [
                "ID",
                "Booking ID",
                "Document Type",
                "File Name",
                "Status",
                "Received At",
                "Processed At",
                "Revision",
                "Source",
                "Notes",
            ],
            [
                [
                    row.get("id", ""),
                    row.get("booking_id", ""),
                    row.get("document_type", ""),
                    row.get("file_name", ""),
                    row.get("document_status", ""),
                    row.get("received_at", ""),
                    row.get("processed_at", ""),
                    row.get("revision", ""),
                    row.get("source", ""),
                    row.get("notes", ""),
                ]
                for row in process_repo.get_documents()
            ],
        ),
        (
            "Process Deadlines",
            [
                "ID",
                "Booking ID",
                "Deadline Type",
                "Raw Value",
                "Source Document",
                "Updated At",
            ],
            [
                [
                    row.get("id", ""),
                    row.get("booking_id", ""),
                    row.get("deadline_type", ""),
                    row.get("raw_value", ""),
                    row.get("source_document", ""),
                    row.get("updated_at", ""),
                ]
                for row in process_repo.get_deadlines()
            ],
        ),
    ]

    header_fill = PatternFill(
        "solid",
        fgColor="E8F2FF",
    )

    border_side = Side(
        style="thin",
        color="D0D7DE",
    )

    cell_border = Border(
        left=border_side,
        right=border_side,
        top=border_side,
        bottom=border_side,
    )

    for sheet_name, headers, rows in sheet_specs:

        if sheet_name in workbook.sheetnames:
            workbook.remove(
                workbook[
                    sheet_name
                ]
            )

        sheet = workbook.create_sheet(
            sheet_name
        )

        for column_index, header in enumerate(
            headers,
            start=1,
        ):
            cell = sheet.cell(
                row=1,
                column=column_index,
                value=header,
            )
            cell.font = Font(
                bold=True
            )
            cell.fill = header_fill
            cell.alignment = Alignment(
                horizontal="center",
                vertical="center",
                wrap_text=True,
            )
            cell.border = cell_border

        for row_index, values in enumerate(
            rows,
            start=2,
        ):
            for column_index, value in enumerate(
                values,
                start=1,
            ):
                cell = sheet.cell(
                    row=row_index,
                    column=column_index,
                    value=value,
                )
                cell.alignment = Alignment(
                    vertical="top",
                    wrap_text=True,
                )
                cell.border = cell_border

        sheet.freeze_panes = "A2"

        if sheet.max_row >= 1:
            sheet.auto_filter.ref = (
                sheet.dimensions
            )

        for column_cells in sheet.columns:
            letter = column_cells[0].column_letter
            max_length = max(
                len(
                    str(
                        cell.value
                        if cell.value is not None
                        else ""
                    )
                )
                for cell in column_cells
            )
            sheet.column_dimensions[
                letter
            ].width = min(
                max(
                    max_length + 2,
                    12,
                ),
                55,
            )

    luu_workbook_an_toan(
        workbook,
        excel_file,
    )

    workbook.close()


def normalize_audit_value(value):
    """Normalize only insignificant whitespace for change detection."""

    value = clean_data_value(value)

    value = value.replace(
        "\r\n",
        "\n",
    ).replace(
        "\r",
        "\n",
    )

    lines = [
        line.strip()
        for line in value.split("\n")
    ]

    return "\n".join(lines).strip()


def audit_values_equal(left, right):
    return (
        normalize_audit_value(left)
        == normalize_audit_value(right)
    )


def normalize_container_key(value):
    value = clean_data_value(value)

    if not value:
        return ""

    try:
        number = float(value)

        if number.is_integer():
            return str(int(number))

    except Exception:
        pass

    return value


def find_old_container_row(
    old_booking_df,
    container_value,
):
    """Find the previous row for one booking container."""

    if old_booking_df.empty:
        return None

    if "Container" not in old_booking_df.columns:
        return None

    target_key = normalize_container_key(
        container_value
    )

    for _, old_row in old_booking_df.iterrows():

        old_key = normalize_container_key(
            old_row.get(
                "Container",
                "",
            )
        )

        if old_key == target_key:
            return old_row

    return None


def compress_common_audit_changes(
    changes,
    expected_container_count,
):
    """
    If a booking-level field changed identically for every container,
    store one booking-level history record instead of duplicates.
    """

    if not changes:
        return []

    output = []
    consumed = set()

    for index, change in enumerate(changes):

        if index in consumed:
            continue

        field_name = change[
            "field_name"
        ]

        if field_name not in COMMON_AUDIT_FIELDS:
            output.append(change)
            continue

        matching = []

        for other_index, other in enumerate(changes):

            if other_index in consumed:
                continue

            if (
                other["field_name"] == field_name
                and other["change_type"]
                == change["change_type"]
                and audit_values_equal(
                    other["old_value"],
                    change["old_value"],
                )
                and audit_values_equal(
                    other["new_value"],
                    change["new_value"],
                )
            ):
                matching.append(
                    (
                        other_index,
                        other,
                    )
                )

        container_keys = {
            normalize_container_key(
                item[1]["container_no"]
            )
            for item in matching
            if normalize_container_key(
                item[1]["container_no"]
            )
        }

        if (
            expected_container_count > 0
            and len(container_keys)
            == expected_container_count
        ):

            booking_level_change = dict(
                change
            )

            booking_level_change[
                "container_no"
            ] = None

            output.append(
                booking_level_change
            )

            for other_index, _ in matching:
                consumed.add(
                    other_index
                )

        else:
            output.append(change)
            consumed.add(index)

    return output


def build_export_dataframe(
    booking_id,
    edited_common,
    edited_container_df,
    old_df,
    now_text,
    cargo_type="NON DG",
    dg_information_file="",
    dg_bl_text="",
):
    """
    Build the rows that will replace this booking in Excel.

    Created At is preserved forever.
    Last Updated changes only when actual data changes.
    The returned audit_changes are written to SQLite only after
    the Excel save succeeds.
    """

    old_booking_df = pd.DataFrame()

    if (
        not old_df.empty
        and "Booking ID" in old_df.columns
    ):
        old_booking_df = old_df[
            old_df["Booking ID"]
            .astype(str)
            == str(booking_id)
        ].copy()

    export_rows = []
    audit_changes = []

    for _, container_row in (
        edited_container_df.iterrows()
    ):

        container_value = (
            container_row.get(
                "Container",
                "",
            )
        )

        row_values = {
            "Booking ID": booking_id,

            "Container":
                container_value,

            "Date of Booking":
                edited_common.get(
                    "date_of_booking",
                    container_row.get(
                        "Date of Booking",
                        "",
                    ),
                ),

            "Shipper":
                edited_common.get(
                    "shipper",
                    container_row.get(
                        "Shipper",
                        "",
                    ),
                ),

            "Consignee":
                edited_common.get(
                    "consignee",
                    container_row.get(
                        "Consignee",
                        "",
                    ),
                ),

            "Notify":
                edited_common.get(
                    "notify",
                    container_row.get(
                        "Notify",
                        "",
                    ),
                ),

            "Product":
                edited_common.get(
                    "product",
                    container_row.get(
                        "Product",
                        "",
                    ),
                ),

            "Total Pallet":
                container_row.get(
                    "Total Pallet",
                    "",
                ),

            "Packing Details":
                container_row.get(
                    "Packing Details",
                    "",
                ),

            "Quantity":
                container_row.get(
                    "Quantity",
                    "",
                ),

            "Marking":
                container_row.get(
                    "Marking",
                    "",
                ),

            "Source File":
                container_row.get(
                    "Source File",
                    "",
                ),

            "Presentation Segment Sizes":
                container_row.get(
                    "Presentation Segment Sizes",
                    "[]",
                ),

            "Cargo Type":
                clean_data_value(
                    cargo_type
                ).upper()
                or "NON DG",

            "DG Information File":
                clean_data_value(
                    dg_information_file
                ),

            "DG B/L Text":
                clean_data_value(
                    dg_bl_text
                ),
        }

        for key in list(
            row_values.keys()
        ):
            if key not in {
                "Booking ID",
                "Container",
            }:
                row_values[key] = (
                    clean_data_value(
                        row_values[key]
                    )
                )

        old_row = find_old_container_row(
            old_booking_df,
            container_value,
        )

        # Packing List export must never erase Booking Confirmation data
        # already attached to this booking.
        if old_row is not None:

            for field_name in BOOKING_CONFIRMATION_FIELDS:

                row_values[
                    field_name
                ] = clean_data_value(
                    old_row.get(
                        field_name,
                        "",
                    )
                )

        row_has_changes = False

        if old_row is None:

            created_at = now_text
            last_updated = now_text

            for field_name in AUDIT_FIELDS:

                new_value = row_values.get(
                    field_name,
                    "",
                )

                # Blank fields have no entered information yet,
                # so there is nothing useful to timestamp.
                if not normalize_audit_value(
                    new_value
                ):
                    continue

                audit_changes.append(
                    {
                        "booking_id": booking_id,
                        "container_no": container_value,
                        "field_name": field_name,
                        "old_value": "",
                        "new_value": new_value,
                        "change_type": "INITIAL",
                    }
                )

        else:

            created_at = clean_data_value(
                old_row.get(
                    "Created At",
                    "",
                )
            ) or now_text

            previous_last_updated = (
                clean_data_value(
                    old_row.get(
                        "Last Updated",
                        "",
                    )
                )
                or created_at
            )

            for field_name in AUDIT_FIELDS:

                old_value = clean_data_value(
                    old_row.get(
                        field_name,
                        "",
                    )
                )

                new_value = row_values.get(
                    field_name,
                    "",
                )

                if audit_values_equal(
                    old_value,
                    new_value,
                ):
                    continue

                row_has_changes = True

                audit_changes.append(
                    {
                        "booking_id": booking_id,
                        "container_no": container_value,
                        "field_name": field_name,
                        "old_value": old_value,
                        "new_value": new_value,
                        "change_type": "UPDATE",
                    }
                )

            if row_has_changes:
                last_updated = now_text
            else:
                last_updated = (
                    previous_last_updated
                )

        row_values[
            "Created At"
        ] = created_at

        row_values[
            "Last Updated"
        ] = last_updated

        export_rows.append(
            row_values
        )

    audit_changes = (
        compress_common_audit_changes(
            audit_changes,
            len(export_rows),
        )
    )

    return (
        pd.DataFrame(export_rows),
        audit_changes,
        old_booking_df,
    )


def build_booking_detail_sheet(
    excel_file,
    booking_df,
):
    """
    Build a vertical, human-readable view in the same workbook.
    Sheet name: Booking Detail
    """

    excel_file = Path(
        excel_file
    )

    workbook = load_workbook(
        excel_file
    )

    if "Booking Detail" in workbook.sheetnames:
        old_sheet = workbook[
            "Booking Detail"
        ]
        workbook.remove(
            old_sheet
        )

    worksheet = workbook.create_sheet(
        "Booking Detail"
    )

    dark_fill = PatternFill(
        "solid",
        fgColor="1F4E78",
    )

    section_fill = PatternFill(
        "solid",
        fgColor="D9EAF7",
    )

    label_fill = PatternFill(
        "solid",
        fgColor="F3F6F9",
    )

    thin_gray = Side(
        style="thin",
        color="D9E1F2",
    )

    value_border = Border(
        bottom=thin_gray,
    )

    worksheet.column_dimensions[
        "A"
    ].width = 24

    for column in [
        "B",
        "C",
        "D",
        "E",
    ]:
        worksheet.column_dimensions[
            column
        ].width = 22

    worksheet.merge_cells(
        "A1:E1"
    )

    title_cell = worksheet[
        "A1"
    ]

    title_cell.value = (
        "BOOKING DETAIL"
    )

    title_cell.font = Font(
        bold=True,
        color="FFFFFF",
        size=16,
    )

    title_cell.fill = dark_fill

    title_cell.alignment = Alignment(
        horizontal="center",
        vertical="center",
    )

    worksheet.row_dimensions[
        1
    ].height = 28

    current_row = 3

    if booking_df.empty:
        worksheet[
            "A3"
        ] = "No booking data."

        luu_workbook_an_toan(
            workbook,
            excel_file,
        )

        workbook.close()
        return

    booking_df = booking_df.copy()

    for booking_id, booking_rows in (
        booking_df.groupby(
            "Booking ID",
            sort=False,
            dropna=False,
        )
    ):

        booking_rows = (
            booking_rows.reset_index(
                drop=True
            )
        )

        worksheet.merge_cells(
            start_row=current_row,
            start_column=1,
            end_row=current_row,
            end_column=5,
        )

        header_cell = worksheet.cell(
            row=current_row,
            column=1,
        )

        header_cell.value = (
            f"BOOKING ID: "
            f"{clean_data_value(booking_id)}"
        )

        header_cell.font = Font(
            bold=True,
            color="FFFFFF",
            size=12,
        )

        header_cell.fill = dark_fill

        header_cell.alignment = Alignment(
            vertical="center",
        )

        current_row += 1

        created_values = [
            clean_data_value(value)
            for value in booking_rows.get(
                "Created At",
                pd.Series(dtype=str),
            ).tolist()
            if clean_data_value(value)
        ]

        updated_values = [
            clean_data_value(value)
            for value in booking_rows.get(
                "Last Updated",
                pd.Series(dtype=str),
            ).tolist()
            if clean_data_value(value)
        ]

        summary_rows = [
            (
                "Created At",
                created_values[0]
                if created_values
                else "",
            ),
            (
                "Last Updated",
                max(updated_values)
                if updated_values
                else "",
            ),
        ]

        common_fields = [
            "Date of Booking",
            "Shipper",
            "Consignee",
            "Notify",
            "Product",
        ]

        common_field_status = {}

        for field_name in common_fields:

            values = [
                clean_data_value(value)
                for value in booking_rows.get(
                    field_name,
                    pd.Series(
                        [""] * len(booking_rows)
                    ),
                ).tolist()
            ]

            normalized_values = {
                normalize_audit_value(value)
                for value in values
            }

            is_common = (
                len(normalized_values) == 1
            )

            common_field_status[
                field_name
            ] = is_common

            if is_common:
                summary_rows.append(
                    (
                        field_name,
                        values[0]
                        if values
                        else "",
                    )
                )

        for label, value in summary_rows:

            worksheet.cell(
                row=current_row,
                column=1,
                value=label,
            )

            label_cell = worksheet.cell(
                row=current_row,
                column=1,
            )

            label_cell.font = Font(
                bold=True
            )

            label_cell.fill = label_fill

            label_cell.alignment = Alignment(
                vertical="top",
            )

            worksheet.merge_cells(
                start_row=current_row,
                start_column=2,
                end_row=current_row,
                end_column=5,
            )

            value_cell = worksheet.cell(
                row=current_row,
                column=2,
                value=value,
            )

            value_cell.alignment = Alignment(
                vertical="top",
                wrap_text=True,
            )

            value_cell.border = value_border

            estimated_lines = max(
                1,
                str(value).count("\n") + 1,
                (len(str(value)) // 85) + 1,
            )

            worksheet.row_dimensions[
                current_row
            ].height = min(
                18 * estimated_lines,
                120,
            )

            current_row += 1

        current_row += 1

        for _, container_row in (
            booking_rows.iterrows()
        ):

            container_value = clean_data_value(
                container_row.get(
                    "Container",
                    "",
                )
            )

            worksheet.merge_cells(
                start_row=current_row,
                start_column=1,
                end_row=current_row,
                end_column=5,
            )

            container_header = worksheet.cell(
                row=current_row,
                column=1,
                value=(
                    f"CONTAINER {container_value}"
                ),
            )

            container_header.font = Font(
                bold=True,
                color="1F1F1F",
            )

            container_header.fill = section_fill

            current_row += 1

            container_fields = []

            for field_name in common_fields:
                if not common_field_status.get(
                    field_name,
                    False,
                ):
                    container_fields.append(
                        field_name
                    )

            container_fields.extend(
                [
                    "Source File",
                    "Total Pallet",
                    "Packing Details",
                    "Quantity",
                    "Marking",
                ]
            )

            for field_name in container_fields:

                value = clean_data_value(
                    container_row.get(
                        field_name,
                        "",
                    )
                )

                worksheet.cell(
                    row=current_row,
                    column=1,
                    value=field_name,
                )

                label_cell = worksheet.cell(
                    row=current_row,
                    column=1,
                )

                label_cell.font = Font(
                    bold=True
                )

                label_cell.fill = label_fill

                label_cell.alignment = Alignment(
                    vertical="top",
                )

                worksheet.merge_cells(
                    start_row=current_row,
                    start_column=2,
                    end_row=current_row,
                    end_column=5,
                )

                value_cell = worksheet.cell(
                    row=current_row,
                    column=2,
                    value=value,
                )

                value_cell.alignment = Alignment(
                    vertical="top",
                    wrap_text=True,
                )

                value_cell.border = value_border

                estimated_lines = max(
                    1,
                    value.count("\n") + 1,
                    (len(value) // 85) + 1,
                )

                worksheet.row_dimensions[
                    current_row
                ].height = min(
                    18 * estimated_lines,
                    140,
                )

                current_row += 1

            current_row += 1

        current_row += 1

    worksheet.freeze_panes = (
        "A2"
    )

    luu_workbook_an_toan(
        workbook,
        excel_file,
    )

    workbook.close()



def build_extracted_data_sheet(
    excel_file,
    booking_df,
    sheet_name="Extracted Data",
    sheet_position=0,
    make_active=True,
):
    """
    Presentation sheet.

    - 1 physical file = 1 container.
    - Repeated PACKING LIST pages remain inside that same container.
    - Total Pallet / Packing Details are line-by-line.
    - Product / Quantity are separated by original PACKING LIST page.
    - Shared container fields stay merged vertically.
    """

    excel_file = Path(
        excel_file
    )

    workbook = load_workbook(
        excel_file
    )

    if sheet_name in workbook.sheetnames:
        old_sheet = workbook[
            sheet_name
        ]
        workbook.remove(
            old_sheet
        )

    worksheet = workbook.create_sheet(
        sheet_name,
        sheet_position,
    )

    headers = [
        "Booking ID",
        "Container",
        "Date of Booking",
        "Shipper",
        "Consignee",
        "Notify",
        "Product",
        "Total Pallet",
        "Packing Details",
        "Quantity",
        "Marking",
        "Source File",
        "Created At",
        "Last Updated",
    ]

    header_fill = PatternFill(
        "solid",
        fgColor="E7E6E6",
    )

    border_side = Side(
        style="thin",
        color="BFBFBF",
    )

    cell_border = Border(
        left=border_side,
        right=border_side,
        top=border_side,
        bottom=border_side,
    )

    for column_index, header in enumerate(
        headers,
        start=1,
    ):

        cell = worksheet.cell(
            row=1,
            column=column_index,
            value=header,
        )

        cell.font = Font(
            bold=True
        )

        cell.fill = header_fill

        cell.alignment = Alignment(
            horizontal="center",
            vertical="center",
            wrap_text=True,
        )

        cell.border = cell_border

    worksheet.freeze_panes = "A2"

    widths = {
        "A": 24,
        "B": 12,
        "C": 18,
        "D": 34,
        "E": 34,
        "F": 28,
        "G": 32,
        "H": 18,
        "I": 48,
        "J": 34,
        "K": 30,
        "L": 42,
        "M": 20,
        "N": 20,
    }

    for column, width in widths.items():

        worksheet.column_dimensions[
            column
        ].width = width

    if booking_df.empty:

        workbook.active = (
            workbook.sheetnames.index(
                sheet_name
            )
        )

        luu_workbook_an_toan(
            workbook,
            excel_file,
        )

        workbook.close()
        return

    def parse_segment_sizes(
        raw_value,
        group_count,
    ):
        try:
            values = json.loads(
                clean_data_value(
                    raw_value
                )
                or "[]"
            )
        except Exception:
            values = []

        sizes = []

        for value in values:

            try:
                value = int(
                    value
                )
            except Exception:
                continue

            if value > 0:
                sizes.append(
                    value
                )

        if (
            sizes
            and sum(
                sizes
            )
            == group_count
        ):
            return sizes

        # Old bookings have no page metadata.
        # Fall back to one visible row per group.
        return [
            1
            for _ in range(
                group_count
            )
        ]

    def split_product_pages(
        raw_value,
        page_count,
    ):
        lines = [
            line.strip()
            for line in clean_data_value(
                raw_value
            ).splitlines()
            if line.strip()
        ]

        if page_count <= 0:
            return []

        if len(lines) == page_count:
            return lines

        if len(lines) == 1:
            return (
                lines
                * page_count
            )

        if not lines:
            return [
                ""
                for _ in range(
                    page_count
                )
            ]

        output = []

        for page_index in range(
            page_count
        ):

            if page_index < len(
                lines
            ):
                output.append(
                    lines[
                        page_index
                    ]
                )
            else:
                output.append(
                    lines[-1]
                )

        return output

    def split_quantity_pages(
        raw_value,
        page_count,
    ):
        lines = [
            line.strip()
            for line in clean_data_value(
                raw_value
            ).splitlines()
            if line.strip()
        ]

        if page_count <= 0:
            return []

        if not lines:
            return [
                ""
                for _ in range(
                    page_count
                )
            ]

        # One-page containers must preserve the complete text exactly.
        if page_count == 1:
            return [
                "\n".join(
                    lines
                )
            ]

        blocks = []
        current = []

        primary_quantity_start = re.compile(
            r"^(?:"
            r"(?:QUANTITY\s+)?TOTAL\s+NET(?:\s+WEIGHT)?"
            r"|NET\s+WEIGHT"
            r"|N\.?\s*W\.?"
            r"|NW"
            r"|TOTAL\s+(?:QTY|QUANTITY)"
            r"|QTY"
            r"|QUANTITY"
            r")\b",
            re.IGNORECASE,
        )

        for line in lines:

            starts_new_block = bool(
                primary_quantity_start.match(
                    line
                )
            )

            if (
                starts_new_block
                and current
            ):
                blocks.append(
                    "\n".join(
                        current
                    )
                )
                current = []

            current.append(
                line
            )

        if current:
            blocks.append(
                "\n".join(
                    current
                )
            )

        if len(blocks) == page_count:
            return blocks

        # Never duplicate a single quantity block across every page.
        # Preserve it once, then leave missing page blocks blank.
        if len(blocks) < page_count:

            return (
                blocks
                + [
                    ""
                    for _ in range(
                        page_count
                        - len(blocks)
                    )
                ]
            )

        # More detected blocks than page spans: preserve ALL information by
        # putting the extra blocks into the final page instead of discarding
        # them.
        output = []

        for page_index in range(
            page_count
        ):

            if page_index < (
                page_count - 1
            ):

                output.append(
                    blocks[
                        page_index
                    ]
                )

            else:

                output.append(
                    "\n".join(
                        blocks[
                            page_index:
                        ]
                    )
                )

        return output

    current_row = 2

    # Track consecutive container blocks that belong to the same
    # Booking ID. After all rows are written, column A will be merged
    # across the whole booking (all of its containers/pallet rows).
    booking_merge_groups = []
    active_booking_id = None
    active_booking_start = None
    active_booking_end = None

    for _, booking_row in booking_df.iterrows():

        pallet_lines = [
            line.strip()
            for line in clean_data_value(
                booking_row.get(
                    "Total Pallet",
                    "",
                )
            ).splitlines()
            if line.strip()
        ]

        detail_lines = [
            line.strip()
            for line in clean_data_value(
                booking_row.get(
                    "Packing Details",
                    "",
                )
            ).splitlines()
            if line.strip()
        ]

        group_count = max(
            len(pallet_lines),
            len(detail_lines),
            1,
        )

        segment_sizes = parse_segment_sizes(
            booking_row.get(
                "Presentation Segment Sizes",
                "[]",
            ),
            group_count,
        )

        page_count = len(
            segment_sizes
        )

        product_pages = split_product_pages(
            booking_row.get(
                "Product",
                "",
            ),
            page_count,
        )

        quantity_pages = split_quantity_pages(
            booking_row.get(
                "Quantity",
                "",
            ),
            page_count,
        )

        start_row = current_row

        end_row = (
            start_row
            + group_count
            - 1
        )

        # Pallet / Packing Details
        for group_index in range(
            group_count
        ):

            row_number = (
                start_row
                + group_index
            )

            worksheet.cell(
                row=row_number,
                column=8,
                value=(
                    pallet_lines[
                        group_index
                    ]
                    if group_index
                    < len(
                        pallet_lines
                    )
                    else ""
                ),
            )

            worksheet.cell(
                row=row_number,
                column=9,
                value=(
                    detail_lines[
                        group_index
                    ]
                    if group_index
                    < len(
                        detail_lines
                    )
                    else ""
                ),
            )

        # Product / Quantity separated by PACKING LIST page.
        segment_start = start_row

        for page_index, segment_size in enumerate(
            segment_sizes
        ):

            segment_end = (
                segment_start
                + segment_size
                - 1
            )

            for column_index, value in [
                (
                    7,
                    product_pages[
                        page_index
                    ],
                ),
                (
                    10,
                    quantity_pages[
                        page_index
                    ],
                ),
            ]:

                if segment_size > 1:

                    worksheet.merge_cells(
                        start_row=segment_start,
                        start_column=column_index,
                        end_row=segment_end,
                        end_column=column_index,
                    )

                cell = worksheet.cell(
                    row=segment_start,
                    column=column_index,
                    value=value,
                )

                cell.alignment = Alignment(
                    vertical="center",
                    wrap_text=True,
                )

            segment_start = (
                segment_end + 1
            )

        # Booking ID is handled separately because it must span
        # ALL containers belonging to the same booking.
        booking_id_value = clean_data_value(
            booking_row.get(
                "Booking ID",
                "",
            )
        )

        booking_id_cell = worksheet.cell(
            row=start_row,
            column=1,
            value=booking_id_value,
        )

        booking_id_cell.alignment = Alignment(
            horizontal="center",
            vertical="center",
            wrap_text=True,
        )

        # Extend the current Booking ID merge block when the next
        # container belongs to the same booking and is directly below it.
        if (
            active_booking_id is not None
            and booking_id_value == active_booking_id
            and active_booking_end is not None
            and start_row == active_booking_end + 1
        ):

            active_booking_end = end_row

        else:

            if active_booking_id is not None:

                booking_merge_groups.append(
                    (
                        active_booking_id,
                        active_booking_start,
                        active_booking_end,
                    )
                )

            active_booking_id = booking_id_value
            active_booking_start = start_row
            active_booking_end = end_row

        # Shared fields for each individual container.
        # These remain separated between Container 1, Container 2, etc.
        common_columns = {
            2: "Container",
            3: "Date of Booking",
            4: "Shipper",
            5: "Consignee",
            6: "Notify",
            11: "Marking",
            12: "Source File",
            13: "Created At",
            14: "Last Updated",
        }

        for column_index, field_name in (
            common_columns.items()
        ):

            value = clean_data_value(
                booking_row.get(
                    field_name,
                    "",
                )
            )

            if group_count > 1:

                worksheet.merge_cells(
                    start_row=start_row,
                    start_column=column_index,
                    end_row=end_row,
                    end_column=column_index,
                )

            cell = worksheet.cell(
                row=start_row,
                column=column_index,
                value=value,
            )

            cell.alignment = Alignment(
                horizontal=(
                    "center"
                    if column_index
                    in {
                        1,
                        2,
                        3,
                        13,
                        14,
                    }
                    else "left"
                ),
                vertical="center",
                wrap_text=True,
            )

        for row_number in range(
            start_row,
            end_row + 1,
        ):

            worksheet.row_dimensions[
                row_number
            ].height = 44

            for column_index in range(
                1,
                len(headers) + 1,
            ):

                cell = worksheet.cell(
                    row=row_number,
                    column=column_index,
                )

                cell.border = cell_border

                if column_index in {
                    7,
                    8,
                    9,
                    10,
                }:

                    cell.alignment = Alignment(
                        vertical="center",
                        wrap_text=True,
                    )

        current_row = (
            end_row + 1
        )

    # Finalize the last Booking ID block.
    if active_booking_id is not None:

        booking_merge_groups.append(
            (
                active_booking_id,
                active_booking_start,
                active_booking_end,
            )
        )

    # Merge column A across every consecutive row that belongs to the
    # same booking. Example:
    #
    # Booking BK-001
    #   Container 1 -> rows 2-3
    #   Container 2 -> rows 4-6
    #
    # becomes one merged Booking ID cell: A2:A6.
    for (
        booking_id_value,
        booking_start,
        booking_end,
    ) in booking_merge_groups:

        if (
            booking_start is None
            or booking_end is None
        ):
            continue

        # Clear repeated Booking ID values from later container starts
        # before merging the full booking range.
        for row_number in range(
            booking_start + 1,
            booking_end + 1,
        ):

            worksheet.cell(
                row=row_number,
                column=1,
            ).value = None

        if booking_end > booking_start:

            worksheet.merge_cells(
                start_row=booking_start,
                start_column=1,
                end_row=booking_end,
                end_column=1,
            )

        booking_cell = worksheet.cell(
            row=booking_start,
            column=1,
            value=booking_id_value,
        )

        booking_cell.alignment = Alignment(
            horizontal="center",
            vertical="center",
            wrap_text=True,
        )

        booking_cell.border = cell_border

    if make_active:

        workbook.active = (
            workbook.sheetnames.index(
                sheet_name
            )
        )

    luu_workbook_an_toan(
        workbook,
        excel_file,
    )

    workbook.close()


def parse_booking_datetime(
    value,
):
    """Best-effort parser for carrier deadline/date strings."""

    text = clean_data_value(
        value
    )

    if not text:
        return None

    text = re.sub(
        r"\([^)]*SUBJECT[^)]*\)",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    # Some carrier documents contain values such as 15:00 PM.
    # 24-hour values already carry the PM meaning, so strip AM/PM there.
    hour_match = re.search(
        r"\b(\d{1,2}):(\d{2})\s*(AM|PM)\b",
        text,
        re.IGNORECASE,
    )

    if hour_match:

        hour = int(
            hour_match.group(1)
        )

        if hour > 12:

            text = (
                text[:hour_match.start(3)]
                + text[hour_match.end(3):]
            ).strip()

    formats = [
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d %I:%M %p",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %I:%M %p",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %I:%M %p",
        "%d/%m/%Y",
        "%d-%m-%Y %H:%M",
        "%d-%m-%Y %I:%M %p",
        "%d-%m-%Y",
        "%d %b %Y %H:%M",
        "%d %b %Y %I:%M %p",
        "%d %b %Y",
        "%d %B %Y %H:%M",
        "%d %B %Y %I:%M %p",
        "%d %B %Y",
    ]

    # Ignore trailing notes after the actual date/time.
    candidates = [
        text,
        re.sub(
            r"\s+(?:SUBJECT|LOCAL|LT)\b.*$",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip(),
    ]

    for candidate in candidates:

        for date_format in formats:

            try:

                return datetime.strptime(
                    candidate,
                    date_format,
                )

            except ValueError:
                pass

    date_match = re.search(
        r"\b(\d{4}[/-]\d{1,2}[/-]\d{1,2})"
        r"(?:\s+(\d{1,2}:\d{2})(?:\s*(AM|PM))?)?",
        text,
        re.IGNORECASE,
    )

    if date_match:

        fallback = date_match.group(1)

        if date_match.group(2):
            fallback += " " + date_match.group(2)

        if date_match.group(3):
            fallback += " " + date_match.group(3)

        for date_format in formats:

            try:
                return datetime.strptime(
                    fallback,
                    date_format,
                )
            except ValueError:
                pass

    return None


def deadline_status(
    value,
):
    """Return status + days remaining for one deadline."""

    deadline_dt = parse_booking_datetime(
        value
    )

    if deadline_dt is None:
        return "", ""

    now_dt = datetime.now()
    delta = deadline_dt - now_dt
    hours = delta.total_seconds() / 3600

    if hours < 0:
        return "Overdue", int(
            delta.total_seconds()
            // 86400
        )

    days = int(
        delta.total_seconds()
        // 86400
    )

    if hours <= 72:
        return "Due Soon", days

    return "Upcoming", days


def apply_booking_confirmation_update(
    booking_df,
    booking_id,
    values,
    source_file,
    now_text,
):
    """Apply booking-level Confirmation data to every container row."""

    if (
        booking_df is None
        or booking_df.empty
        or "Booking ID" not in booking_df.columns
    ):
        return booking_df, []

    updated_df = ensure_text_columns(
        booking_df,
        [
            *BOOKING_CONFIRMATION_FIELDS,
            "Last Updated",
            "Created At",
        ],
    )

    mask = (
        updated_df[
            "Booking ID"
        ].astype(str)
        == str(
            booking_id
        )
    )

    if not mask.any():
        return updated_df, []

    # Columns are already object/text-safe via ensure_text_columns().

    first_index = updated_df[
        mask
    ].index[0]

    changes = []

    field_values = {
        BOOKING_CONFIRMATION_FIELD_MAP[
            key
        ]: clean_data_value(
            value
        )
        for key, value in values.items()
        if key in BOOKING_CONFIRMATION_FIELD_MAP
    }

    field_values[
        "Booking Confirmation File"
    ] = clean_data_value(
        source_file
    )

    for field_name, new_value in field_values.items():

        old_value = clean_data_value(
            updated_df.at[
                first_index,
                field_name,
            ]
        )

        if audit_values_equal(
            old_value,
            new_value,
        ):
            continue

        updated_df.loc[
            mask,
            field_name,
        ] = new_value

        changes.append(
            {
                "booking_id": booking_id,
                "container_no": None,
                "field_name": field_name,
                "old_value": old_value,
                "new_value": new_value,
                "change_type": "BOOKING_CONFIRMATION",
            }
        )

    if changes:

        if "Last Updated" not in updated_df.columns:
            updated_df[
                "Last Updated"
            ] = ""

        updated_df.loc[
            mask,
            "Last Updated",
        ] = now_text

    return updated_df, changes


def build_deadlines_sheet(
    excel_file,
    booking_df,
):
    """Build one editable deadline/confirmation row per internal booking."""

    excel_file = Path(
        excel_file
    )

    if not excel_file.exists():
        return

    workbook = load_workbook(
        excel_file
    )

    sheet_name = "Deadlines"

    if sheet_name in workbook.sheetnames:
        workbook.remove(
            workbook[
                sheet_name
            ]
        )

    worksheet = workbook.create_sheet(
        sheet_name,
        2,
    )

    columns = [
        "Booking ID",
        "Carrier Booking No",
        "BC Revision",
        "BC Confirmation Date",
        "Carrier",
        "Vessel / Voyage",
        "Port of Receipt",
        "Port of Loading",
        "POL Terminal",
        "CY Cut-off",
        "VGM Cut-off",
        "SI Cut-off",
        "Documentation Cut-off",
        "POL ETA",
        "ETD",
        "Port of Discharge",
        "Final Destination",
        "ETA",
        "Service Type / Mode",
        "Stuffing Place",
        "BC Commodity",
        "BC QTY / Type",
        "Empty Pick Up At",
        "Inland Return To",
        "Service Contract",
        "Payment Term",
        "Other Deadlines",
        "Booking Confirmation File",
        "Deadline Status",
        "Days to Next Cut-off",
        "Last Updated",
    ]

    header_fill = PatternFill(
        "solid",
        fgColor="FFF2CC",
    )

    border_side = Side(
        style="thin",
        color="D0D7DE",
    )

    cell_border = Border(
        left=border_side,
        right=border_side,
        top=border_side,
        bottom=border_side,
    )

    for col_idx, header in enumerate(
        columns,
        start=1,
    ):

        cell = worksheet.cell(
            row=1,
            column=col_idx,
            value=header,
        )

        cell.font = Font(
            bold=True
        )
        cell.fill = header_fill
        cell.border = cell_border
        cell.alignment = Alignment(
            horizontal="center",
            vertical="center",
            wrap_text=True,
        )

    if (
        booking_df is not None
        and not booking_df.empty
        and "Booking ID" in booking_df.columns
    ):

        booking_ids = []

        for value in booking_df[
            "Booking ID"
        ].tolist():

            value = clean_data_value(
                value
            )

            if value and value not in booking_ids:
                booking_ids.append(
                    value
                )

        row_no = 2

        for booking_id in booking_ids:

            rows = booking_df[
                booking_df[
                    "Booking ID"
                ].astype(str)
                == str(
                    booking_id
                )
            ]

            if rows.empty:
                continue

            first_row = rows.iloc[0]

            cutoff_candidates = []

            for field_name in [
                "SI Cut-off",
                "VGM Cut-off",
                "CY Cut-off",
                "Documentation Cut-off",
            ]:

                raw_value = clean_data_value(
                    first_row.get(
                        field_name,
                        "",
                    )
                )

                parsed = parse_booking_datetime(
                    raw_value
                )

                if parsed is not None:
                    cutoff_candidates.append(
                        (
                            parsed,
                            raw_value,
                        )
                    )

            deadline_state = ""
            days_to_cutoff = ""

            if cutoff_candidates:

                next_deadline = min(
                    cutoff_candidates,
                    key=lambda item: item[0],
                )

                deadline_state, days_to_cutoff = (
                    deadline_status(
                        next_deadline[1]
                    )
                )

            values = []

            for column in columns:

                if column == "Booking ID":
                    value = booking_id

                elif column == "Deadline Status":
                    value = deadline_state

                elif column == "Days to Next Cut-off":
                    value = days_to_cutoff

                else:
                    value = clean_data_value(
                        first_row.get(
                            column,
                            "",
                        )
                    )

                values.append(
                    value
                )

            for col_idx, value in enumerate(
                values,
                start=1,
            ):

                cell = worksheet.cell(
                    row=row_no,
                    column=col_idx,
                    value=value,
                )

                cell.border = cell_border
                cell.alignment = Alignment(
                    vertical="top",
                    wrap_text=True,
                )

            row_no += 1

    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions

    widths = {
        "A": 24,
        "B": 20,
        "C": 12,
        "D": 24,
        "E": 22,
        "F": 28,
        "G": 28,
        "H": 28,
        "I": 42,
        "J": 24,
        "K": 24,
        "L": 24,
        "M": 26,
        "N": 18,
        "O": 18,
        "P": 30,
        "Q": 30,
        "R": 24,
        "S": 22,
        "T": 20,
        "U": 36,
        "V": 42,
        "W": 42,
        "X": 42,
        "Y": 20,
        "Z": 20,
        "AA": 42,
        "AB": 38,
        "AC": 18,
        "AD": 20,
        "AE": 22,
    }

    for column_letter, width in widths.items():
        worksheet.column_dimensions[
            column_letter
        ].width = width

    luu_workbook_an_toan(
        workbook,
        excel_file,
    )
    workbook.close()


def load_deadlines_excel(
    excel_file,
):
    """Read editable Booking Confirmation/deadline values from Excel."""

    try:
        df = pd.read_excel(
            excel_file,
            sheet_name="Deadlines",
            dtype=object,
        )
    except Exception:
        return pd.DataFrame()

    if df.empty or "Booking ID" not in df.columns:
        return pd.DataFrame()

    keep_columns = [
        "Booking ID",
        *BOOKING_CONFIRMATION_FIELDS,
    ]

    for column in keep_columns:

        if column not in df.columns:
            df[
                column
            ] = ""

    return df[
        keep_columns
    ].copy()


def sync_deadlines_excel_changes(
    excel_file,
    backend_df,
):
    """Sync direct edits made in the visible Excel Deadlines sheet."""

    deadline_df = load_deadlines_excel(
        excel_file
    )

    if (
        deadline_df.empty
        or backend_df is None
        or backend_df.empty
        or "Booking ID" not in backend_df.columns
    ):
        return backend_df, 0

    updated_df = ensure_text_columns(
        backend_df,
        [
            *BOOKING_CONFIRMATION_FIELDS,
            "Last Updated",
            "Created At",
        ],
    )

    changes = []

    edited_datetime = datetime.fromtimestamp(
        excel_file.stat().st_mtime
    ).astimezone()

    edited_iso = edited_datetime.isoformat(
        timespec="seconds"
    )

    edited_text = edited_datetime.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    for _, deadline_row in deadline_df.iterrows():

        booking_id = clean_data_value(
            deadline_row.get(
                "Booking ID",
                "",
            )
        )

        if not booking_id:
            continue

        mask = (
            updated_df[
                "Booking ID"
            ].astype(str)
            == str(
                booking_id
            )
        )

        if not mask.any():
            continue

        first_index = updated_df[
            mask
        ].index[0]

        booking_changed = False

        for field_name in BOOKING_CONFIRMATION_FIELDS:

            old_value = clean_data_value(
                updated_df.at[
                    first_index,
                    field_name,
                ]
            )

            new_value = clean_data_value(
                deadline_row.get(
                    field_name,
                    "",
                )
            )

            if audit_values_equal(
                old_value,
                new_value,
            ):
                continue

            updated_df.loc[
                mask,
                field_name,
            ] = new_value

            changes.append(
                {
                    "booking_id": booking_id,
                    "field_name": field_name,
                    "old_value": old_value,
                    "new_value": new_value,
                }
            )

            booking_changed = True

        if booking_changed:

            if "Last Updated" not in updated_df.columns:
                updated_df[
                    "Last Updated"
                ] = ""

            updated_df.loc[
                mask,
                "Last Updated",
            ] = edited_text

    if not changes:
        return backend_df, 0

    try:
        write_booking_workbook(
            excel_file,
            updated_df,
        )
    except Exception:
        return backend_df, 0

    for change in changes:

        tracker.log_field_change(
            booking_id=change[
                "booking_id"
            ],
            field_name=change[
                "field_name"
            ],
            old_value=change[
                "old_value"
            ],
            new_value=change[
                "new_value"
            ],
            change_type="DEADLINE_EDIT",
            container_no=None,
            change_time=edited_iso,
        )

    for booking_id in sorted(
        {
            change[
                "booking_id"
            ]
            for change in changes
        }
    ):

        count = sum(
            1
            for change in changes
            if change[
                "booking_id"
            ] == booking_id
        )

        tracker.log(
            booking_id=booking_id,
            event_type="DEADLINE_EDIT",
            event_name="Deadlines edited in Excel",
            detail=(
                f"{count} Booking Confirmation/deadline "
                f"field(s) changed directly in Excel."
            ),
        )

    update_tracking_snapshot(
        updated_df
    )

    prune_tracking_to_current_bookings(
        updated_df
    )

    try:
        build_excel_tracking_sheets(
            excel_file
        )
    except Exception:
        pass

    return updated_df, len(
        changes
    )


def build_excel_tracking_sheets(
    excel_file,
):
    """
    Put SQLite tracking directly into booking_data.xlsx so DBeaver is
    not required for normal review.

    Visible workbook sheets:
      1. Extracted Data  -> working / printing view
      2. Tracking        -> process timeline from booking_events
      3. Field History   -> immutable field-change audit trail
      4. Bookings        -> normalized backend data used by the app

    Booking Detail is intentionally removed because Extracted Data is
    already the user's reading/printing layout.
    """

    excel_file = Path(
        excel_file
    )

    if not excel_file.exists():
        return

    workbook = load_workbook(
        excel_file
    )

    # Excel tracking sheets display only bookings that still exist.
    active_booking_ids = set()

    if "_BookingsData" in workbook.sheetnames:

        backend_sheet = workbook[
            "_BookingsData"
        ]

        header_map = {
            str(cell.value).strip():
                cell.column
            for cell in backend_sheet[1]
            if cell.value is not None
        }

        booking_id_column = header_map.get(
            "Booking ID"
        )

        if booking_id_column:

            for row_number in range(
                2,
                backend_sheet.max_row + 1,
            ):

                value = clean_data_value(
                    backend_sheet.cell(
                        row=row_number,
                        column=booking_id_column,
                    ).value
                )

                if value:
                    active_booking_ids.add(
                        value
                    )

    for sheet_name in [
        "Tracking",
        "Field History",
        "Booking Detail",
    ]:

        if sheet_name in workbook.sheetnames:
            workbook.remove(
                workbook[
                    sheet_name
                ]
            )

    tracking_sheet = workbook.create_sheet(
        "Tracking",
        3,
    )

    history_sheet = workbook.create_sheet(
        "Field History",
        4,
    )

    header_fill = PatternFill(
        "solid",
        fgColor="D9EAF7",
    )

    border_side = Side(
        style="thin",
        color="D0D7DE",
    )

    cell_border = Border(
        left=border_side,
        right=border_side,
        top=border_side,
        bottom=border_side,
    )

    tracking_headers = [
        "ID",
        "Booking ID",
        "Event Type",
        "Event Name",
        "Event Time",
        "Source File",
        "Container",
        "Detail",
    ]

    for column_index, header in enumerate(
        tracking_headers,
        start=1,
    ):

        cell = tracking_sheet.cell(
            row=1,
            column=column_index,
            value=header,
        )

        cell.font = Font(
            bold=True
        )

        cell.fill = header_fill

        cell.alignment = Alignment(
            horizontal="center",
            vertical="center",
            wrap_text=True,
        )

        cell.border = cell_border

    events = [
        event
        for event in reversed(
            tracker.get_all_events()
        )
        if (
            not active_booking_ids
            or clean_data_value(
                event[1]
            )
            in active_booking_ids
        )
    ]

    for row_index, event in enumerate(
        events,
        start=2,
    ):

        values = [
            event[0],
            event[1],
            event[2],
            event[3],
            event[4],
            event[5],
            event[6],
            event[7],
        ]

        for column_index, value in enumerate(
            values,
            start=1,
        ):

            cell = tracking_sheet.cell(
                row=row_index,
                column=column_index,
                value=value,
            )

            cell.alignment = Alignment(
                vertical="top",
                wrap_text=True,
            )

            cell.border = cell_border

    tracking_sheet.freeze_panes = "A2"
    tracking_sheet.auto_filter.ref = (
        tracking_sheet.dimensions
    )

    tracking_widths = {
        "A": 8,
        "B": 25,
        "C": 18,
        "D": 30,
        "E": 25,
        "F": 42,
        "G": 12,
        "H": 60,
    }

    for column, width in tracking_widths.items():
        tracking_sheet.column_dimensions[
            column
        ].width = width

    history_headers = [
        "ID",
        "Booking ID",
        "Container",
        "Field",
        "Old Value",
        "New Value",
        "Change Type",
        "Changed At",
        "Note",
    ]

    for column_index, header in enumerate(
        history_headers,
        start=1,
    ):

        cell = history_sheet.cell(
            row=1,
            column=column_index,
            value=header,
        )

        cell.font = Font(
            bold=True
        )

        cell.fill = header_fill

        cell.alignment = Alignment(
            horizontal="center",
            vertical="center",
            wrap_text=True,
        )

        cell.border = cell_border

    changes = [
        change
        for change in reversed(
            tracker.get_all_field_changes()
        )
        if (
            not active_booking_ids
            or clean_data_value(
                change[1]
            )
            in active_booking_ids
        )
    ]

    change_type_labels = {
        "INITIAL":
            "Initial value",

        "UPDATE":
            "Changed in app",

        "EXCEL_EDIT":
            "Changed in Excel",

        "EXTRACTED_EDIT":
            "Changed in Extracted Data",

        "BOOKINGS_EDIT":
            "Changed in Bookings",

        "BOOKING_CONFIRMATION":
            "Booking Confirmation update",

        "DEADLINE_EDIT":
            "Changed in Deadlines sheet",
    }

    for row_index, change in enumerate(
        changes,
        start=2,
    ):

        change_type = str(
            change[6] or ""
        )

        change_time = str(
            change[7] or ""
        )

        if change_type == "INITIAL":

            note = (
                f"(entered at {change_time})"
            )

        elif change_type == "EXTRACTED_EDIT":

            note = (
                f"(changed in Extracted Data "
                f"at {change_time})"
            )

        elif change_type == "BOOKINGS_EDIT":

            note = (
                f"(changed in Bookings "
                f"at {change_time})"
            )

        elif change_type == "UPDATE":

            note = (
                f"(changed in app at "
                f"{change_time})"
            )

        else:

            note = (
                f"(changed at {change_time})"
            )

        values = [
            change[0],
            change[1],
            change[2],
            change[3],
            change[4],
            change[5],
            change_type_labels.get(
                change_type,
                change_type,
            ),
            change_time,
            note,
        ]

        for column_index, value in enumerate(
            values,
            start=1,
        ):

            cell = history_sheet.cell(
                row=row_index,
                column=column_index,
                value=value,
            )

            cell.alignment = Alignment(
                vertical="top",
                wrap_text=True,
            )

            cell.border = cell_border

    history_sheet.freeze_panes = "A2"
    history_sheet.auto_filter.ref = (
        history_sheet.dimensions
    )

    history_widths = {
        "A": 8,
        "B": 25,
        "C": 12,
        "D": 24,
        "E": 48,
        "F": 48,
        "G": 20,
        "H": 25,
        "I": 32,
    }

    for column, width in history_widths.items():
        history_sheet.column_dimensions[
            column
        ].width = width

    if "Extracted Data" in workbook.sheetnames:
        workbook.active = (
            workbook.sheetnames.index(
                "Extracted Data"
            )
        )

    luu_workbook_an_toan(
        workbook,
        excel_file,
    )

    workbook.close()

    # Process-oriented workbook mirrors.
    build_process_excel_sheets(
        excel_file
    )

def write_booking_workbook(
    excel_file,
    booking_df,
):
    """
    Tạo lại toàn bộ workbook từ DataFrame rồi mới thay file chính.

    Lý do:
    - Không append trực tiếp vào booking_data.xlsx.
    - Không phụ thuộc trạng thái ZIP bên trong của file cũ.
    - Nếu file cũ bị lỗi, giữ lại bản backup.
    - Chỉ replace file chính sau khi workbook tạm đã được xác nhận hợp lệ.

    Cách này xử lý triệt để lỗi:
    "There is no item named '[Content_Types].xml' in the archive"
    """
    excel_file = Path(
        excel_file
    )

    excel_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Nếu file hiện tại đã hỏng thì giữ backup để không mất dấu vết.
    corrupted_backup = None

    if (
        excel_file.exists()
        and not file_excel_hop_le(
            excel_file
        )
    ):
        corrupted_backup = (
            sao_luu_file_excel_loi(
                excel_file
            )
        )

    # Luôn build workbook mới ở file tạm.
    # Không dùng mode="a" để tránh đọc/append vào ZIP cũ.
    temp_handle = tempfile.NamedTemporaryFile(
        prefix=f".{excel_file.stem}_rebuild_",
        suffix=".xlsx",
        dir=excel_file.parent,
        delete=False,
    )

    temp_file = Path(
        temp_handle.name
    )

    temp_handle.close()

    # NamedTemporaryFile tạo file rỗng.
    # Pandas/openpyxl cần tự tạo workbook mới từ path chưa tồn tại.
    try:
        temp_file.unlink(
            missing_ok=True
        )
    except TypeError:
        if temp_file.exists():
            temp_file.unlink()

    try:

        # 1. Tạo backend sheet mới hoàn toàn.
        with pd.ExcelWriter(
            temp_file,
            engine="openpyxl",
            mode="w",
        ) as writer:

            booking_df.to_excel(
                writer,
                sheet_name="_BookingsData",
                index=False,
            )

        # 2. Tạo các sheet hiển thị trên chính workbook tạm.
        build_extracted_data_sheet(
            temp_file,
            booking_df,
            sheet_name="Extracted Data",
            sheet_position=0,
            make_active=True,
        )

        build_extracted_data_sheet(
            temp_file,
            booking_df,
            sheet_name="Bookings",
            sheet_position=1,
            make_active=False,
        )

        build_deadlines_sheet(
            temp_file,
            booking_df,
        )

        # 3. Sau khi đã có sheet visible mới hide backend.
        format_booking_excel(
            temp_file
        )

        # 4. Xác nhận workbook tạm thực sự là XLSX hợp lệ.
        if not file_excel_hop_le(
            temp_file
        ):
            raise ValueError(
                "The rebuilt Excel workbook is incomplete."
            )

        # Kiểm tra openpyxl mở được workbook trước khi replace.
        validation_workbook = load_workbook(
            temp_file,
            read_only=True,
            data_only=False,
        )

        validation_sheet_names = set(
            validation_workbook.sheetnames
        )

        validation_workbook.close()

        required_sheets = {
            "_BookingsData",
            "Extracted Data",
            "Bookings",
            "Deadlines",
        }

        missing_sheets = (
            required_sheets
            - validation_sheet_names
        )

        if missing_sheets:
            raise ValueError(
                "The rebuilt Excel workbook is missing sheet(s): "
                + ", ".join(
                    sorted(
                        missing_sheets
                    )
                )
            )

        # 5. Chỉ lúc này mới thay booking_data.xlsx.
        os.replace(
            temp_file,
            excel_file,
        )

        return corrupted_backup

    except Exception:

        # Nếu rebuild lỗi, không để file tạm rác lại trong folder.
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass

        raise


def build_dashboard_summary(
    booking_df,
):
    """Return one compact row per booking for the Dashboard."""

    columns = [
        "Booking ID",
        "Containers",
        "Date of Booking",
        "Shipper",
        "Product",
        "Created At",
        "Last Updated",
    ]

    if (
        booking_df.empty
        or "Booking ID" not in booking_df.columns
    ):
        return pd.DataFrame(
            columns=columns
        )

    summary_rows = []

    for booking_id, rows in booking_df.groupby(
        "Booking ID",
        sort=False,
        dropna=False,
    ):

        rows = rows.reset_index(
            drop=True
        )

        first_row = rows.iloc[0]

        last_updated_values = []

        if "Last Updated" in rows.columns:
            last_updated_values = [
                clean_data_value(value)
                for value in rows[
                    "Last Updated"
                ].tolist()
                if clean_data_value(value)
            ]

        created_values = []

        if "Created At" in rows.columns:
            created_values = [
                clean_data_value(value)
                for value in rows[
                    "Created At"
                ].tolist()
                if clean_data_value(value)
            ]

        summary_rows.append(
            {
                "Booking ID": clean_data_value(
                    booking_id
                ),
                "Containers": (
                    len(
                        {
                            normalize_container_key(
                                value
                            )
                            for value in rows.get(
                                "Container",
                                pd.Series(
                                    range(
                                        1,
                                        len(rows) + 1,
                                    )
                                ),
                            ).tolist()
                        }
                    )
                ),
                "Date of Booking": clean_data_value(
                    first_row.get(
                        "Date of Booking",
                        "",
                    )
                ),
                "Shipper": clean_data_value(
                    first_row.get(
                        "Shipper",
                        "",
                    )
                ),
                "Product": clean_data_value(
                    first_row.get(
                        "Product",
                        "",
                    )
                ),
                "Created At": (
                    min(created_values)
                    if created_values
                    else ""
                ),
                "Last Updated": (
                    max(last_updated_values)
                    if last_updated_values
                    else ""
                ),
            }
        )

    return pd.DataFrame(
        summary_rows,
        columns=columns,
    )


def update_booking_from_dashboard(
    booking_id,
    booking_df,
    common_values,
    container_values,
):
    """
    Update one existing booking from Dashboard editor values.

    Returns:
        updated_df, audit_changes

    Existing Created At is kept.
    Last Updated changes only on rows whose data actually changed.
    """

    updated_df = booking_df.copy()

    if (
        updated_df.empty
        or "Booking ID" not in updated_df.columns
    ):
        return updated_df, []

    now_text = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    booking_mask = (
        updated_df[
            "Booking ID"
        ].astype(str)
        == str(booking_id)
    )

    audit_changes = []

    common_columns = [
        "Date of Booking",
        "Shipper",
        "Consignee",
        "Notify",
        "Product",
    ]

    container_columns = [
        "Total Pallet",
        "Packing Details",
        "Quantity",
        "Marking",
    ]

    for row_index in updated_df[
        booking_mask
    ].index:

        container_value = updated_df.at[
            row_index,
            "Container",
        ] if "Container" in updated_df.columns else ""

        container_key = normalize_container_key(
            container_value
        )

        edits = container_values.get(
            container_key,
            {},
        )

        row_changed = False

        for field_name in common_columns:

            old_value = clean_data_value(
                updated_df.at[
                    row_index,
                    field_name,
                ]
                if field_name in updated_df.columns
                else ""
            )

            if field_name in common_values:
                candidate_value = common_values[
                    field_name
                ]
            else:
                candidate_value = edits.get(
                    field_name,
                    old_value,
                )

            new_value = clean_data_value(
                candidate_value
            )

            if audit_values_equal(
                old_value,
                new_value,
            ):
                continue

            if field_name not in updated_df.columns:
                updated_df[
                    field_name
                ] = ""

            updated_df.at[
                row_index,
                field_name,
            ] = new_value

            row_changed = True

            audit_changes.append(
                {
                    "booking_id": booking_id,
                    "container_no": container_value,
                    "field_name": field_name,
                    "old_value": old_value,
                    "new_value": new_value,
                    "change_type": "UPDATE",
                }
            )

        for field_name in container_columns:

            old_value = clean_data_value(
                updated_df.at[
                    row_index,
                    field_name,
                ]
                if field_name in updated_df.columns
                else ""
            )

            new_value = clean_data_value(
                edits.get(
                    field_name,
                    old_value,
                )
            )

            if audit_values_equal(
                old_value,
                new_value,
            ):
                continue

            if field_name not in updated_df.columns:
                updated_df[
                    field_name
                ] = ""

            updated_df.at[
                row_index,
                field_name,
            ] = new_value

            row_changed = True

            audit_changes.append(
                {
                    "booking_id": booking_id,
                    "container_no": container_value,
                    "field_name": field_name,
                    "old_value": old_value,
                    "new_value": new_value,
                    "change_type": "UPDATE",
                }
            )

        if row_changed:

            if "Last Updated" not in updated_df.columns:
                updated_df[
                    "Last Updated"
                ] = ""

            updated_df.at[
                row_index,
                "Last Updated",
            ] = now_text

    expected_count = int(
        booking_mask.sum()
    )

    audit_changes = (
        compress_common_audit_changes(
            audit_changes,
            expected_count,
        )
    )

    return (
        updated_df,
        audit_changes,
    )


def build_snapshot_records(
    booking_df,
):
    """
    Convert the current Bookings sheet to compact records used
    only for change comparison.

    The snapshot key is:
        Booking ID + Container + Field Name

    If an old/manually formatted workbook contains duplicate rows
    for the same container, keep the last value for that key.
    This prevents duplicate-key crashes without deleting any
    tracking history.

    Created At / Last Updated are intentionally excluded.
    """

    if (
        booking_df is None
        or booking_df.empty
        or "Booking ID" not in booking_df.columns
    ):
        return []

    record_map = {}

    for _, row in booking_df.iterrows():

        booking_id = clean_data_value(
            row.get(
                "Booking ID",
                "",
            )
        )

        container_no = normalize_container_key(
            row.get(
                "Container",
                "",
            )
        )

        if not booking_id:
            continue

        for field_name in AUDIT_FIELDS:

            key = (
                booking_id,
                container_no,
                field_name,
            )

            record_map[
                key
            ] = clean_data_value(
                row.get(
                    field_name,
                    "",
                )
            )

    return [
        (
            booking_id,
            container_no,
            field_name,
            field_value,
        )
        for (
            booking_id,
            container_no,
            field_name,
        ), field_value in record_map.items()
    ]


def update_tracking_snapshot(
    booking_df,
):
    tracker.replace_snapshot(
        build_snapshot_records(
            booking_df
        )
    )


def get_active_booking_ids(
    booking_df,
    include_current_session=True,
    exclude_booking_ids=None,
):
    """
    Return Booking IDs that are currently in use.

    Current Excel bookings are always included.
    The in-progress session Booking ID can also be kept so upload/analyze
    tracking is not accidentally removed before the booking is exported.
    """

    active_ids = set()

    if (
        booking_df is not None
        and not booking_df.empty
        and "Booking ID" in booking_df.columns
    ):

        for value in booking_df[
            "Booking ID"
        ].tolist():

            value = clean_data_value(
                value
            )

            if value:
                active_ids.add(
                    value
                )

    if include_current_session:

        current_booking_id = clean_data_value(
            st.session_state.get(
                "current_booking_id",
                "",
            )
        )

        if current_booking_id:
            active_ids.add(
                current_booking_id
            )

    excluded = {
        clean_data_value(
            value
        )
        for value in (
            exclude_booking_ids
            or []
        )
        if clean_data_value(
            value
        )
    }

    return sorted(
        active_ids
        - excluded
    )


def prune_tracking_to_current_bookings(
    booking_df,
    include_current_session=True,
    exclude_booking_ids=None,
):
    """
    Keep tracking only for bookings that are currently active.
    """

    tracker.prune_to_active_bookings(
        get_active_booking_ids(
            booking_df,
            include_current_session=(
                include_current_session
            ),
            exclude_booking_ids=(
                exclude_booking_ids
            ),
        )
    )


def sync_external_excel_changes():
    """
    Synchronize direct Excel edits back into the whole application.

    Source priority:
      1. Extracted Data  <- preferred user-editable sheet
      2. Bookings        <- accepted as a secondary editable mirror
      3. _BookingsData   <- hidden normalized backend fallback

    When a real change is detected:
      - old -> new is appended to tracking.db,
      - Last Updated changes only for affected containers,
      - _BookingsData is updated,
      - Extracted Data is rebuilt,
      - Bookings is rebuilt to match Extracted Data,
      - Tracking / Field History Excel sheets are refreshed,
      - Dashboard sees the new values on the same rerun,
      - obsolete booking tracking is pruned.

    This function is safe to call repeatedly because the SQLite snapshot
    prevents the same edit from being logged twice.
    """

    excel_file = get_excel_file()

    if (
        excel_file is None
        or not excel_file.exists()
    ):
        return 0

    extracted_df = load_presented_bookings_excel(
        excel_file,
        sheet_name="Extracted Data",
    )

    bookings_df = load_presented_bookings_excel(
        excel_file,
        sheet_name="Bookings",
    )

    backend_df = load_booking_excel()

    # Deadlines is an editable Excel source too. Synchronize it before
    # comparing the Packing List presentation sheets.
    backend_df, deadline_change_count = (
        sync_deadlines_excel_changes(
            excel_file,
            backend_df,
        )
    )

    if deadline_change_count:
        return deadline_change_count

    def snapshot_from_df(
        dataframe,
    ):

        records = build_snapshot_records(
            dataframe
        )

        snapshot = {
            (
                str(record[0]),
                str(record[1]),
                str(record[2]),
            ): str(
                record[3]
                or ""
            )
            for record in records
        }

        return (
            records,
            snapshot,
        )

    def snapshot_differs(
        candidate_snapshot,
        baseline_snapshot,
    ):

        all_keys = (
            set(
                candidate_snapshot
            )
            | set(
                baseline_snapshot
            )
        )

        for key in all_keys:

            if (
                key not in candidate_snapshot
                or key not in baseline_snapshot
            ):
                return True

            if not audit_values_equal(
                candidate_snapshot[
                    key
                ],
                baseline_snapshot[
                    key
                ],
            ):
                return True

        return False

    extracted_records, extracted_snapshot = (
        snapshot_from_df(
            extracted_df
        )
        if not extracted_df.empty
        else (
            [],
            {},
        )
    )

    bookings_records, bookings_snapshot = (
        snapshot_from_df(
            bookings_df
        )
        if not bookings_df.empty
        else (
            [],
            {},
        )
    )

    backend_records, backend_snapshot = (
        snapshot_from_df(
            backend_df
        )
        if not backend_df.empty
        else (
            [],
            {},
        )
    )

    old_snapshot = tracker.get_snapshot()

    # ------------------------------------------------------
    # FIRST BASELINE
    # ------------------------------------------------------

    if not old_snapshot:

        if not extracted_df.empty:

            current_df = extracted_df.copy()
            current_records = extracted_records

        elif not bookings_df.empty:

            current_df = bookings_df.copy()
            current_records = bookings_records

        elif not backend_df.empty:

            current_df = backend_df.copy()
            current_records = backend_records

        else:
            return 0

        try:

            # Normalize all workbook mirrors immediately.
            write_booking_workbook(
                excel_file,
                current_df,
            )

        except Exception:

            # Excel may currently have the file locked.
            return 0

        tracker.replace_snapshot(
            current_records
        )

        prune_tracking_to_current_bookings(
            current_df
        )

        try:
            build_excel_tracking_sheets(
                excel_file
            )
        except Exception:
            pass

        return 0

    # ------------------------------------------------------
    # CHOOSE THE SHEET THAT WAS ACTUALLY EDITED
    # ------------------------------------------------------

    extracted_changed = (
        bool(
            extracted_snapshot
        )
        and snapshot_differs(
            extracted_snapshot,
            old_snapshot,
        )
    )

    bookings_changed = (
        bool(
            bookings_snapshot
        )
        and snapshot_differs(
            bookings_snapshot,
            old_snapshot,
        )
    )

    conflict_detected = False

    if extracted_changed:

        # Extracted Data is the user's primary working sheet.
        current_df = extracted_df.copy()
        current_records = extracted_records
        current_snapshot = extracted_snapshot
        source_sheet = "Extracted Data"
        field_change_type = "EXTRACTED_EDIT"
        event_type = "EXTRACTED_EDIT"

        if (
            bookings_changed
            and bookings_snapshot
            != extracted_snapshot
        ):
            conflict_detected = True

    elif bookings_changed:

        current_df = bookings_df.copy()
        current_records = bookings_records
        current_snapshot = bookings_snapshot
        source_sheet = "Bookings"
        field_change_type = "BOOKINGS_EDIT"
        event_type = "BOOKINGS_EDIT"

    else:

        # No user-data change. Still remove historical rows belonging to
        # bookings that are no longer active, but only when a valid current
        # workbook dataset exists.
        current_df = (
            backend_df.copy()
            if not backend_df.empty
            else (
                extracted_df.copy()
                if not extracted_df.empty
                else bookings_df.copy()
            )
        )

        if not current_df.empty:

            prune_tracking_to_current_bookings(
                current_df
            )

        return 0

    # Excel save/modification timestamp is the best available timestamp
    # for direct workbook edits.
    edited_datetime = (
        datetime.fromtimestamp(
            excel_file.stat().st_mtime
        )
        .astimezone()
    )

    edited_iso = (
        edited_datetime.isoformat(
            timespec="seconds"
        )
    )

    edited_text = (
        edited_datetime.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    changes = []

    # ------------------------------------------------------
    # FIELD CHANGES: OLD -> NEW
    # ------------------------------------------------------

    for key, new_value in (
        current_snapshot.items()
    ):

        old_value = old_snapshot.get(
            key,
            None,
        )

        if old_value is None:

            if normalize_audit_value(
                new_value
            ):

                changes.append(
                    {
                        "booking_id":
                            key[0],

                        "container_no":
                            key[1],

                        "field_name":
                            key[2],

                        "old_value":
                            "",

                        "new_value":
                            new_value,
                    }
                )

            continue

        if audit_values_equal(
            old_value,
            new_value,
        ):
            continue

        changes.append(
            {
                "booking_id":
                    key[0],

                "container_no":
                    key[1],

                "field_name":
                    key[2],

                "old_value":
                    old_value,

                "new_value":
                    new_value,
            }
        )

    old_pairs = {
        (
            key[0],
            key[1],
        )
        for key in old_snapshot
    }

    current_pairs = {
        (
            key[0],
            key[1],
        )
        for key in current_snapshot
    }

    removed_pairs = (
        old_pairs
        - current_pairs
    )

    if (
        not changes
        and not removed_pairs
    ):

        # The visible sheet may only differ in formatting/layout.
        # Rebuild both mirrors so they remain identical.
        try:

            write_booking_workbook(
                excel_file,
                current_df,
            )

        except Exception:
            return 0

        update_tracking_snapshot(
            current_df
        )

        prune_tracking_to_current_bookings(
            current_df
        )

        return 0

    # ------------------------------------------------------
    # LAST UPDATED
    # ------------------------------------------------------

    changed_pairs = {
        (
            str(
                change[
                    "booking_id"
                ]
            ),
            normalize_container_key(
                change[
                    "container_no"
                ]
            ),
        )
        for change in changes
    }

    current_df = current_df.copy()

    if "Last Updated" not in current_df.columns:

        current_df[
            "Last Updated"
        ] = ""

    if "Created At" not in current_df.columns:

        current_df[
            "Created At"
        ] = ""

    for row_index in current_df.index:

        row_booking_id = clean_data_value(
            current_df.at[
                row_index,
                "Booking ID",
            ]
            if "Booking ID" in current_df.columns
            else ""
        )

        row_container = normalize_container_key(
            current_df.at[
                row_index,
                "Container",
            ]
            if "Container" in current_df.columns
            else ""
        )

        if (
            row_booking_id,
            row_container,
        ) not in changed_pairs:
            continue

        created_at = clean_data_value(
            current_df.at[
                row_index,
                "Created At",
            ]
        )

        if not created_at:

            current_df.at[
                row_index,
                "Created At",
            ] = edited_text

        current_df.at[
            row_index,
            "Last Updated",
        ] = edited_text

    # ------------------------------------------------------
    # WRITE ALL MIRRORS FIRST
    # ------------------------------------------------------

    try:

        write_booking_workbook(
            excel_file,
            current_df,
        )

    except Exception:

        # Do not write history until the workbook itself was synchronized.
        return 0

    # ------------------------------------------------------
    # APPEND AUDIT HISTORY
    # ------------------------------------------------------

    for change in changes:

        tracker.log_field_change(
            booking_id=(
                change[
                    "booking_id"
                ]
            ),
            field_name=(
                change[
                    "field_name"
                ]
            ),
            old_value=(
                change[
                    "old_value"
                ]
            ),
            new_value=(
                change[
                    "new_value"
                ]
            ),
            change_type=(
                field_change_type
            ),
            container_no=(
                change[
                    "container_no"
                ]
            ),
            change_time=edited_iso,
        )

    affected_bookings = sorted(
        {
            change[
                "booking_id"
            ]
            for change in changes
        }
    )

    for booking_id in affected_bookings:

        count = sum(
            1
            for change in changes
            if change[
                "booking_id"
            ] == booking_id
        )

        detail = (
            f"{count} field change(s) synchronized from "
            f"{source_sheet}. "
            f"Changed at {edited_text}."
        )

        if conflict_detected:

            detail += (
                " Extracted Data and Bookings both differed; "
                "Extracted Data was used as the source of truth."
            )

        tracker.log(
            booking_id=booking_id,
            event_type=event_type,
            event_name=(
                f"{source_sheet} changes synchronized"
            ),
            detail=detail,
        )

    # Container rows removed manually.
    for booking_id, container_no in removed_pairs:

        tracker.log(
            booking_id=booking_id,
            event_type="EXCEL_DELETE",
            event_name=(
                "Container row removed directly in Excel"
            ),
            container_no=(
                container_no
                if container_no
                else None
            ),
            detail=(
                f"Removal synchronized from "
                f"{source_sheet}. "
                f"Changed at {edited_text}."
            ),
        )

    # Snapshot now matches the normalized workbook.
    update_tracking_snapshot(
        current_df
    )

    # Permanently remove history for bookings that no longer exist.
    prune_tracking_to_current_bookings(
        current_df
    )

    # Refresh Excel-visible audit sheets AFTER SQLite is up to date.
    try:

        build_excel_tracking_sheets(
            excel_file
        )

    except Exception:
        pass

    return (
        len(changes)
        + len(removed_pairs)
    )


def load_storage_folder():
    """Select per-session private temporary storage on public Cloud."""

    if PUBLIC_DEMO_MODE:
        return str(PUBLIC_STORAGE_FOLDER)

    if not STORAGE_SETTINGS_FILE.exists():
        return ""

    try:

        data = json.loads(
            STORAGE_SETTINGS_FILE.read_text(
                encoding="utf-8"
            )
        )

        folder = str(
            data.get(
                "storage_folder",
                "",
            )
        ).strip()

        if not folder:
            return ""

        folder_path = Path(
            folder
        ).expanduser()

        if folder_path.exists() and folder_path.is_dir():
            return str(
                folder_path.resolve()
            )

    except Exception:
        pass

    return ""


def save_storage_folder(folder):
    """Save local folder, or use the isolated demo workspace on Cloud."""

    if PUBLIC_DEMO_MODE:
        st.session_state.storage_folder = str(PUBLIC_STORAGE_FOLDER)
        return PUBLIC_STORAGE_FOLDER

    folder_path = Path(
        folder
    ).expanduser()

    if not folder_path.exists():
        raise ValueError(
            "The selected folder does not exist."
        )

    if not folder_path.is_dir():
        raise ValueError(
            "The selected path is not a folder."
        )

    folder_path = folder_path.resolve()

    STORAGE_SETTINGS_FILE.write_text(
        json.dumps(
            {
                "storage_folder":
                    str(folder_path)
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    st.session_state.storage_folder = (
        str(folder_path)
    )

    # A different storage file needs a fresh comparison baseline.
    # Historical tracking remains untouched.
    tracker.clear_snapshot()

    return folder_path


def choose_storage_folder():
    """Use a private session folder on Cloud and Finder on local macOS."""

    if PUBLIC_DEMO_MODE:
        return str(PUBLIC_STORAGE_FOLDER)

    if sys.platform != "darwin":
        return ""

    script = (
        'POSIX path of '
        '(choose folder with prompt '
        '"Choose folder for booking_data.xlsx")'
    )

    process = subprocess.run(
        [
            "osascript",
            "-e",
            script,
        ],
        capture_output=True,
        text=True,
    )

    if process.returncode != 0:
        return ""

    return process.stdout.strip()


def get_excel_file():
    """Return the session-only Excel workbook in public presentation."""

    if PUBLIC_DEMO_MODE:
        return PUBLIC_STORAGE_FOLDER / "booking_data.xlsx"

    folder = str(
        st.session_state.get(
            "storage_folder",
            "",
        )
    ).strip()

    if not folder:
        return None

    return (
        Path(folder)
        / "booking_data.xlsx"
    )



def load_presented_bookings_excel(
    excel_file,
    sheet_name="Bookings",
):
    """
    Read the merged visible Bookings sheet and rebuild one normalized
    row per Booking ID + Container.

    This keeps Bookings visually identical to Extracted Data without
    breaking Dashboard, tracking, deletion, or direct-Excel edit detection.
    """

    excel_file = Path(
        excel_file
    )

    try:

        presented_df = pd.read_excel(
            excel_file,
            sheet_name=sheet_name,
        )

    except Exception:

        return pd.DataFrame()

    if presented_df.empty:
        return pd.DataFrame()

    required_columns = [
        "Booking ID",
        "Container",
        "Date of Booking",
        "Shipper",
        "Consignee",
        "Notify",
        "Product",
        "Total Pallet",
        "Packing Details",
        "Quantity",
        "Marking",
        "Source File",
        "Created At",
        "Last Updated",
    ]

    for column in required_columns:

        if column not in presented_df.columns:

            presented_df[
                column
            ] = ""

    # Excel merged cells are read as value + blanks.
    # Only grouping keys are forward-filled.
    presented_df[
        "Booking ID"
    ] = presented_df[
        "Booking ID"
    ].ffill()

    presented_df[
        "Container"
    ] = presented_df[
        "Container"
    ].ffill()

    has_inline_segment_sizes = (
        "Presentation Segment Sizes"
        in presented_df.columns
    )

    normalized_rows = []

    def first_non_empty(
        group,
        field_name,
    ):

        for value in group[
            field_name
        ].tolist():

            value = clean_data_value(
                value
            )

            if value:
                return value

        return ""

    def collect_blocks(
        group,
        field_name,
        unique=False,
    ):

        output = []
        seen = set()

        for value in group[
            field_name
        ].tolist():

            value = clean_data_value(
                value
            )

            if not value:
                continue

            if unique:

                normalized = (
                    normalize_audit_value(
                        value
                    )
                    .upper()
                )

                if normalized in seen:
                    continue

                seen.add(
                    normalized
                )

            output.append(
                value
            )

        return "\n".join(
            output
        ).strip()

    ordered_keys = []

    for _, row in presented_df.iterrows():

        booking_id = clean_data_value(
            row.get(
                "Booking ID",
                "",
            )
        )

        container_key = normalize_container_key(
            row.get(
                "Container",
                "",
            )
        )

        if not booking_id:
            continue

        key = (
            booking_id,
            container_key,
        )

        if key not in ordered_keys:

            ordered_keys.append(
                key
            )

    for (
        booking_id,
        container_key,
    ) in ordered_keys:

        group = presented_df[
            (
                presented_df[
                    "Booking ID"
                ].map(
                    clean_data_value
                )
                == booking_id
            )
            & (
                presented_df[
                    "Container"
                ].map(
                    normalize_container_key
                )
                == container_key
            )
        ].copy()

        if group.empty:
            continue

        group = group.reset_index(
            drop=True
        )

        segment_sizes = []

        if has_inline_segment_sizes:

            raw_segment_sizes = first_non_empty(
                group,
                "Presentation Segment Sizes",
            )

            if raw_segment_sizes:

                try:

                    parsed_sizes = json.loads(
                        raw_segment_sizes
                    )

                    segment_sizes = [
                        int(value)
                        for value in parsed_sizes
                        if int(value) > 0
                    ]

                except Exception:

                    segment_sizes = []

        # For the merged presentation sheet, infer each Packing List page
        # from the rows where Product or Quantity starts a new merged block.
        if not segment_sizes:

            segment_starts = []

            for row_index, group_row in (
                group.iterrows()
            ):

                product_value = clean_data_value(
                    group_row.get(
                        "Product",
                        "",
                    )
                )

                quantity_value = clean_data_value(
                    group_row.get(
                        "Quantity",
                        "",
                    )
                )

                if (
                    product_value
                    or quantity_value
                ):

                    segment_starts.append(
                        int(
                            row_index
                        )
                    )

            if (
                not segment_starts
                or segment_starts[0] != 0
            ):

                segment_starts.insert(
                    0,
                    0,
                )

            segment_starts = sorted(
                set(
                    segment_starts
                )
            )

            for start_index, segment_start in enumerate(
                segment_starts
            ):

                if (
                    start_index + 1
                    < len(
                        segment_starts
                    )
                ):

                    segment_end = (
                        segment_starts[
                            start_index + 1
                        ]
                    )

                else:

                    segment_end = len(
                        group
                    )

                segment_size = (
                    segment_end
                    - segment_start
                )

                if segment_size > 0:

                    segment_sizes.append(
                        segment_size
                    )

        if not segment_sizes:

            segment_sizes = [
                max(
                    len(
                        group
                    ),
                    1,
                )
            ]

        normalized_rows.append(
            {
                "Booking ID":
                    booking_id,

                "Container":
                    container_key,

                "Date of Booking":
                    first_non_empty(
                        group,
                        "Date of Booking",
                    ),

                "Shipper":
                    first_non_empty(
                        group,
                        "Shipper",
                    ),

                "Consignee":
                    first_non_empty(
                        group,
                        "Consignee",
                    ),

                "Notify":
                    first_non_empty(
                        group,
                        "Notify",
                    ),

                "Product":
                    collect_blocks(
                        group,
                        "Product",
                        unique=True,
                    ),

                "Total Pallet":
                    collect_blocks(
                        group,
                        "Total Pallet",
                    ),

                "Packing Details":
                    collect_blocks(
                        group,
                        "Packing Details",
                    ),

                "Quantity":
                    collect_blocks(
                        group,
                        "Quantity",
                    ),

                "Marking":
                    first_non_empty(
                        group,
                        "Marking",
                    ),

                "Source File":
                    first_non_empty(
                        group,
                        "Source File",
                    ),

                "Presentation Segment Sizes":
                    json.dumps(
                        segment_sizes,
                        ensure_ascii=False,
                    ),

                "Created At":
                    first_non_empty(
                        group,
                        "Created At",
                    ),

                "Last Updated":
                    first_non_empty(
                        group,
                        "Last Updated",
                    ),
            }
        )

    normalized_df = pd.DataFrame(
        normalized_rows
    )

    # Extracted Data / Bookings intentionally stay focused on Packing List
    # presentation. Pull Booking Confirmation fields from the hidden backend
    # so editing those visible sheets can never erase deadlines/confirmation.
    try:

        backend_df = pd.read_excel(
            excel_file,
            sheet_name="_BookingsData",
            dtype=object,
        )

        backend_df = ensure_text_columns(
            backend_df,
            BOOKING_CONFIRMATION_FIELDS,
        )

    except Exception:

        backend_df = pd.DataFrame()

    if (
        not normalized_df.empty
        and not backend_df.empty
        and "Booking ID" in backend_df.columns
    ):

        for field_name in BOOKING_CONFIRMATION_FIELDS:

            if field_name not in normalized_df.columns:
                normalized_df[
                    field_name
                ] = ""

        for row_index in normalized_df.index:

            booking_id = clean_data_value(
                normalized_df.at[
                    row_index,
                    "Booking ID",
                ]
            )

            matching = backend_df[
                backend_df[
                    "Booking ID"
                ].astype(str)
                == str(
                    booking_id
                )
            ]

            if matching.empty:
                continue

            backend_row = matching.iloc[0]

            for field_name in BOOKING_CONFIRMATION_FIELDS:

                normalized_df.at[
                    row_index,
                    field_name,
                ] = clean_data_value(
                    backend_row.get(
                        field_name,
                        "",
                    )
                )

    return normalized_df


def load_booking_excel():
    """
    Read the selected booking_data.xlsx safely.
    """

    excel_file = get_excel_file()

    if (
        excel_file is None
        or not excel_file.exists()
    ):
        return pd.DataFrame()

    # File tồn tại nhưng cấu trúc .xlsx không hợp lệ:
    # không cố mở bằng pandas/openpyxl vì sẽ phát sinh lỗi
    # "[Content_Types].xml".
    if not file_excel_hop_le(
        excel_file
    ):
        return pd.DataFrame()

    try:

        loaded_df = pd.read_excel(
            excel_file,
            sheet_name="_BookingsData",
            dtype=object,
        )

        return ensure_text_columns(
            loaded_df,
            [
                *BOOKING_CONFIRMATION_FIELDS,
                "Last Updated",
                "Created At",
            ],
        )

    except Exception:

        # Automatic migration/fallback for older workbooks.
        return load_presented_bookings_excel(
            excel_file,
            sheet_name="Bookings",
        )


def format_booking_excel(
    excel_file,
):
    """
    Format and hide the normalized backend sheet after saving.
    """

    excel_file = Path(
        excel_file
    )

    if not excel_file.exists():
        return

    workbook = load_workbook(
        excel_file
    )

    if "_BookingsData" not in workbook.sheetnames:
        workbook.close()
        return

    worksheet = workbook[
        "_BookingsData"
    ]

    worksheet.freeze_panes = "A2"

    worksheet.auto_filter.ref = (
        worksheet.dimensions
    )

    for cell in worksheet[1]:

        cell.font = Font(
            bold=True
        )

        cell.alignment = Alignment(
            horizontal="center",
            vertical="center",
            wrap_text=True,
        )

    for row in worksheet.iter_rows(
        min_row=2
    ):

        for cell in row:

            cell.alignment = Alignment(
                vertical="top",
                wrap_text=True,
            )

    widths = {
        "A": 24,   # Booking ID
        "B": 12,   # Container
        "C": 20,   # Date of Booking
        "D": 40,   # Shipper
        "E": 40,   # Consignee
        "F": 40,   # Notify
        "G": 40,   # Product
        "H": 24,   # Total Pallet
        "I": 50,   # Packing Details
        "J": 35,   # Quantity
        "K": 40,   # Marking
        "L": 45,   # Source File
        "M": 22,   # Created At
        "N": 22,   # Last Updated
    }

    for column, width in widths.items():

        worksheet.column_dimensions[
            column
        ].width = width

    # Không được ẩn sheet backend nếu đây là sheet visible duy nhất.
    # Nếu làm vậy, openpyxl có thể lỗi khi save và trước đây có thể để lại
    # file .xlsx bị truncate / thiếu [Content_Types].xml.
    visible_other_sheets = [
        sheet
        for sheet in workbook.worksheets
        if (
            sheet.title
            != "_BookingsData"
            and sheet.sheet_state == "visible"
        )
    ]

    worksheet.sheet_state = (
        "hidden"
        if visible_other_sheets
        else "visible"
    )

    luu_workbook_an_toan(
        workbook,
        excel_file,
    )

    workbook.close()


def open_storage_folder():
    """Finder is only available in the original local macOS app."""

    if PUBLIC_DEMO_MODE:
        return False

    folder = str(
        st.session_state.get(
            "storage_folder",
            "",
        )
    ).strip()

    if not folder:
        return False

    if sys.platform == "darwin":

        subprocess.run(
            [
                "open",
                folder,
            ],
            check=False,
        )

        return True

    return False


# ==========================================================
# TRẠNG THÁI PHIÊN
# ==========================================================

if "raw_text" not in st.session_state:
    st.session_state.raw_text = ""

if "extracted_data" not in st.session_state:
    st.session_state.extracted_data = []

if "processed_files" not in st.session_state:
    st.session_state.processed_files = []

if "booking_common" not in st.session_state:
    st.session_state.booking_common = {}

if "container_rows" not in st.session_state:
    st.session_state.container_rows = []

if "container_count" not in st.session_state:
    st.session_state.container_count = 1

if "expected_container_count" not in st.session_state:
    st.session_state.expected_container_count = 1

if "analysis_container_count_matches" not in st.session_state:
    st.session_state.analysis_container_count_matches = True

if "current_booking_id" not in st.session_state:
    st.session_state.current_booking_id = ""

if "analysis_id" not in st.session_state:
    st.session_state.analysis_id = 0

if "last_upload_signature" not in st.session_state:
    st.session_state.last_upload_signature = None


if "cargo_type" not in st.session_state:
    st.session_state.cargo_type = "NON DG"

if "dg_info_file_name" not in st.session_state:
    st.session_state.dg_info_file_name = ""

if "dg_info_file_bytes" not in st.session_state:
    st.session_state.dg_info_file_bytes = b""

if "dg_info_raw_text" not in st.session_state:
    st.session_state.dg_info_raw_text = ""

if "dg_bl_text" not in st.session_state:
    st.session_state.dg_bl_text = ""


if "dg_analysis" not in st.session_state:
    st.session_state.dg_analysis = {}

if "bc_analysis" not in st.session_state:
    st.session_state.bc_analysis = {}

if "bc_analysis_booking_id" not in st.session_state:
    st.session_state.bc_analysis_booking_id = ""

if "bc_analysis_source_file" not in st.session_state:
    st.session_state.bc_analysis_source_file = ""

if "bc_analysis_raw_text" not in st.session_state:
    st.session_state.bc_analysis_raw_text = ""


if "storage_folder" not in st.session_state:
    st.session_state.storage_folder = (
        load_storage_folder()
    )


# Detect values edited directly in Excel.
# It is safe to run on every Streamlit rerun because the snapshot
# prevents duplicate tracking entries.
sync_external_excel_changes()

# Backfill / refresh the new process-oriented data model from existing
# booking_data.xlsx records. Existing users keep all current data.
try:

    _startup_booking_df = load_booking_excel()

    if not _startup_booking_df.empty:

        sync_process_model_from_booking_df(
            _startup_booking_df
        )

except Exception:
    # Process analytics must never block the operational booking workflow.
    pass


# Automatic Excel sync while the app is open.
# Native Streamlit fragments are used only when available so older
# environments still work normally with reruns / the Sync button.
if hasattr(
    st,
    "fragment",
):

    @st.fragment(
        run_every="10s"
    )
    def _auto_excel_sync_fragment():

        changed_count = (
            sync_external_excel_changes()
        )

        if changed_count:

            st.rerun()

    _auto_excel_sync_fragment()


# ==========================================================
# CSS
# ==========================================================

st.markdown(
    """
    <style>

    /* ======================================================
       THEME TỰ THÍCH ỨNG LIGHT / DARK
       ======================================================
       - UI tự theo theme của hệ điều hành / trình duyệt.
       - Không dùng màu chữ cố định cho cả hai chế độ.
       - Widget gốc của Streamlit được để Streamlit tự quản lý.
       ====================================================== */

    :root {
        --app-bg: #F7F8FA;
        --card-bg: #FFFFFF;
        --text-main: #111827;
        --text-muted: #4B5563;
        --border: #D1D5DB;

        --accent: #2563EB;
        --accent-hover: #1D4ED8;
        --accent-text: #FFFFFF;

        --info-bg: #DBEAFE;
        --info-text: #1D4ED8;

        /* Ô/chọn chưa active: xanh nhạt để luôn nhìn thấy */
        --control-bg: #DBEAFE;
        --control-bg-hover: #BFDBFE;
        --control-text: #1E3A8A;
        --control-border: #93C5FD;
    }

    @media (prefers-color-scheme: dark) {
        :root {
            --app-bg: #0F172A;
            --card-bg: #1E293B;
            --text-main: #F8FAFC;
            --text-muted: #CBD5E1;
            --border: #475569;

            --accent: #3B82F6;
            --accent-hover: #2563EB;
            --accent-text: #FFFFFF;

            --info-bg: #172554;
            --info-text: #BFDBFE;

            /* Dark Mode vẫn dùng nền xanh nhạt + chữ xanh đậm */
            --control-bg: #DBEAFE;
            --control-bg-hover: #BFDBFE;
            --control-text: #1E3A8A;
            --control-border: #60A5FA;
        }
    }

    /* Toàn app */
    .stApp {
        background: var(--app-bg);
        color: var(--text-main);
    }

    /* Tiêu đề tùy chỉnh */
    .main-title {
        font-size: 34px;
        line-height: 1.15;
        font-weight: 760;
        color: var(--text-main);
        margin: 0 0 8px 0;
    }

    .subtitle {
        color: var(--text-muted);
        font-size: 17px;
        margin: 0 0 24px 0;
    }

    /* Card dùng chung */
    .app-card,
    .card {
        background: var(--card-bg);
        color: var(--text-main);
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 20px;
    }

    /* Metric card riêng của app */
    .app-metric-card {
        min-height: 126px;
        background: var(--card-bg);
        color: var(--text-main);
        border: 1px solid var(--border);
        border-radius: 18px;
        padding: 22px 24px;
        box-sizing: border-box;
        box-shadow: 0 1px 2px rgba(17, 24, 39, 0.05);
    }

    .app-metric-label {
        color: var(--text-muted) !important;
        font-size: 14px;
        font-weight: 650;
        line-height: 1.25;
        margin-bottom: 18px;
        opacity: 1 !important;
    }

    .app-metric-value {
        color: var(--text-main) !important;
        font-size: 34px;
        font-weight: 700;
        line-height: 1.1;
        word-break: break-word;
        opacity: 1 !important;
    }

    /* Button có nền accent nên luôn tương phản ở cả light/dark */
    [data-testid="stButton"] button,
    [data-testid="stDownloadButton"] button,
    [data-testid="stFormSubmitButton"] button {
        background: var(--accent) !important;
        background-color: var(--accent) !important;
        color: var(--accent-text) !important;
        border: 1px solid var(--accent) !important;
        border-radius: 10px !important;
        font-weight: 650 !important;
        box-shadow: none !important;
        opacity: 1 !important;
    }

    [data-testid="stButton"] button *,
    [data-testid="stDownloadButton"] button *,
    [data-testid="stFormSubmitButton"] button * {
        color: var(--accent-text) !important;
        -webkit-text-fill-color: var(--accent-text) !important;
        opacity: 1 !important;
    }

    [data-testid="stButton"] button:hover,
    [data-testid="stDownloadButton"] button:hover,
    [data-testid="stFormSubmitButton"] button:hover,
    [data-testid="stButton"] button:focus,
    [data-testid="stDownloadButton"] button:focus,
    [data-testid="stFormSubmitButton"] button:focus {
        background: var(--accent-hover) !important;
        background-color: var(--accent-hover) !important;
        border-color: var(--accent-hover) !important;
        color: var(--accent-text) !important;
    }

    /* Các vùng custom chỉ đổi nền/viền, không ép text widget gốc */
    [data-testid="stFileUploader"] {
        background: var(--card-bg);
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 16px;
    }

    [data-testid="stExpander"] {
        background: var(--card-bg);
        border-color: var(--border);
        border-radius: 12px;
    }

    [data-testid="stDataFrame"] {
        background: var(--card-bg);
        border-radius: 14px;
    }

    /* Divider tùy chỉnh nếu app có dùng */
    hr {
        border-color: var(--border);
    }



    /* ======================================================
       Ô CHƯA ĐƯỢC CHỌN = XANH NHẠT
       ====================================================== */

    /* Button secondary / button mặc định */
    button[data-testid="stBaseButton-secondary"],
    [data-testid="stBaseButton-secondary"],
    [data-testid="stButton"] button[kind="secondary"] {
        background: var(--control-bg) !important;
        background-color: var(--control-bg) !important;
        color: var(--control-text) !important;
        border: 1px solid var(--control-border) !important;
        box-shadow: none !important;
    }

    button[data-testid="stBaseButton-secondary"] *,
    [data-testid="stBaseButton-secondary"] *,
    [data-testid="stButton"] button[kind="secondary"] * {
        color: var(--control-text) !important;
        -webkit-text-fill-color: var(--control-text) !important;
    }

    button[data-testid="stBaseButton-secondary"]:hover,
    [data-testid="stBaseButton-secondary"]:hover,
    [data-testid="stButton"] button[kind="secondary"]:hover {
        background: var(--control-bg-hover) !important;
        background-color: var(--control-bg-hover) !important;
        border-color: var(--accent) !important;
        color: var(--control-text) !important;
    }

    /* Primary / selected vẫn xanh đậm + chữ trắng */
    button[data-testid="stBaseButton-primary"],
    [data-testid="stButton"] button[kind="primary"] {
        background: var(--accent) !important;
        background-color: var(--accent) !important;
        color: #FFFFFF !important;
        border-color: var(--accent) !important;
    }

    button[data-testid="stBaseButton-primary"] *,
    [data-testid="stButton"] button[kind="primary"] * {
        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;
    }

    /* Tabs: chưa chọn xanh nhạt, đang chọn xanh đậm */
    [data-baseweb="tab"][aria-selected="false"] {
        background: var(--control-bg) !important;
        color: var(--control-text) !important;
        border-radius: 10px 10px 0 0 !important;
        border: 1px solid var(--control-border) !important;
    }

    [data-baseweb="tab"][aria-selected="false"] * {
        color: var(--control-text) !important;
    }

    [data-baseweb="tab"][aria-selected="true"] {
        background: var(--accent) !important;
        color: #FFFFFF !important;
        border-radius: 10px 10px 0 0 !important;
    }

    [data-baseweb="tab"][aria-selected="true"] * {
        color: #FFFFFF !important;
    }

    /* Radio option: chưa chọn xanh nhạt */
    [data-testid="stRadio"] label {
        background: var(--control-bg);
        color: var(--control-text);
        border: 1px solid var(--control-border);
        border-radius: 10px;
        padding: 7px 10px;
        margin-right: 6px;
    }

    [data-testid="stRadio"] label * {
        color: var(--control-text);
    }

    /* Trình duyệt hiện đại hỗ trợ :has(): option đang chọn */
    [data-testid="stRadio"] label:has(input:checked) {
        background: var(--accent) !important;
        color: #FFFFFF !important;
        border-color: var(--accent) !important;
    }

    [data-testid="stRadio"] label:has(input:checked) * {
        color: #FFFFFF !important;
    }

    /* Segmented control / các lựa chọn có aria-pressed */
    button[aria-pressed="false"] {
        background: var(--control-bg) !important;
        color: var(--control-text) !important;
        border-color: var(--control-border) !important;
    }

    button[aria-pressed="false"] * {
        color: var(--control-text) !important;
    }

    button[aria-pressed="true"] {
        background: var(--accent) !important;
        color: #FFFFFF !important;
        border-color: var(--accent) !important;
    }

    button[aria-pressed="true"] * {
        color: #FFFFFF !important;
    }

    /* Selectbox khi chưa mở: nền xanh nhạt để không chìm trong Dark Mode */
    [data-baseweb="select"] > div {
        background: var(--control-bg) !important;
        border-color: var(--control-border) !important;
        color: var(--control-text) !important;
    }

    [data-baseweb="select"] span,
    [data-baseweb="select"] div {
        color: var(--control-text);
    }


</style>
    """,
    unsafe_allow_html=True,
)


# ==========================================================
# THANH ĐIỀU HƯỚNG
# ==========================================================

with st.sidebar:

    st.markdown(
        """
        <h2 style="margin-bottom:0;">
            BOOKING AUTO
        </h2>

        <p style="
            color:#60a5fa;
            margin-top:0;
            margin-bottom:30px;
        ">
            Logistics Automation
        </p>
        """,
        unsafe_allow_html=True,
    )

    page = st.radio(
        "Navigation",
        [
            "Dashboard",
            "Data Analysis",
            "New Booking",
            "Process Overview",
            "Documents",
            "Deadlines",
            "Bookings",
            "Tracking",
            "B/L",
            "Settings",
        ],
        label_visibility="collapsed",
    )

    if PUBLIC_DEMO_MODE:
        st.warning("PUBLIC DEMO — synthetic data only. Do not upload real company documents.")
        if st.button("Load synthetic booking sample", use_container_width=True, key="seed_demo"):
            make_demo_workbook(get_excel_file())
            tracker.clear_snapshot()
            st.success("Loaded synthetic sample for this browser session only.")
            st.rerun()
        if st.button("Reset my demo data", use_container_width=True, key="reset_demo"):
            import shutil
            demo_book = get_excel_file()
            if demo_book.exists():
                demo_book.unlink()
            tracker.clear_snapshot()
            # Delete only per-session SQLite and uploads; never files in project root.
            for folder in (DATA_DIR, UPLOAD_DIR):
                if folder.exists():
                    shutil.rmtree(folder)
                folder.mkdir(parents=True, exist_ok=True)
            st.rerun()


def hien_thi_chi_so(
    cot,
    nhan,
    gia_tri,
):
    """
    Hiển thị metric bằng HTML riêng.

    Dùng card riêng thay cho st.metric để tránh khác biệt màu chữ
    giữa các phiên bản Streamlit và theme của trình duyệt.
    """
    import html

    nhan_an_toan = html.escape(
        str(
            nhan
            if nhan is not None
            else ""
        )
    )

    gia_tri_an_toan = html.escape(
        str(
            gia_tri
            if gia_tri is not None
            else "-"
        )
    )

    cot.markdown(
        f"""
        <div class="app-metric-card">
            <div class="app-metric-label">
                {nhan_an_toan}
            </div>
            <div class="app-metric-value">
                {gia_tri_an_toan}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ==========================================================
# DATA ANALYST VIEW — preserves the original operational pages
# ==========================================================

if page == "Data Analysis":
    render_data_analytics(load_booking_excel())

# ==========================================================
# TRANG TỔNG QUAN
# ==========================================================

if page == "Dashboard":

    st.markdown(
        '<div class="main-title">Dashboard</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="subtitle">'
        'Overview and manage saved bookings'
        '</div>',
        unsafe_allow_html=True,
    )

    # Clicking this forces an immediate rerun/sync. The app also checks
    # Excel automatically on every rerun and, on supported Streamlit
    # versions, periodically while the page is open.
    st.button(
        "🔄 Sync Extracted Data / Excel",
        type="primary",
        use_container_width=False,
        key="dashboard_check_excel_changes",
    )

    booking_df = load_booking_excel()

    total_bookings = 0
    total_containers = 0

    if not booking_df.empty:

        if "Booking ID" in booking_df.columns:

            total_bookings = (
                booking_df[
                    "Booking ID"
                ]
                .dropna()
                .nunique()
            )

        if "Container" in booking_df.columns:

            unique_container_pairs = set()

            for _, dashboard_row in (
                booking_df.iterrows()
            ):

                unique_container_pairs.add(
                    (
                        clean_data_value(
                            dashboard_row.get(
                                "Booking ID",
                                "",
                            )
                        ),
                        normalize_container_key(
                            dashboard_row.get(
                                "Container",
                                "",
                            )
                        ),
                    )
                )

            total_containers = len(
                unique_container_pairs
            )

        else:

            total_containers = len(
                booking_df
            )

    c1, c2, c3, c4 = st.columns(4)

    hien_thi_chi_so(
        c1,
        "Total Bookings",
        total_bookings,
    )

    hien_thi_chi_so(
        c2,
        "Containers",
        total_containers,
    )

    closing_soon_count = 0
    departed_count = 0

    if not booking_df.empty:

        seen_booking_ids = set()

        for _, metric_row in booking_df.iterrows():

            booking_id_value = clean_data_value(
                metric_row.get(
                    "Booking ID",
                    "",
                )
            )

            if (
                not booking_id_value
                or booking_id_value in seen_booking_ids
            ):
                continue

            seen_booking_ids.add(
                booking_id_value
            )

            cutoff_states = []

            for cutoff_field in [
                "SI Cut-off",
                "VGM Cut-off",
                "CY Cut-off",
                "Documentation Cut-off",
            ]:

                state, _ = deadline_status(
                    metric_row.get(
                        cutoff_field,
                        "",
                    )
                )

                if state:
                    cutoff_states.append(
                        state
                    )

            if "Due Soon" in cutoff_states:
                closing_soon_count += 1

            etd_dt = parse_booking_datetime(
                metric_row.get(
                    "ETD",
                    "",
                )
            )

            if (
                etd_dt is not None
                and etd_dt < datetime.now()
            ):
                departed_count += 1

    hien_thi_chi_so(
        c3,
        "Closing Soon",
        closing_soon_count,
    )

    hien_thi_chi_so(
        c4,
        "ETD Passed",
        departed_count,
    )

    st.write("")

    excel_file = get_excel_file()

    if total_bookings == 0:

        if excel_file is None:

            st.info(
                "No booking storage file has been "
                "created yet. Export a booking first."
            )

        else:

            st.info(
                "No bookings saved yet. "
                "Create your first booking to get started."
            )

    else:

        # ==================================================
        # SAVED BOOKING LIST
        # ==================================================

        st.subheader(
            "Saved Bookings"
        )

        dashboard_summary = (
            build_dashboard_summary(
                booking_df
            )
        )

        st.dataframe(
            dashboard_summary,
            use_container_width=True,
            hide_index=True,
        )

        st.divider()

        # ==================================================
        # VIEW BOOKING - READ ONLY
        # ==================================================

        booking_ids = (
            dashboard_summary[
                "Booking ID"
            ]
            .dropna()
            .astype(str)
            .tolist()
        )

        selected_booking = st.selectbox(
            "View Booking",
            booking_ids,
            key="dashboard_booking_selector",
        )

        selected_rows = (
            booking_df[
                booking_df[
                    "Booking ID"
                ].astype(str)
                == str(selected_booking)
            ]
            .copy()
            .reset_index(
                drop=True
            )
        )

        if not selected_rows.empty:

            first_row = selected_rows.iloc[0]

            created_at = clean_data_value(
                first_row.get(
                    "Created At",
                    "",
                )
            )

            if created_at:
                st.caption(
                    f"Created At: {created_at}"
                )

            last_updated_values = [
                clean_data_value(value)
                for value in selected_rows.get(
                    "Last Updated",
                    pd.Series(dtype=str),
                ).tolist()
                if clean_data_value(value)
            ]

            if last_updated_values:

                last_edited = max(
                    last_updated_values
                )

                st.caption(
                    f"(edited at {last_edited})"
                )

            st.subheader(
                "Booking Information"
            )

            cargo_left, cargo_right = st.columns(
                2
            )

            cargo_left.text_input(
                "Cargo Type",
                value=(
                    st.session_state.cargo_type
                ),
                disabled=True,
                key=(
                    f"cargo_type_display_"
                    f"{st.session_state.analysis_id}"
                ),
            )

            cargo_right.text_input(
                "DG Information File",
                value=(
                    st.session_state.dg_info_file_name
                    if st.session_state.cargo_type
                    == "DG"
                    else ""
                ),
                disabled=True,
                key=(
                    f"dg_file_display_"
                    f"{st.session_state.analysis_id}"
                ),
            )

            common_candidate_fields = [
                "Date of Booking",
                "Shipper",
                "Consignee",
                "Notify",
                "Product",
            ]

            dashboard_common_fields = []
            dashboard_different_fields = []

            for field_name in common_candidate_fields:

                field_values = [
                    normalize_audit_value(
                        row.get(
                            field_name,
                            "",
                        )
                    )
                    for _, row in selected_rows.iterrows()
                ]

                if (
                    field_values
                    and len(set(field_values)) == 1
                ):
                    dashboard_common_fields.append(
                        field_name
                    )
                else:
                    dashboard_different_fields.append(
                        field_name
                    )

            for field_name in dashboard_common_fields:

                field_value = clean_data_value(
                    first_row.get(
                        field_name,
                        "",
                    )
                )

                st.text_area(
                    field_name,
                    value=field_value,
                    height=(
                        70
                        if field_name == "Date of Booking"
                        else 110
                    ),
                    disabled=True,
                    key=(
                        f"dashboard_readonly_"
                        f"{selected_booking}_"
                        f"{field_name}"
                    ),
                )

            if dashboard_different_fields:

                st.info(
                    "Some booking fields are different between "
                    "containers, so they are shown inside each "
                    "container below."
                )

            st.divider()

            confirmation_visible = any(
                clean_data_value(
                    first_row.get(
                        field_name,
                        "",
                    )
                )
                for field_name in BOOKING_CONFIRMATION_FIELDS
            )

            if confirmation_visible:

                st.subheader(
                    "Booking Confirmation & Deadlines"
                )

                confirmation_display_fields = [
                    "Carrier Booking No",
                    "Carrier",
                    "Vessel / Voyage",
                    "Port of Loading",
                    "Port of Discharge",
                    "Final Destination",
                    "CY Cut-off",
                    "VGM Cut-off",
                    "SI Cut-off",
                    "Documentation Cut-off",
                    "POL ETA",
                    "ETD",
                    "ETA",
                    "Booking Confirmation File",
                ]

                display_rows = []

                for field_name in confirmation_display_fields:

                    value = clean_data_value(
                        first_row.get(
                            field_name,
                            "",
                        )
                    )

                    if not value:
                        continue

                    status = ""

                    if field_name in [
                        "CY Cut-off",
                        "VGM Cut-off",
                        "SI Cut-off",
                        "Documentation Cut-off",
                    ]:

                        status, _ = deadline_status(
                            value
                        )

                    display_rows.append(
                        {
                            "Field": field_name,
                            "Value": value,
                            "Status": status,
                        }
                    )

                if display_rows:

                    st.dataframe(
                        pd.DataFrame(
                            display_rows
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )

                st.divider()

            st.subheader(
                "Container Details"
            )

            # Count duplicate container labels defensively.
            # Old/manual Excel layouts can contain several rows for the
            # same Booking ID + Container. Streamlit widget keys must still
            # be unique, and the Dashboard must continue rendering so the
            # Delete Booking controls remain available.
            dashboard_container_keys = [
                normalize_container_key(
                    row.get(
                        "Container",
                        row_number + 1,
                    )
                )
                for row_number, row in selected_rows.iterrows()
            ]

            dashboard_container_key_counts = {
                key: dashboard_container_keys.count(key)
                for key in set(dashboard_container_keys)
            }

            dashboard_container_occurrence = {}

            for row_number, row in (
                selected_rows.iterrows()
            ):

                container_value = row.get(
                    "Container",
                    row_number + 1,
                )

                container_key = normalize_container_key(
                    container_value
                )

                dashboard_container_occurrence[
                    container_key
                ] = (
                    dashboard_container_occurrence.get(
                        container_key,
                        0,
                    )
                    + 1
                )

                occurrence_no = (
                    dashboard_container_occurrence[
                        container_key
                    ]
                )

                row_widget_uid = (
                    f"{container_key}_"
                    f"{occurrence_no}_"
                    f"{row_number}"
                )

                expander_label = (
                    f"Container {container_value}"
                )

                if (
                    dashboard_container_key_counts.get(
                        container_key,
                        0,
                    )
                    > 1
                ):
                    expander_label += (
                        f" · entry {occurrence_no}"
                    )

                with st.expander(
                    expander_label,
                    expanded=True,
                ):

                    source_file = clean_data_value(
                        row.get(
                            "Source File",
                            "",
                        )
                    )

                    if source_file:
                        st.caption(
                            f"Source File: {source_file}"
                        )

                    row_last_updated = clean_data_value(
                        row.get(
                            "Last Updated",
                            "",
                        )
                    )

                    if row_last_updated:
                        st.caption(
                            f"(edited at {row_last_updated})"
                        )

                    for field_name in dashboard_different_fields:

                        st.text_area(
                            field_name,
                            value=clean_data_value(
                                row.get(
                                    field_name,
                                    "",
                                )
                            ),
                            height=(
                                70
                                if field_name == "Date of Booking"
                                else 110
                            ),
                            disabled=True,
                            key=(
                                f"dashboard_readonly_"
                                f"{selected_booking}_"
                                f"{row_widget_uid}_"
                                f"{field_name}"
                            ),
                        )

                    for field_name, height in [
                        ("Total Pallet", 90),
                        ("Packing Details", 140),
                        ("Quantity", 120),
                        ("Marking", 140),
                    ]:

                        st.text_area(
                            field_name,
                            value=clean_data_value(
                                row.get(
                                    field_name,
                                    "",
                                )
                            ),
                            height=height,
                            disabled=True,
                            key=(
                                f"dashboard_readonly_"
                                f"{selected_booking}_"
                                f"{row_widget_uid}_"
                                f"{field_name}"
                            ),
                        )

            st.divider()

            # ==============================================
            # DELETE BOOKING ONLY
            # ==============================================

            st.subheader(
                "Delete Booking"
            )

            st.caption(
                "Deleting permanently removes this booking from "
                "the Excel workbook AND tracking.db, including "
                "process events, field-change history, and snapshot data."
            )

            confirm_delete = st.checkbox(
                "Confirm delete",
                key=(
                    f"dashboard_confirm_delete_"
                    f"{selected_booking}"
                ),
            )

            delete_booking = st.button(
                "🗑️ Delete Booking",
                use_container_width=True,
                disabled=(
                    not confirm_delete
                ),
                key=(
                    f"dashboard_delete_"
                    f"{selected_booking}"
                ),
            )

            if delete_booking:

                excel_file = get_excel_file()

                if excel_file is None:

                    st.error(
                        "Storage file not found."
                    )

                else:

                    remaining_df = booking_df[
                        booking_df[
                            "Booking ID"
                        ].astype(str)
                        != str(selected_booking)
                    ].copy()

                    try:

                        write_booking_workbook(
                            excel_file,
                            remaining_df,
                        )

                        # Keep the comparison baseline aligned with Excel.
                        update_tracking_snapshot(
                            remaining_df
                        )

                        # User-requested permanent delete:
                        # remove the same Booking ID from tracking.db too.
                        tracker.delete_booking(
                            selected_booking
                        )

                        process_repo.delete_booking(
                            selected_booking
                        )

                        # Keep database tracking only for bookings that
                        # still exist. Never re-add the booking just deleted.
                        prune_tracking_to_current_bookings(
                            remaining_df,
                            include_current_session=True,
                            exclude_booking_ids=[
                                selected_booking
                            ],
                        )

                        build_excel_tracking_sheets(
                            excel_file
                        )

                    except Exception as error:

                        st.error(
                            "Could not fully delete the booking. "
                            "If booking_data.xlsx is open in Excel, "
                            "close it and try again.\n\n"
                            f"Error: {error}"
                        )

                    else:

                        st.success(
                            f"Booking {selected_booking} was permanently "
                            "deleted from Excel and tracking.db."
                        )

                        st.rerun()

        if (
            excel_file is not None
            and excel_file.exists()
        ):

            st.caption(
                f"Storage file: {excel_file}"
            )

            if st.button(
                "📂 Open Storage Folder",
                use_container_width=True,
                key="dashboard_open_storage",
            ):

                open_storage_folder()


# ==========================================================
# TẠO BOOKING MỚI
# ==========================================================

elif page == "New Booking":

    st.markdown(
        '<div class="main-title">New Booking</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="subtitle">'
        'Import and analyze Packing Lists'
        '</div>',
        unsafe_allow_html=True,
    )

    pl_engine = (
        bo_dieu_phoi_chung_tu
        .engine_cho_loai_chung_tu(
            "Packing List"
        )
    )

    st.info(
        "Processing Engine: Rule-based. "
        "Packing Lists are intentionally processed without AI."
    )

    # ======================================================
    # PHÂN LOẠI HÀNG
    # ======================================================

    st.subheader(
        "Cargo Classification"
    )

    cargo_type = st.radio(
        "Cargo Type",
        options=[
            "NON DG",
            "DG",
        ],
        index=(
            1
            if st.session_state.cargo_type
            == "DG"
            else 0
        ),
        horizontal=True,
        help=(
            "Choose DG for dangerous goods. "
            "DG shipments require an additional DG information file."
        ),
        key="new_booking_cargo_type",
    )

    st.session_state.cargo_type = (
        cargo_type
    )

    dg_info_file = None

    if cargo_type == "DG":

        dg_engine = (
            bo_dieu_phoi_chung_tu
            .engine_cho_loai_chung_tu(
                "DG Information"
            )
        )

        st.warning(
            "DG cargo requires an additional DG information document. "
            "This document will follow the shipment through to the B/L step."
        )

        st.caption(
            "DG Processing Engine: "
            + dg_engine.get(
                "engine",
                "Manual / raw-text fallback",
            )
        )

        dg_info_file = st.file_uploader(
            "Upload DG Information",
            type=None,
            accept_multiple_files=False,
            help=(
                "Attach the dangerous-goods information document "
                "for this shipment."
            ),
            key="new_booking_dg_info",
        )

        if dg_info_file is not None:

            st.session_state.dg_info_file_name = (
                dg_info_file.name
            )

            st.session_state.dg_info_file_bytes = (
                dg_info_file.getvalue()
            )

            try:

                st.session_state.dg_info_raw_text = (
                    bo_doc_tep.doc_bytes(
                        dg_info_file.name,
                        dg_info_file.getvalue(),
                    )
                )

                # Phân tích DG theo mô hình hybrid.
                # Khi AI chưa bật, hệ thống vẫn giữ raw text để review thủ công.
                dg_analysis = (
                    bo_dieu_phoi_chung_tu
                    .phan_tich_dg(
                        st.session_state.dg_info_raw_text
                    )
                )

                st.session_state.dg_bl_text = (
                    clean_data_value(
                        dg_analysis.get(
                            "dg_bl_text",
                            "",
                        )
                    )
                )

                st.session_state[
                    "dg_analysis"
                ] = dg_analysis

            except Exception:

                # Nếu file không có text layer, vẫn giữ file và cho phép
                # người dùng nhập/review DG ở bước B/L.
                st.session_state.dg_info_raw_text = ""
                st.session_state[
                    "dg_analysis"
                ] = {}

            if (
                not st.session_state.dg_bl_text
                and st.session_state.dg_info_raw_text
            ):

                st.session_state.dg_bl_text = (
                    st.session_state.dg_info_raw_text
                )

            st.success(
                f"DG information attached: {dg_info_file.name}"
            )

    else:

        st.session_state.dg_info_file_name = ""
        st.session_state.dg_info_file_bytes = b""
        st.session_state.dg_info_raw_text = ""
        st.session_state.dg_bl_text = ""

    # ======================================================
    # SỐ LƯỢNG CONTAINER
    # ======================================================

    container_count = st.number_input(
        "Number of Containers",
        min_value=1,
        max_value=50,
        value=1,
        step=1,
        help=(
            "One uploaded file = one container. "
            "If one file contains multiple PACKING LIST pages, "
            "those pages still belong to the same container."
        ),
    )

    # ======================================================
    # TẢI TỆP
    # ======================================================

    uploaded_files = st.file_uploader(
        "Upload Packing Lists",
        type=None,
        accept_multiple_files=True,
        help=(
            "Upload exactly one Packing List file per container. "
            "Multiple PACKING LIST pages inside the same file "
            "remain part of that one container."
        ),
    )

    # ======================================================
    # THÔNG TIN TỆP
    # ======================================================

    if uploaded_files:

        uploaded_count = len(
            uploaded_files
        )

        dg_signature = (
            (
                dg_info_file.name,
                dg_info_file.size,
            )
            if dg_info_file is not None
            else None
        )

        upload_signature = (
            cargo_type,
            tuple(
                (
                    file.name,
                    file.size,
                )
                for file in uploaded_files
            ),
            dg_signature,
        )

        if (
            upload_signature
            != st.session_state.last_upload_signature
        ):

            # Tạo Booking ID ngay khi nhận file
            st.session_state.current_booking_id = (
                "BK-"
                + datetime.now().strftime(
                    "%Y%m%d-%H%M%S"
                )
            )

            tracker.log(
                booking_id=(
                    st.session_state.current_booking_id
                ),
                event_type="UPLOAD",
                event_name="Packing Lists uploaded",
                detail=(
                    f"{len(uploaded_files)} "
                    f"Packing List(s) uploaded. "
                    f"Cargo Type: {cargo_type}."
                ),
            )

            if (
                cargo_type == "DG"
                and dg_info_file is not None
            ):

                tracker.log(
                    booking_id=(
                        st.session_state.current_booking_id
                    ),
                    event_type="FILE_RECEIVED",
                    event_name="DG Information file received",
                    source_file=dg_info_file.name,
                    detail=(
                        "Dangerous-goods information attached "
                        "to this shipment."
                    ),
                )

            for file_index, file in enumerate(
                uploaded_files,
                start=1,
            ):

                tracker.log(
                    booking_id=(
                        st.session_state.current_booking_id
                    ),
                    event_type="FILE_RECEIVED",
                    event_name="Packing List file received",
                    source_file=file.name,
                    container_no=file_index,
                )

            st.session_state.last_upload_signature = (
                upload_signature
            )

        if uploaded_count == int(container_count):

            st.success(
                f"{uploaded_count} file(s) uploaded = "
                f"{uploaded_count} container(s). "
                "Multiple PACKING LIST pages inside one file "
                "will stay inside that same container."
            )

        else:

            st.warning(
                f"Expected {int(container_count)} container(s), "
                f"so upload exactly {int(container_count)} file(s). "
                f"Currently uploaded: {uploaded_count}."
            )

        file_table = []

        for uploaded_file in uploaded_files:

            file_table.append(
                {
                    "File":
                        uploaded_file.name,

                    "Size (KB)":
                        round(
                            uploaded_file.size
                            / 1024,
                            2,
                        ),

                    "Type":
                        (
                            Path(
                                uploaded_file.name
                            )
                            .suffix
                            .upper()
                        ),
                }
            )

        st.dataframe(
            pd.DataFrame(
                file_table
            ),
            use_container_width=True,
            hide_index=True,
        )

    # ======================================================
    # NÚT PHÂN TÍCH
    # ======================================================

    dg_requirement_met = (
        cargo_type == "NON DG"
        or dg_info_file is not None
    )

    files_match = (
        bool(uploaded_files)
        and len(uploaded_files)
        == int(container_count)
        and dg_requirement_met
    )

    if (
        cargo_type == "DG"
        and dg_info_file is None
    ):

        st.info(
            "Attach the DG Information file before analyzing the Packing List."
        )

    analyze = st.button(
        "Analyze Packing Lists",
        type="primary",
        use_container_width=True,
        disabled=not files_match,
    )

    # ======================================================
    # PHÂN TÍCH
    # ======================================================

    if analyze:

        expected_container_count = int(
            container_count
        )

        st.session_state.expected_container_count = (
            expected_container_count
        )

        tracker.log(
            booking_id=(
                st.session_state.current_booking_id
            ),
            event_type="ANALYSIS",
            event_name="Analysis started",
            detail=(
                f"Analyzing {len(uploaded_files)} file(s) "
                f"as {expected_container_count} container(s). "
                "Rule: one physical file equals one container."
            ),
        )

        raw_results = []
        extracted_results = []

        success_file_count = 0
        error_count = 0

        progress = st.progress(0)

        for file_index, uploaded_file in enumerate(
            uploaded_files,
            start=1,
        ):

            try:

                file_bytes = (
                    uploaded_file.getvalue()
                )

                raw = bo_doc_tep.doc_bytes(
                    uploaded_file.name,
                    file_bytes,
                )

                # CRITICAL BUSINESS RULE:
                # ONE PHYSICAL FILE = ONE CONTAINER.
                # Repeated PACKING LIST pages are combined inside
                # bo_phan_tich_packing.analyze(), while pallet lines stay separate.
                extracted = bo_phan_tich_packing.analyze(
                    raw
                )

                if not any(
                    str(
                        extracted.get(
                            field,
                            "",
                        )
                    ).strip()
                    for field in [
                        "date_of_booking",
                        "shipper",
                        "consignee",
                        "notify",
                        "product",
                        "total_pallet",
                        "packing_details",
                        "quantity",
                        "marking",
                    ]
                ):

                    raise ValueError(
                        "No Packing List data could be extracted."
                    )

                packing_list_pages = int(
                    extracted.get(
                        "packing_list_pages",
                        1,
                    )
                    or 1
                )

                extracted[
                    "container_no"
                ] = file_index

                extracted[
                    "source_file"
                ] = uploaded_file.name

                extracted_results.append(
                    extracted
                )

                raw_results.append(
                    "\n"
                    "========================================\n"
                    f"CONTAINER: {file_index}\n"
                    f"FILE: {uploaded_file.name}\n"
                    f"PACKING LIST PAGES IN THIS CONTAINER: "
                    f"{packing_list_pages}\n"
                    "========================================\n"
                    f"{raw}"
                )

                pallet_total = extracted.get(
                    "container_pallet_total",
                    0,
                )

                tracker.log(
                    booking_id=(
                        st.session_state.current_booking_id
                    ),
                    event_type="EXTRACT",
                    event_name=(
                        f"Container "
                        f"{file_index} extracted"
                    ),
                    source_file=(
                        uploaded_file.name
                    ),
                    container_no=(
                        file_index
                    ),
                    detail=(
                        f"One file = one container. "
                        f"Packing List pages inside file: "
                        f"{packing_list_pages}. "
                        f"Pallet breakdown total check: "
                        f"{pallet_total}."
                    ),
                )

                success_file_count += 1

            except Exception as error:

                error_count += 1

                tracker.log(
                    booking_id=(
                        st.session_state.current_booking_id
                    ),
                    event_type="ERROR",
                    event_name=(
                        "Packing List extraction failed"
                    ),
                    source_file=(
                        uploaded_file.name
                    ),
                    container_no=(
                        file_index
                    ),
                    detail=str(error),
                )

                st.error(
                    f"Error reading "
                    f"{uploaded_file.name}: "
                    f"{error}"
                )

            progress.progress(
                file_index
                / len(uploaded_files)
            )

        detected_container_count = len(
            extracted_results
        )

        count_matches = (
            detected_container_count
            == expected_container_count
        )

        st.session_state.raw_text = (
            "\n".join(
                raw_results
            )
        )

        st.session_state.extracted_data = (
            extracted_results
        )

        common_data, container_rows = (
            merge_booking_data(
                extracted_results
            )
        )

        st.session_state.booking_common = (
            common_data
        )

        st.session_state.container_rows = (
            container_rows
        )

        st.session_state.container_count = (
            detected_container_count
        )

        st.session_state.analysis_container_count_matches = (
            count_matches
        )

        st.session_state.processed_files = [
            file.name
            for file in uploaded_files
        ]

        st.session_state.analysis_id += 1

        tracker.log(
            booking_id=(
                st.session_state.current_booking_id
            ),
            event_type="ANALYSIS",
            event_name="Analysis completed",
            detail=(
                f"Files successful: "
                f"{success_file_count}. "
                f"Files failed: {error_count}. "
                f"Expected containers: "
                f"{expected_container_count}. "
                f"Extracted containers: "
                f"{detected_container_count}. "
                "One file equals one container."
            ),
        )

        if detected_container_count == 0:

            st.error(
                "No container data was extracted."
            )

        elif not count_matches:

            st.error(
                f"Expected {expected_container_count} "
                f"container(s), but only "
                f"{detected_container_count} file/container(s) "
                "were extracted successfully."
            )

        elif error_count > 0:

            st.warning(
                f"Extracted {detected_container_count} "
                f"container(s), but {error_count} "
                f"file(s) had extraction errors."
            )

        else:

            st.success(
                f"Analyzed {detected_container_count} "
                f"container(s) from "
                f"{success_file_count} file(s). "
                "Repeated PACKING LIST pages inside a file "
                "remain in the same container."
            )

    # ======================================================
    # RESULTS
    # ======================================================

    if st.session_state.extracted_data:

        st.divider()

        if st.session_state.current_booking_id:

            st.caption(
                "Booking ID: "
                f"{st.session_state.current_booking_id}"
            )

        tab1, tab2 = st.tabs(
            [
                "Extracted Data",
                "Raw Text",
            ]
        )

        # ==================================================
        # EXTRACTED DATA
        # ==================================================

        with tab1:

            st.subheader(
                "Booking Information"
            )

            st.caption(
                f"Booking ID: "
                f"{st.session_state.current_booking_id}"
            )

            common = (
                st.session_state.booking_common
            )

            field_names = {
                "date_of_booking": "Date of Booking",
                "shipper": "Shipper",
                "consignee": "Consignee",
                "notify": "Notify",
                "product": "Product",
                "total_pallet": "Total Pallet",
                "packing_details": "Packing Details",
                "quantity": "Quantity",
                "marking": "Marking",
            }

            # ==========================================
            # COMMON BOOKING FIELDS
            # ==========================================

            edited_common = {}

            common_field_order = [
                "date_of_booking",
                "shipper",
                "consignee",
                "notify",
                "product",
            ]

            for field in common_field_order:

                if field not in common:
                    continue

                value = common.get(
                    field,
                    "",
                )

                label = field_names[field]

                if field == "date_of_booking":

                    edited_common[field] = (
                        st.text_input(
                            label,
                            value=str(value),
                            key=(
                                f"common_"
                                f"{st.session_state.analysis_id}_"
                                f"{field}"
                            ),
                        )
                    )

                else:

                    edited_common[field] = (
                        st.text_area(
                            label,
                            value=str(value),
                            height=120,
                            key=(
                                f"common_"
                                f"{st.session_state.analysis_id}_"
                                f"{field}"
                            ),
                        )
                    )

            # ==========================================
            # CONTAINER DETAILS
            # ==========================================

            st.divider()

            st.subheader(
                "Container Details"
            )

            st.caption(
                f"Total Containers: "
                f"{st.session_state.container_count}"
            )

            edited_container_rows = []

            for container_index, row in enumerate(
                st.session_state.container_rows,
                start=1,
            ):

                container_number = row.get(
                    "Container",
                    container_index,
                )

                with st.expander(
                    f"Container {container_number}",
                    expanded=True,
                ):

                    source_file = row.get(
                        "Source File",
                        "",
                    )

                    if source_file:
                        st.caption(
                            f"Packing List: {source_file}"
                        )

                    edited_row = {
                        "Container": container_number,
                        "Source File": source_file,
                        "Presentation Segment Sizes":
                            row.get(
                                "Presentation Segment Sizes",
                                "[]",
                            ),
                    }

                    if "date_of_booking" in row:

                        edited_row[
                            "Date of Booking"
                        ] = st.text_input(
                            "Date of Booking",
                            value=str(
                                row.get(
                                    "date_of_booking",
                                    "",
                                )
                            ),
                            key=(
                                f"container_"
                                f"{st.session_state.analysis_id}_"
                                f"{container_number}_date"
                            ),
                        )

                    if "shipper" in row:

                        edited_row[
                            "Shipper"
                        ] = st.text_area(
                            "Shipper",
                            value=str(
                                row.get(
                                    "shipper",
                                    "",
                                )
                            ),
                            height=120,
                            key=(
                                f"container_"
                                f"{st.session_state.analysis_id}_"
                                f"{container_number}_shipper"
                            ),
                        )

                    if "consignee" in row:

                        edited_row[
                            "Consignee"
                        ] = st.text_area(
                            "Consignee",
                            value=str(
                                row.get(
                                    "consignee",
                                    "",
                                )
                            ),
                            height=120,
                            key=(
                                f"container_"
                                f"{st.session_state.analysis_id}_"
                                f"{container_number}_consignee"
                            ),
                        )

                    if "notify" in row:

                        edited_row[
                            "Notify"
                        ] = st.text_area(
                            "Notify",
                            value=str(
                                row.get(
                                    "notify",
                                    "",
                                )
                            ),
                            height=120,
                            key=(
                                f"container_"
                                f"{st.session_state.analysis_id}_"
                                f"{container_number}_notify"
                            ),
                        )

                    if "product" in row:

                        edited_row[
                            "Product"
                        ] = st.text_area(
                            "Product",
                            value=str(
                                row.get(
                                    "product",
                                    "",
                                )
                            ),
                            height=100,
                            key=(
                                f"container_"
                                f"{st.session_state.analysis_id}_"
                                f"{container_number}_product"
                            ),
                        )

                    edited_row[
                        "Total Pallet"
                    ] = st.text_area(
                        "Total Pallet",
                        value=str(
                            row.get(
                                "total_pallet",
                                "",
                            )
                        ),
                        height=100,
                        key=(
                            f"container_"
                            f"{st.session_state.analysis_id}_"
                            f"{container_number}_pallet"
                        ),
                    )

                    edited_row[
                        "Packing Details"
                    ] = st.text_area(
                        "Packing Details",
                        value=str(
                            row.get(
                                "packing_details",
                                "",
                            )
                        ),
                        height=150,
                        key=(
                            f"container_"
                            f"{st.session_state.analysis_id}_"
                            f"{container_number}_packing"
                        ),
                    )

                    edited_row[
                        "Quantity"
                    ] = st.text_area(
                        "Quantity",
                        value=str(
                            row.get(
                                "quantity",
                                "",
                            )
                        ),
                        height=130,
                        key=(
                            f"container_"
                            f"{st.session_state.analysis_id}_"
                            f"{container_number}_quantity"
                        ),
                    )

                    edited_row[
                        "Marking"
                    ] = st.text_area(
                        "Marking",
                        value=str(
                            row.get(
                                "marking",
                                "",
                            )
                        ),
                        height=150,
                        key=(
                            f"container_"
                            f"{st.session_state.analysis_id}_"
                            f"{container_number}_marking"
                        ),
                    )

                    edited_container_rows.append(
                        edited_row
                    )

            edited_container_df = pd.DataFrame(
                edited_container_rows
            )

            # ==========================================
            # EXPORT TO EXCEL
            # ==========================================

            if not edited_container_df.empty:

                st.divider()

                current_excel_file = get_excel_file()

                if current_excel_file is None:

                    st.info(
                        "On the first export, choose where "
                        "booking_data.xlsx will be stored."
                    )

                else:

                    st.caption(
                        f"Storage file: {current_excel_file}"
                    )

                    if st.button(
                        "📂 Change Storage Folder",
                        use_container_width=True,
                    ):

                        selected_folder = (
                            choose_storage_folder()
                        )

                        if selected_folder:

                            try:

                                save_storage_folder(
                                    selected_folder
                                )

                                st.success(
                                    "Storage folder updated."
                                )

                                st.rerun()

                            except Exception as error:

                                st.error(
                                    f"Could not use folder: "
                                    f"{error}"
                                )

                if (
                    not st.session_state
                    .analysis_container_count_matches
                ):

                    st.error(
                        "Export is disabled because the number of "
                        "successfully extracted files does not match "
                        "the expected container count. "
                        "Rule: one file = one container."
                    )

                if st.button(
                    "📥 Export to Excel",
                    type="primary",
                    use_container_width=True,
                    disabled=(
                        not st.session_state
                        .analysis_container_count_matches
                    ),
                ):

                    excel_file = get_excel_file()

                    # First export:
                    # ask the user to choose a folder,
                    # then create booking_data.xlsx there.
                    if excel_file is None:

                        selected_folder = (
                            choose_storage_folder()
                        )

                        if not selected_folder:

                            st.warning(
                                "Export cancelled because "
                                "no storage folder was selected."
                            )

                        else:

                            try:

                                save_storage_folder(
                                    selected_folder
                                )

                                excel_file = (
                                    get_excel_file()
                                )

                            except Exception as error:

                                st.error(
                                    f"Could not use folder: "
                                    f"{error}"
                                )

                                excel_file = None

                    if excel_file is not None:

                        booking_id = (
                            st.session_state.current_booking_id
                        )

                        if not booking_id:

                            booking_id = (
                                "BK-"
                                + datetime.now().strftime(
                                    "%Y%m%d-%H%M%S"
                                )
                            )

                            st.session_state.current_booking_id = (
                                booking_id
                            )

                        now = datetime.now().strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )

                        old_df = load_booking_excel()

                        (
                            new_df,
                            audit_changes,
                            old_booking_df,
                        ) = build_export_dataframe(
                            booking_id=booking_id,
                            edited_common=edited_common,
                            edited_container_df=(
                                edited_container_df
                            ),
                            old_df=old_df,
                            now_text=now,
                            cargo_type=(
                                st.session_state.cargo_type
                            ),
                            dg_information_file=(
                                st.session_state.dg_info_file_name
                            ),
                            dg_bl_text=(
                                st.session_state.dg_bl_text
                            ),
                        )

                        if not old_df.empty:

                            if (
                                "Booking ID"
                                in old_df.columns
                            ):

                                remaining_df = old_df[
                                    old_df[
                                        "Booking ID"
                                    ].astype(str)
                                    != str(booking_id)
                                ].copy()

                            else:
                                remaining_df = old_df.copy()

                            final_df = pd.concat(
                                [
                                    remaining_df,
                                    new_df,
                                ],
                                ignore_index=True,
                            )

                        else:
                            final_df = new_df

                        try:

                            write_booking_workbook(
                                excel_file,
                                final_df,
                            )

                            # App-generated write becomes the new baseline,
                            # so it will not be mistaken for a manual Excel edit.
                            update_tracking_snapshot(
                                final_df
                            )

                        except Exception as error:

                            st.error(
                                "Could not save Excel. "
                                "The app attempted to rebuild the workbook "
                                "from scratch.\n\n"
                                f"Error: {error}"
                            )

                        else:

                            # Write field history only after Excel
                            # was saved successfully.
                            for change in audit_changes:

                                tracker.log_field_change(
                                    booking_id=(
                                        change[
                                            "booking_id"
                                        ]
                                    ),
                                    field_name=(
                                        change[
                                            "field_name"
                                        ]
                                    ),
                                    old_value=(
                                        change[
                                            "old_value"
                                        ]
                                    ),
                                    new_value=(
                                        change[
                                            "new_value"
                                        ]
                                    ),
                                    change_type=(
                                        change[
                                            "change_type"
                                        ]
                                    ),
                                    container_no=(
                                        change[
                                            "container_no"
                                        ]
                                    ),
                                )

                            if audit_changes:
                                change_detail = (
                                    f"{len(audit_changes)} "
                                    f"data change(s) recorded"
                                )
                            else:
                                change_detail = (
                                    "No data values changed"
                                )

                            tracker.log(
                                booking_id=booking_id,
                                event_type="EXPORT",
                                event_name="Exported to Excel",
                                detail=(
                                    f"{len(new_df)} "
                                    f"container row(s) saved to "
                                    f"{excel_file}. "
                                    f"{change_detail}."
                                ),
                            )

                            prune_tracking_to_current_bookings(
                                final_df
                            )

                            sync_process_model_from_booking_df(
                                final_df
                            )

                            if (
                                st.session_state.cargo_type
                                == "DG"
                                and st.session_state.dg_info_file_name
                                and st.session_state.dg_info_file_bytes
                            ):

                                safe_booking = re.sub(
                                    r"[^A-Za-z0-9_.-]+",
                                    "_",
                                    str(
                                        booking_id
                                    ),
                                )

                                dg_upload_dir = (
                                    UPLOAD_DIR
                                    / safe_booking
                                )

                                dg_upload_dir.mkdir(
                                    parents=True,
                                    exist_ok=True,
                                )

                                dg_target_file = (
                                    dg_upload_dir
                                    / safe_upload_filename(st.session_state.dg_info_file_name)
                                )

                                dg_target_file.write_bytes(
                                    st.session_state.dg_info_file_bytes
                                )

                                dg_document_id = (
                                    process_repo.register_document(
                                        booking_id,
                                        "DG Information",
                                        st.session_state.dg_info_file_name,
                                        document_status="Received",
                                        received_at=(
                                            datetime.now()
                                            .astimezone()
                                            .isoformat(
                                                timespec="seconds"
                                            )
                                        ),
                                        source=str(
                                            dg_target_file
                                        ),
                                        notes=(
                                            "DG information supplied "
                                            "with Packing List."
                                        ),
                                    )
                                )

                                dg_payload = dict(
                                    st.session_state.get(
                                        "dg_analysis",
                                        {},
                                    )
                                    or {}
                                )

                                dg_payload[
                                    "raw_text"
                                ] = st.session_state.dg_info_raw_text

                                dg_payload[
                                    "bl_text"
                                ] = st.session_state.dg_bl_text

                                process_repo.register_extraction(
                                    booking_id,
                                    "DG Information",
                                    dg_payload,
                                    document_id=(
                                        dg_document_id
                                    ),
                                    extractor=(
                                        dg_payload.get(
                                            "__engine__",
                                            "Manual / raw-text fallback",
                                        )
                                    ),
                                    evidence=(
                                        dg_payload.get(
                                            "evidence",
                                            {},
                                        )
                                        or {
                                            "source_file":
                                                st.session_state.dg_info_file_name,
                                        }
                                    ),
                                )

                                process_repo.upsert_shipment(
                                    booking_id,
                                    cargo_type="DG",
                                    dg_information_file=(
                                        st.session_state.dg_info_file_name
                                    ),
                                    dg_bl_text=(
                                        st.session_state.dg_bl_text
                                    ),
                                )

                            else:

                                process_repo.upsert_shipment(
                                    booking_id,
                                    cargo_type="NON DG",
                                    dg_information_file="",
                                    dg_bl_text="",
                                )

                            build_excel_tracking_sheets(
                                excel_file
                            )

                            st.success(
                                f"Booking {booking_id} "
                                f"saved successfully."
                            )

                            if audit_changes:
                                st.caption(
                                    f"{len(audit_changes)} "
                                    "data change(s) added to "
                                    "Tracking. Old history was kept."
                                )
                            else:
                                st.caption(
                                    "No booking information changed, "
                                    "so Last Updated and field "
                                    "timestamps were kept unchanged."
                                )

        # ==================================================
        # RAW TEXT
        # ==================================================

        with tab2:

            st.text_area(
                "Raw Document Text",
                value=(
                    st.session_state.raw_text
                ),
                height=500,
            )


# ==========================================================
# TỔNG QUAN QUY TRÌNH
# ==========================================================

elif page == "Process Overview":

    st.markdown(
        '<div class="main-title">Export Documentation Process</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="subtitle">'
        'Shipment → Documents → Events → Deadlines → Field History → Analytics'
        '</div>',
        unsafe_allow_html=True,
    )

    ai_status = (
        bo_dieu_phoi_chung_tu
        .thong_tin_ai()
    )

    st.caption(
        "Selective document intelligence: Packing List = Rule-based; "
        "Booking Confirmation and supported variable-form documents = AI + validation."
    )

    process_booking_df = load_booking_excel()

    if not process_booking_df.empty:
        sync_process_model_from_booking_df(
            process_booking_df
        )

    shipments = process_repo.get_shipments()
    documents = process_repo.get_documents()
    deadlines = process_repo.get_deadlines()
    coverage = process_repo.get_document_coverage()

    total_shipments = len(
        shipments
    )

    total_documents = len(
        documents
    )

    complete_processes = sum(
        1
        for row in coverage
        if float(
            row.get(
                "coverage_percent",
                0,
            )
        ) >= 100
    )

    average_coverage = (
        round(
            sum(
                float(
                    row.get(
                        "coverage_percent",
                        0,
                    )
                )
                for row in coverage
            )
            / len(
                coverage
            ),
            1,
        )
        if coverage
        else 0.0
    )

    p1, p2, p3, p4 = st.columns(
        4
    )

    hien_thi_chi_so(
        p1,
        "Active Shipments",
        total_shipments,
    )

    hien_thi_chi_so(
        p2,
        "Documents Recorded",
        total_documents,
    )

    hien_thi_chi_so(
        p3,
        "Core Process Complete",
        complete_processes,
    )

    hien_thi_chi_so(
        p4,
        "Avg. Document Coverage",
        f"{average_coverage}%",
    )

    if not shipments:

        st.info(
            "No shipment data yet. Create/export a Packing List booking first."
        )

    else:

        shipment_ids = [
            row[
                "booking_id"
            ]
            for row in shipments
        ]

        selected_process_booking = st.selectbox(
            "Shipment / Booking",
            shipment_ids,
            key="process_overview_booking",
        )

        selected_shipment = next(
            (
                row
                for row in shipments
                if str(
                    row.get(
                        "booking_id",
                        "",
                    )
                )
                == str(
                    selected_process_booking
                )
            ),
            {},
        )

        st.markdown(
            "### Shipment"
        )

        shipment_summary = pd.DataFrame(
            [
                {
                    "Booking ID":
                        selected_shipment.get(
                            "booking_id",
                            "",
                        ),
                    "Cargo Type":
                        selected_shipment.get(
                            "cargo_type",
                            "NON DG",
                        ),
                    "DG Information File":
                        selected_shipment.get(
                            "dg_information_file",
                            "",
                        ),
                    "Carrier Booking No":
                        selected_shipment.get(
                            "carrier_booking_no",
                            "",
                        ),
                    "Carrier":
                        selected_shipment.get(
                            "carrier",
                            "",
                        ),
                    "Vessel / Voyage":
                        selected_shipment.get(
                            "vessel_voyage",
                            "",
                        ),
                    "POL":
                        selected_shipment.get(
                            "port_of_loading",
                            "",
                        ),
                    "POD":
                        selected_shipment.get(
                            "port_of_discharge",
                            "",
                        ),
                    "ETD":
                        selected_shipment.get(
                            "etd",
                            "",
                        ),
                    "ETA":
                        selected_shipment.get(
                            "eta",
                            "",
                        ),
                    "Containers":
                        selected_shipment.get(
                            "container_count",
                            0,
                        ),
                }
            ]
        )

        st.dataframe(
            shipment_summary,
            use_container_width=True,
            hide_index=True,
        )

        selected_documents = [
            row
            for row in documents
            if str(
                row.get(
                    "booking_id",
                    "",
                )
            )
            == str(
                selected_process_booking
            )
        ]

        st.markdown(
            "### Document Flow"
        )

        document_flow_rows = []

        for document_type in (
            process_repo.CORE_DOCUMENT_TYPES
        ):

            matches = [
                row
                for row in selected_documents
                if row.get(
                    "document_type"
                )
                == document_type
            ]

            latest = (
                matches[0]
                if matches
                else {}
            )

            document_flow_rows.append(
                {
                    "Step": document_type,
                    "Status": (
                        latest.get(
                            "document_status",
                            "Missing",
                        )
                        if latest
                        else "Missing"
                    ),
                    "File": latest.get(
                        "file_name",
                        "",
                    ),
                    "Received At":
                        latest.get(
                            "received_at",
                            "",
                        ),
                    "Processed At":
                        latest.get(
                            "processed_at",
                            "",
                        ),
                }
            )

        st.dataframe(
            pd.DataFrame(
                document_flow_rows
            ),
            use_container_width=True,
            hide_index=True,
        )

        selected_deadlines = [
            row
            for row in deadlines
            if str(
                row.get(
                    "booking_id",
                    "",
                )
            )
            == str(
                selected_process_booking
            )
        ]

        st.markdown(
            "### Deadlines"
        )

        if selected_deadlines:

            deadline_rows = []

            for row in selected_deadlines:

                state, detail = deadline_status(
                    row.get(
                        "raw_value",
                        "",
                    )
                )

                deadline_rows.append(
                    {
                        "Deadline":
                            row.get(
                                "deadline_type",
                                "",
                            ),
                        "Value":
                            row.get(
                                "raw_value",
                                "",
                            ),
                        "Status":
                            state,
                        "Detail":
                            detail,
                        "Source":
                            row.get(
                                "source_document",
                                "",
                            ),
                    }
                )

            st.dataframe(
                pd.DataFrame(
                    deadline_rows
                ),
                use_container_width=True,
                hide_index=True,
            )

        else:

            st.caption(
                "No deadlines recorded for this shipment."
            )

        st.markdown(
            "### Process Timeline"
        )

        process_events = (
            process_repo.get_process_events(
                selected_process_booking
            )
        )

        if process_events:

            event_df = pd.DataFrame(
                [
                    {
                        "Time":
                            row.get(
                                "event_time",
                                "",
                            ),
                        "Type":
                            row.get(
                                "event_type",
                                "",
                            ),
                        "Stage":
                            row.get(
                                "event_name",
                                "",
                            ),
                        "File":
                            row.get(
                                "source_file",
                                "",
                            ),
                        "Container":
                            row.get(
                                "container_no",
                                "",
                            ),
                        "Detail":
                            row.get(
                                "detail",
                                "",
                            ),
                    }
                    for row in process_events
                ]
            )

            parsed_times = pd.to_datetime(
                event_df[
                    "Time"
                ],
                errors="coerce",
            )

            event_df[
                "Elapsed From Previous"
            ] = (
                parsed_times.diff()
            )

            event_df[
                "Elapsed From Previous"
            ] = (
                event_df[
                    "Elapsed From Previous"
                ]
                .astype(str)
                .replace(
                    "NaT",
                    "-",
                )
            )

            st.dataframe(
                event_df,
                use_container_width=True,
                hide_index=True,
            )

        else:

            st.caption(
                "No process events yet."
            )

    st.divider()
    st.markdown(
        "### Cross-shipment Analytics"
    )

    if coverage:

        coverage_df = pd.DataFrame(
            [
                {
                    "Booking ID":
                        row.get(
                            "booking_id",
                            "",
                        ),
                    "Completed Core Documents":
                        row.get(
                            "documents_completed",
                            0,
                        ),
                    "Required":
                        row.get(
                            "documents_required",
                            0,
                        ),
                    "Coverage %":
                        row.get(
                            "coverage_percent",
                            0,
                        ),
                }
                for row in coverage
            ]
        )

        st.dataframe(
            coverage_df,
            use_container_width=True,
            hide_index=True,
        )

        document_type_counts = {}

        for row in documents:

            document_type = row.get(
                "document_type",
                "",
            )

            document_type_counts[
                document_type
            ] = (
                document_type_counts.get(
                    document_type,
                    0,
                )
                + 1
            )

        if document_type_counts:

            st.bar_chart(
                pd.DataFrame(
                    {
                        "Documents": (
                            document_type_counts
                        )
                    }
                )
            )


# ==========================================================
# DANH SÁCH BOOKING
# ==========================================================

elif page == "Bookings":

    st.markdown(
        '<div class="main-title">Bookings</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="subtitle">'
        'Saved booking records'
        '</div>',
        unsafe_allow_html=True,
    )

    booking_df = load_booking_excel()

    if booking_df.empty:

        st.info(
            "No bookings saved yet."
        )

    else:

        st.dataframe(
            booking_df,
            use_container_width=True,
            hide_index=True,
        )

        excel_file = get_excel_file()

        if (
            excel_file is not None
            and excel_file.exists()
        ):

            st.caption(
                f"Storage file: {excel_file}"
            )

            if st.button(
                "📂 Open Storage Folder",
                use_container_width=True,
                key="bookings_open_storage",
            ):

                open_storage_folder()



# ==========================================================
# THEO DÕI SỰ KIỆN
# ==========================================================

elif page == "Tracking":

    st.markdown(
        '<div class="main-title">Activity Tracking</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="subtitle">'
        'Process timeline and data change history'
        '</div>',
        unsafe_allow_html=True,
    )

    events = tracker.get_all_events()
    field_changes = (
        tracker.get_all_field_changes()
    )

    booking_ids = []

    for event in events:
        booking_id = str(
            event[1]
        )

        if booking_id not in booking_ids:
            booking_ids.append(
                booking_id
            )

    for change in field_changes:
        booking_id = str(
            change[1]
        )

        if booking_id not in booking_ids:
            booking_ids.append(
                booking_id
            )

    if not booking_ids:

        st.info(
            "No tracking history yet."
        )

    else:

        selected_booking = st.selectbox(
            "Booking",
            booking_ids,
        )

        process_tab, changes_tab = st.tabs(
            [
                "Process Timeline",
                "Data Change History",
            ]
        )

        # ==========================================
        # PROCESS TIMELINE
        # ==========================================

        with process_tab:

            booking_events = [
                event
                for event in events
                if str(event[1])
                == str(selected_booking)
            ]

            if not booking_events:

                st.info(
                    "No process events for this booking."
                )

            else:

                process_df = pd.DataFrame(
                    booking_events,
                    columns=[
                        "ID",
                        "Booking ID",
                        "Type",
                        "Stage",
                        "Time",
                        "Source File",
                        "Container",
                        "Detail",
                    ],
                )

                process_df = (
                    process_df.sort_values(
                        "ID"
                    )
                )

                process_df["Time"] = (
                    pd.to_datetime(
                        process_df[
                            "Time"
                        ],
                        errors="coerce",
                    )
                )

                process_df["Elapsed"] = (
                    process_df[
                        "Time"
                    ].diff()
                )

                def format_elapsed(value):

                    if pd.isna(value):
                        return "-"

                    total_seconds = max(
                        0,
                        int(
                            value.total_seconds()
                        ),
                    )

                    minutes, seconds = divmod(
                        total_seconds,
                        60,
                    )

                    hours, minutes = divmod(
                        minutes,
                        60,
                    )

                    if hours > 0:
                        return (
                            f"{hours}h "
                            f"{minutes}m "
                            f"{seconds}s"
                        )

                    if minutes > 0:
                        return (
                            f"{minutes}m "
                            f"{seconds}s"
                        )

                    return f"{seconds}s"

                process_df["Elapsed"] = (
                    process_df[
                        "Elapsed"
                    ].apply(
                        format_elapsed
                    )
                )

                process_df["Time"] = (
                    process_df[
                        "Time"
                    ]
                    .dt.strftime(
                        "%d/%m/%Y %H:%M:%S"
                    )
                    .fillna("")
                )

                st.dataframe(
                    process_df[
                        [
                            "Time",
                            "Elapsed",
                            "Stage",
                            "Container",
                            "Source File",
                            "Detail",
                        ]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

        # ==========================================
        # DATA CHANGE HISTORY
        # ==========================================

        with changes_tab:

            booking_changes = [
                change
                for change in field_changes
                if str(change[1])
                == str(selected_booking)
            ]

            if not booking_changes:

                st.info(
                    "No field history recorded yet. "
                    "It will start when this booking "
                    "is exported to Excel."
                )

            else:

                changes_df = pd.DataFrame(
                    booking_changes,
                    columns=[
                        "ID",
                        "Booking ID",
                        "Container",
                        "Field",
                        "Old Value",
                        "New Value",
                        "Change Type",
                        "Time",
                    ],
                )

                changes_df = (
                    changes_df.sort_values(
                        "ID"
                    )
                )

                changes_df["Time"] = (
                    pd.to_datetime(
                        changes_df[
                            "Time"
                        ],
                        errors="coerce",
                    )
                    .dt.strftime(
                        "%d/%m/%Y %H:%M:%S"
                    )
                    .fillna("")
                )

                changes_df[
                    "Container"
                ] = changes_df[
                    "Container"
                ].apply(
                    lambda value: (
                        "Booking"
                        if pd.isna(value)
                        or str(value).strip()
                        in {"", "None"}
                        else str(value)
                    )
                )

                changes_df[
                    "Change"
                ] = changes_df[
                    "Change Type"
                ].map(
                    {
                        "INITIAL":
                            "Initial value",

                        "UPDATE":
                            "Changed in app",

                        "EXCEL_EDIT":
                            "Changed in Excel",

                        "EXTRACTED_EDIT":
                            "Changed in Extracted Data",

                        "BOOKINGS_EDIT":
                            "Changed in Bookings",

                        "BOOKING_CONFIRMATION":
                            "Booking Confirmation update",

                        "DEADLINE_EDIT":
                            "Changed in Deadlines sheet",
                    }
                ).fillna(
                    changes_df[
                        "Change Type"
                    ]
                )

                changes_df[
                    "Note"
                ] = changes_df.apply(
                    lambda row: (
                        f"(entered at {row['Time']})"
                        if row[
                            "Change Type"
                        ] == "INITIAL"

                        else (
                            f"(changed in Extracted Data "
                            f"at {row['Time']})"
                            if row[
                                "Change Type"
                            ] == "EXTRACTED_EDIT"

                            else (
                                f"(changed in Bookings "
                                f"at {row['Time']})"
                                if row[
                                    "Change Type"
                                ] == "BOOKINGS_EDIT"

                                else (
                                    f"(changed in app "
                                    f"at {row['Time']})"
                                    if row[
                                        "Change Type"
                                    ] == "UPDATE"

                                    else (
                                        f"(changed at "
                                        f"{row['Time']})"
                                    )
                                )
                            )
                        )
                    ),
                    axis=1,
                )

                st.caption(
                    "History is append-only: old values and "
                    "old timestamps are never overwritten."
                )

                st.dataframe(
                    changes_df[
                        [
                            "Time",
                            "Container",
                            "Field",
                            "Change",
                            "Old Value",
                            "New Value",
                            "Note",
                        ]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )


# ==========================================================
# QUẢN LÝ DEADLINE
# ==========================================================

elif page == "Deadlines":

    st.markdown(
        '<div class="main-title">Booking Confirmation & Deadlines</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="subtitle">'
        'Upload a carrier Booking Confirmation, extract plain text, '
        'review the fields, then synchronize deadlines to Excel, '
        'Dashboard and Tracking.'
        '</div>',
        unsafe_allow_html=True,
    )

    booking_df = load_booking_excel()

    if booking_df.empty:

        st.info(
            "Create/export a Packing List booking first, then attach "
            "its Booking Confirmation here."
        )

    else:

        booking_ids = []

        for value in booking_df[
            "Booking ID"
        ].tolist():

            value = clean_data_value(
                value
            )

            if value and value not in booking_ids:
                booking_ids.append(
                    value
                )

        selected_booking = st.selectbox(
            "Internal Booking ID",
            booking_ids,
            key="deadline_booking_selector",
        )

        selected_rows = booking_df[
            booking_df[
                "Booking ID"
            ].astype(str)
            == str(
                selected_booking
            )
        ].copy()

        current_row = (
            selected_rows.iloc[0]
            if not selected_rows.empty
            else pd.Series(dtype=object)
        )

        current_carrier_booking = clean_data_value(
            current_row.get(
                "Carrier Booking No",
                "",
            )
        )

        if current_carrier_booking:

            st.caption(
                f"Current carrier booking no.: {current_carrier_booking}"
            )

        bc_engine = (
            bo_dieu_phoi_chung_tu
            .engine_cho_loai_chung_tu(
                "Booking Confirmation"
            )
        )

        if bc_engine.get(
            "ai_available"
        ):
            st.success(
                "Processing Engine: Gemini AI + Business Validation. "
                "AI is selected automatically for Booking Confirmation."
            )
        else:
            st.warning(
                "Processing Engine: Rule-based fallback. "
                "Booking Confirmation is configured for AI, but Gemini is currently unavailable."
            )

        uploaded_confirmation = st.file_uploader(
            "Upload Booking Confirmation",
            type=None,
            accept_multiple_files=False,
            key=(
                "booking_confirmation_uploader_"
                f"{selected_booking}"
            ),
            help=(
                "Booking Confirmation automatically uses Gemini AI when configured, "
                "then applies business-rule validation and human review."
            ),
        )

        analyze_confirmation = st.button(
            "Analyze Booking Confirmation",
            type="primary",
            use_container_width=True,
            disabled=(
                uploaded_confirmation is None
            ),
            key=(
                "analyze_booking_confirmation_"
                f"{selected_booking}"
            ),
        )

        if analyze_confirmation:

            try:

                raw_confirmation = bo_doc_tep.doc_bytes(
                    uploaded_confirmation.name,
                    uploaded_confirmation.getvalue(),
                )

                extracted_confirmation = (
                    bo_dieu_phoi_chung_tu
                    .phan_tich_booking_confirmation(
                        raw_confirmation
                    )
                )

                if not any(
                    clean_data_value(
                        extracted_confirmation.get(
                            parser_key,
                            "",
                        )
                    )
                    for parser_key in BOOKING_CONFIRMATION_FIELD_MAP
                ):

                    text_quality = clean_data_value(
                        extracted_confirmation.get(
                            "__text_quality__",
                            "",
                        )
                    )

                    if text_quality == "LOW":

                        raise ValueError(
                            "No usable Booking Confirmation fields were "
                            "detected. Very little text was extracted; this "
                            "may be a scanned/image PDF or a PDF with an "
                            "unusual text layer."
                        )

                    raise ValueError(
                        "No Booking Confirmation fields were detected."
                    )

                st.session_state.bc_analysis = (
                    extracted_confirmation
                )

                st.session_state.bc_analysis_booking_id = (
                    selected_booking
                )

                st.session_state.bc_analysis_source_file = (
                    uploaded_confirmation.name
                )

                st.session_state.bc_analysis_raw_text = (
                    raw_confirmation
                )

                tracker.log(
                    booking_id=selected_booking,
                    event_type="BC_ANALYSIS",
                    event_name="Booking Confirmation analyzed",
                    source_file=uploaded_confirmation.name,
                    detail=(
                        "Hybrid Booking Confirmation analysis completed. "
                        "Carrier page coordinates were not used."
                    ),
                )

                st.success(
                    "Booking Confirmation analyzed. Review the extracted "
                    "fields below before saving."
                )

            except Exception as error:

                tracker.log(
                    booking_id=selected_booking,
                    event_type="ERROR",
                    event_name="Booking Confirmation analysis failed",
                    source_file=(
                        uploaded_confirmation.name
                        if uploaded_confirmation is not None
                        else None
                    ),
                    detail=str(
                        error
                    ),
                )

                st.error(
                    f"Could not analyze Booking Confirmation: {error}"
                )

        active_analysis = (
            st.session_state.bc_analysis
            if st.session_state.bc_analysis_booking_id
            == selected_booking
            else {}
        )

        st.divider()
        st.subheader(
            "Current Deadlines"
        )

        deadline_table = []

        for deadline_field in DEADLINE_FIELDS:

            if deadline_field == "Other Deadlines":
                continue

            value = clean_data_value(
                current_row.get(
                    deadline_field,
                    "",
                )
            )

            if not value:
                continue

            state, days = deadline_status(
                value
            )

            deadline_table.append(
                {
                    "Deadline": deadline_field,
                    "Value": value,
                    "Status": state,
                    "Days": days,
                }
            )

        if deadline_table:

            st.dataframe(
                pd.DataFrame(
                    deadline_table
                ),
                use_container_width=True,
                hide_index=True,
            )

        else:

            st.caption(
                "No Booking Confirmation deadlines saved yet."
            )

        if active_analysis:

            st.divider()
            st.subheader(
                "Review Extracted Booking Confirmation"
            )

            analysis_engine = clean_data_value(
                active_analysis.get(
                    "__engine__",
                    "Rule-based fallback",
                )
            )

            analysis_model = clean_data_value(
                active_analysis.get(
                    "__ai_model__",
                    "",
                )
            )

            engine_col, model_col = st.columns(
                2
            )

            engine_col.info(
                f"Extraction engine: {analysis_engine}"
            )

            if analysis_model:
                model_col.info(
                    f"AI model: {analysis_model}"
                )
            else:
                model_col.caption(
                    "AI model: not used for this extraction"
                )

            analysis_confidence = active_analysis.get(
                "__confidence__",
                {},
            )

            analysis_review_notes = active_analysis.get(
                "__review_notes__",
                [],
            )

            text_quality = clean_data_value(
                active_analysis.get(
                    "__text_quality__",
                    "",
                )
            )

            if text_quality == "LOW":

                st.warning(
                    "Very little usable text was extracted from this file. "
                    "It may be a scanned/image PDF or have an unusual text "
                    "layer. Review every field carefully before saving."
                )

            confidence_rows = []

            confidence_labels = {
                "carrier_booking_no": "Carrier Booking No",
                "vessel_voyage": "Vessel / Voyage",
                "port_of_loading": "Port of Loading",
                "port_of_discharge": "Port of Discharge",
                "cy_cutoff": "CY Cut-off",
                "vgm_cutoff": "VGM Cut-off",
                "si_cutoff": "SI Cut-off",
                "documentation_cutoff": "Documentation Cut-off",
                "pol_eta": "POL ETA",
                "etd": "ETD",
                "eta": "ETA",
            }

            if isinstance(
                analysis_confidence,
                dict,
            ):

                for parser_key, label in confidence_labels.items():

                    extracted_value = clean_data_value(
                        active_analysis.get(
                            parser_key,
                            "",
                        )
                    )

                    if not extracted_value:
                        continue

                    raw_confidence = analysis_confidence.get(
                        parser_key,
                        0.0,
                    )

                    try:
                        confidence_value = float(
                            raw_confidence
                        )
                    except Exception:
                        confidence_value = 0.0

                    confidence_rows.append(
                        {
                            "Field": label,
                            "Confidence": (
                                f"{confidence_value * 100:.0f}%"
                            ),
                            "Review": (
                                "Check"
                                if confidence_value < 0.75
                                else "OK"
                            ),
                        }
                    )

            if confidence_rows:

                st.caption(
                    "Parser confidence is a review aid, not a guarantee. "
                    "The values below remain editable before Save."
                )

                st.dataframe(
                    pd.DataFrame(
                        confidence_rows
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

            analysis_evidence = active_analysis.get(
                "__evidence__",
                {},
            )

            if isinstance(
                analysis_evidence,
                dict,
            ) and analysis_evidence:

                with st.expander(
                    "Source text used by parser",
                    expanded=False,
                ):

                    evidence_labels = {
                        "carrier_booking_no": "Carrier Booking No",
                        "carrier": "Carrier",
                        "vessel_voyage": "Vessel / Voyage",
                        "port_of_loading": "Port of Loading",
                        "port_of_discharge": "Port of Discharge",
                        "final_destination": "Final Destination",
                        "cy_cutoff": "CY Cut-off",
                        "vgm_cutoff": "VGM Cut-off",
                        "si_cutoff": "SI Cut-off",
                        "documentation_cutoff": "Documentation Cut-off",
                        "pol_eta": "POL ETA",
                        "etd": "ETD",
                        "eta": "ETA",
                    }

                    evidence_rows = []

                    for evidence_key, evidence_label in evidence_labels.items():

                        source_text = clean_data_value(
                            analysis_evidence.get(
                                evidence_key,
                                "",
                            )
                        )

                        extracted_text = clean_data_value(
                            active_analysis.get(
                                evidence_key,
                                "",
                            )
                        )

                        if not (
                            source_text
                            or extracted_text
                        ):
                            continue

                        evidence_rows.append(
                            {
                                "Field": evidence_label,
                                "Extracted": extracted_text,
                                "Source line/context": source_text,
                            }
                        )

                    if evidence_rows:

                        st.dataframe(
                            pd.DataFrame(
                                evidence_rows
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )

            if analysis_review_notes:

                missing_notes = [
                    clean_data_value(
                        note
                    )
                    for note in analysis_review_notes
                    if clean_data_value(
                        note
                    )
                ]

                if missing_notes:

                    with st.expander(
                        "Fields to review",
                        expanded=False,
                    ):

                        for note in missing_notes:

                            st.write(
                                f"• {note}"
                            )

            def bc_default(
                parser_key,
            ):

                def clean_bc_value(
                    value,
                ):

                    cleaned = clean_data_value(
                        value
                    )

                    if (
                        cleaned
                        and re.fullmatch(
                            r"[\s.\-_/\\:;|,*]+",
                            cleaned,
                        )
                    ):
                        return ""

                    return cleaned

                extracted_value = clean_bc_value(
                    active_analysis.get(
                        parser_key,
                        "",
                    )
                )

                if extracted_value:
                    return extracted_value

                excel_field = BOOKING_CONFIRMATION_FIELD_MAP.get(
                    parser_key,
                    "",
                )

                return clean_bc_value(
                    current_row.get(
                        excel_field,
                        "",
                    )
                )

            edited_bc = {}

            c1, c2 = st.columns(2)

            with c1:

                edited_bc[
                    "carrier_booking_no"
                ] = st.text_input(
                    "Carrier Booking No",
                    value=bc_default(
                        "carrier_booking_no"
                    ),
                    key=(
                        "bc_carrier_booking_no_"
                        f"{selected_booking}"
                    ),
                )

                edited_bc[
                    "carrier"
                ] = st.text_input(
                    "Carrier",
                    value=bc_default(
                        "carrier"
                    ),
                    key=(
                        "bc_carrier_"
                        f"{selected_booking}"
                    ),
                )

                edited_bc[
                    "vessel_voyage"
                ] = st.text_input(
                    "Vessel / Voyage",
                    value=bc_default(
                        "vessel_voyage"
                    ),
                    key=(
                        "bc_vessel_"
                        f"{selected_booking}"
                    ),
                )

                edited_bc[
                    "port_of_loading"
                ] = st.text_area(
                    "Port of Loading",
                    value=bc_default(
                        "port_of_loading"
                    ),
                    height=80,
                    key=(
                        "bc_pol_"
                        f"{selected_booking}"
                    ),
                )

                edited_bc[
                    "port_of_discharge"
                ] = st.text_area(
                    "Port of Discharge",
                    value=bc_default(
                        "port_of_discharge"
                    ),
                    height=80,
                    key=(
                        "bc_pod_"
                        f"{selected_booking}"
                    ),
                )

            with c2:

                edited_bc[
                    "confirmation_revision"
                ] = st.text_input(
                    "BC Revision",
                    value=bc_default(
                        "confirmation_revision"
                    ),
                    key=(
                        "bc_revision_"
                        f"{selected_booking}"
                    ),
                )

                edited_bc[
                    "confirmation_date"
                ] = st.text_input(
                    "BC Confirmation Date",
                    value=bc_default(
                        "confirmation_date"
                    ),
                    key=(
                        "bc_confirmation_date_"
                        f"{selected_booking}"
                    ),
                )

                edited_bc[
                    "application_no"
                ] = st.text_input(
                    "Application No",
                    value=bc_default(
                        "application_no"
                    ),
                    key=(
                        "bc_application_no_"
                        f"{selected_booking}"
                    ),
                )

                edited_bc[
                    "final_destination"
                ] = st.text_area(
                    "Final Destination",
                    value=bc_default(
                        "final_destination"
                    ),
                    height=80,
                    key=(
                        "bc_final_destination_"
                        f"{selected_booking}"
                    ),
                )

                edited_bc[
                    "service_type_mode"
                ] = st.text_input(
                    "Service Type / Mode",
                    value=bc_default(
                        "service_type_mode"
                    ),
                    key=(
                        "bc_service_mode_"
                        f"{selected_booking}"
                    ),
                )

            st.markdown(
                "#### Deadlines"
            )

            d1, d2, d3 = st.columns(3)

            with d1:

                edited_bc[
                    "cy_cutoff"
                ] = st.text_input(
                    "CY Cut-off",
                    value=bc_default(
                        "cy_cutoff"
                    ),
                    key=(
                        "bc_cy_cutoff_"
                        f"{selected_booking}"
                    ),
                )

                edited_bc[
                    "pol_eta"
                ] = st.text_input(
                    "POL ETA",
                    value=bc_default(
                        "pol_eta"
                    ),
                    key=(
                        "bc_pol_eta_"
                        f"{selected_booking}"
                    ),
                )

            with d2:

                edited_bc[
                    "vgm_cutoff"
                ] = st.text_input(
                    "VGM Cut-off",
                    value=bc_default(
                        "vgm_cutoff"
                    ),
                    key=(
                        "bc_vgm_cutoff_"
                        f"{selected_booking}"
                    ),
                )

                edited_bc[
                    "etd"
                ] = st.text_input(
                    "ETD",
                    value=bc_default(
                        "etd"
                    ),
                    key=(
                        "bc_etd_"
                        f"{selected_booking}"
                    ),
                )

            with d3:

                edited_bc[
                    "si_cutoff"
                ] = st.text_input(
                    "SI Cut-off",
                    value=bc_default(
                        "si_cutoff"
                    ),
                    key=(
                        "bc_si_cutoff_"
                        f"{selected_booking}"
                    ),
                )

                edited_bc[
                    "eta"
                ] = st.text_input(
                    "ETA",
                    value=bc_default(
                        "eta"
                    ),
                    key=(
                        "bc_eta_"
                        f"{selected_booking}"
                    ),
                )

            edited_bc[
                "documentation_cutoff"
            ] = st.text_input(
                "Documentation Cut-off",
                value=bc_default(
                    "documentation_cutoff"
                ),
                key=(
                    "bc_documentation_cutoff_"
                    f"{selected_booking}"
                ),
            )

            st.markdown(
                "#### Additional Booking Confirmation Data"
            )

            additional_fields = [
                ("on_behalf_of", "On Behalf Of"),
                ("port_of_receipt", "Port of Receipt"),
                ("pol_terminal", "POL Terminal"),
                ("shipper", "BC Shipper"),
                ("stuffing_place", "Stuffing Place"),
                ("commodity", "BC Commodity"),
                ("qty_type", "BC QTY / Type"),
                ("empty_pick_up_at", "Empty Pick Up At"),
                ("inland_return_to", "Inland Return To"),
                ("service_contract", "Service Contract"),
                ("payment_term", "Payment Term"),
                ("other_deadlines", "Other Deadlines"),
            ]

            for parser_key, label in additional_fields:

                edited_bc[
                    parser_key
                ] = st.text_area(
                    label,
                    value=bc_default(
                        parser_key
                    ),
                    height=80,
                    key=(
                        "bc_additional_"
                        f"{parser_key}_"
                        f"{selected_booking}"
                    ),
                )

            save_confirmation = st.button(
                "Save Booking Confirmation & Update Deadlines",
                type="primary",
                use_container_width=True,
                key=(
                    "save_booking_confirmation_"
                    f"{selected_booking}"
                ),
            )

            if save_confirmation:

                now_dt = datetime.now().astimezone()
                now_text = now_dt.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                now_iso = now_dt.isoformat(
                    timespec="seconds"
                )

                updated_df, bc_changes = (
                    apply_booking_confirmation_update(
                        booking_df,
                        selected_booking,
                        edited_bc,
                        st.session_state.bc_analysis_source_file,
                        now_text,
                    )
                )

                excel_file = get_excel_file()

                if excel_file is None:

                    st.error(
                        "No Excel storage file is configured. Export the "
                        "Packing List booking first."
                    )

                else:

                    try:

                        write_booking_workbook(
                            excel_file,
                            updated_df,
                        )

                        for change in bc_changes:

                            tracker.log_field_change(
                                booking_id=selected_booking,
                                field_name=change[
                                    "field_name"
                                ],
                                old_value=change[
                                    "old_value"
                                ],
                                new_value=change[
                                    "new_value"
                                ],
                                change_type=(
                                    "BOOKING_CONFIRMATION"
                                ),
                                container_no=None,
                                change_time=now_iso,
                            )

                        tracker.log(
                            booking_id=selected_booking,
                            event_type="BOOKING_CONFIRMATION",
                            event_name=(
                                "Booking Confirmation saved"
                            ),
                            source_file=(
                                st.session_state
                                .bc_analysis_source_file
                            ),
                            detail=(
                                f"{len(bc_changes)} field change(s) saved. "
                                "Deadlines, Excel and Dashboard synchronized."
                            ),
                        )

                        bc_document_id = (
                            process_repo.register_document(
                                selected_booking,
                                "Booking Confirmation",
                                st.session_state.bc_analysis_source_file,
                                document_status="Processed",
                                processed_at=now_iso,
                                revision=edited_bc.get(
                                    "confirmation_revision",
                                    "",
                                ),
                                source="Booking Confirmation workflow",
                            )
                        )

                        process_repo.register_extraction(
                            selected_booking,
                            "Booking Confirmation",
                            edited_bc,
                            document_id=bc_document_id,
                            extractor=(
                                st.session_state.bc_analysis.get(
                                    "__engine__",
                                    "Rule-based fallback",
                                )
                            ),
                            confidence=(
                                st.session_state.bc_analysis.get(
                                    "__confidence__",
                                    {},
                                )
                            ),
                            evidence=(
                                st.session_state.bc_analysis.get(
                                    "__evidence__",
                                    {},
                                )
                            ),
                        )

                        process_repo.sync_from_booking_records(
                            [
                                {
                                    str(column):
                                        clean_data_value(
                                            value
                                        )
                                    for column, value
                                    in row.to_dict().items()
                                }
                                for _, row
                                in updated_df.iterrows()
                            ]
                        )

                        update_tracking_snapshot(
                            updated_df
                        )

                        prune_tracking_to_current_bookings(
                            updated_df
                        )

                        build_excel_tracking_sheets(
                            excel_file
                        )

                        if (
                            st.session_state
                            .bc_analysis_source_file
                            not in st.session_state.processed_files
                        ):

                            st.session_state.processed_files.append(
                                st.session_state
                                .bc_analysis_source_file
                            )

                    except Exception as error:

                        st.error(
                            "Could not save Booking Confirmation. If Excel "
                            "is open, close it and try again.\n\n"
                            f"Error: {error}"
                        )

                    else:

                        st.success(
                            "Booking Confirmation saved. Deadlines, Excel, "
                            "Dashboard and Tracking are updated."
                        )

                        st.session_state.bc_analysis = {}
                        st.session_state.bc_analysis_booking_id = ""
                        st.rerun()

        st.divider()
        st.subheader(
            "All Booking Deadlines"
        )

        current_booking_df = load_booking_excel()
        overview_rows = []
        seen_ids = set()

        if not current_booking_df.empty:

            for _, row in current_booking_df.iterrows():

                booking_id = clean_data_value(
                    row.get(
                        "Booking ID",
                        "",
                    )
                )

                if (
                    not booking_id
                    or booking_id in seen_ids
                ):
                    continue

                seen_ids.add(
                    booking_id
                )

                next_candidates = []

                for field_name in [
                    "SI Cut-off",
                    "VGM Cut-off",
                    "CY Cut-off",
                    "Documentation Cut-off",
                ]:

                    raw_value = clean_data_value(
                        row.get(
                            field_name,
                            "",
                        )
                    )

                    parsed = parse_booking_datetime(
                        raw_value
                    )

                    if parsed is not None:
                        next_candidates.append(
                            (
                                parsed,
                                field_name,
                                raw_value,
                            )
                        )

                next_name = ""
                next_value = ""
                next_state = ""

                if next_candidates:

                    next_item = min(
                        next_candidates,
                        key=lambda item: item[0],
                    )

                    next_name = next_item[1]
                    next_value = next_item[2]
                    next_state, _ = deadline_status(
                        next_value
                    )

                overview_rows.append(
                    {
                        "Booking ID": booking_id,
                        "Carrier Booking No": clean_data_value(
                            row.get(
                                "Carrier Booking No",
                                "",
                            )
                        ),
                        "Carrier": clean_data_value(
                            row.get(
                                "Carrier",
                                "",
                            )
                        ),
                        "Vessel / Voyage": clean_data_value(
                            row.get(
                                "Vessel / Voyage",
                                "",
                            )
                        ),
                        "Next Deadline": next_name,
                        "Deadline": next_value,
                        "Status": next_state,
                        "ETD": clean_data_value(
                            row.get(
                                "ETD",
                                "",
                            )
                        ),
                        "ETA": clean_data_value(
                            row.get(
                                "ETA",
                                "",
                            )
                        ),
                    }
                )

        if overview_rows:

            st.dataframe(
                pd.DataFrame(
                    overview_rows
                ),
                use_container_width=True,
                hide_index=True,
            )

        else:

            st.caption(
                "No Booking Confirmation deadlines saved yet."
            )


# ==========================================================
# QUẢN LÝ CHỨNG TỪ
# ==========================================================

elif page == "Documents":

    st.markdown(
        '<div class="main-title">Shipment Documents</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="subtitle">'
        'Register documents across the full export documentation process'
        '</div>',
        unsafe_allow_html=True,
    )

    document_booking_df = load_booking_excel()

    if document_booking_df.empty:

        st.info(
            "No shipment / booking exists yet. Create/export a Packing List booking first."
        )

    else:

        sync_process_model_from_booking_df(
            document_booking_df
        )

        document_shipments = (
            process_repo.get_shipments()
        )

        document_booking_ids = [
            row[
                "booking_id"
            ]
            for row in document_shipments
        ]

        selected_document_booking = st.selectbox(
            "Shipment / Booking",
            document_booking_ids,
            key="documents_booking",
        )

        st.markdown(
            "### Register / Upload Document"
        )

        document_type = st.selectbox(
            "Document Type",
            process_repo.DOCUMENT_TYPES,
            key="documents_document_type",
        )

        document_engine = (
            bo_dieu_phoi_chung_tu
            .engine_cho_loai_chung_tu(
                document_type
            )
        )

        st.caption(
            "Recommended Processing Engine: "
            + document_engine.get(
                "engine",
                "Manual / Registered Document",
            )
        )

        document_status = st.selectbox(
            "Process Status",
            [
                "Received",
                "Processed",
                "Submitted",
                "Draft",
                "Checked",
                "Approved",
                "Issued",
                "Completed",
            ],
            key="documents_status",
        )

        document_revision = st.text_input(
            "Revision / Version",
            key="documents_revision",
        )

        document_notes = st.text_area(
            "Notes",
            height=80,
            key="documents_notes",
        )

        process_upload = st.file_uploader(
            "Upload document",
            type=None,
            accept_multiple_files=False,
            key="process_document_uploader",
        )

        if st.button(
            "Save Document to Shipment",
            type="primary",
            use_container_width=True,
            disabled=(
                process_upload is None
            ),
            key="save_process_document",
        ):

            if process_upload is None:

                st.error(
                    "Choose a document first."
                )

            else:

                safe_booking = re.sub(
                    r"[^A-Za-z0-9_.-]+",
                    "_",
                    str(
                        selected_document_booking
                    ),
                )

                shipment_upload_dir = (
                    UPLOAD_DIR
                    / safe_booking
                )

                shipment_upload_dir.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                target_file = (
                    shipment_upload_dir
                    / safe_upload_filename(process_upload.name)
                )

                target_file.write_bytes(
                    process_upload.getvalue()
                )

                now_iso = (
                    datetime.now()
                    .astimezone()
                    .isoformat(
                        timespec="seconds"
                    )
                )

                process_repo.register_document(
                    selected_document_booking,
                    document_type,
                    process_upload.name,
                    document_status=document_status,
                    received_at=now_iso,
                    processed_at=(
                        now_iso
                        if document_status
                        in {
                            "Processed",
                            "Submitted",
                            "Checked",
                            "Approved",
                            "Issued",
                            "Completed",
                        }
                        else ""
                    ),
                    revision=document_revision,
                    source=str(
                        target_file
                    ),
                    notes=document_notes,
                )

                tracker.log(
                    booking_id=(
                        selected_document_booking
                    ),
                    event_type="DOCUMENT",
                    event_name=(
                        f"{document_type} - {document_status}"
                    ),
                    source_file=(
                        process_upload.name
                    ),
                    detail=(
                        document_notes
                        or (
                            f"{document_type} registered "
                            f"with status {document_status}."
                        )
                    ),
                )

                process_repo.sync_legacy_events()

                excel_file = get_excel_file()

                if (
                    excel_file is not None
                    and excel_file.exists()
                ):

                    build_excel_tracking_sheets(
                        excel_file
                    )

                st.success(
                    f"{document_type} saved to shipment {selected_document_booking}."
                )

                st.rerun()

        st.divider()
        st.markdown(
            "### Document Register"
        )

        booking_documents = (
            process_repo.get_documents(
                selected_document_booking
            )
        )

        if booking_documents:

            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Type":
                                row.get(
                                    "document_type",
                                    "",
                                ),
                            "File":
                                row.get(
                                    "file_name",
                                    "",
                                ),
                            "Status":
                                row.get(
                                    "document_status",
                                    "",
                                ),
                            "Received At":
                                row.get(
                                    "received_at",
                                    "",
                                ),
                            "Processed At":
                                row.get(
                                    "processed_at",
                                    "",
                                ),
                            "Revision":
                                row.get(
                                    "revision",
                                    "",
                                ),
                            "Notes":
                                row.get(
                                    "notes",
                                    "",
                                ),
                        }
                        for row in booking_documents
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )

        else:

            st.caption(
                "No documents registered for this shipment yet."
            )

        st.markdown(
            "### Process Coverage"
        )

        coverage_lookup = {
            row[
                "booking_id"
            ]: row
            for row in (
                process_repo
                .get_document_coverage()
            )
        }

        selected_coverage = (
            coverage_lookup.get(
                selected_document_booking,
                {},
            )
        )

        coverage_percent = float(
            selected_coverage.get(
                "coverage_percent",
                0,
            )
            or 0
        )

        st.progress(
            min(
                max(
                    coverage_percent
                    / 100,
                    0.0,
                ),
                1.0,
            ),
            text=(
                f"Core document coverage: "
                f"{coverage_percent:.1f}%"
            ),
        )

        present_types = {
            row.get(
                "document_type",
                "",
            )
            for row in booking_documents
        }

        checklist_rows = []

        selected_shipment_info = (
            process_repo.get_shipment(
                selected_document_booking
            )
        )

        required_document_types = list(
            process_repo.CORE_DOCUMENT_TYPES
        )

        if str(
            selected_shipment_info.get(
                "cargo_type",
                "",
            )
        ).strip().upper() == "DG":

            required_document_types.insert(
                1,
                "DG Information",
            )

        for required_type in required_document_types:

            checklist_rows.append(
                {
                    "Document":
                        required_type,
                    "Available":
                        (
                            "Yes"
                            if required_type
                            in present_types
                            else "No"
                        ),
                }
            )

        st.dataframe(
            pd.DataFrame(
                checklist_rows
            ),
            use_container_width=True,
            hide_index=True,
        )


# ==========================================================
# CHUẨN BỊ BILL OF LADING
# ==========================================================

elif page == "B/L":

    st.markdown(
        '<div class="main-title">Bill of Lading</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="subtitle">'
        'Prepare B/L data from the shipment, including DG information when required'
        '</div>',
        unsafe_allow_html=True,
    )

    bl_booking_df = load_booking_excel()

    if bl_booking_df.empty:

        st.info(
            "No shipment / booking exists yet."
        )

    else:

        sync_process_model_from_booking_df(
            bl_booking_df
        )

        bl_shipments = (
            process_repo.get_shipments()
        )

        bl_booking_ids = [
            row[
                "booking_id"
            ]
            for row in bl_shipments
        ]

        selected_bl_booking = st.selectbox(
            "Shipment / Booking",
            bl_booking_ids,
            key="bl_booking_select",
        )

        shipment_info = (
            process_repo.get_shipment(
                selected_bl_booking
            )
        )

        cargo_type = str(
            shipment_info.get(
                "cargo_type",
                "NON DG",
            )
            or "NON DG"
        ).strip().upper()

        selected_rows = bl_booking_df[
            bl_booking_df[
                "Booking ID"
            ].astype(str)
            == str(
                selected_bl_booking
            )
        ].copy()

        first_row = (
            selected_rows.iloc[0]
            if not selected_rows.empty
            else pd.Series(dtype=object)
        )

        c1, c2, c3 = st.columns(
            3
        )

        hien_thi_chi_so(
            c1,
            "Cargo Type",
            cargo_type,
        )

        hien_thi_chi_so(
            c2,
            "Carrier",
            clean_data_value(
                shipment_info.get(
                    "carrier",
                    "",
                )
            )
            or "-",
        )

        hien_thi_chi_so(
            c3,
            "Vessel / Voyage",
            clean_data_value(
                shipment_info.get(
                    "vessel_voyage",
                    "",
                )
            )
            or "-",
        )

        st.markdown(
            "### B/L Source Data"
        )

        bl_source_rows = [
            {
                "Field":
                    "Shipper",
                "Value":
                    clean_data_value(
                        first_row.get(
                            "Shipper",
                            "",
                        )
                    ),
            },
            {
                "Field":
                    "Consignee",
                "Value":
                    clean_data_value(
                        first_row.get(
                            "Consignee",
                            "",
                        )
                    ),
            },
            {
                "Field":
                    "Notify",
                "Value":
                    clean_data_value(
                        first_row.get(
                            "Notify",
                            "",
                        )
                    ),
            },
            {
                "Field":
                    "Product",
                "Value":
                    clean_data_value(
                        first_row.get(
                            "Product",
                            "",
                        )
                    ),
            },
            {
                "Field":
                    "Quantity",
                "Value":
                    clean_data_value(
                        first_row.get(
                            "Quantity",
                            "",
                        )
                    ),
            },
            {
                "Field":
                    "Marking",
                "Value":
                    clean_data_value(
                        first_row.get(
                            "Marking",
                            "",
                        )
                    ),
            },
            {
                "Field":
                    "POL",
                "Value":
                    clean_data_value(
                        shipment_info.get(
                            "port_of_loading",
                            "",
                        )
                    ),
            },
            {
                "Field":
                    "POD",
                "Value":
                    clean_data_value(
                        shipment_info.get(
                            "port_of_discharge",
                            "",
                        )
                    ),
            },
        ]

        st.dataframe(
            pd.DataFrame(
                bl_source_rows
            ),
            use_container_width=True,
            hide_index=True,
        )

        if cargo_type == "DG":

            st.warning(
                "DG shipment: DG information is required in the B/L preparation."
            )

            dg_documents = [
                row
                for row in (
                    process_repo.get_documents(
                        selected_bl_booking
                    )
                )
                if row.get(
                    "document_type"
                )
                == "DG Information"
            ]

            latest_dg_document = (
                dg_documents[0]
                if dg_documents
                else {}
            )

            dg_extraction = (
                process_repo.get_latest_extraction(
                    selected_bl_booking,
                    "DG Information",
                )
            )

            dg_payload = (
                dg_extraction.get(
                    "payload",
                    {},
                )
                if dg_extraction
                else {}
            )

            default_dg_bl_text = (
                clean_data_value(
                    shipment_info.get(
                        "dg_bl_text",
                        "",
                    )
                )
                or clean_data_value(
                    dg_payload.get(
                        "bl_text",
                        "",
                    )
                )
                or clean_data_value(
                    dg_payload.get(
                        "raw_text",
                        "",
                    )
                )
            )

            dg_left, dg_right = st.columns(
                2
            )

            dg_left.text_input(
                "DG Information File",
                value=(
                    latest_dg_document.get(
                        "file_name",
                        "",
                    )
                    or shipment_info.get(
                        "dg_information_file",
                        "",
                    )
                ),
                disabled=True,
                key="bl_dg_source_file",
            )

            dg_right.text_input(
                "DG Document Status",
                value=(
                    latest_dg_document.get(
                        "document_status",
                        "",
                    )
                    or "Missing"
                ),
                disabled=True,
                key="bl_dg_document_status",
            )

            edited_dg_bl_text = st.text_area(
                "DG Information for B/L",
                value=default_dg_bl_text,
                height=280,
                help=(
                    "Review and edit the DG information that should "
                    "be carried into the B/L template."
                ),
                key=(
                    f"bl_dg_text_"
                    f"{selected_bl_booking}"
                ),
            )

            if not default_dg_bl_text:

                st.error(
                    "The DG document is attached but no readable text is available. "
                    "Enter the required DG information manually here before preparing the B/L."
                )

            if st.button(
                "Save DG Information for B/L",
                type="primary",
                use_container_width=True,
                key="save_bl_dg_text",
            ):

                process_repo.update_dg_bl_text(
                    selected_bl_booking,
                    edited_dg_bl_text,
                )

                # Keep the normalized Excel/backend row synchronized.
                if (
                    "DG B/L Text"
                    not in bl_booking_df.columns
                ):

                    bl_booking_df[
                        "DG B/L Text"
                    ] = ""

                bl_booking_df[
                    "DG B/L Text"
                ] = bl_booking_df[
                    "DG B/L Text"
                ].astype(
                    "object"
                )

                bl_booking_df.loc[
                    bl_booking_df[
                        "Booking ID"
                    ].astype(str)
                    == str(
                        selected_bl_booking
                    ),
                    "DG B/L Text",
                ] = edited_dg_bl_text

                excel_file = get_excel_file()

                if excel_file is not None:

                    try:

                        write_booking_workbook(
                            excel_file,
                            bl_booking_df,
                        )

                        tracker.log(
                            booking_id=(
                                selected_bl_booking
                            ),
                            event_type="BILL_OF_LADING",
                            event_name=(
                                "DG information prepared for B/L"
                            ),
                            source_file=(
                                latest_dg_document.get(
                                    "file_name",
                                    "",
                                )
                            ),
                            detail=(
                                "DG information was reviewed and saved "
                                "for use in the B/L."
                            ),
                        )

                        build_excel_tracking_sheets(
                            excel_file
                        )

                        st.success(
                            "DG information saved for the B/L."
                        )

                    except Exception as error:

                        st.error(
                            f"Could not save DG B/L information: {error}"
                        )

        else:

            st.success(
                "NON DG shipment: no DG information section is required for the B/L."
            )

        st.divider()

        st.info(
            "The B/L data layer is now DG-aware. "
            "When the actual B/L template generator is connected, "
            "the saved DG Information for B/L field can be mapped directly into the template."
        )


# ==========================================================
# CÀI ĐẶT
# ==========================================================

elif page == "Settings":

    st.markdown(
        '<div class="main-title">Settings</div>',
        unsafe_allow_html=True,
    )

    st.write(
        "Export Documentation Intelligence"
    )

    st.write(
        "Python + Streamlit"
    )

    st.subheader(
        "Document Intelligence Routing"
    )

    ai_status = (
        bo_dieu_phoi_chung_tu
        .thong_tin_ai()
    )

    ai_col_1, ai_col_2, ai_col_3 = st.columns(
        3
    )

    hien_thi_chi_so(
        ai_col_1,
        "AI Provider",
        ai_status.get(
            "provider",
            "Gemini",
        ),
    )

    hien_thi_chi_so(
        ai_col_2,
        "AI Status",
        (
            "Available"
            if ai_status.get(
                "available"
            )
            else "Fallback Only"
        ),
    )

    hien_thi_chi_so(
        ai_col_3,
        "Configured Model",
        ai_status.get(
            "model",
            "-",
        ),
    )

    routing_rows = []

    for routing_item in (
        bo_dieu_phoi_chung_tu
        .bang_dieu_phoi()
    ):
        routing_rows.append(
            {
                "Document Type":
                    routing_item.get(
                        "document_type",
                        "",
                    ),
                "Processing Engine":
                    routing_item.get(
                        "engine",
                        "",
                    ),
                "AI Used":
                    (
                        "Yes"
                        if routing_item.get(
                            "ai_required"
                        )
                        else "No"
                    ),
            }
        )

    st.dataframe(
        pd.DataFrame(
            routing_rows
        ),
        use_container_width=True,
        hide_index=True,
    )

    if ai_status.get(
        "available"
    ):
        st.success(
            "Gemini is configured. AI-capable document types use it automatically. "
            "Packing List remains rule-based and never calls AI."
        )
    else:
        st.warning(
            "Gemini is not currently available. Packing List continues normally, "
            "and AI-capable documents automatically fall back to rule-based/manual review."
        )

        if ai_status.get(
            "reason"
        ):
            st.caption(
                ai_status[
                    "reason"
                ]
            )

    st.caption(
        "No per-document AI switch is required. Routing is automatic based on document type."
    )

    st.subheader(
        "Data Storage"
    )

    current_folder = str(
        st.session_state.storage_folder
    ).strip()

    if current_folder:

        st.success(
            "Current storage folder:"
        )

        st.code(
            current_folder
        )

        current_excel_file = (
            get_excel_file()
        )

        st.caption(
            f"Excel file: {current_excel_file}"
        )

    else:

        st.warning(
            "No storage folder selected yet. "
            "The app will ask for one on the first export."
        )

    if st.button(
        "📂 Choose Storage Folder",
        type="primary",
        use_container_width=True,
        key="settings_choose_storage",
    ):

        selected_folder = (
            choose_storage_folder()
        )

        if selected_folder:

            try:

                save_storage_folder(
                    selected_folder
                )

                st.success(
                    "Storage folder saved."
                )

                st.rerun()

            except Exception as error:

                st.error(
                    f"Could not use folder: "
                    f"{error}"
                )

    if current_folder:

        if st.button(
            "Open Storage Folder in Finder",
            use_container_width=True,
            key="settings_open_storage",
        ):

            open_storage_folder()
