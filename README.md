# PyPI Dependency Checker

A Python script that checks pinned dependencies against the PyPI JSON API before
installing them. It uses only Python's standard library; no pip installation is
needed to run the checker.

## Run

Use Python 3.7 or newer. Save one `name==version` entry per line, then run:

```bash
python3 check_requirements.py requirement.txt
```

The filename defaults to `requirement.txt` when omitted. You can pass any other
filename, such as `requirements.txt`.

The included `requirement.txt` is an example with eight entries, including
nonexistent packages and versions. A report has this format:

```text
Dependencies checked: 8
Packages not on PyPI: 2
Versions not on PyPI: 2
Oldest pinned release: python-dateutil==2.2 (2013)
```

Results reflect the contents of PyPI at the time of the check.

## How it works

- Checks the package at `https://pypi.org/pypi/<name>/json`.
- Checks its pinned release at `https://pypi.org/pypi/<name>/<version>/json`.
- Counts a 404 as a missing package or version.
- Finds the oldest valid pin using `urls[0]["upload_time"]` for each release.

All physical file lines count toward the total, including duplicates, blank
lines, and comments. Blank lines and comments skip API checks. Only exact
`name==version` pins are accepted; unsupported formats report a line number.
Releases without uploaded files have no available date and are excluded from
the oldest-release comparison. If no dated releases exist, that result is `None`.

Connection failures, other HTTP errors, and invalid API responses cause an error
message and exit code 1. A completed report returns exit code 0.

See the [PyPI JSON API documentation](https://docs.pypi.org/api/json/).

## Tests

```bash
python3 -B -m unittest -v test_check_requirements.py
```

Tests run offline using controlled HTTP responses. They cover missing packages,
missing versions, timestamps, file parsing, duplicate lines, empty releases,
and error handling.
