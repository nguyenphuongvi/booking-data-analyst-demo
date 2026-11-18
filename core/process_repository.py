from datetime import datetime
from pathlib import Path
import json
import sqlite3
from contextlib import contextmanager


class ProcessRepository:
    """
    Central shipment/document/process repository.

    Existing Booking Auto tables are kept for backward compatibility.
    This repository adds a process-oriented data model:

        shipments
        documents
        document_extractions
        deadlines
        process_events

    booking_id remains the stable Shipment / Booking identifier.
    """

    DOCUMENT_TYPES = [
        "Packing List",
        "DG Information",
        "Booking Confirmation",
        "Shipping Instruction",
        "VGM",
        "Draft B/L",
        "Final B/L",
        "C/O",
        "Commercial Invoice",
        "Other",
    ]

    CORE_DOCUMENT_TYPES = [
        "Packing List",
        "Booking Confirmation",
        "Shipping Instruction",
        "VGM",
        "Draft B/L",
        "Final B/L",
    ]

    def __init__(self, database_path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.create_tables()
        self.sync_legacy_events()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def now():
        return (
            datetime.now()
            .astimezone()
            .isoformat(timespec="seconds")
        )

    def create_tables(self):
        with self.connect() as connection:

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS shipments (
                    booking_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    lifecycle_status TEXT NOT NULL DEFAULT 'Active',
                    carrier_booking_no TEXT,
                    carrier TEXT,
                    vessel_voyage TEXT,
                    port_of_loading TEXT,
                    port_of_discharge TEXT,
                    etd TEXT,
                    eta TEXT,
                    container_count INTEGER NOT NULL DEFAULT 0,
                    cargo_type TEXT NOT NULL DEFAULT 'NON DG',
                    dg_information_file TEXT,
                    dg_bl_text TEXT
                )
                """
            )

            shipment_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(shipments)"
                ).fetchall()
            }

            required_shipment_columns = {
                "cargo_type":
                    "TEXT NOT NULL DEFAULT 'NON DG'",
                "dg_information_file":
                    "TEXT",
                "dg_bl_text":
                    "TEXT",
            }

            for column_name, column_sql in (
                required_shipment_columns.items()
            ):

                if column_name in shipment_columns:
                    continue

                connection.execute(
                    f"""
                    ALTER TABLE shipments
                    ADD COLUMN {column_name} {column_sql}
                    """
                )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    booking_id TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    document_status TEXT NOT NULL DEFAULT 'Received',
                    received_at TEXT NOT NULL,
                    processed_at TEXT,
                    revision TEXT,
                    source TEXT,
                    notes TEXT,
                    UNIQUE (
                        booking_id,
                        document_type,
                        file_name
                    )
                )
                """
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS document_extractions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER,
                    booking_id TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    extracted_at TEXT NOT NULL,
                    extractor TEXT NOT NULL,
                    payload_json TEXT,
                    confidence_json TEXT,
                    evidence_json TEXT
                )
                """
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS deadlines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    booking_id TEXT NOT NULL,
                    deadline_type TEXT NOT NULL,
                    raw_value TEXT,
                    source_document TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE (
                        booking_id,
                        deadline_type
                    )
                )
                """
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS process_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_event_id INTEGER UNIQUE,
                    booking_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_name TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    source_file TEXT,
                    container_no TEXT,
                    detail TEXT
                )
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_documents_booking
                ON documents (booking_id)
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_deadlines_booking
                ON deadlines (booking_id)
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_process_events_booking
                ON process_events (booking_id)
                """
            )

            connection.commit()

    def sync_legacy_events(self):
        """
        Mirror existing booking_events into process_events.

        source_event_id prevents duplicate migration on Streamlit reruns.
        """

        with self.connect() as connection:

            table = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type='table'
                  AND name='booking_events'
                """
            ).fetchone()

            if table is None:
                return

            connection.execute(
                """
                INSERT OR IGNORE INTO process_events (
                    source_event_id,
                    booking_id,
                    event_type,
                    event_name,
                    event_time,
                    source_file,
                    container_no,
                    detail
                )
                SELECT
                    id,
                    booking_id,
                    event_type,
                    event_name,
                    event_time,
                    source_file,
                    CAST(container_no AS TEXT),
                    detail
                FROM booking_events
                """
            )

            connection.commit()

    def upsert_shipment(
        self,
        booking_id,
        *,
        carrier_booking_no="",
        carrier="",
        vessel_voyage="",
        port_of_loading="",
        port_of_discharge="",
        etd="",
        eta="",
        container_count=0,
        lifecycle_status="Active",
        cargo_type="",
        dg_information_file="",
        dg_bl_text="",
        created_at="",
        updated_at="",
    ):
        booking_id = str(booking_id or "").strip()

        if not booking_id:
            return

        now = self.now()
        created_at = str(created_at or "").strip() or now
        updated_at = str(updated_at or "").strip() or now

        with self.connect() as connection:

            connection.execute(
                """
                INSERT INTO shipments (
                    booking_id,
                    created_at,
                    updated_at,
                    lifecycle_status,
                    carrier_booking_no,
                    carrier,
                    vessel_voyage,
                    port_of_loading,
                    port_of_discharge,
                    etd,
                    eta,
                    container_count,
                    cargo_type,
                    dg_information_file,
                    dg_bl_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(booking_id) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    lifecycle_status=excluded.lifecycle_status,
                    carrier_booking_no=excluded.carrier_booking_no,
                    carrier=excluded.carrier,
                    vessel_voyage=excluded.vessel_voyage,
                    port_of_loading=excluded.port_of_loading,
                    port_of_discharge=excluded.port_of_discharge,
                    etd=excluded.etd,
                    eta=excluded.eta,
                    container_count=excluded.container_count,
                    cargo_type=CASE
                        WHEN excluded.cargo_type <> ''
                        THEN excluded.cargo_type
                        ELSE shipments.cargo_type
                    END,
                    dg_information_file=CASE
                        WHEN excluded.dg_information_file <> ''
                        THEN excluded.dg_information_file
                        ELSE shipments.dg_information_file
                    END,
                    dg_bl_text=CASE
                        WHEN excluded.dg_bl_text <> ''
                        THEN excluded.dg_bl_text
                        ELSE shipments.dg_bl_text
                    END
                """,
                (
                    booking_id,
                    created_at,
                    updated_at,
                    str(lifecycle_status or "Active"),
                    str(carrier_booking_no or ""),
                    str(carrier or ""),
                    str(vessel_voyage or ""),
                    str(port_of_loading or ""),
                    str(port_of_discharge or ""),
                    str(etd or ""),
                    str(eta or ""),
                    int(container_count or 0),
                    str(cargo_type or ""),
                    str(dg_information_file or ""),
                    str(dg_bl_text or ""),
                ),
            )

            connection.commit()

    def register_document(
        self,
        booking_id,
        document_type,
        file_name,
        *,
        document_status="Received",
        received_at="",
        processed_at="",
        revision="",
        source="",
        notes="",
    ):
        booking_id = str(booking_id or "").strip()
        document_type = str(document_type or "").strip()
        file_name = str(file_name or "").strip()

        if not booking_id or not document_type or not file_name:
            return None

        received_at = (
            str(received_at or "").strip()
            or self.now()
        )

        with self.connect() as connection:

            connection.execute(
                """
                INSERT INTO documents (
                    booking_id,
                    document_type,
                    file_name,
                    document_status,
                    received_at,
                    processed_at,
                    revision,
                    source,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    booking_id,
                    document_type,
                    file_name
                )
                DO UPDATE SET
                    document_status=excluded.document_status,
                    processed_at=CASE
                        WHEN excluded.processed_at <> ''
                        THEN excluded.processed_at
                        ELSE documents.processed_at
                    END,
                    revision=CASE
                        WHEN excluded.revision <> ''
                        THEN excluded.revision
                        ELSE documents.revision
                    END,
                    source=CASE
                        WHEN excluded.source <> ''
                        THEN excluded.source
                        ELSE documents.source
                    END,
                    notes=CASE
                        WHEN excluded.notes <> ''
                        THEN excluded.notes
                        ELSE documents.notes
                    END
                """,
                (
                    booking_id,
                    document_type,
                    file_name,
                    str(document_status or "Received"),
                    received_at,
                    str(processed_at or ""),
                    str(revision or ""),
                    str(source or ""),
                    str(notes or ""),
                ),
            )

            row = connection.execute(
                """
                SELECT id
                FROM documents
                WHERE booking_id = ?
                  AND document_type = ?
                  AND file_name = ?
                """,
                (
                    booking_id,
                    document_type,
                    file_name,
                ),
            ).fetchone()

            connection.commit()

        return (
            int(row["id"])
            if row is not None
            else None
        )

    def register_extraction(
        self,
        booking_id,
        document_type,
        payload,
        *,
        document_id=None,
        extractor="rule-based",
        confidence=None,
        evidence=None,
    ):
        with self.connect() as connection:

            connection.execute(
                """
                INSERT INTO document_extractions (
                    document_id,
                    booking_id,
                    document_type,
                    extracted_at,
                    extractor,
                    payload_json,
                    confidence_json,
                    evidence_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    str(booking_id or ""),
                    str(document_type or ""),
                    self.now(),
                    str(extractor or ""),
                    json.dumps(
                        payload or {},
                        ensure_ascii=False,
                        default=str,
                    ),
                    json.dumps(
                        confidence or {},
                        ensure_ascii=False,
                        default=str,
                    ),
                    json.dumps(
                        evidence or {},
                        ensure_ascii=False,
                        default=str,
                    ),
                ),
            )

            connection.commit()

    def upsert_deadline(
        self,
        booking_id,
        deadline_type,
        raw_value,
        *,
        source_document="",
        updated_at="",
    ):
        booking_id = str(booking_id or "").strip()
        deadline_type = str(deadline_type or "").strip()

        if not booking_id or not deadline_type:
            return

        with self.connect() as connection:

            connection.execute(
                """
                INSERT INTO deadlines (
                    booking_id,
                    deadline_type,
                    raw_value,
                    source_document,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(
                    booking_id,
                    deadline_type
                )
                DO UPDATE SET
                    raw_value=excluded.raw_value,
                    source_document=excluded.source_document,
                    updated_at=excluded.updated_at
                """,
                (
                    booking_id,
                    deadline_type,
                    str(raw_value or ""),
                    str(source_document or ""),
                    (
                        str(updated_at or "").strip()
                        or self.now()
                    ),
                ),
            )

            connection.commit()

    def get_shipment(self, booking_id):
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM shipments
                WHERE booking_id = ?
                """,
                (
                    str(booking_id),
                ),
            ).fetchone()

        return (
            dict(row)
            if row is not None
            else {}
        )

    def update_dg_bl_text(
        self,
        booking_id,
        dg_bl_text,
    ):
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE shipments
                SET
                    dg_bl_text = ?,
                    updated_at = ?
                WHERE booking_id = ?
                """,
                (
                    str(dg_bl_text or ""),
                    self.now(),
                    str(booking_id),
                ),
            )
            connection.commit()

    def get_latest_extraction(
        self,
        booking_id,
        document_type,
    ):
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    document_id,
                    booking_id,
                    document_type,
                    extracted_at,
                    extractor,
                    payload_json,
                    confidence_json,
                    evidence_json
                FROM document_extractions
                WHERE booking_id = ?
                  AND document_type = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    str(booking_id),
                    str(document_type),
                ),
            ).fetchone()

        if row is None:
            return {}

        output = dict(row)

        for key in [
            "payload_json",
            "confidence_json",
            "evidence_json",
        ]:
            raw_value = output.get(
                key,
                "",
            )

            try:
                output[
                    key.replace(
                        "_json",
                        "",
                    )
                ] = json.loads(
                    raw_value
                    or "{}"
                )
            except Exception:
                output[
                    key.replace(
                        "_json",
                        "",
                    )
                ] = {}

        return output

    def sync_from_booking_records(self, records):
        """
        Backfill / refresh process tables from the current normalized
        booking rows. Safe to call on every Streamlit rerun.
        """

        records = list(records or [])

        grouped = {}

        for record in records:
            booking_id = str(
                record.get(
                    "Booking ID",
                    "",
                )
                or ""
            ).strip()

            if not booking_id:
                continue

            grouped.setdefault(
                booking_id,
                [],
            ).append(record)

        active_ids = set(grouped)

        for booking_id, rows in grouped.items():

            first = rows[0]

            existing_shipment = self.get_shipment(
                booking_id
            )

            cargo_type = str(
                first.get(
                    "Cargo Type",
                    "",
                )
                or existing_shipment.get(
                    "cargo_type",
                    "",
                )
                or "NON DG"
            ).strip().upper()

            dg_information_file = str(
                first.get(
                    "DG Information File",
                    "",
                )
                or existing_shipment.get(
                    "dg_information_file",
                    "",
                )
                or ""
            ).strip()

            dg_bl_text = str(
                first.get(
                    "DG B/L Text",
                    "",
                )
                or existing_shipment.get(
                    "dg_bl_text",
                    "",
                )
                or ""
            ).strip()

            containers = {
                str(
                    row.get(
                        "Container",
                        "",
                    )
                    or ""
                ).strip()
                for row in rows
                if str(
                    row.get(
                        "Container",
                        "",
                    )
                    or ""
                ).strip()
            }

            self.upsert_shipment(
                booking_id,
                carrier_booking_no=first.get(
                    "Carrier Booking No",
                    "",
                ),
                carrier=first.get(
                    "Carrier",
                    "",
                ),
                vessel_voyage=first.get(
                    "Vessel / Voyage",
                    "",
                ),
                port_of_loading=first.get(
                    "Port of Loading",
                    "",
                ),
                port_of_discharge=first.get(
                    "Port of Discharge",
                    "",
                ),
                etd=first.get(
                    "ETD",
                    "",
                ),
                eta=first.get(
                    "ETA",
                    "",
                ),
                container_count=len(containers),
                cargo_type=cargo_type,
                dg_information_file=dg_information_file,
                dg_bl_text=dg_bl_text,
                created_at=first.get(
                    "Created At",
                    "",
                ),
                updated_at=first.get(
                    "Last Updated",
                    "",
                ),
            )

            seen_pl_files = set()

            for row in rows:
                source_file = str(
                    row.get(
                        "Source File",
                        "",
                    )
                    or ""
                ).strip()

                if (
                    source_file
                    and source_file not in seen_pl_files
                ):
                    seen_pl_files.add(source_file)

                    self.register_document(
                        booking_id,
                        "Packing List",
                        source_file,
                        document_status="Processed",
                        source="Excel / Packing List workflow",
                    )

            bc_file = str(
                first.get(
                    "Booking Confirmation File",
                    "",
                )
                or ""
            ).strip()

            if bc_file:
                self.register_document(
                    booking_id,
                    "Booking Confirmation",
                    bc_file,
                    document_status="Processed",
                    revision=first.get(
                        "BC Revision",
                        "",
                    ),
                    source="Booking Confirmation workflow",
                )

            for deadline_name in [
                "CY Cut-off",
                "VGM Cut-off",
                "SI Cut-off",
                "Documentation Cut-off",
                "POL ETA",
                "ETD",
                "ETA",
                "Other Deadlines",
            ]:
                raw_value = str(
                    first.get(
                        deadline_name,
                        "",
                    )
                    or ""
                ).strip()

                if raw_value:
                    self.upsert_deadline(
                        booking_id,
                        deadline_name,
                        raw_value,
                        source_document=(
                            bc_file
                            or "booking_data.xlsx"
                        ),
                    )

        self.sync_legacy_events()
        self.prune_to_active_bookings(
            active_ids
        )

    def get_shipments(self):
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    booking_id,
                    created_at,
                    updated_at,
                    lifecycle_status,
                    carrier_booking_no,
                    carrier,
                    vessel_voyage,
                    port_of_loading,
                    port_of_discharge,
                    etd,
                    eta,
                    container_count,
                    cargo_type,
                    dg_information_file,
                    dg_bl_text
                FROM shipments
                ORDER BY created_at DESC, booking_id DESC
                """
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def get_documents(self, booking_id=None):
        with self.connect() as connection:

            if booking_id:
                rows = connection.execute(
                    """
                    SELECT
                        id,
                        booking_id,
                        document_type,
                        file_name,
                        document_status,
                        received_at,
                        processed_at,
                        revision,
                        source,
                        notes
                    FROM documents
                    WHERE booking_id = ?
                    ORDER BY id DESC
                    """,
                    (
                        str(booking_id),
                    ),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT
                        id,
                        booking_id,
                        document_type,
                        file_name,
                        document_status,
                        received_at,
                        processed_at,
                        revision,
                        source,
                        notes
                    FROM documents
                    ORDER BY id DESC
                    """
                ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def get_deadlines(self, booking_id=None):
        with self.connect() as connection:

            if booking_id:
                rows = connection.execute(
                    """
                    SELECT
                        id,
                        booking_id,
                        deadline_type,
                        raw_value,
                        source_document,
                        updated_at
                    FROM deadlines
                    WHERE booking_id = ?
                    ORDER BY id ASC
                    """,
                    (
                        str(booking_id),
                    ),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT
                        id,
                        booking_id,
                        deadline_type,
                        raw_value,
                        source_document,
                        updated_at
                    FROM deadlines
                    ORDER BY booking_id, id
                    """
                ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def get_process_events(self, booking_id=None):
        self.sync_legacy_events()

        with self.connect() as connection:

            if booking_id:
                rows = connection.execute(
                    """
                    SELECT
                        id,
                        booking_id,
                        event_type,
                        event_name,
                        event_time,
                        source_file,
                        container_no,
                        detail
                    FROM process_events
                    WHERE booking_id = ?
                    ORDER BY event_time ASC, id ASC
                    """,
                    (
                        str(booking_id),
                    ),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT
                        id,
                        booking_id,
                        event_type,
                        event_name,
                        event_time,
                        source_file,
                        container_no,
                        detail
                    FROM process_events
                    ORDER BY event_time DESC, id DESC
                    """
                ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def get_document_coverage(self):
        shipments = self.get_shipments()
        documents = self.get_documents()

        by_booking = {}

        for document in documents:
            by_booking.setdefault(
                document["booking_id"],
                set(),
            ).add(
                document["document_type"]
            )

        output = []

        for shipment in shipments:
            booking_id = shipment["booking_id"]
            present = by_booking.get(
                booking_id,
                set(),
            )

            required_documents = list(
                self.CORE_DOCUMENT_TYPES
            )

            if str(
                shipment.get(
                    "cargo_type",
                    "",
                )
            ).strip().upper() == "DG":

                required_documents.insert(
                    1,
                    "DG Information",
                )

            completed = sum(
                1
                for document_type
                in required_documents
                if document_type in present
            )

            output.append(
                {
                    "booking_id": booking_id,
                    "cargo_type": shipment.get(
                        "cargo_type",
                        "NON DG",
                    ),
                    "documents_completed": completed,
                    "documents_required": len(
                        required_documents
                    ),
                    "coverage_percent": (
                        round(
                            100
                            * completed
                            / len(
                                required_documents
                            ),
                            1,
                        )
                        if required_documents
                        else 0.0
                    ),
                }
            )

        return output

    def delete_booking(self, booking_id):
        booking_id = str(booking_id)

        with self.connect() as connection:

            for table_name in [
                "document_extractions",
                "documents",
                "deadlines",
                "process_events",
                "shipments",
            ]:
                connection.execute(
                    f"""
                    DELETE FROM {table_name}
                    WHERE booking_id = ?
                    """,
                    (
                        booking_id,
                    ),
                )

            connection.commit()

    def prune_to_active_bookings(self, active_booking_ids):
        active_ids = sorted(
            {
                str(value).strip()
                for value in (
                    active_booking_ids
                    or []
                )
                if str(value).strip()
            }
        )

        with self.connect() as connection:

            tables = [
                "document_extractions",
                "documents",
                "deadlines",
                "process_events",
                "shipments",
            ]

            if not active_ids:
                for table_name in tables:
                    connection.execute(
                        f"DELETE FROM {table_name}"
                    )
            else:
                placeholders = ",".join(
                    "?"
                    for _ in active_ids
                )

                for table_name in tables:
                    connection.execute(
                        f"""
                        DELETE FROM {table_name}
                        WHERE booking_id NOT IN (
                            {placeholders}
                        )
                        """,
                        active_ids,
                    )

            connection.commit()
