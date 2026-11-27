"""Load bearing: the model, ported line by line from the model block in app/index.html.

An invented rugby squad's season of training load, injuries, selection and results, four injury warning
flags (and a perfect-knowledge ceiling), and the analyses built on them. Every function mirrors its
JavaScript twin operation by operation, so both languages produce bit-identical numbers.

Conventions of the port:
  * Results are plain dicts and lists whose keys match the JavaScript object keys (camelCase), so a JSON
    dump of either side can be compared directly. Typed arrays become lists.
  * Options objects keep their JavaScript keys too, e.g. simulate_season(..., {'collectRows': True}).
  * None stands for JavaScript's undefined: a setting given as None is ignored, a missing CSV cell is None.
  * Sums run left to right in plain loops (the built-in sum() compensates float rounding since Python 3.12),
    and exp and log come from det_exp and det_log, never from the math module.
"""
import math
import re

__all__ = [
    'VERSION', 'det_exp', 'det_log', 'inv_norm', 'norm_cdf', 'Rng', 'hash_seed', 'clamp', 'round_half_up',
    'quantile', 'sort_numbers', 'HIST', 'PRE_WEEKS', 'COMP_WEEKS', 'WEEKS', 'SEASON_DAYS', 'TOTAL_DAYS',
    'COMP_PLAN', 'CTL_REF', 'GROUPS', 'SLOTS', 'CLUB', 'DEFAULTS', 'POLICIES', 'FLAGS', 'FEATURES', 'BASE',
    'week_info', 'make_squad', 'with_defaults', 'truth_mult', 'perf_mult', 'train_logistic', 'predict_logistic',
    'solve_linear', 'simulate_season', 'prepare', 'run_season', 'mean', 'sd', 'auc', 'roc_curve', 'confusion',
    'boot_mean', 'FLAG_LABELS', 'POLICY_LABELS', 'METRICS', 'evaluate_flags', 'coupling_demo',
    'compare_policies', 'pilot_study', 'power_two_sample', 'seasons_for', 'coach_view', 'days_from_civil',
    'civil_from_days', 'format_day', 'parse_day', 'SEASON_START', 'season_logbook', 'parse_csv', 'to_csv',
    'read_logbook', 'analyse_logbook', 'player_series', 'FACTOR_LABELS', 'injury_factors', 'inquest',
]

VERSION = '1.0'

# ---------- JavaScript semantics ----------
_UINT32 = 0x100000000
_MASK = 0xFFFFFFFF
# The characters JavaScript's trim() and \s treat as white space (Python's str.isspace() differs slightly).
_JS_WS = ('\t\n\x0b\x0c\r \xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a'
          '\u2028\u2029\u202f\u205f\u3000\ufeff')
_WS_CLASS = '[' + re.escape(_JS_WS) + ']'
_DECIMAL = re.compile(r'[+-]?(?:Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)\Z')
_NON_DECIMAL = re.compile(r'0(?:[xX][0-9a-fA-F]+|[oO][0-7]+|[bB][01]+)\Z')
_RADIX = {'x': 16, 'o': 8, 'b': 2}


def _to_number(v):
    """JavaScript's unary plus: strings are parsed as number literals, None (undefined) gives NaN."""
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        t = v.strip(_JS_WS)
        if t == '':
            return 0
        if _DECIMAL.match(t):
            return float(t.replace('Infinity', 'inf'))
        if _NON_DECIMAL.match(t):
            return float(int(t[2:], _RADIX[t[1].lower()]))
    return math.nan


def _to_uint32(v):
    """JavaScript's `v >>> 0`."""
    n = _to_number(v)
    if not math.isfinite(n):
        return 0
    return math.trunc(n) % _UINT32


def _floor(x):
    """Math.floor: an int for finite values; NaN and the infinities pass through."""
    return math.floor(x) if math.isfinite(x) else x


def _ceil(x):
    """Math.ceil: an int for finite values; NaN and the infinities pass through."""
    return math.ceil(x) if math.isfinite(x) else x


def _max(a, b):
    """Math.max of two numbers (NaN if either is NaN)."""
    if a != a or b != b:
        return math.nan
    return b if b > a else a


def _min(a, b):
    """Math.min of two numbers (NaN if either is NaN)."""
    if a != a or b != b:
        return math.nan
    return b if b < a else a


def _div(a, b):
    """a / b with JavaScript's results for a zero divisor (Python raises instead)."""
    if b == 0:
        if a != a or a == 0:
            return math.nan
        return math.copysign(math.inf, a) * math.copysign(1.0, b)
    return a / b


def _js_mod(a, b):
    """JavaScript's %, whose result takes the sign of the dividend."""
    if b == 0 or not math.isfinite(a) or b != b:
        return math.nan
    if isinstance(a, int) and isinstance(b, int):
        r = abs(a) % abs(b)
        return -r if a < 0 else r
    return math.fmod(a, b)


def _truthy(v):
    """JavaScript truthiness: 0, NaN, '', None and False are falsy; lists and dicts are always truthy."""
    if v is None or v is False:
        return False
    if isinstance(v, (int, float)):
        return v == v and v != 0
    if isinstance(v, str):
        return v != ''
    return True


def _or(v, alt):
    """JavaScript's `v || alt`."""
    return v if _truthy(v) else alt


def _sum(values):
    """Left-to-right sum, the same additions as a JavaScript loop."""
    s = 0
    for v in values:
        s += v
    return s


def _js_range(limit):
    """The indices of the JavaScript loop `for (i = 0; i < limit; i++)`."""
    return range(_ceil(limit)) if limit > 0 else range(0)


def _index_of(seq, v):
    """Array.prototype.indexOf."""
    for i, x in enumerate(seq):
        if x == v:
            return i
    return -1


def _number_to_string(x):
    """Number.prototype.toString(): shortest round-trip digits, integral values without '.0'."""
    if x != x:
        return 'NaN'
    if x == 0:
        return '0'
    if math.isinf(x):
        return 'Infinity' if x > 0 else '-Infinity'
    sign = '-' if x < 0 else ''
    mantissa, _, exp = repr(abs(float(x))).partition('e')
    whole, _, frac = mantissa.partition('.')
    all_digits = (whole + frac).lstrip('0')
    digits = all_digits.rstrip('0')
    k = len(digits)
    n = k + (int(exp) if exp else 0) - len(frac) + (len(all_digits) - k)
    if k <= n <= 21:
        return sign + digits + '0' * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + '.' + digits[n:]
    if -6 < n <= 0:
        return sign + '0.' + '0' * -n + digits
    e = n - 1
    tail = 'e' + ('+' if e >= 0 else '-') + str(abs(e))
    return sign + (digits if k == 1 else digits[0] + '.' + digits[1:]) + tail


def _js_str(v):
    """JavaScript's String(v) for the values the model handles (None prints as undefined)."""
    if v is None:
        return 'undefined'
    if v is True:
        return 'true'
    if v is False:
        return 'false'
    if isinstance(v, int):
        return str(v) if abs(v) <= 2 ** 53 else _number_to_string(float(v))
    if isinstance(v, float):
        return _number_to_string(v)
    return str(v)


def _cell(row, i):
    """row[i] as JavaScript reads it: None (undefined) outside the row, including negative indices."""
    return row[i] if 0 <= i < len(row) else None


# ---------- deterministic maths (identical in the JavaScript model) ----------
_LN2_HI = 6.93147180369123816490e-01
_LN2_LO = 1.90821492927058770002e-10
_LN2 = 0.6931471805599453
_SQRT2 = 1.4142135623730951
_EXP_DIVISORS = tuple(float(i) for i in range(18, 0, -1))
_LOG_COEFFS = tuple(1 / (2 * j + 1) for j in range(14, -1, -1))


def _pow2(k):
    """Math.pow(2, k) for an integer k: exact, and Infinity beyond the double range."""
    return math.ldexp(1.0, k) if k < 1024 else math.inf


def det_exp(x):
    """e to the power x by range reduction and an 18-term series (the same bits as the JavaScript detExp)."""
    if x != x:
        return math.nan
    if x > 709.78:
        return math.inf
    if x < -745.1:
        return 0.0
    k = math.floor(x / _LN2 + 0.5)
    r = (x - k * _LN2_HI) - k * _LN2_LO
    s = 1
    for i in _EXP_DIVISORS:
        s = 1 + r * s / i
    if k > 1000:
        return s * _pow2(k - 1000) * _pow2(1000)
    if k < -1000:
        return s * _pow2(k + 1000) * _pow2(-1000)
    return s * _pow2(k)


def det_log(x):
    """Natural logarithm by an exact binary exponent and an atanh series (the same bits as detLog)."""
    if x != x or x < 0:
        return math.nan
    if x == 0:
        return -math.inf
    if x == math.inf:
        return math.inf
    e = math.floor(math.log2(x))
    while _pow2(e) > x:
        e -= 1
    while _pow2(e + 1) <= x:
        e += 1
    if e > 1000:
        m = (x / _pow2(1000)) / _pow2(e - 1000)
    elif e < -1000:
        m = (x * _pow2(1000)) / _pow2(e + 1000)
    else:
        m = x / _pow2(e)
    if m > _SQRT2:
        m = m / 2
        e += 1
    s = (m - 1) / (m + 1)
    s2 = s * s
    t = 0
    for c in _LOG_COEFFS:
        t = c + s2 * t
    return e * _LN2_HI + (e * _LN2_LO + 2 * s * t)


def clamp(x, lo, hi):
    """x limited to [lo, hi]; NaN passes through, as in JavaScript."""
    return lo if x < lo else hi if x > hi else x


def round_half_up(x):
    """Math.floor(x + 0.5): halves round towards plus infinity."""
    return _floor(x + 0.5)


_IA = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02,
       -3.066479806614716e+01, 2.506628277459239e+00]
_IB = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01,
       -1.328068155288572e+01]
_IC = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00,
       4.374664141464968e+00, 2.938163982698783e+00]
_ID = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]


def inv_norm(p):
    """Inverse of the standard normal distribution function (Acklam's rational approximation)."""
    if p <= 0:
        return -8.5
    if p >= 1:
        return 8.5
    if p < 0.02425:
        q = math.sqrt(-2 * det_log(p))
        x = ((((((_IC[0] * q + _IC[1]) * q + _IC[2]) * q + _IC[3]) * q + _IC[4]) * q + _IC[5]) /
             ((((_ID[0] * q + _ID[1]) * q + _ID[2]) * q + _ID[3]) * q + 1))
    elif p <= 1 - 0.02425:
        q = p - 0.5
        r = q * q
        x = ((((((_IA[0] * r + _IA[1]) * r + _IA[2]) * r + _IA[3]) * r + _IA[4]) * r + _IA[5]) * q /
             (((((_IB[0] * r + _IB[1]) * r + _IB[2]) * r + _IB[3]) * r + _IB[4]) * r + 1))
    else:
        q = math.sqrt(-2 * det_log(1 - p))
        x = (-(((((_IC[0] * q + _IC[1]) * q + _IC[2]) * q + _IC[3]) * q + _IC[4]) * q + _IC[5]) /
             ((((_ID[0] * q + _ID[1]) * q + _ID[2]) * q + _ID[3]) * q + 1))
    return clamp(x, -8.5, 8.5)


def norm_cdf(x):
    """Standard normal distribution function (Abramowitz and Stegun 26.2.17, error below 1e-7)."""
    z = abs(x)
    t = 1 / (1 + 0.2316419 * z)
    poly = t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
    p = 1 - 0.3989422804014327 * det_exp(-z * z / 2) * poly
    return p if x >= 0 else 1 - p


# ---------- seeded random numbers (mulberry32) ----------
class Rng:
    """The mulberry32 generator, state for state the same as the JavaScript Rng.

    next() is uniform on [0, 1), open() on (0, 1), normal() a standard normal draw, and int_(n) is the
    JavaScript int(n): a whole number from 0 to n - 1 (renamed so it does not shadow the built-in).
    """

    __slots__ = ('s',)

    def __init__(self, seed):
        self.s = _to_uint32(seed)

    def next(self):
        """The next value on [0, 1), a multiple of 2 to the power -32."""
        self.s = (self.s + 0x6D2B79F5) & _MASK
        t = self.s
        t = ((t ^ (t >> 15)) * (t | 1)) & _MASK
        t = (t ^ ((t + (((t ^ (t >> 7)) * (t | 61)) & _MASK)) & _MASK)) & _MASK
        return ((t ^ (t >> 14)) & _MASK) / 4294967296

    def normal(self):
        """A standard normal draw by inversion."""
        return inv_norm(self.open())

    def open(self):
        """A value strictly between 0 and 1."""
        return (self.next() * 4294967295 + 0.5) / 4294967296

    def int_(self, n):
        """A whole number from 0 to n - 1 (the JavaScript int(n))."""
        return _floor(self.next() * n)


def hash_seed(*args):
    """FNV-1a over the four bytes of each argument (as a 32-bit unsigned integer), then a murmur3 finish."""
    h = 2166136261
    for a in args:
        v = _to_uint32(a)
        for b in range(4):
            h ^= (v >> (8 * b)) & 255
            h = (h * 16777619) & _MASK
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & _MASK
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & _MASK
    return h ^ (h >> 16)


# ---------- the calendar ----------
HIST = 28                 # off-season days simulated before pre-season starts
PRE_WEEKS = 6
COMP_WEEKS = 30
WEEKS = PRE_WEEKS + COMP_WEEKS
SEASON_DAYS = WEEKS * 7   # 252, day 0 is the Monday of pre-season week 1
TOTAL_DAYS = HIST + SEASON_DAYS
COMP_PLAN = 'LLLLLBLLLLBLLLLBLLLBLLLLBLLCBC'  # L league, B bye, C cup semi-final and final
_MATCH_DAY = 5            # Saturday
_DECISION_DAY = 3         # Thursday: flags are read and the week is planned
CTL_REF = 260             # in-season fitness of a regular starter (arbitrary units a day)


def week_info(w):
    """Phase ('pre' or 'comp'), week type (T training, F friendly, L, B or C) and competition week."""
    if w < PRE_WEEKS:
        return {'phase': 'pre', 'type': 'F' if w >= PRE_WEEKS - 2 else 'T', 'comp': -1}
    cw = w - PRE_WEEKS
    return {'phase': 'comp', 'type': COMP_PLAN[cw] if cw < len(COMP_PLAN) else '', 'comp': cw}


# ---------- the squad ----------
GROUPS = [
    {'id': 'prop', 'label': 'Prop', 'unit': 'F', 'count': 6},
    {'id': 'hooker', 'label': 'Hooker', 'unit': 'F', 'count': 3},
    {'id': 'lock', 'label': 'Lock', 'unit': 'F', 'count': 5},
    {'id': 'backrow', 'label': 'Back row', 'unit': 'F', 'count': 6},
    {'id': 'scrumhalf', 'label': 'Scrum-half', 'unit': 'B', 'count': 3},
    {'id': 'flyhalf', 'label': 'Fly-half', 'unit': 'B', 'count': 3},
    {'id': 'centre', 'label': 'Centre', 'unit': 'B', 'count': 5},
    {'id': 'back3', 'label': 'Back three', 'unit': 'B', 'count': 5},
]
# Matchday 23: shirt number, position group, planned minutes.
SLOTS = [
    [1, 'prop', 55], [2, 'hooker', 55], [3, 'prop', 55], [4, 'lock', 65], [5, 'lock', 80], [6, 'backrow', 70],
    [7, 'backrow', 80], [8, 'backrow', 80], [9, 'scrumhalf', 65], [10, 'flyhalf', 80], [11, 'back3', 80],
    [12, 'centre', 80], [13, 'centre', 75], [14, 'back3', 80], [15, 'back3', 80],
    [16, 'hooker', 25], [17, 'prop', 25], [18, 'prop', 25], [19, 'lock', 15], [20, 'backrow', 10],
    [21, 'scrumhalf', 15], [22, 'centre', 5], [23, 'back3', 5],
]
_SURNAMES = ['Ashworth', 'Bramley', 'Calloway', 'Dunmore', 'Ellery', 'Fairbank', 'Gilmour', 'Hartigan',
             'Ingram', 'Jessop', 'Kershaw', 'Lindley', 'Merriman', 'Northcott', 'Ormerod', 'Pickering', 'Quarrie',
             'Radcliffe', 'Sefton', 'Thackeray', 'Underhill', 'Venables', 'Whitlock', 'Yardley', 'Abbott',
             'Birtwistle', 'Cottam', 'Dewhurst', 'Elsworth', 'Fenwick', 'Greaves', 'Hepworth', 'Illingworth',
             'Kenyon', 'Lomax', 'Mellor', 'Naylor', 'Oldroyd', 'Pilling', 'Rushworth', 'Swales', 'Tattersall',
             'Uttley', 'Wadsworth']
_INITIALS = 'ABCDEFGHJKLMNPRSTW'
_OPPONENTS = ['Ashmoor', 'Bramblecombe', 'Fernhythe', 'Gullstead', 'Heronwick', 'Kestrel Vale',
              'Marlstone', 'Oakmere', 'Rookhaven', 'Thistlebury', 'Wyvern Park']
CLUB = 'Hollowmere'


def make_squad(squad_seed):
    """The 36 players (with hidden frailty), the eleven opponents and the first-choice XV."""
    rng = Rng(hash_seed(squad_seed, 101))
    players = []
    used = set()
    for g in GROUPS:
        group = []
        for _ in range(g['count']):
            ability = clamp(70 + 5 * rng.normal(), 56, 86)
            age = 19 + rng.int_(15)
            frailty = det_exp(0.4 * rng.normal() - 0.08)
            off_load = clamp(110 + 30 * rng.normal(), 40, 180)
            rpe_bias = clamp(1 + 0.06 * rng.normal(), 0.85, 1.15)
            prior = 0
            for _t in range(4):
                if rng.next() < 0.16 * frailty:
                    prior += 1
            while True:
                name = _INITIALS[rng.int_(len(_INITIALS))] + '. ' + _SURNAMES[rng.int_(len(_SURNAMES))]
                if name not in used:
                    break
            used.add(name)
            group.append({'name': name, 'group': g['id'], 'unit': g['unit'], 'ability': ability, 'age': age,
                          'frailty': frailty, 'offLoad': off_load, 'rpeBias': rpe_bias, 'prior': prior})
        group.sort(key=lambda p: -p['ability'])
        for k, p in enumerate(group):
            p['depth'] = k + 1
            players.append(p)
    for i, p in enumerate(players):
        p['id'] = i
    orng = Rng(hash_seed(squad_seed, 202))
    opponents = [{'name': n, 'rating': clamp(70.5 + 2.6 * orng.normal(), 64, 77)} for n in _OPPONENTS]
    # The first-choice XV: the best player for each starting slot at the start of the season.
    best_xv = _pick_xv(players, lambda p: True, lambda p: p['ability'])
    return {'players': players, 'opponents': opponents, 'bestXV': best_xv}


def _pick_xv(players, eligible, key):
    """Indices of the highest-key eligible player for each of the 15 starting slots."""
    taken = set()
    out = []
    for s in range(15):
        g = SLOTS[s][1]
        best, best_key = -1, -math.inf
        for i, p in enumerate(players):
            if i in taken or p['group'] != g or not eligible(p):
                continue
            k = key(p)
            if k > best_key:
                best_key = k
                best = i
        if best >= 0:
            taken.add(best)
            out.append(best)
    return out


# ---------- settings ----------
DEFAULTS = {
    'squadSeed': 7,
    'seasonSeed': 1,
    'policy': 'none',        # none | rest | modify | rotate | readiness
    'flag': 'ewma',          # coupled | uncoupled | ewma | model | oracle
    'threshold': 1.5,        # ratio flags: flag when the workload ratio reaches this
    'budget': 10,            # model and oracle: flag the riskiest share (%) of player-weeks
    'preseason': 'gradual',  # gradual | steep
    'intensity': 1.0,        # multiplies the effort (RPE) of every training session
    'gradedReturn': True,    # ten days of modified training after an injury before selection
    'rotateAfter': 4,        # planned rotation: rest anyone who has started this many in a row
    'restTraining': 0.5,     # share of training a flagged player keeps under "rest" (0.6 under "modify")
    'spike': 2.0,            # truth: how strongly a load spike raises non-contact injury risk
    'contactScale': 1.0,     # truth: multiplies the contact injury rate
    'historySeasons': 2,     # past seasons the risk model learns from
}
POLICIES = ['none', 'rest', 'modify', 'rotate', 'readiness']
FLAGS = ['coupled', 'uncoupled', 'ewma', 'model', 'oracle']
_RATIO_FLAGS = {'coupled', 'uncoupled', 'ewma'}


def with_defaults(s=None):
    """A full settings dict: defaults filled in, numbers coerced and clamped, unknown choices replaced."""
    out = dict(DEFAULTS)
    if s:
        for j in s:
            if s[j] is not None and j in DEFAULTS:
                out[j] = s[j]
    def num(k):
        x = _to_number(out[k])
        return x if x == x and x not in (math.inf, -math.inf) else DEFAULTS[k]
    out['threshold'] = clamp(num('threshold'), 1.0, 3.0)
    out['budget'] = clamp(num('budget'), 1, 50)
    out['intensity'] = clamp(num('intensity'), 0.7, 1.3)
    out['rotateAfter'] = clamp(_floor(num('rotateAfter')), 2, 10)
    out['restTraining'] = clamp(num('restTraining'), 0, 1)
    out['spike'] = clamp(num('spike'), 0, 4)
    out['contactScale'] = clamp(num('contactScale'), 0, 3)
    out['historySeasons'] = clamp(_floor(num('historySeasons')), 1, 6)
    out['squadSeed'] = _to_uint32(_floor(num('squadSeed')))
    out['seasonSeed'] = _to_uint32(_floor(num('seasonSeed')))
    if out['policy'] not in POLICIES:
        out['policy'] = 'none'
    if out['flag'] not in FLAGS:
        out['flag'] = 'ewma'
    if out['preseason'] != 'steep':
        out['preseason'] = 'gradual'
    out['gradedReturn'] = _truthy(out['gradedReturn'])
    return out


# ---------- injury hazards (the hidden truth) ----------
BASE = {'trainNC': 1.4e-5, 'matchNC': 4.5e-5, 'trainC': 1.1e-5, 'matchC': 3.9e-4}
_SPIKE_FROM = 1.1
# Session kinds, as stored in the daily 'kinds' arrays.
_OFF, _TRAIN, _CONTACT, _MATCH, _SECOND, _REHAB = range(6)
_RAMP = {'gradual': [0.6, 0.72, 0.84, 0.94, 1, 1], 'steep': [1, 1, 1, 1, 1, 1]}


def _base_rates(kind, contact_scale):
    """Non-contact and contact hazards per minute for a session kind."""
    if kind == _TRAIN:
        return (BASE['trainNC'], 0)
    if kind == _CONTACT:
        return (BASE['trainNC'], BASE['trainC'] * contact_scale)
    if kind == _MATCH:
        return (BASE['matchNC'], BASE['matchC'] * contact_scale)
    if kind == _SECOND:
        return (BASE['matchNC'] * 0.8, BASE['matchC'] * 0.6 * contact_scale)
    if kind == _REHAB:
        return (BASE['trainNC'] * 0.5, 0)
    return (0, 0)


def truth_mult(p, atl, ctl, recent, spike_effect):
    """Multipliers on the base rates from the player's state after today's session: [nc, c, spike, under]."""
    ratio = atl / _max(ctl, 80)
    spike = _max(0, ratio - _SPIKE_FROM)
    under = _max(0, 1 - ctl / CTL_REF)
    nc = p['frailty'] * det_exp(0.03 * (p['age'] - 26) + spike_effect * spike + 0.8 * under) * (1.6 if recent else 1)
    c = (1.15 if p['unit'] == 'F' else 0.85) * det_exp(0.3 * det_log(p['frailty'])) * (1 + 0.5 * spike)
    return [nc, c, spike, under]


def perf_mult(atl, ctl):
    """Match-day performance from fitness (ctl) and freshness (ctl minus atl)."""
    return clamp(1 + 0.12 * (ctl / CTL_REF - 1) + 0.10 * (ctl - atl) / CTL_REF, 0.82, 1.06)


# ---------- the week's sessions ----------
def _session(info, wd, role, ramp_f, off_f):
    """(minutes, rpe, kind) for one player on one weekday; minutes of -1 mean the player's match minutes."""
    if info is None:  # off-season history
        if wd in (0, 2, 4):
            return (50 * off_f, 5, _TRAIN)
        return (0, 0, _OFF)
    if role == 'injured':
        return (0, 0, _OFF)
    if role == 'rehab':
        return (40, 4, _REHAB) if wd in (0, 1, 3, 4) else (0, 0, _OFF)
    if info['phase'] == 'pre':
        friendly = info['type'] == 'F'
        if wd == 0:
            return (60 * ramp_f, 6, _TRAIN)
        if wd == 1:
            return (90 * ramp_f, 7, _CONTACT)
        if wd == 2:
            return (50 * ramp_f, 5, _TRAIN)
        if wd == 3:
            return (75 * ramp_f, 6, _CONTACT) if friendly else (90 * ramp_f, 7, _CONTACT)
        if wd == 5:
            if friendly:
                return (0, 0, _OFF) if role in ('rested', 'returning') else (40, 7.5, _SECOND)
            return (60 * ramp_f, 7, _TRAIN)
        return (0, 0, _OFF)
    match = info['type'] != 'B'
    if wd == 0:
        return (45, 4, _TRAIN)
    if wd == 1:
        return (80, 7, _CONTACT)
    if wd == 3:
        return (70, 6, _TRAIN)
    if wd == 4:
        return (30, 3, _TRAIN) if match else (0, 0, _OFF)
    if wd == 5:
        if not match:
            return (60, 6, _TRAIN)
        if role in ('starter', 'bench'):
            return (-1, 8.5 if role == 'starter' else 8, _MATCH)
        if role == 'reserve':
            return (60, 7, _SECOND)
        return (0, 0, _OFF)
    return (0, 0, _OFF)


# ---------- the risk model (the club's "AI") ----------
FEATURES = ['Workload ratio (EWMA)', 'Fitness base (log)', 'Change on last week', 'Monotony',
            'Back within six weeks', 'Earlier injuries', 'Age', 'Match minutes last week', 'Forward']


def _sigmoid(z):
    """The logistic function, written to avoid overflow on either side."""
    if z >= 0:
        return 1 / (1 + det_exp(-z))
    e = det_exp(z)
    return e / (1 + e)


def solve_linear(A, b):
    """Solves A x = b by Gauss-Jordan elimination with partial pivoting; near-zero pivots give 0."""
    n = len(b)
    M = [list(row) + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = c
        for r in range(c + 1, n):
            if abs(M[r][c]) > abs(M[piv][c]):
                piv = r
        M[c], M[piv] = M[piv], M[c]
        d = M[c][c]
        if abs(d) < 1e-12:
            continue
        for r2 in range(n):
            if r2 == c:
                continue
            f = M[r2][c] / d
            if f == 0:
                continue
            row, pivot_row = M[r2], M[c]
            for k in range(c, n + 1):
                row[k] -= f * pivot_row[k]
    return [0 if abs(M[i][i]) < 1e-12 else M[i][n] / M[i][i] for i in range(n)]


def train_logistic(X, y, lam):
    """L2-regularised logistic regression by Newton's method on standardised features."""
    n, m = len(X), len(X[0])
    means, sds = [], []
    for j in range(m):
        s = 0
        s2 = 0
        for i in range(n):
            s += X[i][j]
        mu = s / n
        for i in range(n):
            s2 += (X[i][j] - mu) * (X[i][j] - mu)
        means.append(mu)
        sds.append(_or(math.sqrt(s2 / n), 1))
    Z = [[1] + [(row[j] - means[j]) / sds[j] for j in range(m)] for row in X]
    w = [0] * (m + 1)
    pos = _sum(y)
    w[0] = det_log((pos + 0.5) / (n - pos + 0.5))
    size = range(m + 1)
    for _ in range(12):
        g = [0 if r == 0 else lam * w[r] for r in size]
        H = [[lam if r == c and r > 0 else 0 for c in size] for r in size]
        for i in range(n):
            zi = Z[i]
            eta = 0
            for k in size:
                eta += w[k] * zi[k]
            pr = _sigmoid(eta)
            wt = pr * (1 - pr)
            res = pr - y[i]
            for r in size:
                g[r] += res * zi[r]
                hz = wt * zi[r]
                Hr = H[r]
                for c in range(r, m + 1):
                    Hr[c] += hz * zi[c]
        for r in size:
            for c in range(r):
                H[r][c] = H[c][r]
        step = solve_linear(H, g)
        max_step = 0
        for k in size:
            w[k] -= step[k]
            max_step = _max(max_step, abs(step[k]))
        if max_step < 1e-9:
            break
    return {'mean': means, 'sd': sds, 'w': w}


def predict_logistic(model, x):
    """Predicted probability for one raw feature vector."""
    eta = model['w'][0]
    for j in range(len(x)):
        eta += model['w'][j + 1] * (x[j] - model['mean'][j]) / model['sd'][j]
    return _sigmoid(eta)


def quantile(sorted_values, q):
    """Linear-interpolation quantile of an ascending list (NaN when empty or out of range)."""
    n = len(sorted_values)
    if not n:
        return math.nan
    pos = (n - 1) * q
    lo, hi = _floor(pos), _ceil(pos)
    if not (0 <= lo and hi < n):
        return math.nan
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def sort_numbers(a):
    """An ascending copy (a stable sort, like the JavaScript comparator x - y)."""
    return sorted(a)


# ---------- one season ----------
def simulate_season(ctx, S, season_seed, opts=None):
    """One season, day by day.

    ctx: {'squad', 'model', 'cutoffs'} from prepare(); S: settings from with_defaults(); opts may set
    'collectRows' (Thursday flag readings with injury labels) and 'keepDaily' (the per-day arrays).
    Status codes per player-day: 0 normal, 1 injured, 2 graded return, 3 load cut after a flag.
    """
    opts = opts or {}
    collect_rows = _truthy(opts.get('collectRows'))
    squad = ctx['squad']
    players = squad['players']
    P, N = len(players), TOTAL_DAYS
    load = [[0.0] * N for _ in range(P)]
    minutes = [[0.0] * N for _ in range(P)]
    kinds = [[0] * N for _ in range(P)]
    status = [[0] * N for _ in range(P)]
    atl = [p['offLoad'] for p in players]
    ctl, ew_a, ew_c = list(atl), list(atl), list(atl)
    injured_until, inj_start = [-1e9] * P, [-1e9] * P
    returned_day, graded_until = [-1e9] * P, [-1e9] * P
    inj_count = [p['prior'] for p in players]
    streak, mod_until, mod_factor = [0] * P, [-1e9] * P, [1] * P
    role, role_mins = ['reserve'] * P, [0] * P
    luck = [Rng(hash_seed(season_seed, p, 3, S['squadSeed'])) for p in range(P)]
    noise = [Rng(hash_seed(season_seed, p, 4, S['squadSeed'])) for p in range(P)]
    match_rng = Rng(hash_seed(season_seed, 900, S['squadSeed']))
    league_order = _make_league_order(S['squadSeed'])
    injuries, matches, rows, weekly = [], [], [], []
    excluded = [0] * P
    selection = None
    opp_index = 0
    lam_a, lam_c = 2 / (7 + 1), 2 / (28 + 1)
    forced_plays = rests = flags_raised = flag_weeks = 0
    model = ctx.get('model')

    def fit(q, d):
        return injured_until[q] <= d and not (S['gradedReturn'] and graded_until[q] > d)

    def flag_scores(q, i_now):
        lq, kq, mq = load[q], kinds[q], minutes[q]
        a7 = c28 = c21 = prev7 = mm = 0
        vals = []
        for k in range(1, 29):
            v = lq[i_now - k]
            c28 += v
            if k <= 7:
                a7 += v
                vals.append(v)
                if kq[i_now - k] == _MATCH:
                    mm += mq[i_now - k]
            else:
                c21 += v
            if 7 < k <= 14:
                prev7 += v
        mean7 = a7 / 7
        var7 = 0
        for t in range(7):
            var7 += (vals[t] - mean7) * (vals[t] - mean7)
        sd7 = math.sqrt(var7 / 7)
        d_now = i_now - HIST
        pl = players[q]
        feats = [ew_a[q] / _max(ew_c[q], 100 / 7), det_log(_max(c28 / 28, 20) / CTL_REF),
                 clamp(a7 / _max(prev7, 100) - 1, -1, 3), _min(mean7 / sd7 if sd7 > 0 else 5, 5),
                 1 if d_now - returned_day[q] < 42 else 0, inj_count[q], (pl['age'] - 26) / 5, mm / 80,
                 1 if pl['unit'] == 'F' else 0]
        return {
            'coupled': a7 / _max(c28 / 4, 100),
            'uncoupled': a7 / _max(c21 / 3, 100),
            'ewma': feats[0],
            'model': predict_logistic(model, feats) if model is not None else 0,
            'oracle': oracle_risk(q, i_now),
            'features': feats,
        }

    def oracle_risk(q, i_now):
        # The perfect-knowledge ceiling: the true non-contact hazard over the next seven days, assuming the
        # week repeats the last one. It knows the hidden mechanism and each player's frailty, but not the luck.
        a, c, h, pl, d_now = atl[q], ctl[q], 0, players[q], i_now - HIST
        for k in range(7):
            j = i_now - 7 + k
            wl, mn = load[q][j], minutes[q][j]
            a = a + (wl - a) / 7
            c = c + (wl - c) / 42
            if mn <= 0:
                continue
            tm = truth_mult(pl, a, c, d_now + k - returned_day[q] < 42, S['spike'])
            h += _base_rates(kinds[q][j], S['contactScale'])[0] * mn * tm[0]
        return 1 - det_exp(-h)

    def mark_rows(q, d0, inj_type):
        r = len(rows) - 1
        while r >= 0 and r >= len(rows) - 2 * P:
            row = rows[r]
            if row['player'] == q and row['day'] <= d0 <= row['day'] + 6:
                row['any'] = 1
                if inj_type == 'nc':
                    row['nc'] = 1
            r -= 1

    def select_team(d):
        nonlocal forced_plays, rests, selection
        readiness = S['policy'] == 'readiness'

        def key(k):
            if readiness:
                return players[k]['ability'] * perf_mult(atl[k], ctl[k])
            return players[k]['ability']

        def rotated(k):
            return S['policy'] == 'rotate' and streak[k] >= S['rotateAfter']

        def preferred(k):
            return fit(k, d) and not excluded[k] and not rotated(k)

        taken, slot_player, slot_penalty = [0] * P, [], []
        for k0 in range(P):
            role[k0] = 'reserve'
            role_mins[k0] = 0
        for s, slot in enumerate(SLOTS):
            g, unit, choice, pen = slot[1], _group_unit(slot[1]), -1, 1
            t = 0
            while t < 4 and choice < 0:
                best_k = -math.inf
                for k in range(P):
                    if taken[k]:
                        continue
                    pl = players[k]
                    if t == 0:
                        ok = pl['group'] == g and preferred(k)
                    elif t == 1:
                        ok = pl['unit'] == unit and preferred(k)
                    elif t == 2:
                        ok = pl['group'] == g and fit(k, d)
                    else:
                        ok = pl['unit'] == unit and fit(k, d)
                    if not ok:
                        continue
                    kv = key(k)
                    if kv > best_k:
                        best_k = kv
                        choice = k
                if choice >= 0:
                    pen = 0.85 if t == 1 or t == 3 else 1
                    if t >= 2 and (excluded[choice] or rotated(choice)):
                        forced_plays += 1
                t += 1
            slot_player.append(choice)
            slot_penalty.append(pen)
            if choice >= 0:
                taken[choice] = 1
                role[choice] = 'starter' if s < 15 else 'bench'
                role_mins[choice] = slot[2]
        for k2 in range(P):
            if not taken[k2] and fit(k2, d) and (excluded[k2] or rotated(k2)):
                role[k2] = 'rested'
                rests += 1
            if taken[k2] and role[k2] == 'starter':
                streak[k2] += 1
            else:
                streak[k2] = 0
        xi = bench = 0
        for s2 in range(len(SLOTS)):
            pid = slot_player[s2]
            val = players[pid]['ability'] * perf_mult(atl[pid], ctl[pid]) * slot_penalty[s2] if pid >= 0 else 50
            if s2 < 15:
                xi += val
            else:
                bench += val
        selection = {'starters': slot_player[:15], 'bench': slot_player[15:],
                     'rating': 0.85 * xi / 15 + 0.15 * bench / (len(SLOTS) - 15)}

    def play_match(d, w, info):
        nonlocal opp_index
        u, uf = match_rng.open(), match_rng.open()
        opponents = squad['opponents']
        if info['type'] == 'L':
            rnd = opp_index
            opp_index += 1
            opp = league_order[rnd % 11]
            home = rnd % 2 == 0 if rnd < 11 else (rnd - 11) % 2 == 1
            label = 'League round ' + _js_str(rnd + 1)
        else:
            by_rating = sorted(range(len(opponents)), key=lambda k: (-opponents[k]['rating'], k))
            is_final = info['comp'] == COMP_WEEKS - 1
            opp = by_rating[0] if is_final else by_rating[1]
            home = None if is_final else True
            label = 'Cup final' if is_final else 'Cup semi-final'
        opp_rating = opponents[opp]['rating'] + inv_norm(uf)
        adv = 0 if home is None else 3 if home else -3
        margin = round_half_up(2.0 * (selection['rating'] - opp_rating) + adv + 12 * inv_norm(u))
        result = 'W' if margin > 0 else 'D' if margin == 0 else 'L'
        if info['type'] == 'L':
            pts = 4 if result == 'W' else 2 if result == 'D' else 1 if margin >= -7 else 0
        else:
            pts = 0
        best_playing = 0
        for pid in squad['bestXV']:
            if pid in selection['starters']:
                best_playing += 1
        matches.append({'week': w, 'day': d, 'label': label, 'type': info['type'], 'opponent': opp, 'home': home,
                        'rating': selection['rating'], 'oppRating': opp_rating, 'margin': margin, 'result': result,
                        'points': pts, 'bestXVPlaying': best_playing, 'starters': list(selection['starters']),
                        'bench': list(selection['bench'])})

    for i in range(N):
        d, wd = i - HIST, i % 7
        w = d // 7 if d >= 0 else -1
        info = week_info(w) if d >= 0 else None
        is_match_day = info is not None and wd == _MATCH_DAY and info['phase'] == 'comp' and info['type'] != 'B'

        # Thursday: read the warning lights and plan the coming week.
        if info is not None and wd == _DECISION_DAY:
            wk = {'week': w, 'flags': [], 'available': 0}
            for p1 in range(P):
                excluded[p1] = 0
                if injured_until[p1] > d:
                    continue
                sc = flag_scores(p1, i)
                is_flag = _active_flag(sc, S, ctx)
                wk['available'] += 1
                flag_weeks += 1
                if is_flag:
                    flags_raised += 1
                    wk['flags'].append(p1)
                if collect_rows:
                    rows.append({'season': season_seed, 'week': w, 'day': d, 'player': p1, 'scores': sc,
                                 'nc': 0, 'any': 0})
                if is_flag and S['policy'] in ('rest', 'modify'):
                    mod_until[p1] = d + 6
                    mod_factor[p1] = S['restTraining'] if S['policy'] == 'rest' else 0.6
                    if S['policy'] == 'rest':
                        excluded[p1] = 1
                force = opts.get('forceRest')
                if force and force.get('player') == p1 and force.get('week') == w:
                    mod_until[p1] = d + 6
                    mod_factor[p1] = S['restTraining']
                    excluded[p1] = 1
            weekly.append(wk)
        if is_match_day:
            select_team(d)

        for q in range(P):
            pl = players[q]
            u1, u2, u3 = luck[q].next(), luck[q].next(), luck[q].open()
            z = noise[q].normal()
            injured = injured_until[q] > d
            if injured:
                mn, rpe, kind = _session(info, wd, 'rehab' if d - inj_start[q] >= 3 else 'injured', 1, 1)
                status[q][i] = 1
            else:
                graded = S['gradedReturn'] and graded_until[q] > d
                cut = d >= 0 and mod_until[q] >= d
                if d < 0:
                    rl = 'reserve'
                elif graded:
                    rl = 'returning'
                elif is_match_day:
                    rl = role[q]
                elif cut and S['policy'] == 'rest':
                    rl = 'rested'
                else:
                    rl = 'reserve'
                ramp = _RAMP[S['preseason']][min(w, PRE_WEEKS - 1)] if info is not None else 1
                sess = _session(info, wd, rl, ramp, pl['offLoad'] / 107)
                mn = role_mins[q] if sess[0] < 0 else sess[0]
                rpe, kind = sess[1], sess[2]
                game = kind == _MATCH or kind == _SECOND
                if not game and info is not None:
                    if graded:
                        mn *= 0.6
                    if cut:
                        mn *= mod_factor[q]
                    rpe *= S['intensity']
                status[q][i] = 2 if graded else 3 if cut else 0
            if not (mn > 0):
                mn, kind = 0, _OFF
            wl = mn * rpe * pl['rpeBias'] * det_exp(0.15 * z - 0.01125) if mn > 0 else 0
            load[q][i], minutes[q][i], kinds[q][i] = wl, mn, kind
            atl_new = atl[q] + (wl - atl[q]) / 7
            ctl_new = ctl[q] + (wl - ctl[q]) / 42
            if mn > 0 and d >= 0 and not injured:
                recent = d - returned_day[q] < 42
                tm = truth_mult(pl, atl_new, ctl_new, recent, S['spike'])
                br = _base_rates(kind, S['contactScale'])
                p_nc = 1 - det_exp(-br[0] * mn * tm[0])
                p_c = 1 - det_exp(-br[1] * mn * tm[1])
                inj_type = 'nc' if u1 < p_nc else 'contact' if u2 < p_c else None
                if inj_type:
                    med, sig = (10, 0.75) if inj_type == 'nc' else (13, 0.95)
                    days = round_half_up(clamp(det_exp(det_log(med) + sig * inv_norm(u3)) * (1.4 if recent else 1),
                                               2, 120))
                    injuries.append({
                        'player': q, 'day': d, 'week': w, 'type': inj_type, 'days': days,
                        'setting': 'match' if kind == _MATCH else 'second' if kind == _SECOND else 'training',
                        'recurrence': recent, 'spike': tm[2], 'under': tm[3],
                        'mult': tm[0] if inj_type == 'nc' else tm[1], 'minutes': mn, 'kind': kind,
                        'chance': p_nc if inj_type == 'nc' else p_c})
                    injured_until[q] = d + 1 + days
                    inj_start[q] = d
                    returned_day[q] = d + 1 + days
                    graded_until[q] = d + 1 + days + 10 if S['gradedReturn'] else -1e9
                    inj_count[q] += 1
                    if collect_rows:
                        mark_rows(q, d, inj_type)
            atl[q], ctl[q] = atl_new, ctl_new
            ew_a[q] = lam_a * wl + (1 - lam_a) * ew_a[q]
            ew_c[q] = lam_c * wl + (1 - lam_c) * ew_c[q]
        if is_match_day:
            play_match(d, w, info)

    nc = contact = days_lost = in_match = 0
    for inj in injuries:
        if inj['type'] == 'nc':
            nc += 1
        else:
            contact += 1
        if inj['setting'] != 'training':
            in_match += 1
        days_lost += _min(inj['days'], SEASON_DAYS - 1 - inj['day'])
    points = wins = draws = losses = 0
    mean_rating = 0
    for m in matches:
        mean_rating += m['rating']
        if m['type'] != 'L':
            continue
        points += m['points']
        if m['result'] == 'W':
            wins += 1
        elif m['result'] == 'D':
            draws += 1
        else:
            losses += 1
    mean_rating /= _max(1, len(matches))
    table = _league_table(S['squadSeed'], season_seed, squad, matches)
    final = matches[-1]
    out = {
        'seed': season_seed, 'injuries': injuries, 'matches': matches, 'weekly': weekly,
        'injuriesTotal': len(injuries), 'nc': nc, 'contact': contact, 'inMatch': in_match, 'daysLost': days_lost,
        'points': points, 'wins': wins, 'draws': draws, 'losses': losses, 'position': table['position'],
        'table': table['rows'], 'finalWon': final['result'] == 'W', 'finalBestXV': final['bestXVPlaying'],
        'meanRating': mean_rating, 'flagsRaised': flags_raised, 'flagWeeks': flag_weeks, 'rests': rests,
        'forcedPlays': forced_plays,
    }
    if collect_rows:
        out['rows'] = rows
    if _truthy(opts.get('keepDaily')):
        out['load'], out['minutes'], out['kinds'], out['status'] = load, minutes, kinds, status
    return out


def _group_unit(g):
    """'F' (forwards) or 'B' (backs) for a position group."""
    for grp in GROUPS:
        if grp['id'] == g:
            return grp['unit']
    return 'B'


def _make_league_order(squad_seed):
    """The order of the eleven league opponents (a seeded Fisher-Yates shuffle)."""
    rng = Rng(hash_seed(squad_seed, 303))
    order = list(range(11))
    for j in range(len(order) - 1, 0, -1):
        r = rng.int_(j + 1)
        order[j], order[r] = order[r], order[j]
    return order


def _league_table(squad_seed, season_seed, squad, matches):
    """The other eleven clubs play each other home and away; our results come from the season itself."""
    rng = Rng(hash_seed(season_seed, 404, squad_seed))
    opponents = squad['opponents']
    n = len(opponents)
    pts, diff = [0] * (n + 1), [0] * (n + 1)

    def award(h, aw, m):
        pts[h] += 4 if m > 0 else 2 if m == 0 else 1 if m >= -7 else 0
        pts[aw] += 4 if m < 0 else 2 if m == 0 else 1 if m <= 7 else 0
        diff[h] += m
        diff[aw] -= m

    for a in range(n):
        for b in range(n):
            if a == b:
                continue
            m = round_half_up(2.0 * (opponents[a]['rating'] - opponents[b]['rating']) + 3 + 12 * inv_norm(rng.open()))
            award(a, b, m)
    for mt in matches:
        if mt['type'] != 'L':
            continue
        us, mm = n, mt['margin']
        pts[us] += mt['points']
        diff[us] += mm
        op_pts = 4 if mm < 0 else 2 if mm == 0 else 1 if mm <= 7 else 0
        pts[mt['opponent']] += op_pts
        diff[mt['opponent']] -= mm
    idx = sorted(range(n + 1), key=lambda k: (-pts[k], -diff[k], k))
    rows = [{'name': CLUB if k == n else opponents[k]['name'], 'us': k == n, 'points': pts[k], 'diff': diff[k],
             'position': pos + 1} for pos, k in enumerate(idx)]
    return {'rows': rows, 'position': idx.index(n) + 1}


def _active_flag(sc, S, ctx):
    """Whether the chosen warning light is on for one player-week."""
    if S['flag'] in _RATIO_FLAGS:
        return sc[S['flag']] >= S['threshold']
    if ctx.get('cutoffs') is None:
        return False
    return sc[S['flag']] >= ctx['cutoffs'][S['flag']]


# ---------- preparation: the squad, its history and the trained risk model ----------
_CACHE = {}
_CACHE_KEYS = ('squadSeed', 'preseason', 'intensity', 'gradedReturn', 'spike', 'contactScale', 'historySeasons',
               'budget')


def prepare(settings=None):
    """The squad, the risk model trained on past seasons and the model and oracle cutoffs (cached)."""
    S = with_defaults(settings)
    key = '|'.join(_js_str(S[k]) for k in _CACHE_KEYS)
    if key in _CACHE:
        return _CACHE[key]
    squad = make_squad(S['squadSeed'])
    hist = with_defaults(S)
    hist['policy'] = 'none'
    rows = []
    for h in _js_range(S['historySeasons']):
        res = simulate_season({'squad': squad, 'model': None, 'cutoffs': None}, hist, 1000000 + h,
                              {'collectRows': True})
        rows = rows + res['rows']
    X = [r['scores']['features'] for r in rows]
    y = [r['nc'] for r in rows]
    model = train_logistic(X, y, 1.0)
    for r in rows:
        r['scores']['model'] = predict_logistic(model, r['scores']['features'])
    cutoffs = {}
    for f in ('model', 'oracle'):
        sc = sort_numbers([r['scores'][f] for r in rows])
        cutoffs[f] = quantile(sc, 1 - S['budget'] / 100)
    ctx = {'squad': squad, 'model': model, 'cutoffs': cutoffs, 'historyRows': len(rows),
           'historyInjuries': _sum(y)}
    if len(_CACHE) > 40:
        del _CACHE[next(iter(_CACHE))]
    _CACHE[key] = ctx
    return ctx


def run_season(settings=None, seed=None, opts=None):
    """One season under the given settings (seed defaults to settings['seasonSeed'])."""
    S = with_defaults(settings)
    ctx = prepare(S)
    return simulate_season(ctx, S, S['seasonSeed'] if seed is None else seed, opts)


# ---------- the inquest: why each injury happened, and could a rest have avoided it? ----------
FACTOR_LABELS = {'spike': 'Load spike', 'under': 'Under-trained', 'recent': 'Back from injury', 'frailty': 'Frailty',
                 'age': 'Age', 'position': 'Position', 'fatigue': 'Fatigue in contact', 'exposure': 'Match or session'}


def injury_factors(player, inj, S):
    """The injury's true risk that day as log-multipliers against an average player in a typical session."""
    br = _base_rates(inj['kind'], S['contactScale'])
    if inj['type'] == 'nc':
        f = [('spike', S['spike'] * inj['spike']), ('under', 0.8 * inj['under']),
             ('recent', det_log(1.6) if inj['recurrence'] else 0), ('frailty', det_log(player['frailty'])),
             ('age', 0.03 * (player['age'] - 26)),
             ('exposure', det_log(br[0] * inj['minutes'] / (BASE['trainNC'] * 70)))]
    else:
        f = [('position', det_log(1.15 if player['unit'] == 'F' else 0.85)), ('frailty', 0.3 * det_log(player['frailty'])),
             ('fatigue', det_log(1 + 0.5 * inj['spike'])),
             ('exposure', det_log(br[1] * inj['minutes'] / (BASE['trainC'] * S['contactScale'] * 80)))]
    total, personal, out = 0, 0, []
    for key, value in f:
        total += value
        if key != 'exposure':
            personal += value
        out.append({'id': key, 'label': FACTOR_LABELS[key], 'value': value})
    main = None
    for x in out:
        if (x['id'] != 'exposure' or inj['type'] != 'nc') and x['value'] > 0 and (main is None or x['value'] > main['value']):
            main = x
    return {'factors': out, 'logTotal': total, 'personal': det_exp(personal), 'main': main['id'] if main else 'luck'}


def _active_flag_for(f, sc, S, ctx):
    if f in _RATIO_FLAGS:
        return sc[f] >= S['threshold']
    return sc[f] >= ctx['cutoffs'][f]


def inquest(settings=None, seed=None):
    """Every injury of one season: its true risk factors, what each light said the Thursday before, and whether
    resting that player for that week (same luck) would have avoided it."""
    S = with_defaults(settings)
    ctx = prepare(S)
    sd0 = S['seasonSeed'] if seed is None else seed
    res = simulate_season(ctx, S, sd0, {'collectRows': True})
    players = ctx['squad']['players']
    by_week = {}
    for r in res['rows']:
        by_week.setdefault(r['week'], []).append(r)
    items = []
    for inj in res['injuries']:
        wk = math.floor((inj['day'] - _DECISION_DAY) / 7)
        pl = players[inj['player']]
        item = {'player': inj['player'], 'name': pl['name'], 'group': pl['group'], 'day': inj['day'],
                'week': inj['week'], 'type': inj['type'], 'setting': inj['setting'], 'days': inj['days'],
                'chance': inj['chance'], 'explain': injury_factors(pl, inj, S), 'decisionWeek': wk,
                'lights': None, 'avoided': None, 'pointsCost': None}
        rows_w = by_week.get(wk, []) if wk >= 0 else []
        row = None
        for r in rows_w:
            if r['player'] == inj['player']:
                row = r
        if row is not None:
            item['lights'] = {}
            for f in FLAGS:
                below = sum(1 for r in rows_w if r['scores'][f] < row['scores'][f])
                item['lights'][f] = {'score': row['scores'][f], 'fired': _active_flag_for(f, row['scores'], S, ctx),
                                     'rank': below / (len(rows_w) - 1) if len(rows_w) > 1 else 0}
            alt = simulate_season(ctx, S, sd0, {'forceRest': {'player': inj['player'], 'week': wk}})
            start = wk * 7 + _DECISION_DAY
            hit = any(j['player'] == inj['player'] and start <= j['day'] <= start + 6 for j in alt['injuries'])
            item['avoided'] = not hit
            item['pointsCost'] = alt['points'] - res['points']
        items.append(item)

    def tally(kind, key=None):
        return sum(1 for it in items if it['type'] == kind and (key is None or key(it)))

    def flagged_by(it):
        return it['lights'] is not None and it['lights'][S['flag']]['fired']

    causes = {}
    for it in items:
        causes[it['explain']['main']] = causes.get(it['explain']['main'], 0) + 1
    return {
        'seed': sd0, 'flag': S['flag'], 'items': items,
        'summary': {
            'nc': tally('nc'), 'contact': tally('contact'),
            'ncFlagged': tally('nc', flagged_by), 'contactFlagged': tally('contact', flagged_by),
            'ncAvoidable': tally('nc', lambda it: it['avoided'] is True),
            'contactAvoidable': tally('contact', lambda it: it['avoided'] is True),
            'ncChecked': tally('nc', lambda it: it['avoided'] is not None),
            'contactChecked': tally('contact', lambda it: it['avoided'] is not None),
            'mainCauses': causes,
        },
    }


# ---------- statistics helpers ----------
def mean(a):
    """Arithmetic mean (NaN for an empty list)."""
    s = 0
    for v in a:
        s += v
    return s / len(a) if len(a) else math.nan


def sd(a):
    """Sample standard deviation (0 for fewer than two values)."""
    if len(a) < 2:
        return 0
    m, s = mean(a), 0
    for v in a:
        s += (v - m) * (v - m)
    return math.sqrt(s / (len(a) - 1))


def auc(scores, labels):
    """Area under the ROC curve by the rank-sum method, with ties shared."""
    n = len(scores)
    idx = sorted(range(n), key=lambda a: scores[a])
    ranks = [0.0] * n
    k = 0
    while k < n:
        j = k
        while j + 1 < n and scores[idx[j + 1]] == scores[idx[k]]:
            j += 1
        r = (k + j) / 2 + 1
        for t in range(k, j + 1):
            ranks[idx[t]] = r
        k = j + 1
    pos = sum_pos = 0
    for q in range(len(labels)):
        if _truthy(labels[q]):
            pos += 1
            sum_pos += ranks[q]
    neg = len(labels) - pos
    if not pos or not neg:
        return math.nan
    return (sum_pos - pos * (pos + 1) / 2) / (pos * neg)


def roc_curve(scores, labels, n=None):
    """ROC curve points [false-positive rate, true-positive rate], thinned to about n points."""
    idx = sorted(range(len(scores)), key=lambda a: -scores[a])
    pos = 0
    for q in range(len(labels)):
        pos += 1 if _truthy(labels[q]) else 0
    neg, tp, fp, pts = len(labels) - pos, 0, 0, [[0, 0]]
    step_every = _max(1, _floor(len(idx) / _or(n, 60)))
    for k in range(len(idx)):
        if _truthy(labels[idx[k]]):
            tp += 1
        else:
            fp += 1
        last = k == len(idx) - 1 or scores[idx[k + 1]] != scores[idx[k]]
        if last and (k % step_every == 0 or k == len(idx) - 1):
            pts.append([fp / neg if neg else 0, tp / pos if pos else 0])
    return pts


def confusion(scores, labels, cut):
    """Counts and rates of flagging every score at or above cut."""
    tp = fp = fn = tn = 0
    for i in range(len(scores)):
        f = scores[i] >= cut
        lab = _truthy(labels[i])
        if f and lab:
            tp += 1
        elif f:
            fp += 1
        elif lab:
            fn += 1
        else:
            tn += 1
    return {'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn, 'flagged': tp + fp,
            'share': (tp + fp) / _max(1, len(scores)),
            'precision': tp / (tp + fp) if tp + fp else math.nan, 'recall': tp / (tp + fn) if tp + fn else math.nan}


def boot_mean(a, seed, reps=None):
    """Percentile bootstrap interval [2.5%, 97.5%] of a mean, seeded."""
    rng, n, ms = Rng(hash_seed(seed, 77)), len(a), []
    if not n:
        return [math.nan, math.nan]
    for _ in _js_range(_or(reps, 1000)):
        s = 0
        for _i in range(n):
            s += a[rng.int_(n)]
        ms.append(s / n)
    ms = sort_numbers(ms)
    return [quantile(ms, 0.025), quantile(ms, 0.975)]


# ---------- analysis 2: how good is each warning light? ----------
# Seasons are played with nobody acting on any flag (a silent trial), so every flag is scored against the same
# injuries. Rows are player-weeks: the flag read on Thursday, the label is an injury in the next seven days.
FLAG_LABELS = {'coupled': 'Workload ratio, rolling (coupled)', 'uncoupled': 'Workload ratio, rolling (uncoupled)',
               'ewma': 'Workload ratio, EWMA', 'model': 'Risk model (the AI)',
               'oracle': 'Perfect knowledge (ceiling)'}


def evaluate_flags(settings, seeds):
    """AUCs, ROC curves and confusion tables of every flag over silent-trial seasons."""
    S = with_defaults(settings)
    ctx = prepare(S)
    silent = with_defaults(S)
    silent['policy'] = 'none'
    rows, per_season, totals = [], [], {'injuries': 0, 'nc': 0, 'contact': 0}
    for seed in seeds:
        res = simulate_season(ctx, silent, seed, {'collectRows': True})
        totals['injuries'] += res['injuriesTotal']
        totals['nc'] += res['nc']
        totals['contact'] += res['contact']
        labels = [r['nc'] for r in res['rows']]
        one = {'seed': seed}
        for f in FLAGS:
            one[f] = auc([r['scores'][f] for r in res['rows']], labels)
        per_season.append(one)
        rows = rows + res['rows']
    nc_lab = [r['nc'] for r in rows]
    any_lab = [r['any'] for r in rows]
    flags = []
    for f in FLAGS:
        sc = [r['scores'][f] for r in rows]
        cut = S['threshold'] if f in _RATIO_FLAGS else ctx['cutoffs'][f]
        budget_cut = quantile(sort_numbers(sc), 1 - S['budget'] / 100)
        aucs = [o[f] for o in per_season if o[f] == o[f]]
        flags.append({
            'id': f, 'label': FLAG_LABELS[f], 'auc': auc(sc, nc_lab), 'aucAny': auc(sc, any_lab),
            'seasonAuc': {'mean': mean(aucs), 'lo': quantile(sort_numbers(aucs), 0.1),
                          'hi': quantile(sort_numbers(aucs), 0.9)},
            'roc': roc_curve(sc, nc_lab, 50), 'atRule': confusion(sc, nc_lab, cut), 'rule': cut,
            'atBudget': confusion(sc, nc_lab, budget_cut), 'budgetCut': budget_cut})
    return {'seeds': list(seeds), 'rows': len(rows), 'flags': flags, 'perSeason': per_season, 'totals': totals,
            'baseRate': mean(nc_lab), 'anyRate': mean(any_lab),
            'contactShare': totals['contact'] / _max(1, totals['injuries']),
            'historyRows': ctx['historyRows'], 'historyInjuries': ctx['historyInjuries'], 'model': ctx['model']}


def coupling_demo(seed, n=None):
    """The coupling artefact: with independent random weekly loads, the rolling (coupled) ratio's acute and
    chronic parts are correlated only because the chronic window contains the acute week."""
    rng, pts = Rng(hash_seed(seed, 55)), []
    ac, cc, cu = [], [], []
    for _ in _js_range(_or(n, 400)):
        wk = [1800 * det_exp(0.3 * rng.normal()) for _k in range(4)]
        acute = wk[0]
        coupled_c = (wk[0] + wk[1] + wk[2] + wk[3]) / 4
        uncoupled_c = (wk[1] + wk[2] + wk[3]) / 3
        ac.append(acute)
        cc.append(coupled_c)
        cu.append(uncoupled_c)
        pts.append({'acute': acute, 'coupled': acute / coupled_c, 'uncoupled': acute / uncoupled_c})

    def corr(x, y):
        mx, my, sxy, sxx, syy = mean(x), mean(y), 0, 0, 0
        for j in range(len(x)):
            sxy += (x[j] - mx) * (y[j] - my)
            sxx += (x[j] - mx) * (x[j] - mx)
            syy += (y[j] - my) * (y[j] - my)
        return _div(sxy, math.sqrt(sxx * syy))

    max_c = max_u = 0
    for p in pts:
        max_c = _max(max_c, p['coupled'])
        max_u = _max(max_u, p['uncoupled'])
    return {'points': pts, 'corrCoupled': corr(ac, cc), 'corrUncoupled': corr(ac, cu), 'maxCoupled': max_c,
            'maxUncoupled': max_u}


# ---------- analysis 4: compare ways of managing the squad ----------
POLICY_LABELS = {'none': 'Pick the best, ignore the light', 'rest': 'Rest anyone flagged',
                 'modify': 'Cut training when flagged', 'rotate': 'Planned rotation', 'readiness': 'Pick on readiness'}
METRICS = ['injuriesTotal', 'nc', 'contact', 'daysLost', 'points', 'position', 'finalBestXV', 'meanRating', 'rests']


def _season_summary(res):
    """The METRICS of one season, plus finalWon as 0 or 1."""
    o = {m: res[m] for m in METRICS}
    o['finalWon'] = 1 if res['finalWon'] else 0
    return o


def compare_policies(settings, seeds, policies=None):
    """Every policy over the same seeds (common random numbers), with bootstrap intervals of the differences."""
    S = with_defaults(settings)
    ctx = prepare(S)
    policies = POLICIES if policies is None else policies
    runs = {}
    for pol in policies:
        s2 = with_defaults(S)
        s2['policy'] = pol
        runs[pol] = [_season_summary(simulate_season(ctx, s2, seed)) for seed in seeds]
    ref = policies[0] if policies else None
    table = []
    for pol in policies:
        row = {'policy': pol, 'label': POLICY_LABELS.get(pol), 'seasons': len(runs[pol]), 'metrics': {}}
        for m in METRICS + ['finalWon']:
            vals = [r[m] for r in runs[pol]]
            diffs = [r[m] - runs[ref][k][m] for k, r in enumerate(runs[pol])]
            ci = boot_mean(diffs, 11 + _index_of(METRICS + ['finalWon'], m))
            row['metrics'][m] = {'mean': mean(vals), 'sd': sd(vals), 'diff': mean(diffs), 'lo': ci[0], 'hi': ci[1]}
        table.append(row)
    return {'seeds': list(seeds), 'policies': policies, 'reference': ref, 'table': table, 'runs': runs}


# ---------- analysis 3: could a one-season pilot tell? ----------
# A club plays a normal season, then pilots the warning light (acting on it) the next season, and compares.
# Different seasons have different luck, which is what the pilot cannot see. The true effect uses the same
# luck with and without the light (common random numbers), which only a simulation can do.
def pilot_study(settings, pairs):
    """What a before-and-after pilot measures against the true effect, over the given number of season pairs."""
    S = with_defaults(settings)
    if S['policy'] == 'none':
        S['policy'] = 'rest'
    ctx = prepare(S)
    off = with_defaults(S)
    off['policy'] = 'none'
    measured, true_diff, points_diff, actions, quiet, before, after = [], [], [], [], [], [], []
    true_days, measured_days, true_nc, missed = [], [], [], []
    for k in _js_range(pairs):
        seed_a, seed_b = 5000 + 2 * k, 5001 + 2 * k
        base_a = simulate_season(ctx, off, seed_a)
        pilot_b = simulate_season(ctx, S, seed_b)
        with_a = simulate_season(ctx, S, seed_a)
        before.append(base_a['injuriesTotal'])
        after.append(pilot_b['injuriesTotal'])
        measured.append(pilot_b['injuriesTotal'] - base_a['injuriesTotal'])
        measured_days.append(pilot_b['daysLost'] - base_a['daysLost'])
        true_diff.append(with_a['injuriesTotal'] - base_a['injuriesTotal'])
        true_nc.append(with_a['nc'] - base_a['nc'])
        true_days.append(with_a['daysLost'] - base_a['daysLost'])
        points_diff.append(with_a['points'] - base_a['points'])
        missed.append(with_a['rests'])
        co = coach_view(with_a)
        actions.append(co['actions'])
        quiet.append(co['quiet'])
    true_effect, base_mean, after_mean = mean(true_diff), mean(before), mean(after)
    pooled = [v - base_mean for v in before] + [v - after_mean for v in after]
    squares = 0
    for v in pooled:
        squares = squares + v * v
    season_sd = math.sqrt(squares / _max(1, len(pooled) - 2))

    def count(f):
        return _div(len([v for i, v in enumerate(measured) if f(v, i)]), pairs)

    power = [{'seasons': n, 'power': power_two_sample(true_effect, season_sd, n)} for n in range(1, 101)]
    needed = seasons_for(true_effect, season_sd, 0.8)
    total_actions, total_quiet = _sum(actions), _sum(quiet)
    return {
        'pairs': pairs, 'policy': S['policy'], 'flag': S['flag'], 'measured': measured, 'trueDiff': true_diff,
        'before': before, 'after': after,
        'trueEffect': true_effect, 'trueEffectCI': boot_mean(true_diff, 31), 'trueNC': mean(true_nc),
        'baseMean': base_mean, 'measuredMean': mean(measured), 'measuredSd': sd(measured), 'seasonSd': season_sd,
        'trueDays': mean(true_days), 'measuredDays': measured_days,
        'pointsEffect': mean(points_diff), 'pointsCI': boot_mean(points_diff, 37), 'matchesMissed': mean(missed),
        'looksBetter': count(lambda v, i: v < 0),
        'looksGreat': count(lambda v, i: v <= -0.2 * before[i]),
        'looksWorse': count(lambda v, i: v > 0),
        'power': power, 'seasonsNeeded': needed,
        'actionsPerSeason': _div(total_actions, pairs),
        'quietShare': total_quiet / total_actions if total_actions else math.nan,
        'actionsPerInjuryPrevented': _div(total_actions, pairs) / -true_effect if true_effect < 0 else math.inf,
    }


def coach_view(res):
    """What a coach sees after acting on a flag: was that player injured in the following fortnight?"""
    actions = quiet = 0
    for wk in res['weekly']:
        for pid in wk['flags']:
            actions += 1
            start, hit = wk['week'] * 7 + _DECISION_DAY, False
            for inj in res['injuries']:
                if inj['player'] == pid and start <= inj['day'] < start + 14:
                    hit = True
                    break
            if not hit:
                quiet += 1
    return {'actions': actions, 'quiet': quiet}


def power_two_sample(delta, sigma, n):
    """Power of a two-sided two-sample comparison of mean injuries a season, n seasons in each arm."""
    if not (sigma > 0):
        return 1 if delta != 0 else 0.05
    se, zc = sigma * math.sqrt(2 / n), 1.959963984540054
    return norm_cdf(abs(delta) / se - zc) + norm_cdf(-abs(delta) / se - zc)


def seasons_for(delta, sigma, target):
    """Seasons in each arm for the target power (normal approximation); Infinity when delta is 0."""
    if not _truthy(delta):
        return math.inf
    if not (sigma > 0):
        return 1
    zsum = 1.959963984540054 + inv_norm(target)
    return _ceil(2 * (zsum * sigma / delta) * (zsum * sigma / delta))


def player_series(res, player):
    """Daily fitness (42-day), fatigue (7-day) and the workload ratios for one player, from a season kept with
    keepDaily. Ratios are read on the morning of each day, from the days before it."""
    L, T, lam_a, lam_c = res['load'][player['id']], TOTAL_DAYS, 2 / (7 + 1), 2 / (28 + 1)
    atl = ctl = e_a = e_c = player['offLoad']
    out = {'fitness': [0.0] * T, 'fatigue': [0.0] * T, 'ewma': [0.0] * T, 'coupled': [0.0] * T, 'weekly': []}
    run = 0
    for i in range(T):
        a7 = c28 = 0
        for k in range(1, 29):
            v = L[i - k] if i - k >= 0 else 0
            c28 += v
            if k <= 7:
                a7 += v
        out['coupled'][i] = a7 / _max(c28 / 4, 100) if i >= 28 else math.nan
        out['ewma'][i] = e_a / _max(e_c, 100 / 7)
        atl = atl + (L[i] - atl) / 7
        ctl = ctl + (L[i] - ctl) / 42
        e_a = lam_a * L[i] + (1 - lam_a) * e_a
        e_c = lam_c * L[i] + (1 - lam_c) * e_c
        out['fitness'][i] = ctl
        out['fatigue'][i] = atl
        run += L[i]
        if i % 7 == 6:
            out['weekly'].append(run)
            run = 0
    return out


# ---------- dates (civil calendar, no time zones) ----------
def days_from_civil(y, m, d):
    """Days since 1970-01-01 of a proleptic Gregorian date."""
    y -= 1 if m <= 2 else 0
    era = _floor(y / 400)
    yoe = y - era * 400
    mp = _js_mod(m + 9, 12)
    doy = _floor((153 * mp + 2) / 5) + d - 1
    doe = yoe * 365 + _floor(yoe / 4) - _floor(yoe / 100) + doy
    return era * 146097 + doe - 719468


def civil_from_days(z):
    """[year, month, day] of a day number counted from 1970-01-01."""
    z += 719468
    era = _floor(z / 146097)
    doe = z - era * 146097
    yoe = _floor((doe - _floor(doe / 1460) + _floor(doe / 36524) - _floor(doe / 146096)) / 365)
    y = yoe + era * 400
    doy = doe - (365 * yoe + _floor(yoe / 4) - _floor(yoe / 100))
    mp = _floor((5 * doy + 2) / 153)
    d = doy - _floor((153 * mp + 2) / 5) + 1
    m = mp + 3 if mp < 10 else mp - 9
    return [y + 1 if m <= 2 else y, m, d]


def _pad2(n):
    return ('0' if n < 10 else '') + _js_str(n)


def format_day(z):
    """A day number as YYYY-MM-DD."""
    c = civil_from_days(z)
    return _js_str(c[0]) + '-' + _pad2(c[1]) + '-' + _pad2(c[2])


_ISO_DATE = re.compile('^' + _WS_CLASS + '*([0-9]{4})-([0-9]{1,2})-([0-9]{1,2})' + _WS_CLASS + r'*\Z')
_UK_DATE = re.compile('^' + _WS_CLASS + '*([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})' + _WS_CLASS + r'*\Z')


def parse_day(s):
    """The day number of 'YYYY-M-D' or 'D/M/YYYY' (UK order), or None if it is not a real date."""
    text = _js_str(s)
    m = _ISO_DATE.match(text)
    if m:
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    else:
        u = _UK_DATE.match(text)
        if not u:
            return None
        y, mo, d = int(u[3]), int(u[2]), int(u[1])
    if mo < 1 or mo > 12 or d < 1 or d > 31:
        return None
    z = days_from_civil(y, mo, d)
    back = civil_from_days(z)
    return z if back[1] == mo and back[2] == d else None


SEASON_START = days_from_civil(2026, 7, 20) - HIST  # the first off-season day in the logbook: Monday 22 June 2026


# ---------- a season as a club logbook (one row per session) ----------
_SESSION_NAMES = {_OFF: 'training', _TRAIN: 'training', _CONTACT: 'contact training', _MATCH: 'match',
                  _SECOND: 'second-team match', _REHAB: 'rehab'}


def season_logbook(settings=None, seed=None):
    """One season written out as a club would log it: date, player, position, session, minutes, rpe, injury."""
    S = with_defaults(settings)
    ctx = prepare(S)
    res = simulate_season(ctx, S, S['seasonSeed'] if seed is None else seed, {'keepDaily': True})
    players, out = ctx['squad']['players'], []
    inj_at = {}
    for inj in res['injuries']:
        inj_at[(inj['player'], inj['day'] + HIST)] = 'non-contact' if inj['type'] == 'nc' else 'contact'
    for i in range(TOTAL_DAYS):
        for p in range(len(players)):
            mn = res['minutes'][p][i]
            if not (mn > 0):
                continue
            mins = round_half_up(mn)
            if mins < 1:
                mins = 1
            rpe = clamp(round_half_up(res['load'][p][i] / mins * 2) / 2, 1, 10)
            kind = res['kinds'][p][i]
            out.append({'date': format_day(SEASON_START + i), 'player': players[p]['name'],
                        'position': _group_label(players[p]['group']), 'session': _SESSION_NAMES[kind],
                        'minutes': mins, 'rpe': rpe, 'injury': inj_at.get((p, i), '')})
    return {'rows': out, 'season': res}


def _group_label(g):
    for grp in GROUPS:
        if grp['id'] == g:
            return grp['label']
    return g


# ---------- CSV ----------
def parse_csv(text):
    """Rows of fields. Commas, semicolons and tabs all separate fields; quotes may wrap a field; CR is dropped;
    a leading byte-order mark is ignored; blank lines are skipped."""
    rows, row, field, in_q, i = [], [], '', False, 0
    s = _js_str(text)
    if s.startswith('\ufeff'):
        s = s[1:]
    while i < len(s):
        ch = s[i]
        if in_q:
            if ch == '"':
                if s[i + 1:i + 2] == '"':
                    field += '"'
                    i += 2
                    continue
                in_q = False
                i += 1
                continue
            field += ch
            i += 1
            continue
        if ch == '"' and field == '':
            in_q = True
            i += 1
            continue
        if ch in ',;\t':
            row.append(field)
            field = ''
            i += 1
            continue
        if ch == '\r':
            i += 1
            continue
        if ch == '\n':
            row.append(field)
            rows.append(row)
            row, field = [], ''
            i += 1
            continue
        field += ch
        i += 1
    if field != '' or row:
        row.append(field)
        rows.append(row)
    return [r for r in rows if len(r) > 1 or (r[0] or '').strip(_JS_WS) != '']


NO_INJURY = ('0', 'no', 'none', 'n', 'false', 'n/a', 'na', '-', 'fit', 'nil')
_CSV_SPECIAL = re.compile('[",\n\r;\t]')


def _csv_cell(v):
    t = '' if v is None else _js_str(v)
    return '"' + t.replace('"', '""') + '"' if _CSV_SPECIAL.search(t) else t


def to_csv(header, rows):
    """CSV text with a header line, quoting cells that contain quotes, commas, semicolons or line breaks."""
    lines = [','.join(_csv_cell(v) for v in header)] + [','.join(_csv_cell(v) for v in r) for r in rows]
    return '\n'.join(lines) + '\n'


# ---------- analysis 5: a club's own logbook ----------
_LOG_ALIASES = {
    'date': ['date', 'day', 'session date'], 'player': ['player', 'name', 'athlete', 'player id', 'id'],
    'minutes': ['minutes', 'duration', 'mins', 'duration (min)', 'time'],
    'rpe': ['rpe', 'srpe', 'effort', 'session rpe'],
    'load': ['load', 'session load', 'au', 'srpe load'], 'injury': ['injury', 'injured', 'injury type'],
}


def read_logbook(table):
    """Reads session rows into per-player daily loads. Returns warnings rather than raising on messy rows."""
    if not len(table):
        return {'error': 'The file is empty.'}
    head = [_js_str(h).strip(_JS_WS).lower() for h in table[0]]
    col = {}
    for k, aliases in _LOG_ALIASES.items():
        col[k] = -1
        for a in aliases:
            if col[k] < 0 and a in head:
                col[k] = head.index(a)
    if col['date'] < 0 or col['player'] < 0:
        return {'error': 'The first row needs a date column and a player column.'}
    if col['load'] < 0 and (col['minutes'] < 0 or col['rpe'] < 0):
        return {'error': 'Add minutes and rpe columns, or a load column.'}
    sessions, skipped, warnings, min_day, max_day = [], 0, [], math.inf, -math.inf
    for r in range(1, len(table)):
        row = table[r]
        day = parse_day(_cell(row, col['date']))
        player = _cell(row, col['player'])
        name = _js_str('' if player is None else player).strip(_JS_WS)
        if col['load'] >= 0 and _js_str(_or(_cell(row, col['load']), '')).strip(_JS_WS) != '':
            ld = _to_number(_cell(row, col['load']))
        else:
            ld = _to_number(_cell(row, col['minutes'])) * _to_number(_cell(row, col['rpe']))
        inj = _js_str(_or(_cell(row, col['injury']), '')).strip(_JS_WS).lower() if col['injury'] >= 0 else ''
        if day is None or not name or not (ld >= 0) or ld > 5000:
            skipped += 1
            continue
        if not inj or inj in NO_INJURY:
            inj_type = ''
        else:
            inj_type = 'contact' if inj.startswith('contact') else 'non-contact'
        sessions.append({'day': day, 'player': name, 'load': ld, 'injury': inj_type})
        if day < min_day:
            min_day = day
        if day > max_day:
            max_day = day
    if not sessions:
        return {'error': 'No rows could be read. Dates should look like 2026-09-05.'}
    if skipped:
        warnings.append(_js_str(skipped) + ' row' + (' was' if skipped == 1 else 's were') +
                        ' skipped (unreadable date, empty player or load).')
    span = max_day - min_day + 1
    if span > 3 * 366:
        return {'error': 'The logbook covers more than three years; split it into seasons.'}
    names, index = [], {}
    for s in sessions:
        if s['player'] not in index:
            index[s['player']] = len(names)
            names.append(s['player'])
    loads = [[0.0] * span for _ in names]
    injuries = []
    for s in sessions:
        p = index[s['player']]
        loads[p][s['day'] - min_day] += s['load']
        if s['injury']:
            injuries.append({'player': p, 'day': s['day'] - min_day, 'type': s['injury']})
    injuries.sort(key=lambda x: (x['player'], x['day']))
    dedup = []
    for x in injuries:
        last = dedup[-1] if dedup else None
        if last is None or last['player'] != x['player'] or x['day'] - last['day'] > 3:
            dedup.append(x)
    if span < 35:
        warnings.append('Less than five weeks of data: the 28-day ratios need four weeks before they mean anything.')
    return {'names': names, 'start': min_day, 'span': span, 'loads': loads, 'injuries': dedup,
            'sessions': len(sessions), 'warnings': warnings}


def analyse_logbook(book, opts=None):
    """Workload ratios for every player and day, the weekly flags, and how well each ratio anticipated injuries.

    opts (JavaScript keys): threshold (1.5), permutations (200), only ('non-contact' when any are logged,
    otherwise 'all') and seed (1) for the permutation test.
    """
    opts = opts or {}
    threshold = _or(opts.get('threshold'), 1.5)
    perms = 200 if opts.get('permutations') is None else opts['permutations']
    P, T = len(book['names']), book['span']
    has_nc = any(x['type'] == 'non-contact' for x in book['injuries'])
    only = _or(opts.get('only'), 'non-contact' if has_nc else 'all')
    counted = [x for x in book['injuries'] if only == 'all' or x['type'] == only]
    lam_a, lam_c = 2 / (7 + 1), 2 / (28 + 1)
    series = []
    for p in range(P):
        L = book['loads'][p]
        first = 0
        while first < T and not (L[first] > 0):
            first += 1
        seed7 = 0
        for k in range(first, _min(T, first + 7)):
            seed7 += L[k]
        e_a, e_c = seed7 / 7, seed7 / 7
        coupled, uncoupled, ewma = [0.0] * T, [0.0] * T, [0.0] * T
        monotony, strain, acute, chronic = [0.0] * T, [0.0] * T, [0.0] * T, [0.0] * T
        for t in range(T):
            # values for the morning of day t, from days t-28 .. t-1
            a7 = c28 = c21 = 0
            vals = []
            for j in range(1, 29):
                v = L[t - j] if t - j >= 0 else 0
                c28 += v
                if j <= 7:
                    a7 += v
                    vals.append(v)
                else:
                    c21 += v
            valid = t - first >= 28
            acute[t] = a7
            chronic[t] = c28 / 4
            coupled[t] = a7 / _max(c28 / 4, 100) if valid else math.nan
            uncoupled[t] = a7 / _max(c21 / 3, 100) if valid else math.nan
            ewma[t] = e_a / _max(e_c, 100 / 7) if valid else math.nan
            m7, s7 = a7 / 7, 0
            for q in range(7):
                s7 += (vals[q] - m7) * (vals[q] - m7)
            s7 = math.sqrt(s7 / 7)
            monotony[t] = _min(m7 / s7 if s7 > 0 else 5, 5) if valid else math.nan
            strain[t] = a7 * monotony[t] if valid else math.nan
            if t >= first:
                e_a = lam_a * L[t] + (1 - lam_a) * e_a
                e_c = lam_c * L[t] + (1 - lam_c) * e_c
        series.append({'name': book['names'][p], 'coupled': coupled, 'uncoupled': uncoupled, 'ewma': ewma,
                       'monotony': monotony, 'strain': strain, 'acute': acute, 'chronic': chronic, 'first': first})
    # Weekly decision points on the logbook's own weekday pattern: every seventh day from day 28.
    inj_by_player = [[] for _ in range(P)]
    out_by_player = [[] for _ in range(P)]
    for x in counted:
        inj_by_player[x['player']].append(x['day'])
    for x in book['injuries']:
        out_by_player[x['player']].append(x['day'])

    def build_rows(inj_days):
        rows = []
        for p3 in range(P):
            se = series[p3]
            for t2 in range(28, T, 7):
                if not (se['coupled'][t2] == se['coupled'][t2]):
                    continue
                out = any(dd < t2 and t2 - dd < 14 for dd in out_by_player[p3])
                lab = 1 if any(t2 <= dd < t2 + 7 for dd in inj_days[p3]) else 0
                if out:
                    continue
                rows.append({'player': p3, 't': t2, 'label': lab})
        return rows

    rows = build_rows(inj_by_player)
    ratio_ids = ['coupled', 'uncoupled', 'ewma']

    def score_of(r, f):
        return series[r['player']][f][r['t']]

    labels = [r['label'] for r in rows]
    positives = _sum(labels)
    results = []
    for f in ratio_ids:
        sc = [score_of(r, f) for r in rows]
        results.append({'id': f, 'label': FLAG_LABELS[f], 'auc': auc(sc, labels) if positives else math.nan,
                        'atRule': confusion(sc, labels, threshold)})
    # Circular-shift permutation test: each player's injuries slide round the season by a random amount,
    # which keeps how many injuries each player had and how their loads run, but breaks any link between the two.
    if positives >= 3 and perms > 0:
        rng = Rng(hash_seed(_or(opts.get('seed'), 1), 66))
        exceed = [0 for _ in ratio_ids]
        width = _max(1, T - 28)
        for _ in _js_range(perms):
            shifted = []
            for lst in inj_by_player:
                sh = 28 + rng.int_(width)
                # The double remainder is a true modulo in both languages, so Python's % is safe here.
                shifted.append([28 + ((dd - 28 + sh) % width + width) % width for dd in lst])
            prow = build_rows(shifted)
            plab = [r['label'] for r in prow]
            for k, f in enumerate(ratio_ids):
                a = auc([score_of(r, f) for r in prow], plab)
                if a >= results[k]['auc']:
                    exceed[k] += 1
        for k, r in enumerate(results):
            r['p'] = (exceed[k] + 1) / (perms + 1)
    # The latest week: who would be flagged on the last day of the logbook.
    last_t = T - 1
    latest = [{'player': k, 'name': se['name'], 'coupled': se['coupled'][last_t],
               'uncoupled': se['uncoupled'][last_t], 'ewma': se['ewma'][last_t],
               'monotony': se['monotony'][last_t], 'strain': se['strain'][last_t], 'acute': se['acute'][last_t],
               'chronic': se['chronic'][last_t],
               'flagged': se['ewma'][last_t] >= threshold or se['coupled'][last_t] >= threshold}
              for k, se in enumerate(series)]
    latest.sort(key=lambda x: -(x['ewma'] if x['ewma'] == x['ewma'] else -1))
    weekly_load = 0
    for L in book['loads']:
        s = 0
        for t3 in range(T):
            s += L[t3]
        weekly_load += s
    n_weeks = T / 7
    return {'series': series, 'rows': len(rows), 'injuries': len(book['injuries']), 'counted': len(counted),
            'only': only, 'positives': positives, 'results': results,
            'latest': latest, 'threshold': threshold,
            'meanWeekly': weekly_load / _max(1, P) / _max(1, n_weeks),
            'start': book['start'], 'span': T, 'permutations': perms if positives >= 3 else 0}
