"""Check a file of name==version pins using only the Python standard library.

All physical lines count toward the total. Blank lines and comments are skipped
for API checks; other requirement formats are rejected with a line number.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


PIN = re.compile(r"([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*==\s*([^\s=<>!~;*]+)")


def fetch_json(url):
    """Return JSON, or None for 404; propagate all other failures."""
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise


def check_requirements(lines):
    pins = []
    for number, line in enumerate(lines, start=1):
        entry = line.split("#", 1)[0].strip()
        if not entry:
            continue
        match = PIN.fullmatch(entry)
        if not match:
            raise ValueError(f"Line {number}: expected name==version, got {entry!r}")
        pins.append(match.groups())

    missing_packages = 0
    missing_versions = 0
    oldest = None

    for name, version in pins:
        base_url = f"https://pypi.org/pypi/{quote(name, safe='')}"
        if fetch_json(f"{base_url}/json") is None:
            missing_packages += 1
            continue

        release = fetch_json(f"{base_url}/{quote(version, safe='')}/json")
        if release is None:
            missing_versions += 1
            continue

        files = release["urls"]
        if not files:
            print(f"No uploaded files for {name}=={version}; no release date available.",
                  file=sys.stderr)
            continue

        uploaded = datetime.fromisoformat(files[0]["upload_time"])
        if oldest is None or uploaded < oldest[0]:
            oldest = (uploaded, name, version)

    oldest_label = "None"
    if oldest is not None:
        uploaded, name, version = oldest
        oldest_label = f"{name}=={version} ({uploaded.year})"

    return "\n".join([
        f"Dependencies checked: {len(lines)}",
        f"Packages not on PyPI: {missing_packages}",
        f"Versions not on PyPI: {missing_versions}",
        f"Oldest pinned release: {oldest_label}",
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", nargs="?", default="requirement.txt",
                        help="requirements file (default: requirement.txt)")
    args = parser.parse_args()
    try:
        lines = Path(args.file).read_text(encoding="utf-8-sig").splitlines()
        report = check_requirements(lines)
    except (OSError, URLError, ValueError, KeyError, TypeError) as error:
        print(f"Check failed: {error}", file=sys.stderr)
        return 1
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
