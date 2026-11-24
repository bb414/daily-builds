"""Copy rangefinder/templates.json into the model block of app/index.html.

Run this after editing the templates so the browser app and the Python
package start from exactly the same examples:

    python tools/embed_templates.py

tests/test_app.py fails if the two copies ever differ.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = "/* TEMPLATES START */"
END = "/* TEMPLATES END */"


def main():
    templates = json.loads((ROOT / "rangefinder" / "templates.json").read_text(encoding="utf-8"))
    html_path = ROOT / "app" / "index.html"
    html = html_path.read_text(encoding="utf-8")
    i = html.index(START) + len(START)
    j = html.index(END)
    literal = json.dumps(templates, ensure_ascii=False, indent=1)
    html_path.write_text(html[:i] + literal + html[j:], encoding="utf-8")
    print("Embedded %d templates into %s" % (len(templates), html_path.relative_to(ROOT)))


if __name__ == "__main__":
    main()
