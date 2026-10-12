import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from check_requirements import check_requirements, fetch_json, main


class RequirementsTests(unittest.TestCase):
    @patch("check_requirements.fetch_json")
    def test_counts_and_oldest_use_first_file(self, fetch):
        fetch.side_effect = [
            None,                           # Missing package: no release lookup.
            {}, None,                       # Existing package, missing version.
            {}, {"urls": [
                {"upload_time": "2020-01-01T00:00:00"},
                {"upload_time": "2000-01-01T00:00:00"},
            ]},
            {}, {"urls": [{"upload_time": "2019-12-31T23:59:59"}]},
        ]
        report = check_requirements([
            "absent==1", "badversion==2", "newer==3", "older==4",
        ])
        self.assertEqual(report, "\n".join([
            "Dependencies checked: 4",
            "Packages not on PyPI: 1",
            "Versions not on PyPI: 1",
            "Oldest pinned release: older==4 (2019)",
        ]))
        self.assertEqual(fetch.call_count, 7)

    @patch("check_requirements.fetch_json")
    def test_empty_release_and_physical_line_count(self, fetch):
        fetch.side_effect = [{}, {"urls": []}]
        with redirect_stderr(io.StringIO()) as warnings:
            report = check_requirements(["", "# comment", "pkg==1 # pin"])
        self.assertIn("Dependencies checked: 3", report)
        self.assertIn("Versions not on PyPI: 0", report)
        self.assertIn("Oldest pinned release: None", report)
        self.assertIn("No uploaded files", warnings.getvalue())

    @patch("check_requirements.fetch_json")
    def test_invalid_input_fails_before_network_calls(self, fetch):
        with self.assertRaisesRegex(ValueError, "Line 2"):
            check_requirements(["valid==1", "invalid>=2"])
        fetch.assert_not_called()

    @patch("check_requirements.urlopen")
    def test_only_404_means_missing(self, open_url):
        for status in (404, 429, 500):
            with self.subTest(status=status):
                open_url.side_effect = HTTPError("https://pypi.org", status,
                                                 "error", {}, None)
                if status == 404:
                    self.assertIsNone(fetch_json("https://pypi.org"))
                else:
                    with self.assertRaises(HTTPError):
                        fetch_json("https://pypi.org")


class ExampleFileTests(unittest.TestCase):
    """Run real files through the CLI, replacing only the HTTP transport.

    Requests' timestamp comes from its PyPI JSON response. The demo package
    names and dates below are synthetic fixtures for deterministic edge cases.
    """

    def run_file(self, contents, failure=None):
        root = "https://pypi.org/pypi"
        responses = {
            f"{root}/requests/json": {},
            f"{root}/requests/2.31.0/json": {
                "urls": [{"upload_time": "2023-05-22T15:12:42"}]},
            f"{root}/demo-older/json": {},
            f"{root}/demo-older/1.0/json": {
                "urls": [{"upload_time": "2019-12-31T23:59:59"}]},
            f"{root}/demo-earlier/json": {},
            f"{root}/demo-earlier/99.0/json": {
                "urls": [{"upload_time": "2019-01-01T00:00:00"}]},
            f"{root}/demo-empty/json": {},
            f"{root}/demo-empty/1.0/json": {"urls": []},
        }

        def open_response(request, timeout):
            self.assertEqual(timeout, 20)
            if isinstance(failure, Exception):
                raise failure
            if failure == "invalid-json":
                return io.BytesIO(b"not JSON")
            if request.full_url not in responses:
                raise HTTPError(request.full_url, 404, "Not Found", {}, None)
            return io.BytesIO(json.dumps(responses[request.full_url]).encode())

        stdout, stderr = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "requirement.txt"
            file.write_text(contents, encoding="utf-8")
            with patch("sys.argv", ["check_requirements.py", str(file)]), \
                    patch("check_requirements.urlopen", side_effect=open_response), \
                    redirect_stdout(stdout), redirect_stderr(stderr):
                status = main()
        return status, stdout.getvalue(), stderr.getvalue()

    def test_example_files(self):
        # expected: total physical lines, missing packages, missing versions,
        # oldest release label. Every case checks all four output lines.
        examples = [
            ("all valid", "requests==2.31.0\ndemo-older==1.0\n",
             (2, 0, 0, "demo-older==1.0 (2019)")),
            ("missing package", "demo-nonexistent==1\n",
             (1, 1, 0, "None")),
            ("missing version", "requests==999999.0\n",
             (1, 0, 1, "None")),
            ("mixed results", "requests==2.31.0\ndemo-nonexistent==1\n"
             "requests==999999.0\ndemo-older==1.0\n",
             (4, 1, 1, "demo-older==1.0 (2019)")),
            ("duplicate lines", "demo-nonexistent==1\ndemo-nonexistent==1\n",
             (2, 2, 0, "None")),
            ("comments, blank line, BOM", "\ufeff# comment\n\n requests == 2.31.0 # pin\n",
             (3, 0, 0, "requests==2.31.0 (2023)")),
            ("empty file", "", (0, 0, 0, "None")),
            ("release without files", "demo-empty==1.0\n",
             (1, 0, 0, "None")),
            ("same year, different dates", "demo-older==1.0\ndemo-earlier==99.0",
             (2, 0, 0, "demo-earlier==99.0 (2019)")),
        ]
        for label, contents, expected in examples:
            with self.subTest(example=label):
                status, stdout, stderr = self.run_file(contents)
                total, packages, versions, oldest = expected
                self.assertEqual(status, 0)
                self.assertEqual(stdout, (
                    f"Dependencies checked: {total}\n"
                    f"Packages not on PyPI: {packages}\n"
                    f"Versions not on PyPI: {versions}\n"
                    f"Oldest pinned release: {oldest}\n"))
                if label == "release without files":
                    self.assertIn("No uploaded files", stderr)
                else:
                    self.assertEqual(stderr, "")
                print(f"PASS {label}: {total} lines, {packages} missing packages, "
                      f"{versions} missing versions, oldest {oldest}")

    def test_failures_do_not_print_a_success_report(self):
        failures = [
            ("invalid pin", "requests>=2", None),
            ("server error", "requests==2.31.0",
             HTTPError("https://pypi.org", 500, "server error", {}, None)),
            ("network error", "requests==2.31.0", URLError("connection failed")),
            ("invalid API JSON", "requests==2.31.0", "invalid-json"),
        ]
        for label, contents, failure in failures:
            with self.subTest(example=label):
                status, stdout, stderr = self.run_file(contents, failure)
                self.assertEqual(status, 1)
                self.assertEqual(stdout, "")
                self.assertIn("Check failed:", stderr)
                print(f"PASS {label}: exits with an error and no success report")


if __name__ == "__main__":
    unittest.main()
