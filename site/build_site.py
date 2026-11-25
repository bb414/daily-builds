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


def render_markdown(text, published, page_map, drop_lead=None, source=None):
    """Render and rewrite links so every link works on the site.

    Published files and pages stay. When the repository is public, `source`
    ({"url", "branch", "files"}) sends links to code and other files to GitHub;
    otherwise they become plain text. The title is dropped (the page shows its
    own), and so is a bold opening line that repeats the tagline shown above it."""
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
            if "github.com/bb414/daily-builds" in target and not source:
                return None  # the repository is private
            return target
        path, _, frag = target.partition("#")
        path = path.lstrip("./")
        if path in page_map:
            return page_map[path] + ("#" + frag if frag else "")
        if path in published:
            return path + ("#" + frag if frag else "")
        if source:
            clean = path.rstrip("/")
            if clean in source["files"]:
                return "%s/blob/%s/%s" % (source["url"], source["branch"], clean) + ("#" + frag if frag else "")
            if any(f.startswith(clean + "/") for f in source["files"]):
                return "%s/tree/%s/%s" % (source["url"], source["branch"], clean)
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


ARROW = '<svg class="ic" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'
EXTERNAL = '<svg class="ic" viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5H3.5v9h9V10M9 3h4v4M13 3 7.5 8.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'
SEARCH = '<svg class="ic" viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="m10.5 10.5 3 3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>'


def page(title, body, depth, description, config, current=""):
    up = "../" * depth
    links = [("projects", "index.html#archive", "Projects"), ("archive", "archive.html", "Archive"), ("about", "about.html", "About")]
    nav = "".join('<a href="%s%s"%s>%s</a>' % (up, href, ' aria-current="page"' if key == current else "", label) for key, href, label in links)
    foot_links = "".join('<a href="%s" target="_blank" rel="noopener">%s</a>' % (esc(l["url"]), esc(l["label"])) for l in config.get("links", []))
    return """<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<meta name="description" content="%(desc)s">
<meta name="theme-color" content="#08090c">
<meta name="color-scheme" content="dark">
<link rel="preload" href="%(up)sstatic/fonts/inter.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="%(up)sstatic/style.css">
<link rel="icon" href="%(up)sstatic/icon.svg" type="image/svg+xml">
<script src="%(up)sstatic/ui.js" defer></script>
</head>
<body>
<a class="skip" href="#main">Skip to the content</a>
<header class="site-head"><div class="wrap head-row">
<a class="brand" href="%(up)sindex.html"><img src="%(up)sstatic/icon.svg" alt="" width="26" height="26"><span>%(name)s</span></a>
<nav class="site-nav" aria-label="Site">%(nav)s</nav>
</div></header>
<main id="main">
%(body)s
</main>
<footer class="site-foot"><div class="wrap foot-row">
<div><p class="foot-name">%(name)s</p><p>%(foot)s</p></div>
<nav aria-label="Footer">%(navfoot)s%(links)s</nav>
</div></footer>
</body>
</html>
""" % {"title": esc(title), "desc": esc(description), "up": up, "name": esc(config["name"]), "nav": nav,
       "navfoot": "".join('<a href="%s%s">%s</a>' % (up, href, label) for _k, href, label in links),
       "links": foot_links, "body": body, "foot": esc(config["footer"])}


def fmt_date(iso, short=False):
    d = datetime.date.fromisoformat(iso)
    return "%d %s %d" % (d.day, d.strftime("%b" if short else "%B"), d.year)


def cat_color(cats, cid):
    return cats.get(cid, cats["other"]).get("color", "#64748b")


def topic_html(cats, cid):
    cat = cats.get(cid, cats["other"])
    return '<span class="topic"><span class="dot" style="--c:%s"></span>%s</span>' % (esc(cat_color(cats, cid)), esc(cat["name"]))


def card_html(p, cats, up=""):
    shot = ('<img src="%s%s" alt="" loading="lazy" width="960" height="600">' % (up, esc(p["cover"]))
            if p.get("cover") else '<span class="no-shot" aria-hidden="true">%s</span>' % esc(p["name"][:1]))
    return ('<article class="card" style="--c:%(color)s"><a class="card-link" href="%(up)s%(url)s">'
            '<div class="shot" style="--c:%(color)s">%(shot)s</div><div class="card-body">'
            '<p class="card-meta"><span class="num">No. %(num)03d</span><time datetime="%(date)s">%(nice)s</time></p>'
            '<h3>%(name)s</h3><p class="tag">%(tag)s</p>%(topic)s</div></a></article>') % {
        "up": up, "url": esc(p["url"]), "shot": shot, "color": esc(cat_color(cats, p["category"])), "num": p["number"],
        "date": esc(p["date"]), "nice": esc(fmt_date(p["date"], True)), "name": esc(p["name"]), "tag": esc(p["tagline"]),
        "topic": topic_html(cats, p["category"])}


def build(out, config, cache=None):
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
        readme = f.read()
    rows = parse_table(readme)
    cats = {c["id"]: c for c in config["categories"]}
    cats["other"] = {"id": "other", "name": "Other", "keywords": [], "blurb": "Projects outside the usual themes.",
                     "color": config.get("otherColor", "#64748b")}

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
        repo = config.get("repo", {})
        source = {"url": repo["url"].rstrip("/"), "branch": row["branch"], "files": set(files)} if repo.get("public") and repo.get("url") else None
        category = categorise(row["theme"], row["branch"], config)
        color = cat_color(cats, category)
        shot = first_image(readme_text, published)
        cover = None
        if shot:
            key = "cover-dark-%s-%s.jpg" % (blob_id(ref, shot), color.lstrip("#"))
            cover_cache = os.path.join(cache, key) if cache else None
            target = os.path.join(dest, "cover.jpg")
            if cover_cache and os.path.exists(cover_cache):
                shutil.copyfile(cover_cache, target)
                made = True
            else:
                made = make_cover(os.path.join(dest, shot), target, color)
                if made and cover_cache:
                    shutil.copyfile(target, cover_cache)
            cover = "projects/%s/%s" % (slug, "cover.jpg" if made else shot)
        line = tagline(readme_text, row["what"], config.get("taglines", {}).get(row["branch"]))
        caps = image_captions(readme_text)
        shown = [m.group(1) or m.group(2) for m in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)\)|<img[^>]+src=\"([^\"]+)\"", readme_text)]
        order = [x.lstrip("./") for x in shown if x.lstrip("./") in published and x.lower().endswith(IMAGE_EXT)]
        order += sorted(x for x in published if x.startswith("docs/") and x.lower().endswith(IMAGE_EXT) and x not in order)
        shots = []
        for x in order:
            if x not in [pair[0] for pair in shots]:
                shots.append((x, caption_for(x, caps)))
        projects.append({
            "slug": slug, "branch": row["branch"], "date": row["date"], "name": strip_md(row["name"]),
            "what": strip_md(row["what"]), "theme": strip_md(row["theme"]), "stack": strip_md(row["stack"]),
            "category": category, "tagline": line,
            "url": "projects/%s/index.html" % slug, "app": app, "shot": shot, "cover": cover,
            "findings": bool(findings_text), "shots": shots,
            "code": "%s/tree/%s" % (source["url"], row["branch"]) if source else None,
            "_readme": render_markdown(readme_text, published, page_map, line, source) if readme_text else "",
            "_findings": render_markdown(findings_text, published, page_map, None, source) if findings_text else "",
        })

    # Newest first; ties keep the order of the index (newest first within a day).
    # Numbers count up from the very first project.
    projects.sort(key=lambda p: p["date"], reverse=True)
    for i, p in enumerate(projects):
        p["number"] = len(projects) - i
    for i, p in enumerate(projects):
        newer = projects[i - 1] if i > 0 else None
        older = projects[i + 1] if i + 1 < len(projects) else None
        write_project(out, p, newer, older, cats, config)

    write_index(out, projects, cats, config)
    write_archive(out, projects, cats, config)
    write_about(out, projects, cats, config)
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


def _rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def _blend(a, b, t):
    """Blend colour a towards colour b by t (0 to 1)."""
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


BASE = (11, 12, 16)


def make_cover(src, dest, color, size=(960, 600)):
    """A product shot: the top of the screenshot in a window, lit by its topic's colour on a dark backdrop."""
    if Image is None:
        return False
    try:
        from PIL import ImageDraw, ImageFilter
        W, H = size
        col = _rgb(color)
        bg = Image.new("RGB", size, BASE)
        glow = Image.radial_gradient("L").resize((int(W * 1.6), int(H * 1.6)))
        glow = glow.point(lambda v: 255 - v)               # bright in the middle
        glow = glow.crop((int(W * 0.15), int(H * 0.55), int(W * 0.15) + W, int(H * 0.55) + H))
        glow = glow.point(lambda v: int(v * 0.55))
        bg = Image.composite(Image.new("RGB", size, _blend(BASE, col, 0.85)), bg, glow)
        with Image.open(src) as im:
            im = im.convert("RGB")
            if im.height > im.width * 1.3:      # a phone screenshot: show it like a phone
                w = 300
                shot = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
                x, y, radius = (W - w) // 2, 64, 30
            else:                               # a desktop screenshot: the top-left corner, legibly
                cw = min(im.width, 1120)
                crop = im.crop((0, 0, cw, min(im.height, round(cw * 0.72))))
                w = 820
                shot = crop.resize((w, round(crop.height * w / crop.width)), Image.LANCZOS)
                x, y, radius = (W - w) // 2, 72, 14
        h = min(shot.height, H - y + radius)
        shot = shot.crop((0, 0, shot.width, h))
        shadow = Image.new("L", size, 0)
        ImageDraw.Draw(shadow).rounded_rectangle((x - 6, y + 6, x + shot.width + 6, y + shot.height + 60), radius=radius, fill=150)
        shadow = shadow.filter(ImageFilter.GaussianBlur(24))
        bg = Image.composite(Image.new("RGB", size, (0, 0, 0)), bg, shadow)
        frame = Image.new("RGB", (shot.width + 2, shot.height + 2), _blend(BASE, (255, 255, 255), 0.22))
        fmask = Image.new("L", frame.size, 0)
        ImageDraw.Draw(fmask).rounded_rectangle((0, 0, frame.width - 1, frame.height + radius), radius=radius + 1, fill=255)
        bg.paste(frame, (x - 1, y - 1), fmask)
        mask = Image.new("L", shot.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, shot.width - 1, shot.height + radius), radius=radius, fill=255)
        bg.paste(shot, (x, y), mask)
        bg.save(dest, "JPEG", quality=86, optimize=True, progressive=True)
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

    def add(key, label, body):
        tabs.append('<button type="button" role="tab" id="tab-%s" aria-controls="panel-%s" data-tab="%s">%s</button>' % (key, key, key, esc(label)))
        panels.append('<section class="tab-panel" role="tabpanel" id="panel-%s" aria-labelledby="tab-%s" tabindex="0">%s</section>' % (key, key, body))

    if p["app"]:
        add("try", "Try it", (
            '<div class="wrap"><div class="window"><div class="window-bar"><span class="lights" aria-hidden="true"><i></i><i></i><i></i></span>'
            '<span class="window-title">%(name)s <span>Running live in your browser</span></span>'
            '<a class="window-link" href="%(app)s" target="_blank" rel="noopener">Full screen %(ext)s</a></div>'
            '<iframe src="%(app)s" title="%(name)s: the interactive app" allow="clipboard-write; fullscreen"></iframe></div>'
            '<p class="fine">Everything runs on your device with synthetic data. Nothing you enter is sent anywhere.</p></div>') % {
                "app": esc(p["app"]), "name": esc(p["name"]), "ext": EXTERNAL})
    facts = ('<aside class="facts"><dl>'
             '<div><dt>Project</dt><dd>No. %03d</dd></div>'
             '<div><dt>Published</dt><dd><time datetime="%s">%s</time></dd></div>'
             '<div><dt>Topic</dt><dd>%s</dd></div>'
             '<div><dt>Built with</dt><dd>%s</dd></div>%s</dl>'
             '<details><summary>The whole project in one sentence</summary><p>%s</p></details></aside>') % (
        p["number"], esc(p["date"]), esc(fmt_date(p["date"])), topic_html(cats, p["category"]), esc(p["stack"]),
        ('<div><dt>Source code</dt><dd><a href="%s" target="_blank" rel="noopener">On GitHub %s</a></dd></div>' % (esc(p["code"]), EXTERNAL)) if p.get("code") else "",
        esc(p["what"]))
    add("how", "How it works", '<div class="wrap read-grid"><article class="prose">%s</article>%s</div>' % (p["_readme"], facts))
    if p["findings"]:
        add("findings", "Findings", '<div class="wrap read-grid"><article class="prose">%s</article>%s</div>' % (p["_findings"], facts))
    if p["shots"]:
        steps = []
        n = len(p["shots"])
        for i, (path, cap) in enumerate(p["shots"]):
            steps.append('<figure class="tour-step"><img src="%s" alt="%s" loading="lazy"><figcaption><span class="step-no">%d / %d</span>%s</figcaption></figure>' % (
                esc(path), esc(cap), i + 1, n, esc(cap)))
        intro = ("A walk through the app, one screen at a time." if p["app"]
                 else "This project has no app to run here, so this tour shows what it does, one screen at a time.")
        add("tour", "Screenshots" if p["app"] else "Tour", (
            '<div class="wrap"><p class="tour-intro">%s</p><div class="tour">%s'
            '<div class="tour-nav" hidden><button type="button" class="btn" data-move="-1">Previous</button>'
            '<span class="tour-pos" aria-live="polite"></span><button type="button" class="btn" data-move="1">Next</button></div></div></div>') % (
                intro, "".join(steps)))

    actions = []
    if p["app"]:
        actions.append('<a class="btn primary" href="#try">Try it live %s</a>' % ARROW)
        actions.append('<a class="btn" href="%s" target="_blank" rel="noopener">Open full screen %s</a>' % (esc(p["app"]), EXTERNAL))
    if p["findings"]:
        actions.append('<a class="btn" href="#findings">Read the findings</a>')
    if p.get("code"):
        actions.append('<a class="btn" href="%s" target="_blank" rel="noopener">View the code %s</a>' % (esc(p["code"]), EXTERNAL))
    head = ('<section class="p-hero" style="--c:%(color)s"><div class="wrap">'
            '<nav class="crumbs" aria-label="Breadcrumb"><a href="%(up)sindex.html#archive">Projects</a><span aria-hidden="true">/</span><a href="%(up)sindex.html#category=%(cid)s">%(cat)s</a></nav>'
            '<p class="p-meta"><span class="num">No. %(num)03d</span><time datetime="%(date)s">%(nice)s</time>%(topic)s</p>'
            '<h1>%(name)s</h1><p class="lede">%(tag)s</p><div class="actions">%(actions)s</div></div></section>') % {
        "up": up, "color": esc(cat_color(cats, p["category"])), "cid": esc(p["category"]), "cat": esc(cat["name"]), "num": p["number"], "date": esc(p["date"]),
        "nice": esc(fmt_date(p["date"])), "topic": topic_html(cats, p["category"]), "name": esc(p["name"]),
        "tag": esc(p["tagline"]), "actions": "".join(actions)}
    nav = '<nav class="prev-next" aria-label="More projects">'
    nav += ('<a class="older" href="%sprojects/%s/index.html"><span>Previous project</span>%s</a>' % (up, esc(older["slug"]), esc(older["name"]))) if older else "<span></span>"
    nav += ('<a class="newer" href="%sprojects/%s/index.html"><span>Next project</span>%s</a>' % (up, esc(newer["slug"]), esc(newer["name"]))) if newer else "<span></span>"
    nav += "</nav>"
    body = (head + '<div class="wrap tabs-row"><div class="tabs" role="tablist" aria-label="%s">%s</div></div>' % (esc(p["name"]), "".join(tabs)) +
            "".join(panels) + '<div class="wrap"><p class="note">%s</p>%s</div>' % (esc(config["projectNote"]), nav) +
            '<script src="%sstatic/project.js"></script>' % up)
    with open(os.path.join(out, "projects", p["slug"], "index.html"), "w", encoding="utf-8") as f:
        f.write(page("%s | %s" % (p["name"], config["name"]), body, 2, p["tagline"], config, "projects"))
    if p["findings"]:
        fbody = ('<section class="p-hero"><div class="wrap"><nav class="crumbs" aria-label="Breadcrumb"><a href="%(up)sindex.html#archive">Projects</a><span aria-hidden="true">/</span><a href="index.html">%(name)s</a></nav>'
                 '<h1>Findings</h1><p class="lede">%(name)s</p><div class="actions">%(app)s<a class="btn" href="index.html#how">How it works</a></div></div></section>'
                 '<div class="wrap read-grid single"><article class="prose">%(body)s</article></div>') % {
            "up": up, "name": esc(p["name"]), "body": p["_findings"],
            "app": ('<a class="btn primary" href="index.html#try">Try it live %s</a>' % ARROW) if p["app"] else ""}
        with open(os.path.join(out, "projects", p["slug"], "findings.html"), "w", encoding="utf-8") as f:
            f.write(page("Findings: %s | %s" % (p["name"], config["name"]), fbody, 2, p["tagline"], config, "projects"))


def year_grid(projects, config, today=None):
    """One square per day of the first year, shaded by how many projects that day has."""
    length = int(config.get("yearLength", 365))
    if not projects:
        return "", 0
    start = datetime.date.fromisoformat(min(p["date"] for p in projects))
    today = today or datetime.date.today()
    per_day = {}
    for p in projects:
        per_day[p["date"]] = per_day.get(p["date"], 0) + 1
    year = (today - start).days // length
    first = start + datetime.timedelta(days=year * length)
    day_no = min((today - first).days + 1, length)
    cells = ['<span class="d pad"></span>' for _ in range(first.weekday())]
    for i in range(length):
        d = first + datetime.timedelta(days=i)
        n = per_day.get(d.isoformat(), 0)
        if d > today:
            cls = "d future"
        else:
            cls = "d l%d" % (0 if n == 0 else 1 if n == 1 else 2 if n <= 3 else 3 if n <= 6 else 4)
        label = "%s: %d project%s" % (fmt_date(d.isoformat()), n, "" if n == 1 else "s") if d <= today else ""
        cells.append('<span class="%s"%s></span>' % (cls, ' title="%s"' % esc(label) if label else ""))
    total = sum(per_day.values())
    days_with = sum(1 for k in per_day if first.isoformat() <= k <= today.isoformat())
    summary = "Year %d, day %d of %d: %d projects on %d days so far." % (year + 1, day_no, length, total, days_with)
    html_out = ('<figure class="year"><figcaption><span>Year %d</span><span>Day %d of %d</span></figcaption>'
                '<div class="year-scroll"><div class="year-grid" role="img" aria-label="%s">%s</div></div>'
                '<div class="year-legend" aria-hidden="true"><span>Fewer</span><i class="d l1"></i><i class="d l2"></i><i class="d l3"></i><i class="d l4"></i><span>More</span></div></figure>') % (
        year + 1, day_no, length, esc(summary), "".join(cells))
    return html_out, day_no


def wall_html(projects, rows=4, per_row=14):
    """The moving wall of project covers at the top of the home page (decorative; the archive is the way in)."""
    pool = [p for p in projects if p.get("cover")][:60]
    if not pool:
        return ""
    out = []
    for r in range(rows):
        order = pool[r * 5 % len(pool):] + pool[:r * 5 % len(pool)]
        row = (order * (per_row // len(order) + 1))[:max(per_row, len(order))]
        tiles = "".join('<a class="tile" href="%s" tabindex="-1"><img src="%s" alt="" loading="%s" width="480" height="300"></a>' % (
            esc(p["url"]), esc(p["cover"]), "eager" if r == 0 else "lazy") for p in row)
        out.append('<div class="wall-row%s"><div class="wall-track">%s%s</div></div>' % (" rev" if r % 2 else "", tiles, tiles))
    return '<div class="wall" aria-hidden="true"><div class="wall-tilt">%s</div></div>' % "".join(out)


def write_index(out, projects, cats, config):
    counts = {}
    for p in projects:
        counts[p["category"]] = counts.get(p["category"], 0) + 1
    used = [c for c in cats.values() if counts.get(c["id"])]
    first = min((p["date"] for p in projects), default=None)
    days = (datetime.date.today() - datetime.date.fromisoformat(first)).days + 1 if first else 0
    by_branch = {p["branch"]: p for p in projects}
    latest = projects[0] if projects else None
    featured = [by_branch[b] for b in config.get("featured", []) if b in by_branch and by_branch[b] is not latest][:3]
    for p in projects[1:]:                      # top up with recent projects so the row is always full
        if len(featured) >= 3:
            break
        if p not in featured:
            featured.append(p)
    grid, day_no = year_grid(projects, config)
    data = [{"n": p["number"], "date": p["date"], "name": p["name"], "tag": p["tagline"], "what": p["what"], "theme": p["theme"],
             "cat": p["category"], "url": p["url"], "cover": p["cover"]} for p in projects]

    hero = ('<section class="hero"><div class="hero-bg" aria-hidden="true"></div><div class="wrap hero-copy">'
            '<a class="pill" href="#archive"><span class="live" aria-hidden="true"></span>%(count)d projects so far<span class="pill-sep" aria-hidden="true"></span>a new one every day %(arrow)s</a>'
            '<h1>%(title)s</h1><p class="lede">%(tag)s</p>'
            '<div class="actions center"><a class="btn primary" href="#archive">Explore the projects %(arrow)s</a>%(latest)s</div></div>'
            '%(wall)s</section>') % {
        "count": len(projects), "arrow": ARROW, "title": title_html(config["title"]), "tag": esc(config["tagline"]),
        "latest": ('<a class="btn ghost" href="%s">Try the latest: %s</a>' % (esc(latest["url"]), esc(latest["name"]))) if latest else "",
        "wall": wall_html(projects)}
    stats = ('<section class="stats-strip"><div class="wrap stats">'
             '<div><span class="stat">%d</span><span class="stat-label">projects built</span></div>'
             '<div><span class="stat">%d</span><span class="stat-label">topics covered</span></div>'
             '<div><span class="stat">%d</span><span class="stat-label">%s since %s</span></div>'
             '<div><span class="stat">0</span><span class="stat-label">installs needed to try one</span></div>'
             '</div></section>') % (len(projects), len(used), days, "day" if days == 1 else "days", esc(fmt_date(first, True)) if first else "")

    spot = ""
    if latest:
        spot = ('<section class="section reveal" aria-labelledby="h-latest"><div class="wrap">'
                '<div class="section-head"><div><p class="kicker">Latest</p><h2 id="h-latest">The newest project</h2></div></div>'
                '<a class="spotlight" href="%(url)s" style="--c:%(color)s"><div class="spot-shot"><img src="%(cover)s" alt="" width="960" height="600"></div>'
                '<div class="spot-body"><p class="card-meta"><span class="num">No. %(num)03d</span><time datetime="%(date)s">%(nice)s</time></p>'
                '<h3>%(name)s</h3><p class="spot-tag">%(tag)s</p>%(topic)s<span class="btn primary small">Try it live %(arrow)s</span></div></a>'
                '</div></section>') % {
            "url": esc(latest["url"]), "color": esc(cat_color(cats, latest["category"])), "cover": esc(latest["cover"] or ""),
            "num": latest["number"], "date": esc(latest["date"]), "nice": esc(fmt_date(latest["date"])), "name": esc(latest["name"]),
            "tag": esc(latest["tagline"]), "topic": topic_html(cats, latest["category"]), "arrow": ARROW}
    feat = ""
    if featured:
        feat = ('<section class="section reveal" aria-labelledby="h-feat"><div class="wrap"><div class="section-head"><div><p class="kicker">Start here</p>'
                '<h2 id="h-feat">A few favourites</h2></div></div><div class="grid feat">%s</div></div></section>') % "".join(card_html(p, cats) for p in featured)
    tiles = "".join(('<a class="topic-tile" href="#category=%s" style="--c:%s"><span class="tt-count">%d</span>'
                     '<span class="tt-name">%s</span><span class="tt-blurb">%s</span></a>') % (
        esc(c["id"]), esc(c.get("color", "#64748b")), counts[c["id"]], esc(c["name"]), esc(c.get("blurb", ""))) for c in used)
    topics = ('<section class="section reveal" aria-labelledby="h-topics"><div class="wrap"><div class="section-head"><div><p class="kicker">Topics</p>'
              '<h2 id="h-topics">What the projects are about</h2></div><p class="head-note">From why AI stalls at the pilot stage to markets, retail and carbon.</p></div>'
              '<div class="topic-grid">%s</div></div></section>') % tiles

    chips = '<button type="button" class="chip" data-cat="" aria-pressed="true">All <span>%d</span></button>' % len(projects)
    chips += "".join('<button type="button" class="chip" data-cat="%s" aria-pressed="false"><span class="dot" style="--c:%s"></span>%s <span>%d</span></button>' % (
        esc(c["id"]), esc(c.get("color", "#64748b")), esc(c["name"]), counts[c["id"]]) for c in used)
    archive = ('<section class="section archive" id="archive" aria-labelledby="h-arch"><div class="wrap">'
               '<div class="section-head"><div><p class="kicker">Archive</p><h2 id="h-arch">Every project</h2></div>'
               '<p class="count" id="count" role="status" aria-live="polite">%d projects</p></div>'
               '<div class="filters"><label class="search">%s<span class="sr-only">Search projects</span>'
               '<input type="search" id="q" placeholder="Search projects, for example forecasting or AI Act" autocomplete="off"></label>'
               '<label class="select"><span class="sr-only">Sort</span><select id="sort"><option value="new">Newest first</option><option value="old">Oldest first</option><option value="az">A to Z</option></select></label>'
               '<div class="view" role="group" aria-label="Layout"><button type="button" id="view-grid" aria-pressed="true">Grid</button><button type="button" id="view-list" aria-pressed="false">List</button></div></div>'
               '<div class="chips" role="group" aria-label="Filter by topic">%s</div>'
               '<p class="cat-blurb" id="cat-blurb"></p>'
               '<div class="grid" id="grid">%s</div>'
               '<p class="empty" id="empty" hidden>No projects match. Try another word or topic.</p>'
               '<div class="more"><button type="button" class="btn ghost" id="more" hidden>Show more</button></div>'
               '<noscript><p><a href="archive.html">See every project in the archive</a>.</p></noscript>'
               '</div></section>') % (len(projects), SEARCH, chips, "".join(card_html(p, cats) for p in projects[:24]))
    challenge = ('<section class="section reveal" aria-labelledby="h-chal"><div class="wrap challenge"><div class="chal-copy"><p class="kicker">The challenge</p>'
                 '<h2 id="h-chal">One project a day, for a year</h2><p>%s</p><p><a class="text-link" href="about.html">How I make them %s</a></p></div>%s</div></section>') % (
        esc(config["how"]), ARROW, grid)
    cat_data = {c["id"]: {"name": c["name"], "blurb": c.get("blurb", ""), "color": c.get("color", "#64748b")} for c in used}
    script = ('<script type="application/json" id="data">%s</script><script type="application/json" id="cats">%s</script>'
              '<script src="static/site.js"></script>') % (json.dumps(data).replace("</", "<\\/"), json.dumps(cat_data).replace("</", "<\\/"))
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(page("%s: %s" % (config["name"], config["title"]), hero + stats + spot + feat + topics + archive + challenge + script,
                     0, config["tagline"], config, "projects"))


def title_html(title):
    """Highlight the last two words of the headline (\"every day\") with the accent gradient."""
    words = title.split()
    if len(words) < 3:
        return esc(title)
    return '%s <span class="grad">%s</span>' % (esc(" ".join(words[:-2])), esc(" ".join(words[-2:])))


def write_archive(out, projects, cats, config):
    months = {}
    for p in projects:
        months.setdefault(p["date"][:7], []).append(p)
    parts = ['<section class="p-hero"><div class="wrap"><h1>Archive</h1><p class="lede">Every project, month by month. %d so far.</p></div></section><div class="wrap">' % len(projects)]
    for m in sorted(months, reverse=True):
        d = datetime.date.fromisoformat(m + "-01")
        parts.append('<section class="month" id="m-%s"><h2>%s <span>%d projects</span></h2><ol class="rows">' % (esc(m), esc(d.strftime("%B %Y")), len(months[m])))
        for p in months[m]:
            parts.append('<li><a class="row" href="%s"><span class="num">No. %03d</span><span class="row-main"><strong>%s</strong><span>%s</span></span>%s<time datetime="%s">%s</time></a></li>' % (
                esc(p["url"]), p["number"], esc(p["name"]), esc(p["tagline"]), topic_html(cats, p["category"]), esc(p["date"]), esc(fmt_date(p["date"], True))))
        parts.append("</ol></section>")
    parts.append("</div>")
    with open(os.path.join(out, "archive.html"), "w", encoding="utf-8") as f:
        f.write(page("Archive | %s" % config["name"], "".join(parts), 0, config["tagline"], config, "archive"))


def write_about(out, projects, cats, config):
    paras = "".join("<p>%s</p>" % esc(t) for t in config["about"])
    counts = {}
    for p in projects:
        counts[p["category"]] = counts.get(p["category"], 0) + 1
    topics = "".join('<li><a href="index.html#category=%s">%s</a><span>%d</span></li>' % (esc(c["id"]), topic_html(cats, c["id"]), counts[c["id"]])
                     for c in cats.values() if counts.get(c["id"]))
    body = ('<section class="p-hero"><div class="wrap"><h1>About</h1><p class="lede">%s</p></div></section>'
            '<div class="wrap read-grid"><article class="prose">%s<h2>How I make them</h2><p>%s</p></article>'
            '<aside class="facts"><h2 class="facts-title">Topics so far</h2><ul class="topic-list">%s</ul></aside></div>') % (
        esc(config["tagline"]), paras, esc(config["how"]), topics)
    with open(os.path.join(out, "about.html"), "w", encoding="utf-8") as f:
        f.write(page("About | %s" % config["name"], body, 0, config["tagline"], config, "about"))


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
