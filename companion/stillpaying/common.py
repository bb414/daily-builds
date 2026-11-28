"""Helpers that copy the browser model's JavaScript behaviour exactly.

The browser model (src/model.js) is the source of truth. Wherever Python and
JavaScript differ by default, the difference is settled here: rounding halves
up, plain code-point comparison, what counts as white space, how a regular
expression treats ".", "$" and "\\s", truthiness, how values turn into text,
how object keys are ordered and how JSON is written. Money is formatted here
too, because every other module needs it.
"""

import math
import re

# JavaScript's white space and line terminators (what \s matches and trim() removes).
SPACE_CHARS = ('\t\n\x0b\x0c\r \xa0\u1680' + ''.join(chr(c) for c in range(0x2000, 0x200B))
               + '\u2028\u2029\u202f\u205f\u3000\ufeff')
_SPACE_CLASS = '[' + SPACE_CHARS + ']'
_NOT_SPACE_CLASS = '[^' + SPACE_CHARS + ']'
# "." in a JavaScript regular expression stops at every line terminator, not just \n.
_DOT = '[^\n\r\u2028\u2029]'


def js_regex(source, flags=''):
    """Compile a JavaScript regular expression source so Python matches the same text.

    The source is written exactly as it appears in model.js. \\s and \\S become
    JavaScript's white space classes, an unescaped "." stops at all line
    terminators, an unescaped "$" only matches at the very end, and \\d, \\w and
    \\b are ASCII only, as they are in JavaScript. flags may contain "i".
    """
    out = []
    i, n = 0, len(source)
    in_class = False
    while i < n:
        ch = source[i]
        if ch == '\\' and i + 1 < n:
            nxt = source[i + 1]
            if nxt == 's':
                out.append(SPACE_CHARS if in_class else _SPACE_CLASS)
            elif nxt == 'S':
                out.append(_NOT_SPACE_CLASS)
            else:
                out.append(source[i:i + 2])
            i += 2
            continue
        if in_class:
            if ch == ']':
                in_class = False
            out.append(ch)
        elif ch == '[':
            in_class = True
            out.append(ch)
        elif ch == '.':
            out.append(_DOT)
        elif ch == '$':
            out.append(r'\Z')
        else:
            out.append(ch)
        i += 1
    return re.compile(''.join(out), re.ASCII | (re.IGNORECASE if 'i' in flags else 0))


_SPACE_RUN = js_regex(r'\s+')


def collapse_spaces(text, replacement=' '):
    """Replace every run of JavaScript white space, like text.replace(/\\s+/g, ' ')."""
    return _SPACE_RUN.sub(replacement, text)


def js_trim(text):
    """String.prototype.trim(): strips JavaScript white space from both ends."""
    return text.strip(SPACE_CHARS)


def round_half_up(x):
    """Math.floor(x + 0.5), the rounding the model uses everywhere."""
    return math.floor(x + 0.5)


def cmp(a, b):
    """Plain code-point order, the model's comparison for strings."""
    return -1 if a < b else 1 if a > b else 0


def is_number(v):
    """True for a JSON number (typeof v === 'number'); booleans are not numbers."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def truthy(v):
    """JavaScript truthiness: empty lists and objects are true, 0, '' and null are false."""
    if v is None or v is False:
        return False
    if is_number(v):
        return v != 0 and v == v
    if isinstance(v, str):
        return v != ''
    return True


def js_number_text(x):
    """String(number) for a float, using JavaScript's switch points for exponents."""
    if x != x:
        return 'NaN'
    if x in (math.inf, -math.inf):
        return 'Infinity' if x > 0 else '-Infinity'
    if x == 0:
        return '0'
    if x == int(x) and abs(x) < 1e21:
        return str(int(x))
    sign = '-' if x < 0 else ''
    mantissa, _, exp = repr(abs(x)).partition('e')
    whole, _, frac = mantissa.partition('.')
    all_digits = whole + frac
    digits = all_digits.lstrip('0')
    # The value is 0.<digits> times ten to the power of point.
    point = len(whole) + int(exp or 0) - (len(all_digits) - len(digits))
    digits = digits.rstrip('0')
    k = len(digits)
    if k <= point <= 21:
        return sign + digits + '0' * (point - k)
    if 0 < point <= 21:
        return sign + digits[:point] + '.' + digits[point:]
    if -6 < point <= 0:
        return sign + '0.' + '0' * (-point) + digits
    e = point - 1
    tail = digits[0] + ('.' + digits[1:] if k > 1 else '')
    return sign + tail + 'e' + ('+' if e >= 0 else '-') + str(abs(e))


def js_string(v):
    """String(v) for JSON values: numbers, booleans, null, lists and objects as JavaScript writes them."""
    if isinstance(v, str):
        return v
    if v is None:
        return 'null'
    if v is True:
        return 'true'
    if v is False:
        return 'false'
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return js_number_text(v)
    if isinstance(v, list):
        return ','.join('' if x is None else js_string(x) for x in v)
    if isinstance(v, dict):
        return '[object Object]'
    return str(v)


def text_or(v, fallback=''):
    """String(v || fallback): the text of a truthy value, otherwise the fallback."""
    return js_string(v) if truthy(v) else fallback


def _is_index_key(k):
    return k.isascii() and k.isdigit() and (k == '0' or not k.startswith('0')) and int(k) < 4294967295


def js_keys(obj):
    """Object.keys order: array-index keys in numeric order, then the rest as inserted."""
    keys = list(obj.keys())
    index_keys = sorted((k for k in keys if isinstance(k, str) and _is_index_key(k)), key=int)
    return index_keys + [k for k in keys if not (isinstance(k, str) and _is_index_key(k))]


_JSON_ESCAPE = re.compile('[\x00-\x1f"\\\\\ud800-\udfff]')
_JSON_SHORT = {'\b': '\\b', '\t': '\\t', '\n': '\\n', '\x0c': '\\f', '\r': '\\r', '"': '\\"', '\\': '\\\\'}


def _quote(s):
    return '"' + _JSON_ESCAPE.sub(lambda m: _JSON_SHORT.get(m.group(0), '\\u%04x' % ord(m.group(0))), s) + '"'


def js_stringify(value, indent=' ', _level=0):
    """JSON.stringify(value, null, indent) for plain JSON data, character for character."""
    if value is None or (isinstance(value, float) and (value != value or value in (math.inf, -math.inf))):
        return 'null'
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return js_number_text(value)
    if isinstance(value, str):
        return _quote(value)
    inner = '\n' + indent * (_level + 1)
    if isinstance(value, (list, tuple)):
        if not value:
            return '[]'
        parts = [js_stringify(v, indent, _level + 1) for v in value]
        return '[' + inner + (',' + inner).join(parts) + '\n' + indent * _level + ']'
    if isinstance(value, dict):
        keys = js_keys(value)
        if not keys:
            return '{}'
        parts = [_quote(str(k)) + ': ' + js_stringify(value[k], indent, _level + 1) for k in keys]
        return '{' + inner + (',' + inner).join(parts) + '\n' + indent * _level + '}'
    raise TypeError('Cannot write %r as JSON' % (value,))


def pad2(n):
    """Two-digit form of a day or month number."""
    return ('0' if n < 10 else '') + str(n)


def money(pence, whole=False):
    """Pence as pounds for people: £1,234.56 (or £12 with whole=True when there are no pence)."""
    neg = pence < 0
    p = abs(pence)
    pounds, rest = p // 100, p % 100
    out = '\u00a3' + format(pounds, ',') + ('' if whole and rest == 0 else '.' + pad2(rest))
    return ('-' if neg else '') + out


def plain_money(pence):
    """Pence as a plain number for spreadsheets: 1234.56, -3.20."""
    neg = pence < 0
    p = abs(pence)
    return ('-' if neg else '') + str(p // 100) + '.' + pad2(p % 100)
