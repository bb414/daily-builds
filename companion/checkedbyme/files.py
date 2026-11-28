"""Reading the files people actually have: text, Markdown, HTML and Word .docx."""

import os
import zipfile

from . import model as M

TEXT_SUFFIXES = (".txt", ".md", ".markdown", ".html", ".htm")
DRAFT_SUFFIXES = TEXT_SUFFIXES + (".docx",)


class ReadError(Exception):
    """A file that cannot be read as text, with a plain reason."""


def read_text(path):
    """Returns the text of a draft or notes file, whatever its format."""
    name = os.path.basename(path)
    lower = name.lower()
    if lower.endswith(".docx"):
        return read_docx(path)
    if lower.endswith((".pdf", ".doc", ".odt", ".pages", ".rtf", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".png", ".jpg", ".jpeg", ".gif")):
        raise ReadError('"%s" is not a text file. Save it as .txt, .md or .docx first.' % name)
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as err:
        raise ReadError('Could not open "%s": %s' % (name, err.strerror or err))
    if b"\x00" in raw[:2000]:
        raise ReadError('"%s" looks like a binary file, not text.' % name)
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def read_docx(path):
    name = os.path.basename(path)
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "word/document.xml" not in names:
                raise ReadError('"%s" has no word/document.xml inside, so it is not a Word document.' % name)
            doc = z.read("word/document.xml").decode("utf-8")
            notes = z.read("word/footnotes.xml").decode("utf-8") if "word/footnotes.xml" in names else ""
    except zipfile.BadZipFile:
        raise ReadError('"%s" is not a valid .docx file.' % name)
    except OSError as err:
        raise ReadError('Could not open "%s": %s' % (name, err.strerror or err))
    return M.docx_text(doc, notes)


def write_text(path, text):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def final_pairs(folder):
    """Lists the drafts in a folder as (name, draft path, final path or None).

    A file whose name ends in "-final" or ".final" (before the extension) is the
    final version of the file with the same name without that ending.
    """
    entries = sorted(f for f in os.listdir(folder) if f.lower().endswith(DRAFT_SUFFIXES) and not f.startswith("."))
    finals, drafts = {}, []
    for f in entries:
        stem, _ = os.path.splitext(f)
        low = stem.lower()
        if low.endswith("-final") or low.endswith(".final") or low.endswith("_final"):
            finals[low[:-6]] = f
        else:
            drafts.append(f)
    out = []
    for f in drafts:
        stem = os.path.splitext(f)[0].lower()
        fin = finals.pop(stem, None)
        out.append((f, os.path.join(folder, f), os.path.join(folder, fin) if fin else None))
    for stem, fin in sorted(finals.items()):
        out.append((fin, os.path.join(folder, fin), None))
    return out
