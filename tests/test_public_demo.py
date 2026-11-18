import tempfile
import unittest
from pathlib import Path
import pandas as pd

from cloud_demo import make_demo_rows, make_demo_workbook, compute_booking_analytics, safe_upload_filename
from core.process_repository import ProcessRepository


class PublicDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = make_demo_rows()
        cls.results = compute_booking_analytics(cls.df)

    def test_deterministic_rows(self):
        self.assertEqual(len(self.df), 262)
        self.assertEqual(len(self.results["shipments"]), 162)

    def test_shipments_vs_containers(self):
        self.assertEqual(int(self.results["shipments"]["Container Count"].sum()), 262)

    def test_valid_lead_time_and_invalid_etd(self):
        self.assertEqual(self.results["quality"]["valid_lead_time"], 160)
        self.assertEqual(self.results["quality"]["invalid_etd"], 2)

    def test_carrier_share_and_hhi(self):
        self.assertAlmostEqual(self.results["carriers"]["Share %"].sum(), 100, delta=.05)
        self.assertGreater(self.results["hhi"], 0)
        self.assertLessEqual(self.results["hhi"], 1)

    def test_monthly_data(self):
        self.assertEqual(len(self.results["monthly"]), 22)
        self.assertTrue(pd.isna(self.results["monthly"].iloc[0]["MoM %"]))
        self.assertEqual(self.results["monthly"]["Bookings"].sum(), 162)

    def test_empty_data_is_safe(self):
        self.assertEqual(len(compute_booking_analytics(pd.DataFrame())["monthly"]), 0)

    def test_safe_file_names(self):
        self.assertEqual(safe_upload_filename('../../customer.pdf'), 'customer.pdf')
        self.assertEqual(safe_upload_filename(r'C:\private\bill.xlsx'), 'bill.xlsx')

    def test_excel_roundtrip(self):
        with tempfile.TemporaryDirectory() as root:
            path = make_demo_workbook(Path(root) / 'booking_data.xlsx')
            loaded = pd.read_excel(path, sheet_name='_BookingsData')
            self.assertEqual(loaded['Booking ID'].nunique(), 162)

    def test_original_process_repository_sync(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'db.sqlite'
            repo=ProcessRepository(p)
            rows=self.df.fillna('').to_dict('records')
            repo.sync_from_booking_records(rows)
            got=repo.get_shipments()
            self.assertEqual(len(got), 162)
            self.assertEqual(sum(x['container_count'] for x in got), 262)


if __name__ == '__main__':
    unittest.main()
