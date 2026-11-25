"""Build the portfolio website from the index on main and every build branch.

Run from the repository root, with the build branches fetched:

    git fetch --depth=1 origin '+refs/heads/build/*:refs/remotes/origin/build/*'
    python site/build_site.py --out _site

It reads the projects table in README.md, then for each project takes the
browser app, the screenshots and example outputs, the README and (if there is
one) FINDINGS.md from its branch. Source code is never copied, so the site
shows each app and its write-up while the code stays in the private repo.

Needs the `markdown` package; `Pillow` is optional and makes small thumbnails.
"""

import argparse
import datetime
import html
import json
import os
import re
import shutil
import subprocess
import sys

import markdown

try:
    from PIL import Image
except ImportError:  # thumbnails fall back to the full screenshot
    Image = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# File types that are safe and useful to publish: the app and its media.
PUBLISH_EXT = {".html", ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
               ".csv", ".json", ".txt", ".pdf"}
PUBLISH_DIRS = ("app/", "docs/", "examples/", "data/")
MAX_FILE_BYTES = 8 * 1024 * 1024
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")
# Screenshots are the bulk of the site. Big ones are resized and given a
# 256-colour palette, which keeps app screenshots sharp at a third of the size.
SHRINK_OVER_BYTES = 150 * 1024
MAX_IMAGE_WIDTH = 1400
# GitHub Pages sites should stay under 1 GB; warn well before that.
WARN_SITE_BYTES = 800 * 1024 * 1024


# ---------------------------------------------------------------------------
# Reading the repository
# ---------------------------------------------------------------------------

def git(*args, binary=False):
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True)
    return out.stdout if binary else out.stdout.decode("utf-8")


def branch_ref(branch):
    """Prefer the fetched remote branch, fall back to a local one."""
    for ref in ("origin/" + branch, branch):
        try:
            git("rev-parse", "--verify", "--quiet", ref + "^{commit}")
            return ref
        except subprocess.CalledProcessError:
            continue
    return None


def list_files(ref):
    return [f for f in git("ls-tree", "-r", "--name-only", ref).splitlines() if f]


def read_file(ref, path, binary=False):
    return git("show", "%s:%s" % (ref, path), binary=binary)


def blob_id(ref, path):
    return git("rev-parse", "%s:%s" % (ref, path)).strip()


def file_size(ref, path):
    return int(git("cat-file", "-s", "%s:%s" % (ref, path)).strip())


def parse_table(readme):
    """Rows of the projects table: date, name, what, theme, stack, branch."""
    rows = []
    in_table = False
    for line in readme.splitlines():
        if line.startswith("|------|"):
            in_table = True
            continue
        if not in_table:
            continue
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6:
            continue
        m = re.search(r"\[([^\]]+)\]", cells[5])
        branch = m.group(1) if m else cells[5]
        if not branch.startswith("build/"):
            continue
        rows.append({"date": cells[0], "name": cells[1], "what": cells[2], "theme": cells[3],
                     "stack": cells[4], "branch": branch})
    return rows


# ---------------------------------------------------------------------------
# Categories, summaries and slugs
# ---------------------------------------------------------------------------

def load_config():
    with open(os.path.join(HERE, "site.json"), encoding="utf-8") as f:
        return json.load(f)


def categorise(theme, branch, config):
    """The first category whose keywords appear in the theme, unless overridden."""
    override = config.get("categoryOverrides", {}).get(branch)
    if override:
        return override
    low = theme.lower()
    for cat in config["categories"]:
        if any(k in low for k in cat["keywords"]):
            return cat["id"]
    return "other"


def slugify(branch):
    return re.sub(r"[^a-z0-9-]+", "-", branch.split("/", 1)[-1].lower()).strip("-")


def strip_md(text):
    text = re.sub(r"\*\*|__|`", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return text.strip()


def shorten(text, limit=190):
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:(")
    return cut + "…"


DISCLAIMER_RE = re.compile(r"illustrative|not legal advice|not financial advice|disclaimer", re.I)


def opening_paragraphs(readme_text, limit=4):
    """The first few plain paragraphs after the title, stopping at the first heading."""
    paras, cur, seen_h1 = [], [], False
    for line in readme_text.splitlines():
        if line.startswith("# ") and not seen_h1:
            seen_h1 = True
            continue
        if not seen_h1:
            continue
        if line.startswith("#"):
            break
        if not line.strip() or line.startswith(("!", "|", "-", "<", "```", "*   ")):
            if cur:
                paras.append(" ".join(cur))
                cur = []
            if len(paras) >= limit:
                break
            continue
        cur.append(line.strip())
    if cur and len(paras) < limit:
        paras.append(" ".join(cur))
    return paras


def tagline(readme_text, what, override=None):
    """A one-line hook for cards: the README's bold opening question if it has one,
    else the first sentence of its opening, skipping disclaimers; else the index summary."""
    if override:
        return override
    paras = opening_paragraphs(readme_text)
    for para in paras:
        whole = re.fullmatch(r"\*\*(.+?)\*\*", para)
        if whole and not DISCLAIMER_RE.search(whole.group(1)):
            return shorten(whole.group(1))
    for para in paras:
        lead = re.match(r"\*\*(.+?)\*\*\s*(.*)", para)
        if lead and DISCLAIMER_RE.search(lead.group(1)):
            continue  # a disclaimer paragraph: look further
        if lead and len(lead.group(1)) >= 25:
            return shorten(strip_md(lead.group(1)))
        sentence = re.split(r"(?<=[.?!])\s", strip_md(para), maxsplit=1)[0]
        if len(sentence) > 30 and not DISCLAIMER_RE.search(sentence):
            return shorten(sentence)
    return shorten(strip_md(what))


def first_image(readme_text, published):
    """The first screenshot the README shows that we publish, else the first in docs/."""
    for m in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)\)|<img[^>]+src=\"([^\"]+)\"", readme_text):
        path = (m.group(1) or m.group(2)).lstrip("./")
        if path in published and path.lower().endswith(IMAGE_EXT):
            return path
    for path in sorted(published):
        if path.startswith("docs/") and path.lower().endswith(IMAGE_EXT):
            return path
    return None


# ---------------------------------------------------------------------------
# Markdown to HTML, keeping only links that work on the public site
# ---------------------------------------------------------------------------

LINK_RE = re.compile(r"<a\s+([^>]*?)href=\"([^\"]*)\"([^>]*)>(.*?)</a>", re.S)
IMG_RE = re.compile(r"<img\s+[^>]*?src=\"([^\"]*)\"[^>]*>", re.S)


def render_markdown(text, published, page_map, drop_lead=None):
    """Render and rewrite links: published files and pages stay, everything else becomes text.

    The title is dropped (the page shows its own), and so is a bold opening line
    that repeats the tagline shown above it."""
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"], output_format="html")
    body = re.sub(r"<h1>.*?</h1>\s*", "", body, count=1, flags=re.S)
    if drop_lead:
        lead = re.match(r"\s*<p><strong>(.*?)</strong></p>\s*", body, re.S)
        if lead and html.unescape(re.sub(r"<[^>]+>", "", lead.group(1))).strip() == drop_lead.rstrip("\u2026").strip():
            body = body[lead.end():]

    def fix_href(target):
        if target.startswith("#") or target.startswith("mailto:"):
            return target
        if re.match(r"https?://", target):
            if "github.com/bb414/daily-builds" in target:
                return None  # the repository is private
            return target
        path, _, frag = target.partition("#")
        path = path.lstrip("./")
        if path in page_map:
            return page_map[path] + ("#" + frag if frag else "")
        if path in published:
            return path + ("#" + frag if frag else "")
        return None

    def link(m):
        new = fix_href(html.unescape(m.group(2)))
        if new is None:
            return '<span class="was-link">%s</span>' % m.group(4)
        ext = ' target="_blank" rel="noopener"' if re.match(r"https?://", new) else ""
        return '<a %shref="%s"%s%s>%s</a>' % (m.group(1), html.escape(new, quote=True), m.group(3), ext, m.group(4))

    def img(m):
        src = html.unescape(m.group(1)).lstrip("./")
        if src in published:
            tag = m.group(0)
            return tag if "loading=" in tag else tag.replace("<img ", '<img loading="lazy" ', 1)
        return ""

    body = LINK_RE.sub(link, body)
    body = IMG_RE.sub(img, body)
    body = body.replace("<table>", '<div class="table-scroll"><table>').replace("</table>", "</table></div>")
    return body


# ---------------------------------------------------------------------------
# Page templates
# ---------------------------------------------------------------------------

def esc(text):
    return html.escape(str(text), quote=True)


def page(title, body, depth, description, config, page_class=""):
    up = "../" * depth
    return """<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<meta name="description" content="%(desc)s">
<link rel="stylesheet" href="%(up)sstatic/style.css">
<link rel="icon" href="%(up)sstatic/icon.svg" type="image/svg+xml">
</head>
<body class="%(cls)s">
<a class="skip" href="#main">Skip to the content</a>
<header class="site-head"><div class="wrap">
<a class="brand" href="%(up)sindex.html">%(name)s</a>
<nav aria-label="Site"><a href="%(up)sindex.html#archive">Projects</a><a href="%(up)sarchive.html">By month</a><a href="%(up)sabout.html">About</a></nav>
</div></header>
<main id="main">
%(body)s
</main>
<footer class="site-foot"><div class="wrap">
<p>%(foot)s</p>
</div></footer>
</body>
</html>
""" % {"title": esc(title), "desc": esc(description), "up": up, "cls": page_class, "name": esc(config["name"]),
       "body": body, "foot": esc(config["footer"])}


def fmt_date(iso):
    d = datetime.date.fromisoformat(iso)
    return "%d %s %d" % (d.day, d.strftime("%B"), d.year)


def card_html(p, cats, up=""):
    thumb = ('<img src="%s%s" alt="" loading="lazy" width="640" height="400">' % (up, esc(p["thumb"]))
             if p.get("thumb") else '<span class="no-thumb" aria-hidden="true">%s</span>' % esc(p["name"][:1]))
    cat = cats.get(p["category"], {"name": "Other"})
    return ('<article class="card"><a class="card-link" href="%(up)s%(url)s">'
            '<div class="thumb">%(thumb)s</div><div class="card-body">'
            '<p class="meta"><time datetime="%(date)s">%(nice)s</time><span class="cat" data-cat="%(cid)s">%(cat)s</span></p>'
            '<h3>%(name)s</h3><p class="tag">%(tag)s</p></div></a></article>') % {
        "up": up, "url": esc(p["url"]), "thumb": thumb, "date": esc(p["date"]), "nice": esc(fmt_date(p["date"])),
        "cid": esc(p["category"]), "cat": esc(cat["name"]), "name": esc(p["name"]), "tag": esc(p["tagline"])}


def build(out, config, cache=None):
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
        readme = f.read()
    rows = parse_table(readme)
    cats = {c["id"]: c for c in config["categories"]}
    cats["other"] = {"id": "other", "name": "Other", "keywords": [], "blurb": "Projects outside the usual themes."}

    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(os.path.join(out, "projects"))
    shutil.copytree(os.path.join(HERE, "static"), os.path.join(out, "static"))

    projects, skipped = [], []
    for row in rows:
        ref = branch_ref(row["branch"])
        if not ref:
            skipped.append(row["branch"])
            continue
        slug = slugify(row["branch"])
        dest = os.path.join(out, "projects", slug)
        os.makedirs(dest)
        files = list_files(ref)
        published = set()
        for path in files:
            ext = os.path.splitext(path)[1].lower()
            if not path.startswith(PUBLISH_DIRS) or ext not in PUBLISH_EXT:
                continue
            if file_size(ref, path) > MAX_FILE_BYTES:
                continue
            target = os.path.join(dest, path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            cached = os.path.join(cache, blob_id(ref, path) + ext) if cache and ext in (".png", ".jpg", ".jpeg") else None
            if cached and os.path.exists(cached):
                shutil.copyfile(cached, target)
            else:
                with open(target, "wb") as f:
                    f.write(read_file(ref, path, binary=True))
                if ext in (".png", ".jpg", ".jpeg"):
                    shrink_image(target)
                    if cached:
                        shutil.copyfile(target, cached)
            published.add(path)
        app = "app/index.html" if "app/index.html" in published else next((p for p in sorted(published) if p.startswith("app/") and p.endswith(".html")), None)
        readme_text = read_file(ref, "README.md") if "README.md" in files else ""
        findings_text = read_file(ref, "FINDINGS.md") if "FINDINGS.md" in files else ""
        page_map = {"README.md": "index.html"}
        if findings_text:
            page_map["FINDINGS.md"] = "findings.html"
        shot = first_image(readme_text, published)
        thumb = None
        if shot:
            thumb_cache = os.path.join(cache, "thumb-" + blob_id(ref, shot) + ".jpg") if cache else None
            if thumb_cache and os.path.exists(thumb_cache):
                shutil.copyfile(thumb_cache, os.path.join(dest, "thumb.jpg"))
                thumb = True
            else:
                thumb = make_thumb(os.path.join(dest, shot), os.path.join(dest, "thumb.jpg"))
                if thumb and thumb_cache:
                    shutil.copyfile(os.path.join(dest, "thumb.jpg"), thumb_cache)
            thumb = "projects/%s/%s" % (slug, "thumb.jpg" if thumb else shot)
        line = tagline(readme_text, row["what"], config.get("taglines", {}).get(row["branch"]))
        caps = image_captions(readme_text)
        shown = [m.group(1) or m.group(2) for m in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)\)|<img[^>]+src=\"([^\"]+)\"", readme_text)]
        order = [x.lstrip("./") for x in shown if x.lstrip("./") in published and x.lower().endswith(IMAGE_EXT)]
        order += sorted(x for x in published if x.startswith("docs/") and x.lower().endswith(IMAGE_EXT) and x not in order)
        shots = []
        for x in order:
            if x not in [s[0] for s in shots]:
                shots.append((x, caption_for(x, caps)))
        projects.append({
            "slug": slug, "branch": row["branch"], "date": row["date"], "name": strip_md(row["name"]),
            "what": strip_md(row["what"]), "theme": strip_md(row["theme"]), "stack": strip_md(row["stack"]),
            "category": categorise(row["theme"], row["branch"], config),
            "tagline": line,
            "url": "projects/%s/index.html" % slug, "app": app, "shot": shot, "thumb": thumb,
            "findings": bool(findings_text), "shots": shots,
            "_readme": render_markdown(readme_text, published, page_map, line) if readme_text else "",
            "_findings": render_markdown(findings_text, published, page_map) if findings_text else "",
        })

    # Newest first; ties keep the order of the index (newest first within a day).
    projects.sort(key=lambda p: p["date"], reverse=True)
    for i, p in enumerate(projects):
        newer = projects[i - 1] if i > 0 else None
        older = projects[i + 1] if i + 1 < len(projects) else None
        write_project(out, p, newer, older, cats, config)

    write_index(out, projects, cats, config)
    write_archive(out, projects, cats, config)
    write_about(out, projects, config)
    public = [{k: v for k, v in p.items() if not k.startswith("_")} for p in projects]
    with open(os.path.join(out, "projects.json"), "w", encoding="utf-8") as f:
        json.dump({"generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "projects": public}, f, indent=1)
    return projects, skipped


def shrink_image(path):
    """Resize and compress a large screenshot in place, keeping its file name."""
    if Image is None or os.path.getsize(path) <= SHRINK_OVER_BYTES:
        return
    try:
        with Image.open(path) as im:
            fmt = im.format
            im = im.convert("RGB")
            if im.width > MAX_IMAGE_WIDTH:
                im = im.resize((MAX_IMAGE_WIDTH, round(im.height * MAX_IMAGE_WIDTH / im.width)), Image.LANCZOS)
            if fmt == "PNG":
                im = im.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
                im.save(path, "PNG", optimize=True)
            else:
                im.save(path, "JPEG", quality=82, optimize=True, progressive=True)
    except (OSError, ValueError):
        pass  # leave the original if it cannot be processed


def site_size(out):
    total = 0
    for folder, _dirs, files in os.walk(out):
        for name in files:
            total += os.path.getsize(os.path.join(folder, name))
    return total


def make_thumb(src, dest):
    if Image is None:
        return False
    try:
        with Image.open(src) as im:
            im = im.convert("RGB")
            w, h = im.size
            crop_h = min(h, int(w * 10 / 16))
            im = im.crop((0, 0, w, crop_h))
            im.thumbnail((640, 400))
            im.save(dest, "JPEG", quality=78, optimize=True, progressive=True)
        return True
    except (OSError, ValueError):
        return False


def image_captions(readme_text):
    """Alt text the README gives each screenshot, used as captions in the tour."""
    caps = {}
    for m in re.finditer(r"!\[([^\]]*)\]\(([^)\s]+)\)", readme_text):
        caps.setdefault(m.group(2).lstrip("./"), m.group(1))
    for m in re.finditer(r"<img[^>]*>", readme_text):
        src = re.search(r'src="([^"]+)"', m.group(0))
        alt = re.search(r'alt="([^"]*)"', m.group(0))
        if src:
            caps.setdefault(src.group(1).lstrip("./"), alt.group(1) if alt else "")
    return caps


def caption_for(path, caps):
    text = caps.get(path) or ""
    if not text:
        stem = os.path.splitext(os.path.basename(path))[0]
        text = re.sub(r"[-_]+", " ", stem).strip().capitalize()
    return text


def write_project(out, p, newer, older, cats, config):
    cat = cats.get(p["category"], cats["other"])
    up = "../../"
    tabs, panels = [], []

    def add(key, label, body, cls=""):
        tabs.append('<button type="button" role="tab" id="tab-%s" aria-controls="panel-%s" data-tab="%s">%s</button>' % (key, key, key, esc(label)))
        panels.append('<section class="tab-panel %s" role="tabpanel" id="panel-%s" aria-labelledby="tab-%s" tabindex="0">%s</section>' % (cls, key, key, body))

    if p["app"]:
        add("try", "Try it", (
            '<div class="wrap"><div class="app-bar"><p>The real app, running live in your browser on synthetic data. Nothing you enter leaves your device.</p>'
            '<a class="btn small" href="%(app)s" target="_blank" rel="noopener">Open full screen</a></div>'
            '<div class="app-frame"><iframe src="%(app)s" title="%(name)s: the interactive app" allow="clipboard-write; fullscreen"></iframe></div>'
            '<p class="app-hint">On a small screen the app is easier to use <a href="%(app)s" target="_blank" rel="noopener">full screen</a>.</p></div>') % {
                "app": esc(p["app"]), "name": esc(p["name"])}, "wide")
    how = ('<div class="wrap narrow"><details class="summary"><summary>Everything it does, in one sentence</summary><p>%s</p></details>'
           '<article class="prose">%s</article></div>') % (esc(p["what"]), p["_readme"])
    add("how", "How it works", how)
    if p["findings"]:
        add("findings", "Findings", '<div class="wrap narrow"><article class="prose">%s</article></div>' % p["_findings"])
    if p["shots"]:
        steps = []
        n = len(p["shots"])
        for i, (path, cap) in enumerate(p["shots"]):
            steps.append('<figure class="tour-step" data-step="%d"><img src="%s" alt="%s" loading="lazy"><figcaption><span class="step-no">Step %d of %d</span> %s</figcaption></figure>' % (
                i, esc(path), esc(cap), i + 1, n, esc(cap)))
        intro = ("A walk through the app, one screen at a time." if p["app"]
                 else "This project has no app to run here, so this tour shows what it does, one screen at a time.")
        add("tour", "Tour" if not p["app"] else "Screenshots", (
            '<div class="wrap"><p class="tour-intro">%s</p><div class="tour" data-count="%d">%s'
            '<div class="tour-nav" hidden><button type="button" class="btn small" data-move="-1">Previous</button>'
            '<span class="tour-pos" aria-live="polite"></span><button type="button" class="btn small" data-move="1">Next</button></div></div></div>') % (
                intro, n, "".join(steps)), "wide")

    nav = '<nav class="prev-next" aria-label="More projects">'
    nav += ('<a class="older" href="%sprojects/%s/index.html"><span>Older</span>%s</a>' % (up, esc(older["slug"]), esc(older["name"]))) if older else "<span></span>"
    nav += ('<a class="newer" href="%sprojects/%s/index.html"><span>Newer</span>%s</a>' % (up, esc(newer["slug"]), esc(newer["name"]))) if newer else "<span></span>"
    nav += "</nav>"
    head = ('<div class="wrap project-head">'
            '<p class="crumbs"><a href="%(up)sindex.html#archive">Projects</a> / <a href="%(up)sindex.html#category=%(cid)s">%(cat)s</a></p>'
            '<h1>%(name)s</h1><p class="lede">%(tag)s</p>'
            '<p class="meta"><time datetime="%(date)s">%(nice)s</time><span class="cat" data-cat="%(cid)s">%(cat)s</span><span>%(stack)s</span></p></div>') % {
        "up": up, "cid": esc(p["category"]), "cat": esc(cat["name"]), "name": esc(p["name"]), "tag": esc(p["tagline"]),
        "date": esc(p["date"]), "nice": esc(fmt_date(p["date"])), "stack": esc(p["stack"])}
    body = (head + '<div class="wrap"><div class="tabs" role="tablist" aria-label="%s">%s</div></div>' % (esc(p["name"]), "".join(tabs)) +
            "".join(panels) +
            '<div class="wrap narrow"><p class="note">%s</p>%s</div>' % (esc(config["projectNote"]), nav) +
            '<script src="%sstatic/project.js"></script>' % up)
    with open(os.path.join(out, "projects", p["slug"], "index.html"), "w", encoding="utf-8") as f:
        f.write(page("%s | %s" % (p["name"], config["name"]), body, 2, p["tagline"], config, "project"))
    if p["findings"]:
        fbody = ('<div class="wrap narrow project-head"><p class="crumbs"><a href="%(up)sindex.html#archive">Projects</a> / <a href="index.html">%(name)s</a></p>'
                 '<h1>Findings: %(name)s</h1><div class="actions"><a class="btn" href="index.html#how">How it works</a>%(app)s</div></div>'
                 '<div class="wrap narrow"><article class="prose">%(body)s</article></div>') % {
            "up": up, "name": esc(p["name"]), "body": p["_findings"],
            "app": ('<a class="btn primary" href="index.html#try">Try the app</a>') if p["app"] else ""}
        with open(os.path.join(out, "projects", p["slug"], "findings.html"), "w", encoding="utf-8") as f:
            f.write(page("Findings: %s | %s" % (p["name"], config["name"]), fbody, 2, p["tagline"], config, "project"))


def write_index(out, projects, cats, config):
    counts = {}
    for p in projects:
        counts[p["category"]] = counts.get(p["category"], 0) + 1
    used = [c for c in list(cats.values()) if counts.get(c["id"])]
    first = min((p["date"] for p in projects), default=None)
    days = (datetime.date.today() - datetime.date.fromisoformat(first)).days + 1 if first else 0
    by_slug = {p["branch"]: p for p in projects}
    featured = [by_slug[b] for b in config.get("featured", []) if b in by_slug][:3]
    data = [{k: p[k] for k in ("slug", "date", "name", "tagline", "what", "theme", "category", "url", "thumb")} for p in projects]

    stats = ('<dl class="stats"><div><dt>Projects</dt><dd>%d</dd></div><div><dt>Topics</dt><dd>%d</dd></div>'
             '<div><dt>Started</dt><dd>%s</dd></div><div><dt>Days so far</dt><dd>%d</dd></div></dl>') % (
        len(projects), len(used), esc(fmt_date(first)) if first else "Soon", days)
    hero = ('<section class="intro"><div class="wrap"><p class="kicker">%s</p><h1>%s</h1><p class="lede">%s</p>%s</div></section>') % (
        esc(config["name"]), esc(config["title"]), esc(config["tagline"]), stats)
    feat = ""
    if featured:
        feat = '<section class="featured" aria-labelledby="h-feat"><div class="wrap"><h2 id="h-feat">Start with these</h2><div class="grid three">%s</div></div></section>' % \
            "".join(card_html(p, cats) for p in featured)
    chips = '<button type="button" class="chip" data-cat="" aria-pressed="true">All <span>%d</span></button>' % len(projects)
    chips += "".join('<button type="button" class="chip" data-cat="%s" aria-pressed="false">%s <span>%d</span></button>' % (
        esc(c["id"]), esc(c["name"]), counts[c["id"]]) for c in used)
    static_cards = "".join(card_html(p, cats) for p in projects[:24])
    archive = ('<section class="archive" id="archive" aria-labelledby="h-arch"><div class="wrap">'
               '<div class="arch-head"><h2 id="h-arch">Every project</h2><p class="count" id="count" role="status" aria-live="polite">%d projects</p></div>'
               '<p class="arch-sub">Open any project to try it right here in your browser, then read how it works.</p>'
               '<div class="tools"><label class="search"><span class="sr-only">Search projects</span><input type="search" id="q" placeholder="Search projects, for example forecasting or AI Act" autocomplete="off"></label>'
               '<label class="sort"><span>Sort</span><select id="sort"><option value="new">Newest first</option><option value="old">Oldest first</option><option value="az">A to Z</option></select></label></div>'
               '<div class="chips" role="group" aria-label="Filter by topic">%s</div>'
               '<p class="cat-blurb" id="cat-blurb"></p>'
               '<div class="grid" id="grid">%s</div>'
               '<p class="empty" id="empty" hidden>No projects match. Try a different word or topic.</p>'
               '<div class="more"><button type="button" class="btn" id="more" hidden>Show more</button></div>'
               '<noscript><p><a href="archive.html">See every project by month</a>.</p></noscript>'
               '</div></section>') % (len(projects), chips, static_cards)
    cat_data = {c["id"]: {"name": c["name"], "blurb": c.get("blurb", "")} for c in used}
    script = ('<script type="application/json" id="data">%s</script><script type="application/json" id="cats">%s</script>'
              '<script src="static/site.js"></script>') % (
        json.dumps(data).replace("</", "<\\/"), json.dumps(cat_data).replace("</", "<\\/"))
    how = '<section class="how"><div class="wrap narrow"><h2>How these are made</h2><p>%s</p><p><a href="about.html">More about this project</a></p></div></section>' % esc(config["how"])
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(page("%s: %s" % (config["name"], config["title"]), hero + feat + archive + how + script, 0, config["tagline"], config, "home"))


def write_archive(out, projects, cats, config):
    months = {}
    for p in projects:
        months.setdefault(p["date"][:7], []).append(p)
    parts = ['<div class="wrap narrow project-head"><h1>Every project, by month</h1><p class="lede">%d projects so far, newest first.</p></div><div class="wrap narrow">' % len(projects)]
    for m in sorted(months, reverse=True):
        d = datetime.date.fromisoformat(m + "-01")
        parts.append('<section class="month"><h2>%s <span>%d</span></h2><ol class="month-list">' % (esc(d.strftime("%B %Y")), len(months[m])))
        for p in months[m]:
            parts.append('<li><time datetime="%s">%s</time><a href="%s">%s</a><span class="cat" data-cat="%s">%s</span><p>%s</p></li>' % (
                esc(p["date"]), esc(fmt_date(p["date"])), esc(p["url"]), esc(p["name"]), esc(p["category"]),
                esc(cats.get(p["category"], cats["other"])["name"]), esc(p["tagline"])))
        parts.append("</ol></section>")
    parts.append("</div>")
    with open(os.path.join(out, "archive.html"), "w", encoding="utf-8") as f:
        f.write(page("Every project by month | %s" % config["name"], "".join(parts), 0, config["tagline"], config, "archive-page"))


def write_about(out, projects, config):
    paras = "".join("<p>%s</p>" % esc(t) for t in config["about"])
    links = "".join('<li><a href="%s" target="_blank" rel="noopener">%s</a></li>' % (esc(l["url"]), esc(l["label"])) for l in config.get("links", []))
    body = ('<div class="wrap narrow project-head"><h1>About</h1><p class="lede">%s</p></div><div class="wrap narrow prose">%s'
            '<h2>How these are made</h2><p>%s</p>%s</div>') % (
        esc(config["tagline"]), paras, esc(config["how"]), ("<h2>Elsewhere</h2><ul>%s</ul>" % links) if links else "")
    with open(os.path.join(out, "about.html"), "w", encoding="utf-8") as f:
        f.write(page("About | %s" % config["name"], body, 0, config["tagline"], config, "about-page"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default="_site", help="folder to write the site to (default: _site)")
    ap.add_argument("--cache", help="folder that keeps shrunk screenshots between builds (optional)")
    args = ap.parse_args(argv)
    config = load_config()
    if args.cache:
        os.makedirs(args.cache, exist_ok=True)
    projects, skipped = build(os.path.abspath(args.out), config, os.path.abspath(args.cache) if args.cache else None)
    size = site_size(args.out)
    print("Built %d project pages into %s (%.1f MB)" % (len(projects), args.out, size / 1e6))
    if size > WARN_SITE_BYTES:
        print("Warning: the site is %.0f MB; GitHub Pages sites should stay under 1 GB. "
              "Lower MAX_IMAGE_WIDTH or publish fewer screenshots." % (size / 1e6), file=sys.stderr)
    for b in skipped:
        print("Skipped %s: the branch was not found (fetch the build branches first)" % b, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
