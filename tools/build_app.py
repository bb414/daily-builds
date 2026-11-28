"""Assemble the single, self-contained app/index.html from the files in src/.

The app is one HTML file that works offline when double-clicked, so the fonts
(as base64 WOFF2), the stylesheet, the model, the interface code and the
sample exports and journal are all written into it.

Run:            python tools/build_app.py
Check only:     python tools/build_app.py --check   (exit 1 if app/index.html is out of date)
"""

import base64
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
OUT = os.path.join(ROOT, "app", "index.html")

FONTS = [
    ("Unbounded", 500, "unbounded-latin-500-normal.woff2"),
    ("Unbounded", 800, "unbounded-latin-800-normal.woff2"),
    ("Manrope", 400, "manrope-latin-400-normal.woff2"),
    ("Manrope", 600, "manrope-latin-600-normal.woff2"),
    ("Manrope", 700, "manrope-latin-700-normal.woff2"),
    ("Manrope", 800, "manrope-latin-800-normal.woff2"),
    ("Martian Mono", 400, "martian-mono-latin-400-normal.woff2"),
    ("Martian Mono", 600, "martian-mono-latin-600-normal.woff2"),
]

# The sample exports the app opens with, and the journal notes that go with them.
SAMPLES = ["challenge-equities.csv", "futures-messy.csv", "dealing-account.csv"]
JOURNAL = "sample-journal.json"


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def font_css():
    rules = ["/* Fonts: Unbounded, Manrope and Martian Mono (Latin subsets), each under the SIL Open Font License 1.1."
             " Embedded so the page works offline. Licence text: src/fonts/OFL.txt */"]
    for family, weight, name in FONTS:
        with open(os.path.join(SRC, "fonts", name), "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        rules.append("@font-face{font-family:'%s';font-style:normal;font-weight:%d;font-display:swap;"
                     "src:url(data:font/woff2;base64,%s) format('woff2');}" % (family, weight, data))
    return "\n".join(rules)


def samples_json():
    data = {
        "files": [{"name": name, "text": read(os.path.join(ROOT, "data", name))} for name in SAMPLES],
        "journal": read(os.path.join(ROOT, "data", JOURNAL)),
    }
    # Keep "</" out of the script block so the HTML parser cannot end it early.
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def build():
    html = read(os.path.join(SRC, "shell.html"))
    parts = {
        "/*FONTS*/": font_css(),
        "/*STYLE*/": read(os.path.join(SRC, "style.css")),
        "/*SAMPLES*/": samples_json(),
        "/*MODEL*/": read(os.path.join(SRC, "model.js")),
        "/*UI*/": read(os.path.join(SRC, "ui.js")),
    }
    for marker, text in parts.items():
        if html.count(marker) != 1:
            raise SystemExit("The marker %s should appear exactly once in src/shell.html" % marker)
        html = html.replace(marker, text.rstrip("\n"))
    return html


def main():
    html = build()
    if "--check" in sys.argv:
        current = read(OUT) if os.path.exists(OUT) else ""
        if current != html:
            print("app/index.html is out of date: run python tools/build_app.py")
            sys.exit(1)
        print("app/index.html is up to date")
        return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    print("Wrote %s (%d KB)" % (os.path.relpath(OUT, ROOT), len(html.encode("utf-8")) // 1024))


if __name__ == "__main__":
    main()
