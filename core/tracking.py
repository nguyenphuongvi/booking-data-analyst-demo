from datetime import datetime
from pathlib import Path
import sqlite3
from contextlib import contextmanager


class TrackingService:

    def __init__(self, database_path):
        self.database_path = Path(
            database_path
        )

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.create_tables()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database_path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create_tables(self):
        with self.connect() as connection:

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS booking_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    booking_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_name TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    source_file TEXT,
                    container_no INTEGER,
                    detail TEXT
                )
                """
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS booking_field_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    booking_id TEXT NOT NULL,
                    container_no TEXT,
                    field_name TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    change_type TEXT NOT NULL,
                    change_time TEXT NOT NULL
                )
                """
            )

            # Snapshot used to detect edits made directly in Excel.
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS booking_snapshot (
                    booking_id TEXT NOT NULL,
                    container_no TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    field_value TEXT,
                    PRIMARY KEY (
                        booking_id,
                        container_no,
                        field_name
                    )
                )
                """
            )

            connection.commit()

    def now(self):
        return (
            datetime.now()
            .astimezone()
            .isoformat(
                timespec="seconds"
            )
        )

    # ======================================================
    # PROCESS EVENTS
    # ======================================================

    def log(
        self,
        booking_id,
        event_type,
        event_name,
        source_file="",
        container_no=None,
        detail="",
    ):
        booking_id = str(
            booking_id or "UNASSIGNED"
        )

        event_time = self.now()

        with self.connect() as connection:

            connection.execute(
                """
                INSERT INTO booking_events (
                    booking_id,
                    event_type,
                    event_name,
                    event_time,
                    source_file,
                    container_no,
                    detail
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    booking_id,
                    event_type,
                    event_name,
                    event_time,
                    source_file,
                    container_no,
                    detail,
                ),
            )

            connection.commit()

        return event_time

    def get_all_events(self):
        with self.connect() as connection:

            cursor = connection.execute(
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
                FROM booking_events
                ORDER BY id DESC
                """
            )

            return cursor.fetchall()

    def get_booking_events(
        self,
        booking_id,
    ):
        with self.connect() as connection:

            cursor = connection.execute(
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
                FROM booking_events
                WHERE booking_id = ?
                ORDER BY id ASC
                """,
                (
                    booking_id,
                ),
            )

            return cursor.fetchall()

    # ======================================================
    # FIELD CHANGE HISTORY
    # ======================================================

    def log_field_change(
        self,
        booking_id,
        field_name,
        old_value,
        new_value,
        change_type,
        container_no=None,
        change_time=None,
    ):
        """
        Append one immutable field-history record.

        change_time can be supplied when the app detects an edit
        made directly in Excel. In that case we use the Excel file's
        saved/modified time instead of the later detection time.

        Existing history is never updated or deleted.
        """

        booking_id = str(
            booking_id or "UNASSIGNED"
        )

        if not change_time:
            change_time = self.now()

        with self.connect() as connection:

            connection.execute(
                """
                INSERT INTO booking_field_history (
                    booking_id,
                    container_no,
                    field_name,
                    old_value,
                    new_value,
                    change_type,
                    change_time
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    booking_id,
                    (
                        None
                        if container_no is None
                        else str(container_no)
                    ),
                    str(field_name),
                    str(old_value or ""),
                    str(new_value or ""),
                    str(change_type),
                    str(change_time),
                ),
            )

            connection.commit()

        return change_time

    def get_all_field_changes(self):
        with self.connect() as connection:

            cursor = connection.execute(
                """
                SELECT
                    id,
                    booking_id,
                    container_no,
                    field_name,
                    old_value,
                    new_value,
                    change_type,
                    change_time
                FROM booking_field_history
                ORDER BY id DESC
                """
            )

            return cursor.fetchall()

    def get_booking_field_changes(
        self,
        booking_id,
    ):
        with self.connect() as connection:

            cursor = connection.execute(
                """
                SELECT
                    id,
                    booking_id,
                    container_no,
                    field_name,
                    old_value,
                    new_value,
                    change_type,
                    change_time
                FROM booking_field_history
                WHERE booking_id = ?
                ORDER BY id ASC
                """,
                (
                    booking_id,
                ),
            )

            return cursor.fetchall()

    # ======================================================
    # EXCEL SNAPSHOT
    # ======================================================

    def get_snapshot(self):
        """
        Return the last known booking data as:
        {
            (booking_id, container_no, field_name): field_value
        }
        """

        with self.connect() as connection:

            cursor = connection.execute(
                """
                SELECT
                    booking_id,
                    container_no,
                    field_name,
                    field_value
                FROM booking_snapshot
                """
            )

            rows = cursor.fetchall()

        return {
            (
                str(booking_id),
                str(container_no),
                str(field_name),
            ): str(field_value or "")
            for (
                booking_id,
                container_no,
                field_name,
                field_value,
            ) in rows
        }

    def replace_snapshot(
        self,
        records,
    ):
        """
        Replace only the current comparison snapshot.

        Defensive rule:
        booking_snapshot has a UNIQUE key on
        (booking_id, container_no, field_name).
        If duplicate records arrive from an Excel layout, keep the
        last value for that key instead of crashing the app.

        This changes ONLY the temporary comparison snapshot.
        Process history and immutable field-history rows are untouched.
        """

        deduplicated = {}

        for record in records or []:

            key = (
                str(record[0]),
                str(record[1]),
                str(record[2]),
            )

            deduplicated[
                key
            ] = str(
                record[3] or ""
            )

        snapshot_rows = [
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
            ), field_value in deduplicated.items()
        ]

        with self.connect() as connection:

            connection.execute(
                """
                DELETE FROM booking_snapshot
                """
            )

            if snapshot_rows:

                connection.executemany(
                    """
                    INSERT INTO booking_snapshot (
                        booking_id,
                        container_no,
                        field_name,
                        field_value
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    snapshot_rows,
                )

            connection.commit()

    def delete_booking(
        self,
        booking_id,
    ):
        """
        Permanently delete one booking from tracking.db.

        Removes every row for the booking from:
        - booking_snapshot
        - booking_field_history
        - booking_events

        The deletion is done in one SQLite transaction.
        """

        booking_id = str(
            booking_id
        )

        with self.connect() as connection:

            connection.execute(
                """
                DELETE FROM booking_snapshot
                WHERE booking_id = ?
                """,
                (
                    booking_id,
                ),
            )

            connection.execute(
                """
                DELETE FROM booking_field_history
                WHERE booking_id = ?
                """,
                (
                    booking_id,
                ),
            )

            connection.execute(
                """
                DELETE FROM booking_events
                WHERE booking_id = ?
                """,
                (
                    booking_id,
                ),
            )

            # Process-oriented model added in the export-process refactor.
            # These tables may not exist in older databases, so check first.
            existing_tables = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type='table'
                    """
                ).fetchall()
            }

            for table_name in [
                "document_extractions",
                "documents",
                "deadlines",
                "process_events",
                "shipments",
            ]:

                if table_name not in existing_tables:
                    continue

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

    def prune_to_active_bookings(
        self,
        active_booking_ids,
    ):
        """
        Permanently remove tracking rows for bookings that are no longer
        active.

        Applies to:
        - booking_events
        - booking_field_history
        - booking_snapshot

        This is intentionally destructive and is used only when the app
        has a confirmed current booking list (for example after export,
        sync, or Delete Booking).
        """

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

            existing_tables = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type='table'
                    """
                ).fetchall()
            }

            tables = [
                table_name
                for table_name in [
                    "booking_snapshot",
                    "booking_field_history",
                    "booking_events",
                    "document_extractions",
                    "documents",
                    "deadlines",
                    "process_events",
                    "shipments",
                ]
                if table_name in existing_tables
            ]

            if active_ids:

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

            else:

                for table_name in tables:

                    connection.execute(
                        f"""
                        DELETE FROM {table_name}
                        """
                    )

            connection.commit()

    def clear_snapshot(self):
        """
        Clear only the comparison snapshot.
        Historical tracking remains untouched.
        """

        with self.connect() as connection:

            connection.execute(
                """
                DELETE FROM booking_snapshot
                """
            )

            connection.commit()
