"""Copy the rules from ai_act_triage/rules.json into app/index.html.

The browser app has to be a single self-contained file, so it carries its own
copy of the rules between the RULES START and RULES END markers. Run this after
editing rules.json:

    python tools/sync_rules.py

The tests fail if the two copies ever drift apart.
"""

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
RULES = ROOT / "ai_act_triage" / "rules.json"
APP = ROOT / "app" / "index.html"
PATTERN = re.compile(r"(/\* RULES START \*/\n)(.*?)(\n\s*/\* RULES END \*/)", re.S)


def render(rules, indent="  "):
    """The JavaScript statement that defines RULES, one top-level key per line."""
    lines = [indent + "var RULES = {"]
    keys = list(rules)
    for i, key in enumerate(keys):
        value = rules[key]
        comma = "," if i < len(keys) - 1 else ""
        if isinstance(value, list):
            lines.append(indent + "  " + json.dumps(key) + ": [")
            for k, item in enumerate(value):
                lines.append(indent + "    " + json.dumps(item, ensure_ascii=False) + ("," if k < len(value) - 1 else ""))
            lines.append(indent + "  ]" + comma)
        else:
            lines.append(indent + "  " + json.dumps(key) + ": " + json.dumps(value, ensure_ascii=False) + comma)
    lines.append(indent + "};")
    return "\n".join(lines)


def main():
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    html = APP.read_text(encoding="utf-8")
    if not PATTERN.search(html):
        raise SystemExit("Could not find the RULES START / RULES END markers in app/index.html")
    APP.write_text(PATTERN.sub(lambda m: m.group(1) + render(rules) + m.group(3), html, count=1), encoding="utf-8")
    print("Copied the rules into %s" % APP.relative_to(ROOT))


if __name__ == "__main__":
    main()
