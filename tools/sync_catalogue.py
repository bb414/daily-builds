"""Copy assurance_mix/catalogue.json into the app, between DATA START and DATA END.

The app has to work as a single file opened straight from disk, so it carries its
own copy of the catalogue. Run this after editing catalogue.json; the tests fail
if the two copies differ.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app" / "index.html"
CATALOGUE = ROOT / "assurance_mix" / "catalogue.json"
PATTERN = re.compile(r"(/\* DATA START \*/)(.*?)(/\* DATA END \*/)", re.S)


def embedded(html):
    m = PATTERN.search(html)
    if not m:
        raise SystemExit("DATA START/END markers not found in app/index.html")
    return json.loads(m.group(2))


def main():
    data = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    html = APP.read_text(encoding="utf-8")
    compact = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    new = PATTERN.sub(lambda m: m.group(1) + compact + m.group(3), html, count=1)
    if new != html:
        APP.write_text(new, encoding="utf-8")
        print("Updated the catalogue in app/index.html")
    else:
        print("app/index.html already has the current catalogue")
    return 0


if __name__ == "__main__":
    sys.exit(main())
