import csv
import importlib.util
import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import urlopen, Request, build_opener
from http.server import ThreadingHTTPServer

spec = importlib.util.spec_from_file_location("exporter", Path(__file__).parents[1] / "unifi_badge_export/exporter.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def user(key="a", first="José, \"Joe\"", last="Pietkiewicz", number="00123", status="ACTIVE"):
    return dict(id=key, first_name=first, last_name=last, employee_number=number, status=status)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.options = {"output_folder": "unifi-badges"}
        self.client = Mock()
        self.client.users.return_value = [user(), user("b", status="DEACTIVATED")]

    def tearDown(self):
        self.temp.cleanup()

    def csv_bytes(self):
        return (self.root / "unifi-badges/employees.csv").read_bytes()

    def run_export(self):
        return m.export(self.options, self.client, self.root)

    def test_windows_csv_unicode_quoted_name_zeroes_and_active_filter(self):
        result = self.run_export()
        data = self.csv_bytes()
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(data.count(b"\r\n"), 2)
        rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
        self.assertEqual(rows[0]["ID"], "00123")
        self.assertEqual(rows[0]["FullName"], 'José, "Joe" Pietkiewicz')
        self.assertEqual(result["active_users"], 1)
        self.assertEqual(rows[0]["UserID"], "a")
        self.assertIn("Col5=ID Text", (self.root / "unifi-badges/schema.ini").read_text())

    def test_empty_or_failed_sync_preserves_existing_export(self):
        self.run_export()
        before = self.csv_bytes()
        self.client.users.return_value = []
        with self.assertRaises(m.ExportError):
            self.run_export()
        self.assertEqual(before, self.csv_bytes())
        self.client.users.side_effect = m.ExportError("401")
        with self.assertRaises(m.ExportError):
            self.run_export()
        self.assertEqual(before, self.csv_bytes())

    def test_incomplete_validation_does_not_replace_csv(self):
        self.run_export()
        before = self.csv_bytes()
        self.client.users.return_value = [user(), user("c", number=456)]
        with self.assertRaises(m.ExportError):
            self.run_export()
        self.assertEqual(before, self.csv_bytes())

    def test_empty_can_be_intentionally_exported(self):
        self.options["allow_empty_export"] = True
        self.client.users.return_value = []
        self.assertEqual(self.run_export()["active_users"], 0)
        self.assertEqual(self.csv_bytes().count(b"\r\n"), 1)

    def test_failed_atomic_replace_leaves_previous_file(self):
        self.run_export()
        before = self.csv_bytes()
        self.client.users.return_value = [user(first="Changed")]
        original = m.os.replace
        def replace(src, dst):
            if Path(dst).name == "employees.csv":
                raise PermissionError("locked")
            return original(src, dst)
        with patch.object(m.os, "replace", side_effect=replace):
            with self.assertRaises(PermissionError):
                self.run_export()
        self.assertEqual(before, self.csv_bytes())

    def test_missing_and_duplicate_employee_numbers_reported(self):
        self.client.users.return_value = [user(), user("b"), user("c", number="")]
        self.assertEqual(len(self.run_export()["warnings"]), 2)

    def test_output_traversal_rejected(self):
        self.options["output_folder"] = "../elsewhere"
        with self.assertRaises(m.ExportError):
            self.run_export()

    def test_photos_use_static_api_and_keep_existing_on_failure(self):
        self.options.update(export_photos=True, windows_photo_folder=r"\\HA\share\unifi-badges\photos")
        self.client.users.return_value = [dict(user(), user_avatar="https://external.example/avatar/abc-123")]
        self.client.get.return_value = b"\xff\xd8\xfftestfixture"
        self.run_export()
        self.client.get.assert_called_with("/api/v1/developer/system/static/avatar/abc-123", binary=True)
        before = self.csv_bytes()
        self.client.get.side_effect = m.ExportError("403")
        self.assertEqual(len(self.run_export()["warnings"]), 1)
        self.assertEqual(before, self.csv_bytes())


class ApiTests(unittest.TestCase):
    def client(self):
        return m.Client({"console_url": "https://192.168.1.2", "api_token": "SECRET"})

    def test_api_host_defaults_and_explicit_ports(self):
        self.assertEqual(self.client().base, "https://192.168.1.2:12445")
        c = m.Client({"console_url": "https://192.168.1.2:12455", "api_token": "SECRET"})
        self.assertEqual(c.base, "https://192.168.1.2:12455")

    def test_pagination_fetches_all_pages_even_with_server_page_limit(self):
        c = self.client()
        c.get = Mock(side_effect=[
            dict(data=[user()], pagination=dict(total=2, page_num=1)),
            dict(data=[user("b")], pagination=dict(total=2, page_num=2))])
        self.assertEqual(len(c.users()), 2)
        self.assertIn("page_num=2", c.get.call_args.args[0])

    def test_duplicate_missing_and_changing_pages_fail(self):
        for second in [dict(data=[user()], pagination=dict(total=2, page_num=2)),
                       dict(data=[], pagination=dict(total=2, page_num=2)),
                       dict(data=[user("b")], pagination=dict(total=3, page_num=2))]:
            c = self.client()
            c.get = Mock(side_effect=[dict(data=[user()], pagination=dict(total=2, page_num=1)), second])
            with self.assertRaises(m.ExportError):
                c.users()

    def test_http_error_does_not_disclose_token(self):
        c = self.client()
        c.opener = Mock()
        c.opener.open.side_effect = HTTPError("https://example/SECRET", 401, "SECRET", {}, None)
        with self.assertRaises(m.ExportError) as caught:
            c.get("/api/v1/developer/users")
        self.assertNotIn("SECRET", str(caught.exception))

    def test_api_can_only_read_developer_path(self):
        with self.assertRaises(m.ExportError):
            self.client().get("https://other.example")


class WebTests(unittest.TestCase):
    def test_ingress_denies_direct_requests_and_manual_sync_works(self):
        service = Mock()
        service.status.return_value = {"active_users": 2, "error": None}
        service.wake = threading.Event()
        handler = m.handler_for(service)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with self.assertRaises(HTTPError) as caught:
                urlopen(base + "/status")
            self.assertEqual(caught.exception.code, 403)
            with patch.object(handler, "allowed", return_value=True):
                with urlopen(base + "/status") as response:
                    self.assertIn(b'"active_users": 2', response.read())
                with urlopen(base + "/") as response:
                    self.assertIn(b'action="sync"', response.read())
                opener = build_opener(m.NoRedirect())
                with self.assertRaises(HTTPError) as caught:
                    opener.open(Request(base + "/sync", data=b"", method="POST"))
                self.assertEqual(caught.exception.code, 303)
                self.assertTrue(service.wake.is_set())
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
