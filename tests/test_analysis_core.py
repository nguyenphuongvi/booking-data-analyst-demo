import io
import sqlite3
import sys
from pathlib import Path
import tempfile
import unittest

import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from analysis_core import (
    analysis_sample, category_breakdown, hhi, insights, monthly_trend,
    numeric_summary, prepare_bookings, profile, quality_metrics, safe_export_csv,
)
from sample_data import make_demo
from sqlite_export import export_sqlite_bytes


class TestBookingAnalysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw=make_demo(n=130)
        cls.df=prepare_bookings(cls.raw)
        cls.clean=analysis_sample(cls.df)

    def test_demo_has_multiple_months_and_explicit_duplicates(self):
        self.assertGreater(self.df["booking_month"].nunique(),12)
        self.assertTrue(self.df["suspected_duplicate"].any())

    def test_no_row_deleted_during_cleaning(self):
        self.assertEqual(len(self.df),len(self.raw))

    def test_deduplicate_scenario_excludes_all_flagged_rows(self):
        self.assertFalse(self.clean["suspected_duplicate"].any())
        self.assertEqual(len(self.clean), len(self.df)-self.df["suspected_duplicate"].sum())

    def test_profile_distinguishes_present_and_valid_dates(self):
        p=profile(self.df).set_index("Trường dữ liệu")
        self.assertGreater(p.loc["etd","Có giá trị"],p.loc["etd","Hợp lệ định dạng"])

    def test_alias_mapping(self):
        columns={"carrier":"shipping_line","pol":"port_of_loading","pod":"port_of_discharge","gross_weight_kg":"gross_weight"}
        d=prepare_bookings(self.raw.rename(columns=columns))
        self.assertIn("carrier",d.columns)
        self.assertIn("gross_weight_kg",d.columns)

    def test_date_parse_and_negative_leads(self):
        tiny=pd.DataFrame([{"shipment_id":"X","booking_date":"2026-09-10","etd":"2026-09-01"}])
        f=prepare_bookings(tiny)
        self.assertTrue(f["lead_anomaly"].iloc[0])
        self.assertTrue(pd.isna(f["lead_days"].iloc[0]))

    def test_numeric_summary_matches_pandas(self):
        s=numeric_summary(self.clean,"lead_days")
        expected=self.clean["lead_days"].dropna()
        self.assertEqual(s["n"],len(expected))
        self.assertAlmostEqual(s["median"],float(expected.median()))
        self.assertAlmostEqual(s["p90"],float(expected.quantile(.9)))

    def test_hhi_bounds(self):
        v=hhi(self.clean)
        self.assertGreaterEqual(v,0)
        self.assertLessEqual(v,10000)

    def test_trend_mom_yoy_ma(self):
        t=monthly_trend(self.clean)
        self.assertTrue(pd.isna(t["mom_pct"].iloc[0]))
        self.assertTrue(pd.isna(t["yoy_pct"].iloc[0]))
        self.assertTrue(pd.isna(t["ma3"].iloc[0]))
        self.assertTrue((t["bookings"]>=0).all())

    def test_categories_and_insight(self):
        c=category_breakdown(self.clean,"carrier")
        self.assertGreaterEqual(len(c),1)
        self.assertTrue(len(insights(self.df,self.clean))>=3)

    def test_missing_key_error(self):
        with self.assertRaisesRegex(ValueError,"Thiếu cột"):
            prepare_bookings(pd.DataFrame({"shipment_id":["X"],"etd":["2026-01-01"]}))

    def test_safe_csv_formula(self):
        v=safe_export_csv(pd.DataFrame({"x":["=SUM(1,2)","hello", "@cmd"]})).decode("utf-8-sig")
        self.assertIn("'=SUM",v)
        self.assertIn("'@cmd",v)

    def test_sqlite_export_fk_and_count(self):
        payload=export_sqlite_bytes(self.clean)
        with tempfile.NamedTemporaryFile(suffix=".db") as f:
            Path(f.name).write_bytes(payload)
            conn=sqlite3.connect(f.name)
            self.assertEqual(conn.execute("SELECT count(*) FROM booking_analysis").fetchone()[0],len(self.clean))
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(),[])
            self.assertGreater(conn.execute("SELECT count(*) FROM carriers").fetchone()[0],0)
            conn.close()


if __name__ == "__main__":
    unittest.main()
