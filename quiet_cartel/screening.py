"""Screening a panel of markets for signs of algorithmic coordination, from daily prices.

A regulator gets a file of daily prices (and perhaps costs and sales) for many
markets. For each market this module runs the browser app's price screens
(:func:`quiet_cartel.model.screens`) and its circular-shift permutation test of
retaliation (:func:`quiet_cartel.model.permutation_test`). Screening many
markets at once means many tests, so the p-values are turned into
Benjamini-Hochberg q-values (:func:`benjamini_hochberg`) and a market is
flagged only when its q-value is below 0.10 and rivals do hit back more often
after an unprovoked cut than on an ordinary day (retaliation above zero).

When the hidden truth is known, as for the bundled synthetic data,
:func:`evaluate` scores every screen by how well it ranks the real cases.
"""

import csv
import math
import multiprocessing
import os

from . import model

__all__ = ['read_panel', 'read_truth', 'screen_panel', 'benjamini_hochberg', 'evaluate',
           'TARGETS', 'FLAG_Q', 'MIN_DAYS', 'EXTRA_SCREENS']

MIN_DAYS = 30           # the permutation test needs at least 30 days
FLAG_Q = 0.10           # flag markets whose q-value is below this (and whose rivals hit back)
NAN = float('nan')

REQUIRED = ('day', 'price_a', 'price_b')

# The two definitions of a "real case" used by the browser app.
TARGETS = [
    {'id': 'coordinated', 'label': 'Held up by a threat',
     'note': 'Cuts are punished and the profit gain is at least 20%.'},
    {'id': 'high_price', 'label': 'High prices',
     'note': 'The profit gain is 50% or more, whatever the cause.'},
]

# A screen that needs sales data (added by quiet_cartel.calibrate when it is available).
EXTRA_SCREENS = [
    {'id': 'excessPrice', 'label': 'Excess over fitted competitive price', 'sign': 1,
     'note': 'Where prices sit between the competitive and monopoly prices of a demand model fitted to sales '
             '(0 competitive, 1 monopoly).'},
]


# ------------------------------------------------------------ reading files

def _where(path, row):
    return '%s, row %d' % (path, row)


def _number(text, col, path, row, money=False):
    t = (text or '').strip()
    if money and t[:1] in ('£', '$', '€'):
        t = t[1:].strip()
    try:
        x = float(t)
    except ValueError:
        if t == '':
            raise ValueError('%s: %s is blank' % (_where(path, row), col)) from None
        raise ValueError('%s: %s is not a number (%r)' % (_where(path, row), col, text)) from None
    if not math.isfinite(x):
        raise ValueError('%s: %s is not a finite number (%r)' % (_where(path, row), col, text))
    return int(x) if x == int(x) and 'e' not in t.lower() and '.' not in t else x


def _market_id(text, path, row):
    t = (text or '').strip()
    if t == '':
        raise ValueError('%s: market is blank' % _where(path, row))
    try:
        return int(t)
    except ValueError:
        return t


def _sort_key(market):
    return (0, market, '') if isinstance(market, int) else (1, 0, market)


def _open_rows(path):
    """Yield (row number, {column: text}) for every non-blank row, with tidy lower-case column names.

    Row numbers count the header as row 1, so they match the line numbers a
    spreadsheet or text editor shows (for files without line breaks inside quotes).
    The delimiter is whichever of comma, semicolon or tab splits the header most.
    """
    with open(path, newline='', encoding='utf-8-sig') as f:
        try:
            first = f.readline()
            if not first.strip():
                raise ValueError('%s is empty (no header row)' % path)
            delim = max([',', ';', '\t'], key=first.count)
            f.seek(0)       # utf-8-sig drops a byte order mark again after the seek
            reader = csv.reader(f, delimiter=delim)
            header = [h.strip().lower() for h in next(reader)]
            seen = set()
            for h in header:
                if h and h in seen:
                    raise ValueError('%s: the column %s appears twice in the header' % (path, h))
                seen.add(h)
            yield header
            for cells in reader:
                if not any(c.strip() for c in cells):
                    continue
                if len(cells) > len(header) and any(c.strip() for c in cells[len(header):]):
                    raise ValueError('%s: more values than columns in the header' % _where(path, reader.line_num))
                yield reader.line_num, {h: (cells[k] if k < len(cells) else '') for k, h in enumerate(header)}
        except UnicodeDecodeError:
            # name the file: the command line may read two (prices and truth)
            raise ValueError('%s is not UTF-8 text (save it as UTF-8 CSV)' % path) from None


def read_panel(path):
    """Read a file of daily prices for one or more markets.

    Required columns: ``day``, ``price_a`` and ``price_b``. ``market`` is
    optional: without it the whole file is market 1. Optional pairs: ``cost_a``
    and ``cost_b`` (unit costs, averaged over the days of each market), and
    ``shoppers`` with ``units_a`` and ``units_b`` (daily sales, needed to fit a
    demand model). Column names are not case sensitive, other columns are
    ignored, and a leading currency sign on prices and costs is allowed.

    Returns ``{market: {'day': [...], 'prices': [[a...], [b...]], 'cost': [ca, cb]
    or None}}``, with ``'shoppers'`` and ``'units'`` ([[a...], [b...]]) when the
    file has sales, every list sorted by day, and markets in order. Raises
    ValueError with the row number for a missing column, a value that is not a
    number, a price that is not above zero, a negative cost, negative or
    impossible sales, a day that appears twice in a market, or a market with
    fewer than 30 days.
    """
    rows = _open_rows(path)
    header = next(rows)
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise ValueError('%s: missing required column%s %s (found: %s)' % (
            path, 's' if len(missing) > 1 else '', ', '.join(missing), ', '.join(h for h in header if h) or 'none'))
    has_market = 'market' in header
    has_cost = 'cost_a' in header or 'cost_b' in header
    if has_cost and not ('cost_a' in header and 'cost_b' in header):
        raise ValueError('%s: cost_a and cost_b must be given together' % path)
    sales_cols = [c for c in ('shoppers', 'units_a', 'units_b') if c in header]
    has_sales = bool(sales_cols)
    if has_sales and len(sales_cols) < 3:
        raise ValueError('%s: shoppers, units_a and units_b must be given together (found only %s)' % (
            path, ', '.join(sales_cols)))
    markets = {}
    for row, cells in rows:
        m = _market_id(cells['market'], path, row) if has_market else 1
        rec = {'row': row, 'day': _number(cells['day'], 'day', path, row)}
        for col in ('price_a', 'price_b'):
            p = _number(cells[col], col, path, row, money=True)
            if not p > 0:
                raise ValueError('%s: %s must be above zero (got %s)' % (_where(path, row), col, cells[col].strip()))
            rec[col] = p
        if has_cost:
            rec['cost'] = [_number(cells[c], c, path, row, money=True) for c in ('cost_a', 'cost_b')]
            for col, c in zip(('cost_a', 'cost_b'), rec['cost']):
                if c < 0:
                    raise ValueError('%s: %s must not be negative (got %s)' % (_where(path, row), col, cells[col].strip()))
        if has_sales:
            n, ua, ub = (_number(cells[c], c, path, row) for c in ('shoppers', 'units_a', 'units_b'))
            for col, v in (('shoppers', n), ('units_a', ua), ('units_b', ub)):
                if v < 0:
                    raise ValueError('%s: %s must not be negative (got %s)' % (_where(path, row), col, cells[col].strip()))
            if ua + ub > n:
                raise ValueError('%s: units_a + units_b (%s) is more than shoppers (%s)' % (_where(path, row), ua + ub, n))
            rec['sales'] = (n, ua, ub)
        markets.setdefault(m, []).append(rec)
    if not markets:
        raise ValueError('%s has a header but no data rows' % path)
    panel = {}
    for m in sorted(markets, key=_sort_key):
        recs = sorted(markets[m], key=lambda r: r['day'])
        for prev, cur in zip(recs, recs[1:]):
            if prev['day'] == cur['day']:
                raise ValueError('%s: market %s has day %s twice (rows %d and %d)' % (
                    path, m, cur['day'], min(prev['row'], cur['row']), max(prev['row'], cur['row'])))
        if len(recs) < MIN_DAYS:
            raise ValueError('%s: market %s has only %d days (row %d onwards); screening needs at least %d' % (
                path, m, len(recs), min(r['row'] for r in recs), MIN_DAYS))
        entry = {'day': [r['day'] for r in recs],
                 'prices': [[r['price_a'] for r in recs], [r['price_b'] for r in recs]],
                 'cost': None}
        if has_cost:
            entry['cost'] = [_steady_mean([r['cost'][i] for r in recs]) for i in range(2)]
        if has_sales:
            entry['shoppers'] = [r['sales'][0] for r in recs]
            entry['units'] = [[r['sales'][1] for r in recs], [r['sales'][2] for r in recs]]
        panel[m] = entry
    return panel


def _steady_mean(xs):
    """The value itself when every day has the same cost, otherwise the exactly rounded mean."""
    return xs[0] if all(x == xs[0] for x in xs) else math.fsum(xs) / len(xs)


def _flag01(text, col, path, row):
    t = (text or '').strip().lower()
    if t in ('1', 'true', 'yes', 'y'):
        return True
    if t in ('0', 'false', 'no', 'n'):
        return False
    raise ValueError('%s: %s must be 1 or 0 (got %r)' % (_where(path, row), col, text))


def read_truth(path):
    """Read the hidden truth for a panel: ``{market: {column: value}}``.

    Required columns: ``market``, ``coordinated`` and ``high_price`` (1 or 0).
    When present, ``punished`` is read as a flag, ``mu``, ``profit_gain``,
    ``competitive_price`` and ``monopoly_price`` as numbers, ``training_seed``
    as a whole number, and any other column as text.
    """
    rows = _open_rows(path)
    header = next(rows)
    missing = [c for c in ('market', 'coordinated', 'high_price') if c not in header]
    if missing:
        raise ValueError('%s: missing required column%s %s' % (path, 's' if len(missing) > 1 else '', ', '.join(missing)))
    truth = {}
    for row, cells in rows:
        m = _market_id(cells['market'], path, row)
        if m in truth:
            raise ValueError('%s: market %s appears twice' % (_where(path, row), m))
        rec = {}
        for col, text in cells.items():
            if not col or col == 'market':
                continue
            if col in ('coordinated', 'high_price', 'punished'):
                rec[col] = _flag01(text, col, path, row)
            elif col in ('mu', 'profit_gain', 'competitive_price', 'monopoly_price'):
                rec[col] = float(_number(text, col, path, row))
            elif col == 'training_seed':
                rec[col] = int(_number(text, col, path, row))
            else:
                rec[col] = text.strip()
        truth[m] = rec
    if not truth:
        raise ValueError('%s has a header but no data rows' % path)
    return truth


# ------------------------------------------------------------ screening

def benjamini_hochberg(pvalues):
    """Benjamini-Hochberg q-values: the smallest false discovery rate at which each test is a discovery.

    Sort the m p-values in increasing order, p(1) <= ... <= p(m). The q-value of
    p(k) is the smallest of min(1, p(j) * m / j) over j = k..m, so flagging every
    market with q below a level L keeps the expected share of false flags among
    all flags at or below L (for independent or positively dependent tests).
    A missing p-value (``None`` or NaN, a market with no unprovoked cut to test)
    still counts in m as a p-value of 1, which can only make the others more
    cautious; its own q-value comes back as NaN.
    """
    return model.benjamini_hochberg(pvalues)


def _screen_one(task):
    """Screens and permutation test for one market. Top level so that a process pool can run it."""
    market, prices, cost, reps, tol, seed = task
    sc = model.screens(prices, {'tol': tol, 'cost': cost})
    # The retaliation statistic does not use costs, so the permutation test runs without them (faster).
    perm = model.permutation_test(prices, {'tol': tol, 'reps': reps, 'seed': seed})
    return {
        'market': market, 'days': len(prices[0]), 'cost': cost,
        'meanPrice': [model.mean(p) for p in prices],
        'screens': sc,
        'scores': {s['id']: model.screen_score(sc, s['id']) for s in model.SCREEN_LIST},
        'pValue': perm['pValue'], 'permReps': perm['reps'],
    }


def screen_panel(panel, reps=999, tol=0.005, seed=4242, jobs=1, progress=None):
    """Screen every market in a panel and flag the suspicious ones.

    For each market: :func:`quiet_cartel.model.screens` (with its unit costs
    when the file has them, so the margin screen is available) and the p-value
    of :func:`quiet_cartel.model.permutation_test` with ``reps`` circular
    shifts. Every market uses the same ``seed``, so a market's result does not
    depend on which other markets are in the file. The p-values are then
    adjusted across markets with :func:`benjamini_hochberg`, and a market is
    flagged when its q-value is below 0.10 and its retaliation screen is above
    zero (a significant result in the direction of punishment).

    ``jobs`` above 1 spreads the markets over worker processes;
    ``progress(done, total, market)`` is called as each market finishes.
    """
    if not panel:
        raise ValueError('the panel has no markets')
    if not (isinstance(reps, int) and not isinstance(reps, bool) and reps >= 1):
        raise ValueError('reps must be a whole number of at least 1')
    if not (isinstance(tol, (int, float)) and not isinstance(tol, bool) and 0 <= tol < 1):
        raise ValueError('tol must be at least 0 and below 1')
    tasks = [(m, d['prices'], d['cost'], reps, tol, seed) for m, d in panel.items()]
    out = []
    n = 1 if jobs is not None and jobs <= 1 else min((os.cpu_count() or 1) if jobs is None else jobs, len(tasks))
    if n > 1:           # one worker would only add the cost of a process (and the command line says "this process")
        with multiprocessing.Pool(processes=n) as pool:
            for res in pool.imap(_screen_one, tasks):
                out.append(res)
                if progress:
                    progress(len(out), len(tasks), res['market'])
    else:
        for task in tasks:
            out.append(_screen_one(task))
            if progress:
                progress(len(out), len(tasks), out[-1]['market'])
    qs = benjamini_hochberg([r['pValue'] for r in out])
    for r, q in zip(out, qs):
        ret = r['screens']['retaliation']
        r['qValue'] = q
        r['flag'] = bool(q == q and q < FLAG_Q and ret == ret and ret > 0)
    return {'settings': {'reps': reps, 'tol': tol, 'seed': seed, 'flagQ': FLAG_Q},
            'markets': out, 'flagged': [r['market'] for r in out if r['flag']]}


# ------------------------------------------------------------ scoring against the truth

def _score(market, sid):
    v = market.get('scores', {}).get(sid)
    return NAN if v is None else v


def evaluate(results, truth):
    """Score the screens against the hidden truth, for both definitions of a case.

    ``results`` is the output of :func:`screen_panel` (or anything with a
    ``markets`` list whose entries have ``market`` and ``scores``, and
    optionally ``flag``). Markets missing from ``truth`` are left out and
    listed. For each target (``coordinated`` and ``high_price``) it reports
    the ROC AUC (:func:`quiet_cartel.model.roc_curve`: the chance that a random
    real case scores higher than a random innocent market, 0.5 being no better
    than chance) of every screen in ``model.SCREEN_LIST`` that the results
    carry, plus ``excessPrice`` when any market has it (markets whose demand
    fit was unusable score NaN and rank last), and the confusion
    (:func:`quiet_cartel.model.confusion`) of the Benjamini-Hochberg flag
    against the target when the results carry flags.
    """
    markets = [r for r in results['markets'] if r['market'] in truth]
    missing = [r['market'] for r in results['markets'] if r['market'] not in truth]
    if not markets:
        raise ValueError('none of the screened markets appears in the truth file')
    present = set()
    for r in markets:
        present.update(r.get('scores', {}))
    screens = [s for s in model.SCREEN_LIST + EXTRA_SCREENS if s['id'] in present]
    if 'excessPrice' in present and all(r['scores'].get('excessPrice') is None for r in markets):
        screens = [s for s in screens if s['id'] != 'excessPrice']
    has_flags = all('flag' in r for r in markets)
    out = {'markets': len(markets), 'missing': missing, 'targets': []}
    for tg in TARGETS:
        labels = [bool(truth[r['market']][tg['id']]) for r in markets]
        rows = []
        for s in screens:
            roc = model.roc_curve([_score(r, s['id']) for r in markets], labels)
            rows.append({'id': s['id'], 'label': s['label'], 'note': s['note'], 'auc': roc['auc']})
        flag = None
        if has_flags:
            flag = model.confusion([1.0 if r['flag'] else 0.0 for r in markets], labels, 0.5)
        out['targets'].append({'id': tg['id'], 'label': tg['label'], 'note': tg['note'],
                               'positives': sum(labels), 'negatives': len(labels) - sum(labels),
                               'screens': rows, 'flag': flag})
    return out
