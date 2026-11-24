"""Copy crutch_check/messages.json into the model block of app/index.html.

Run this after editing the message bank so the browser app and the Python
package use exactly the same messages:

    python tools/embed_messages.py

tests/test_app.py fails if the two copies ever differ.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = "/* MESSAGES START */"
END = "/* MESSAGES END */"


def main():
    bank = json.loads((ROOT / "crutch_check" / "messages.json").read_text(encoding="utf-8"))
    html_path = ROOT / "app" / "index.html"
    html = html_path.read_text(encoding="utf-8")
    i = html.index(START) + len(START)
    j = html.index(END)
    literal = json.dumps(bank, ensure_ascii=False, indent=1)
    html_path.write_text(html[:i] + literal + html[j:], encoding="utf-8")
    print("Embedded %d messages into %s" % (len(bank["messages"]), html_path.relative_to(ROOT)))


if __name__ == "__main__":
    main()
