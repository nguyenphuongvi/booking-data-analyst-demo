"""Chuyển một tập dữ liệu phân tích thành SQLite độc lập (KHÔNG ghi DB gốc)."""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import tempfile

import pandas as pd


def _val(v):
    if v is None or pd.isna(v):
        return None
    if isinstance(v,pd.Timestamp):
        return v.strftime("%Y-%m-%d")
    if hasattr(v, "item"):
        v=v.item()
    return v


def export_sqlite_bytes(data: pd.DataFrame) -> bytes:
    """Xuất snapshot theo mô hình dimension/carrier/port + fact shipments.

    Fact dùng analysis_row_id làm PK vì shipment_id có thể lặp trong bản thô;
    tuyệt đối không thay đổi khóa nghiệp vụ của cơ sở dữ liệu chính.
    """
    con=sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript("""
        CREATE TABLE carriers (carrier_id INTEGER PRIMARY KEY, carrier_name TEXT NOT NULL UNIQUE);
        CREATE TABLE ports (port_id INTEGER PRIMARY KEY, port_name TEXT NOT NULL UNIQUE);
        CREATE TABLE booking_analysis (
            analysis_row_id INTEGER PRIMARY KEY,
            shipment_id TEXT, booking_no TEXT, booking_date TEXT, etd TEXT, eta TEXT,
            carrier_id INTEGER REFERENCES carriers(carrier_id),
            pol_id INTEGER REFERENCES ports(port_id),
            pod_id INTEGER REFERENCES ports(port_id),
            customer TEXT, container_count REAL, gross_weight_kg REAL, cbm REAL,
            product TEXT, status TEXT, suspected_duplicate INTEGER NOT NULL DEFAULT 0,
            lead_days REAL, transit_days REAL
        );
        CREATE INDEX idx_analysis_booking_date ON booking_analysis(booking_date);
        CREATE INDEX idx_analysis_carrier ON booking_analysis(carrier_id);
        CREATE INDEX idx_analysis_route ON booking_analysis(pol_id, pod_id);
    """)
    carriers=sorted({str(v) for v in data["carrier"].dropna()})
    ports=sorted({str(v) for c in ("pol","pod") for v in data[c].dropna()})
    con.executemany("INSERT INTO carriers(carrier_name) VALUES (?)",[(c,) for c in carriers])
    con.executemany("INSERT INTO ports(port_name) VALUES (?)",[(p,) for p in ports])
    ids_carrier={row[1]:row[0] for row in con.execute("SELECT carrier_id,carrier_name FROM carriers")}
    ids_port={row[1]:row[0] for row in con.execute("SELECT port_id,port_name FROM ports")}
    stmt="""INSERT INTO booking_analysis(
      shipment_id, booking_no, booking_date, etd, eta, carrier_id, pol_id, pod_id,
      customer, container_count, gross_weight_kg, cbm, product, status,
      suspected_duplicate, lead_days, transit_days
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    values=[]
    for row in data.to_dict("records"):
        carrier=_val(row.get("carrier")); pol=_val(row.get("pol")); pod=_val(row.get("pod"))
        values.append((
            _val(row.get("shipment_id")), _val(row.get("booking_no")),
            _val(row.get("booking_date_parsed")),_val(row.get("etd_parsed")),_val(row.get("eta_parsed")),
            ids_carrier.get(carrier),ids_port.get(pol),ids_port.get(pod),
            _val(row.get("customer")),_val(row.get("container_count")),
            _val(row.get("gross_weight_kg")),_val(row.get("cbm")),
            _val(row.get("product")),_val(row.get("status")),
            int(bool(row.get("suspected_duplicate",False))),_val(row.get("lead_days")),_val(row.get("transit_days"))
        ))
    con.executemany(stmt,values)
    failures=con.execute("PRAGMA foreign_key_check").fetchall()
    if failures:
        raise RuntimeError(f"SQLite FK integrity error: {failures}")
    con.commit()  # sqlite3.backup phải chạy bên ngoài write transaction.
    with tempfile.NamedTemporaryFile(prefix="booking_analysis_",suffix=".db",delete=False) as tf:
        path=Path(tf.name)
    try:
        disk=sqlite3.connect(str(path))
        con.backup(disk)
        disk.close()
        payload=path.read_bytes()
    finally:
        path.unlink(missing_ok=True)
        con.close()
    return payload
