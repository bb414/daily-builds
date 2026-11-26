"""Command line for the Quiet cartel companion: ``python -m quiet_cartel <command>``.

Commands
  train      one training run, explained: prices, the cycle, a one-day price cut and the reply
  remedies   many runs of each remedy, compared with the baseline run by run
  sweep      a grid of two settings, showing where prices settle
  screen     screen a file of daily prices (and sales) for signs of coordination
  calibrate  fit the demand model to daily sales and measure how far prices sit above competitive
  report     build one offline HTML report from saved JSON results

Results go to standard output, progress and timings to standard error. Any
error prints one line and exits with status 2.
"""

import argparse
import copy
import csv
import json
import math
import os
import shlex
import sys
import time

from . import calibrate, experiments, model, report, screening

PRESETS = {
    'textbook': {}, 'close': {'mu': 0.1}, 'loyal': {'mu': 0.5}, 'three': {'nFirms': 3, 'maxPeriods': 6000000},
    'impatient': {'delta': 0.5}, 'fast': {'beta': 2e-5}, 'matcher': {'firmTypes': ['learn', 'match', 'learn']},
}
SELLERS = 'ABC'
PER = 1000              # profits are shown per 1,000 shoppers, as in the browser app
RULE_LABEL = {'learn': 'self-learning', 'nash': 'fixed competitive price', 'match': 'matches the cheapest rival',
              'undercut': 'undercuts the cheapest rival'}


class CliError(Exception):
    """A problem to report in one line, with exit status 2."""


class ConfigErrors(Exception):
    """Validation errors from model.validate_config, one per line."""


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CliError('%s: %s (see --help)' % (self.prog, message))


# ------------------------------------------------------------ formatting

def money(x):
    return 'n/a' if not _finite(x) else ('-' if x < 0 else '') + '£%.2f' % abs(x)


def pct(x, d=0):
    if not _finite(x):
        return 'n/a'
    s = '%.*f%%' % (d, x * 100)
    return s[1:] if s.startswith('-') and not s.strip('-0.%') else s      # no "-0%"


def pts(x):
    return 'n/a' if not _finite(x) else _signed0(x) + ' pts'


def pval(p):
    if not _finite(p):
        return 'n/a'
    return '<0.001' if p < 0.001 else '%.3f' % p


def num(x, d=3):
    return 'n/a' if not _finite(x) else '%.*f' % (d, x)


def rounds(t):
    return '%.2fm' % (t / 1e6) if t >= 1e6 else '%dk' % round(t / 1e3) if t >= 1e4 else str(t)


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def table(headers, rows, right=None):
    """Plain-text table. ``right`` is the set of column indexes to right-align (default: all but the first)."""
    right = set(range(1, len(headers))) if right is None else set(right)
    cells = [[str(c) for c in headers]] + [[str(c) for c in r] for r in rows]
    widths = [max(len(r[k]) for r in cells) for k in range(len(headers))]
    lines = []
    for n, r in enumerate(cells):
        parts = [c.rjust(widths[k]) if k in right else c.ljust(widths[k]) for k, c in enumerate(r)]
        lines.append('  '.join(parts).rstrip())
        if n == 0:
            lines.append('  '.join('-' * w for w in widths))
    return '\n'.join(lines)


def out(text=''):
    print(text, file=sys.stdout)


def err(text):
    print(text, file=sys.stderr, flush=True)


class Progress(object):
    """Progress on standard error: one updating line on a terminal, otherwise a line every tenth.

    ``start(total)``, when given, returns a line to print when the work begins (``done == 0``).
    """

    def __init__(self, label, start=None):
        self.label = label
        self.start = start
        self.tty = hasattr(sys.stderr, 'isatty') and sys.stderr.isatty()

    def __call__(self, done, total, item=None):
        if done == 0:
            if self.start:
                err(self.start(total))
            return
        if self.tty:
            sys.stderr.write('\r%s %d of %d' % (self.label, done, total) + ('\n' if done == total else ''))
            sys.stderr.flush()
        elif done == total or done % max(1, total // 10) == 0:
            err('%s %d of %d' % (self.label, done, total))


# ------------------------------------------------------------ settings

def parse_value(text):
    """A --set value: true/false, a number, a comma list of those, or text."""
    t = text.strip()
    if ',' in t:
        return [parse_value(x) for x in t.split(',') if x.strip() != '']
    if t.lower() in ('true', 'false'):
        return t.lower() == 'true'
    try:
        return int(t)
    except ValueError:
        pass
    try:
        x = float(t)
        return x if math.isfinite(x) else t
    except ValueError:
        return t


def parse_sets(items):
    known = model.default_config()
    out_ = {}
    for item in items or []:
        if '=' not in item:
            raise CliError("--set needs key=value, got '%s'" % item)
        key, _, value = item.partition('=')
        key = key.strip()
        if key not in known:
            raise CliError("unknown setting '%s' (known: %s)" % (key, ', '.join(sorted(known))))
        out_[key] = parse_value(value)
    return out_


def build_config(args, seed=None):
    """Preset, then --set values, then the seed; validated. Raises ConfigErrors listing every problem."""
    cfg = copy.deepcopy(PRESETS[args.preset])
    cfg.update(parse_sets(args.set))
    if seed is not None:
        cfg['seed'] = seed
    v = model.validate_config(cfg)
    if v['errors']:
        raise ConfigErrors(v['errors'])
    return v['config']


def describe(cfg, swept=()):
    """One line of settings in words; ``swept`` names settings that vary, so their base value is not shown."""
    cfg = dict(cfg)
    for k in swept:
        cfg[k] = 'swept'
    n = cfg['nFirms'] if cfg['nFirms'] != 'swept' else 3
    types = cfg['firmTypes'][:n]
    who = 'all self-learning' if all(t == 'learn' for t in types) else ', '.join(
        '%s %s' % (SELLERS[i], RULE_LABEL[t]) for i, t in enumerate(types))
    text = ('%s sellers (%s), loyalty mu %s, patience delta %s, learning rate alpha %s, exploration decay beta %s, '
            '%s prices, memory %s' % (n, who, cfg['mu'], cfg['delta'], cfg['alpha'], cfg['beta'], cfg['nPrices'],
                                      cfg['memory']))
    extras = []
    if cfg['sharedVendor']:
        extras.append('shared vendor')
    if cfg['exploreFloor']:
        extras.append('exploration floor %s' % cfg['exploreFloor'])
    if cfg['demandNoise']:
        extras.append('demand noise %s' % cfg['demandNoise'])
    if any(x != 2 for x in cfg['quality'][:n]) or any(x != 1 for x in cfg['cost'][:n]):
        extras.append('quality %s, cost %s' % (cfg['quality'][:n], cfg['cost'][:n]))
    return text + (', ' + ', '.join(extras) if extras else '')


# ------------------------------------------------------------ files

def _clean(x):
    """JSON-safe copy: NaN and infinities become null, tuples become lists."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


def _parent(path):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)


def write_json(path, obj):
    _parent(path)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(_clean(obj), f, indent=1, ensure_ascii=False, allow_nan=False)
        f.write('\n')
    err('Wrote %s' % path)


def write_csv(path, rows, fields=None):
    if fields is None:
        fields = []
        for r in rows:
            for k in r:
                if k not in fields:
                    fields.append(k)
    _parent(path)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, restval='', extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow({k: ('' if v is None or (isinstance(v, float) and not math.isfinite(v)) else v)
                        for k, v in r.items()})
    err('Wrote %s' % path)


def read_json(path, kind):
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise CliError('%s is not valid JSON (line %d: %s)' % (path, e.lineno, e.msg)) from None
    if not isinstance(data, dict) or data.get('kind') != kind:
        raise CliError('%s is not saved %s results (make it with: python -m quiet_cartel %s --json %s)' % (
            path, kind, kind, path))
    return data


# ------------------------------------------------------------ train

def cmd_train(args, ctx):
    cfg = build_config(args, args.seed)
    tr = model.Trainer(cfg)
    prog = Progress('Training: round')
    while not tr.run(500000):
        if prog.tty:
            sys.stderr.write('\rTraining: round %s, exploring on %s of days ' % (rounds(tr.t), pct(tr.eps, 2)))
            sys.stderr.flush()
    if prog.tty:
        sys.stderr.write('\r' + ' ' * 60 + '\r')
    s = model.summarise(tr)
    mk, n = tr.market, tr.market['n']
    ir = model.impulse_response(tr, {'cycle': s['cycle']})
    brs = [model.best_response_check(tr, i, s['cycle']) for i in range(n)]

    def each(xs):
        if all(abs(x - xs[0]) < 1e-9 for x in xs):
            return money(xs[0]) + ' each'
        return ', '.join('%s %s' % (SELLERS[i], money(x)) for i, x in enumerate(xs))

    out('Quiet cartel: one training run')
    out('Settings: %s, seed %s' % (describe(cfg), cfg['seed']))
    out()
    out('Market')
    out('  Competitive price          %s' % each(mk['pN']))
    out('  Monopoly price             %s' % each(mk['pM']))
    out('Training')
    out('  Rounds                     %s' % rounds(s['periods']))
    out('  Settled                    %s' % ('yes: no strategy changed for %s rounds' % rounds(cfg['stableWindow'])
                                             if s['converged'] else 'no: stopped at the limit of %s rounds'
                                             % rounds(cfg['maxPeriods'])))
    out('Settled play')
    out('  Prices                     %s (average over a cycle of %d day%s)' % (
        ', '.join('%s %s' % (SELLERS[i], money(p)) for i, p in enumerate(s['price'])), s['cycleLength'],
        '' if s['cycleLength'] == 1 else 's'))
    out('  Profit gain                %s (0%% is competitive, 100%% monopoly)' % pct(s['avgGain']))
    out('  Profit gain in training    %s (the last 100k rounds, exploration included)' % pct(s['realisedGain']))
    out('  Shoppers\' loss             %s of what they would lose if prices went from competitive to monopoly'
        % pct(s['harm']))
    out()
    rows = []
    for k, j in enumerate(s['cycle'][:8]):
        a = model.decode_joint(j, n, mk['m'])
        rows.append([k + 1] + [money(mk['grids'][i][a[i]]) for i in range(n)]
                    + [money(mk['profit'][0][i][j] * PER) for i in range(n)])
    out('The cycle%s (profit per 1,000 shoppers a day)' % (' (first 8 days)' if s['cycleLength'] > 8 else ''))
    out(table(['day'] + ['price %s' % SELLERS[i] for i in range(n)] + ['profit %s' % SELLERS[i] for i in range(n)],
              rows))
    out()
    H = ir['horizon']
    # Show every day up to two days after the last one that differs from the path without the cut
    # (a cycle can return out of step, so returning to the cycle is not enough).
    differs = [t for t in range(H + 1) if any(abs(ir['prices'][i][t] - ir['cfPrices'][i][t]) > 1e-9 for i in range(n))]
    last = min(H, max(8, (differs[-1] if differs else 0) + 2))
    out('Impulse response: seller A cuts to %s for one day (its best one-day cut), then the strategies play on'
        % money(ir['devPrice']))
    rows = []
    for t in range(last + 1):
        rows.append([t] + ['%.2f%s' % (ir['prices'][i][t], '*' if abs(ir['prices'][i][t] - ir['cfPrices'][i][t]) > 1e-9
                                       else '') for i in range(n)]
                    + ['%.2f' % ir['cfPrices'][i][t] for i in range(n)])
    out(table(['day'] + ['%s' % SELLERS[i] for i in range(n)] + ['%s without the cut' % SELLERS[i] for i in range(n)],
              rows))
    if last < H:
        out('  (days %d to %d are the same with or without the cut)' % (last + 1, H))
    out('  * differs from the path without the cut')
    back = 'back in the settled cycle from day %d' % ir['returnedAt'] if ir['returnedAt'] is not None else \
        'not back in the settled cycle within %d days' % H
    now = ('gains %s today' if ir['gainNow'] >= 0 else 'loses %s today') % money(abs(ir['gainNow']) * PER)
    later = ('loses %s' if ir['lossLater'] >= 0 else 'gains %s') % money(abs(ir['lossLater']) * PER)
    out('  Seller A %s and %s over the next %d days (discounted at delta %s): net %s per 1,000 shoppers; %s.'
        % (now, later, H - 1, cfg['delta'], money(ir['net'] * PER), back))
    if s['punished']:
        out('  Punished: yes. A rival answers with a lower price and the cut loses money overall.')
    elif ir['rivalCut']:
        out('  Punished: no. A rival answers with a lower price, but the cut still pays.')
    else:
        out('  Punished: no. No rival answers the cut with a lower price.')
    out()
    out('Best-response check (each seller against the others\' learned strategies, solved exactly)')
    rows = []
    for i, b in enumerate(brs):
        if b is None:
            rows.append(['seller %s' % SELLERS[i], 'fixed rule: ' + RULE_LABEL[cfg['firmTypes'][i]], '', ''])
        else:
            rows.append(['seller %s' % SELLERS[i], pct(b['shareOptimal']), 'yes' if b['onPathOptimal'] else 'no',
                         pct(b['bestReplyGain'], 1) + ('' if b['settled'] else ' (not settled)')])
    out(table(['', 'best reply in every situation', 'best reply where play settled', 'gain from best reply'], rows))
    out('  Gain from best reply: how much more the seller would earn over time, from where play settled, by switching')
    out('  to the best possible strategy against the others\' learned strategies (which stay fixed).')
    if args.json:
        write_json(args.json, {
            'kind': 'train', 'command': ctx['command'], 'config': cfg,
            'market': {k: mk[k] for k in ('pN', 'pM', 'piN', 'piM', 'csN', 'csM', 'grids')},
            'summary': s, 'impulse': ir, 'bestResponse': brs, 'seconds': time.time() - ctx['start'],
        })
    return 0


# ------------------------------------------------------------ remedies

def _scenario_ids(text):
    if not text:
        return [sc['id'] for sc in model.SCENARIOS]
    return [x.strip() for x in text.split(',') if x.strip()]


def cmd_remedies(args, ctx):
    if args.runs < 1:
        raise CliError('--runs must be at least 1')
    base = build_config(args)
    ids = _scenario_ids(args.scenarios)
    seeds = list(range(1, args.runs + 1))

    def start(total):
        return 'Training %d runs (%d per option, seeds 1 to %d) on %s ...' % (
            total, len(seeds), len(seeds), _workers(args.jobs, total))

    rows = experiments.run_batch(base, ids, seeds, jobs=args.jobs, progress=Progress('Run', start))
    summary = experiments.summarise_batch(rows)
    out('Quiet cartel: remedies compared with the baseline')
    out('Settings: %s; %d runs per option (seeds 1 to %d)' % (describe(base), len(seeds), len(seeds)))
    out()
    out(remedies_table(summary))
    out()
    out('Gain is the realised profit gain (0% competitive, 100% monopoly) with its 90% bootstrap interval. Change is')
    out('the mean paired difference from the baseline run with the same seed, with a 90% paired bootstrap interval')
    out('and a sign-flip permutation p-value, Holm-adjusted across the options. Loss is the shoppers\' loss. Reply')
    out('gain is how much more a learning seller would earn over time by switching to its exact best reply to the')
    out('others\' learned strategies (0% would mean they form an equilibrium).')
    if args.csv:
        write_csv(args.csv, rows)
    if args.json:
        write_json(args.json, {
            'kind': 'remedies', 'command': ctx['command'],
            'settings': {'preset': args.preset, 'set': args.set or [], 'runs': args.runs, 'seeds': seeds,
                         'scenarios': summary['order'], 'base': base},
            'summary': summary, 'runs': rows, 'seconds': time.time() - ctx['start'],
        })
    return 0


def remedies_table(summary):
    rows = []
    for sid in summary['order']:
        sc = summary['scenarios'][sid]
        a, vs = sc['agg'], sc['vsBaseline']
        g = vs['realisedGain'] if vs else None
        rows.append([
            sc['label'], sc['group'], pct(a['gain']['mean']), '%s to %s' % (pct(a['gain']['lo']), pct(a['gain']['hi'])),
            pts(g['diff']) if g else '', '%s to %s' % (_signed0(g['lo']), _signed0(g['hi'])) if g else '',
            pval(g['pHolm']) if g else '', pct(a['harm']['mean']), pct(a['punishedShare']), pct(a['convergedShare']),
            pct(sc['replyGain'], 1) if sc['replyGain'] is not None else 'n/a',
        ])
    return table(['option', 'group', 'gain', '90% interval', 'change', '90% interval', 'Holm p', 'loss', 'punished',
                  'settled', 'reply gain'], rows, right=range(2, 11))


def _signed0(x):
    """A difference in percentage points, signed, with no "-0" or "+0"."""
    if not _finite(x):
        return 'n/a'
    s = '%+.0f' % (x * 100)
    return '0' if s in ('+0', '-0') else s


def _workers(jobs, count):
    n = min((os.cpu_count() or 1) if jobs is None else jobs, count)
    return 'this process' if n <= 1 else '%d worker processes' % n


# ------------------------------------------------------------ sweep

def _axis(text, flag):
    if not text or '=' not in text:
        raise CliError('%s needs param=v1,v2,... (for example mu=0.1,0.25,0.5)' % flag)
    name, _, values = text.partition('=')
    vals = []
    for v in values.split(','):
        if not v.strip():
            continue
        x = parse_value(v)
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise CliError("%s: '%s' is not a number" % (flag, v.strip()))
        vals.append(x)
    return name.strip(), vals


def cmd_sweep(args, ctx):
    if args.runs < 1:
        raise CliError('--runs must be at least 1')
    base = build_config(args)
    xp, xs = _axis(args.x, '--x')
    yp, ys = _axis(args.y, '--y')
    seeds = list(range(1, args.runs + 1))

    def start(total):
        return 'Training %d runs (%d by %d grid, %d per cell) on %s ...' % (
            total, len(xs), len(ys), len(seeds), _workers(args.jobs, total))

    res = experiments.sweep(base, xp, xs, yp, ys, seeds, scenario=args.scenario, jobs=args.jobs,
                            progress=Progress('Run', start))
    sc = model.scenario_by_id(args.scenario)
    out('Quiet cartel: sweep of %s and %s (%s)' % (xp, yp, sc['label']))
    out('Settings: %s; %d run%s per cell' % (describe(base, (xp, yp)), len(seeds), '' if len(seeds) == 1 else 's'))
    for title, key, fmt in (('Mean realised profit gain', 'gain', pct), ('Mean shoppers\' loss', 'harm', pct),
                            ('Share of runs where a cut is punished', 'punishedShare', pct),
                            ('Share of runs that settled', 'convergedShare', pct)):
        out()
        out('%s (rows %s, columns %s)' % (title, yp, xp))
        out(table([yp + ' \\ ' + xp] + [str(x) for x in xs],
                  [[str(y)] + [fmt(c[key]) for c in line] for y, line in zip(ys, res['cells'])]))
    flat = [dict(c) for line in res['cells'] for c in line]
    for c in flat:
        c[xp], c[yp] = c.pop('x'), c.pop('y')
    if args.csv:
        write_csv(args.csv, flat, [xp, yp, 'runs', 'gain', 'harm', 'punishedShare', 'convergedShare'])
    if args.json:
        write_json(args.json, {
            'kind': 'sweep', 'command': ctx['command'],
            'settings': {'preset': args.preset, 'set': args.set or [], 'runs': args.runs, 'seeds': seeds,
                         'scenario': args.scenario, 'scenarioLabel': sc['label'], 'base': base},
            'sweep': res, 'seconds': time.time() - ctx['start'],
        })
    return 0


# ------------------------------------------------------------ screen and calibrate

def _attach_calibration(res, cal):
    by_market = {r['market']: r for r in cal['markets']}
    for r in res['markets']:
        c = by_market.get(r['market'])
        r['excessPrice'] = c['excessPrice'] if c else None
        r['scores']['excessPrice'] = r['excessPrice']
    res['calibration'] = cal


def cmd_screen(args, ctx):
    if args.reps < 1:
        raise CliError('--reps must be at least 1')
    panel = screening.read_panel(args.path)
    truth = screening.read_truth(args.truth) if args.truth else None
    sales = all('units' in d for d in panel.values())
    err('Screening %d market%s (%d permutation shifts each) on %s ...' % (
        len(panel), '' if len(panel) == 1 else 's', args.reps, _workers(args.jobs, len(panel))))
    res = screening.screen_panel(panel, reps=args.reps, tol=args.tol, jobs=args.jobs, progress=Progress('Market'))
    if sales:
        _attach_calibration(res, calibrate.calibrate_panel(panel, truth))
    if truth:
        res['evaluation'] = screening.evaluate(res, truth)
        for r in res['markets']:
            r['truth'] = truth.get(r['market'])
    out('Quiet cartel: price screens for %d market%s in %s' % (len(panel), '' if len(panel) == 1 else 's', args.path))
    out('Settings: tolerance %s, %d permutation shifts, flag when q < %.2f and retaliation > 0%s' % (
        pct(args.tol, 1), args.reps, screening.FLAG_Q, '; sales data found, so the excess price screen is included'
        if sales else ''))
    out()
    rows = []
    for r in res['markets']:
        sc = r['screens']
        row = [r['market'], r['days'], pct(sc['margin']) if sc['margin'] is not None else 'n/a', num(sc['cv']),
               sc['events'], pct(sc['retaliation']), pval(r['pValue']), pval(r['qValue']), 'FLAG' if r['flag'] else '']
        if sales:
            row.append(num(r['excessPrice'], 2))
        if truth:
            t = truth.get(r['market'], {})
            row += [t.get('setup', '?'), _yes(t.get('coordinated')), _yes(t.get('high_price'))]
        rows.append(row)
    headers = ['market', 'days', 'margin', 'cv', 'cuts', 'retaliation', 'p', 'q', 'flag']
    if sales:
        headers.append('excess')
    if truth:
        headers += ['setup', 'threat', 'high']
    out(table(headers, rows, right=range(1, 10 if sales else 9)))
    out()
    out('Flagged: %s' % (', '.join(str(m) for m in res['flagged']) or 'none'))
    if truth:
        out()
        out(evaluation_text(res['evaluation']))
    if sales and res['calibration']['truth']:
        out()
        out(calibration_summary(res['calibration']))
    if args.csv:
        flat = []
        for r in res['markets']:
            row = {'market': r['market'], 'days': r['days']}
            row.update({k: v for k, v in r['screens'].items() if k != 'eventList'})
            row.update({'pValue': r['pValue'], 'qValue': r['qValue'], 'flag': int(r['flag'])})
            if sales:
                row['excessPrice'] = r['excessPrice']
            flat.append(row)
        write_csv(args.csv, flat)
    if args.json:
        write_json(args.json, {
            'kind': 'screen', 'command': ctx['command'],
            'settings': {'path': args.path, 'truth': args.truth, 'reps': args.reps, 'tol': args.tol,
                         'seed': res['settings']['seed'], 'flagQ': screening.FLAG_Q, 'sales': sales},
            'results': res, 'seconds': time.time() - ctx['start'],
        })
    return 0


def _yes(v):
    return '' if v is None else 'yes' if v else 'no'


def evaluation_text(ev):
    lines = ['How well each screen ranks the real cases (ROC AUC; 0.5 is chance, 1 perfect) over %d markets'
             % ev['markets']]
    targets = ev['targets']
    rows = []
    for k, s in enumerate(targets[0]['screens']):
        rows.append([s['label']] + [num(tg['screens'][k]['auc'], 2) for tg in targets])
    lines.append(table(['screen'] + ['%s (%d cases)' % (tg['label'], tg['positives']) for tg in targets], rows))
    if targets[0]['flag'] is not None:
        lines.append('')
        lines.append('The flag (q < %.2f and retaliation > 0) against each definition' % screening.FLAG_Q)
        rows = []
        for tg in targets:
            c = tg['flag']
            rows.append([tg['label'], c['caught'], c['falseAlarms'], c['missed'], c['cleared'], pct(c['precision']),
                         pct(c['recall'])])
        lines.append(table(['definition', 'caught', 'false alarms', 'missed', 'cleared', 'precision', 'recall'], rows))
    if ev['missing']:
        lines.append('Not in the truth file, so left out: %s' % ', '.join(str(m) for m in ev['missing']))
    return '\n'.join(lines)


def calibration_summary(cal):
    t = cal['truth']
    lines = ['Demand fit against the truth: %d of %d markets usable; fitted mu off by %s on average (mean error %s);'
             % (cal['usable'], len(cal['markets']), num(t['muMae']), _signed(t['muBias']))]
    if t['competitiveMae'] is not None:
        lines.append('fitted competitive price off by %s on average.' % money(t['competitiveMae']))
    if t['evaluation']:
        aucs = ['%s %s' % (tg['label'].lower(), num(tg['screens'][0]['auc'], 2)) for tg in t['evaluation']['targets']]
        lines.append('Excess price index AUC: %s.' % ', '.join(aucs))
    return ' '.join(lines)


def _signed(x):
    return 'n/a' if not _finite(x) else '%+.3f' % x


def cmd_calibrate(args, ctx):
    panel = screening.read_panel(args.path)
    if not all('units' in d for d in panel.values()):
        raise CliError('%s has no sales: calibration needs shoppers, units_a and units_b columns' % args.path)
    truth = screening.read_truth(args.truth) if args.truth else None
    cal = calibrate.calibrate_panel(panel, truth)
    out('Quiet cartel: logit demand fitted to daily sales in %s' % args.path)
    out('ln(s_i / s_0) = a_i / mu - p_i / mu, pooled OLS with one intercept per seller; excess index is 0 at the')
    out('fitted competitive price and 1 at the fitted monopoly price.')
    out()
    rows, notes = [], []
    for r in cal['markets']:
        f, b = r['fit'], r['benchmark']
        row = [r['market']]
        if f['usable']:
            row += ['%s (%s)' % (num(f['mu']), num(f['muSe']))]
        else:
            row += ['unusable']
        if truth:
            row.append(num(r.get('trueMu')))
        row += [num(f['r2'], 2), '%d/%d' % (f['days'], f['days'] + f['dropped']),
                money(model.mean(b['competitive'])) if b['competitive'] else 'n/a',
                money(model.mean(b['monopoly'])) if b['monopoly'] else 'n/a',
                money(model.mean(f['meanPrice'])), num(b['excessPrice'], 2)]
        rows.append(row)
        if f['problem'] or f['note']:
            notes.append('market %s: %s' % (r['market'], f['problem'] or f['note']))
    headers = ['market', 'mu (SE)'] + (['true mu'] if truth else []) + ['R2', 'days used', 'competitive', 'monopoly',
                                                                       'mean price', 'excess']
    out(table(headers, rows))
    if notes:
        out()
        out('Notes')
        for n in notes:
            out('  ' + n)
    if cal['truth']:
        out()
        out(calibration_summary(cal))
    if args.csv:
        flat = []
        for r in cal['markets']:
            f, b = r['fit'], r['benchmark']
            flat.append({
                'market': r['market'], 'usable': int(f['usable']), 'mu': f['mu'], 'mu_se': f['muSe'],
                'true_mu': r.get('trueMu'), 'slope': f['slope'], 'slope_se': f['slopeSe'],
                'quality_a': f['quality'][0] if f['quality'] else None,
                'quality_b': f['quality'][1] if f['quality'] else None, 'r2': f['r2'], 'days_used': f['days'],
                'days_dropped': f['dropped'],
                'competitive_a': b['competitive'][0] if b['competitive'] else None,
                'competitive_b': b['competitive'][1] if b['competitive'] else None,
                'monopoly_a': b['monopoly'][0] if b['monopoly'] else None,
                'monopoly_b': b['monopoly'][1] if b['monopoly'] else None,
                'mean_price_a': f['meanPrice'][0], 'mean_price_b': f['meanPrice'][1],
                'excess_price': b['excessPrice'], 'problem': f['problem'] or f['note'] or '',
            })
        write_csv(args.csv, flat)
    return 0


# ------------------------------------------------------------ report

def cmd_report(args, ctx):
    if not (args.remedies or args.sweep or args.screen):
        raise CliError('report needs at least one of --remedies, --sweep and --screen')
    parts = {
        'remedies': read_json(args.remedies, 'remedies') if args.remedies else None,
        'sweep': read_json(args.sweep, 'sweep') if args.sweep else None,
        'screen': read_json(args.screen, 'screen') if args.screen else None,
    }
    html = report.build_report(command=ctx['command'], **parts)
    _parent(args.out)
    with open(args.out, 'w', encoding='utf-8') as f:
        f.write(html)
    names = [k for k, v in parts.items() if v]
    if parts['screen'] and parts['screen'].get('results', {}).get('calibration'):
        names.append('calibration')
    names = ' and '.join([', '.join(names[:-1]), names[-1]]) if len(names) > 1 else names[0]
    out('Wrote %s (%s KB) with the %s results.' % (args.out, max(1, round(len(html.encode('utf-8')) / 1024)), names))
    return 0


# ------------------------------------------------------------ parser

def _model_options(p):
    p.add_argument('--preset', choices=sorted(PRESETS), default='textbook',
                   help='start from one of the browser app\'s presets (default textbook)')
    p.add_argument('--set', action='extend', nargs='+', metavar='KEY=VALUE',
                   help='change a setting, e.g. --set mu=0.5 firmTypes=learn,nash (numbers, true/false, comma lists)')


def _jobs(p):
    p.add_argument('--jobs', type=int, default=None, metavar='N',
                   help='worker processes (default: one per CPU; 1 runs everything in this process)')


def make_parser():
    p = _Parser(prog='python -m quiet_cartel', description=__doc__.split('\n\n')[0])
    sub = p.add_subparsers(dest='command', metavar='command')
    sub.required = True

    t = sub.add_parser('train', help='one training run, explained')
    _model_options(t)
    t.add_argument('--seed', type=int, default=None, help='random seed for training (default 1)')
    t.add_argument('--json', metavar='PATH', help='save the run as JSON')
    t.set_defaults(func=cmd_train)

    r = sub.add_parser('remedies', help='compare the remedies with the baseline over many runs')
    _model_options(r)
    r.add_argument('--runs', type=int, default=10, help='runs per option, seeds 1 to N (default 10)')
    r.add_argument('--scenarios', metavar='ID,ID', help='options to run (default all: %s)' % ', '.join(
        sc['id'] for sc in model.SCENARIOS))
    _jobs(r)
    r.add_argument('--csv', metavar='PATH', help='save one row per run as CSV')
    r.add_argument('--json', metavar='PATH', help='save the runs and the summary as JSON (for report)')
    r.set_defaults(func=cmd_remedies)

    w = sub.add_parser('sweep', help='a grid of two settings')
    _model_options(w)
    w.add_argument('--x', required=True, metavar='PARAM=V1,V2', help='setting across the columns, e.g. mu=0.1,0.25,0.5')
    w.add_argument('--y', required=True, metavar='PARAM=V1,V2', help='setting down the rows, e.g. delta=0.5,0.8,0.95')
    w.add_argument('--runs', type=int, default=3, help='runs per cell, seeds 1 to N (default 3)')
    w.add_argument('--scenario', default='baseline', choices=[sc['id'] for sc in model.SCENARIOS],
                   help='scenario applied in every cell (default baseline)')
    _jobs(w)
    w.add_argument('--csv', metavar='PATH', help='save one row per cell as CSV')
    w.add_argument('--json', metavar='PATH', help='save the grid as JSON (for report)')
    w.set_defaults(func=cmd_sweep)

    s = sub.add_parser('screen', help='screen a file of daily prices for signs of coordination')
    s.add_argument('path', help='CSV with day, price_a, price_b and optionally market, cost_a, cost_b, shoppers, '
                                'units_a, units_b')
    s.add_argument('--truth', metavar='PATH', help='CSV of the hidden truth, to score the screens')
    s.add_argument('--reps', type=int, default=999, help='circular shifts in each permutation test (default 999)')
    s.add_argument('--tol', type=float, default=0.005, help='price moves smaller than this share count as still '
                                                            '(default 0.005)')
    _jobs(s)
    s.add_argument('--csv', metavar='PATH', help='save one row per market as CSV')
    s.add_argument('--json', metavar='PATH', help='save everything as JSON (for report)')
    s.set_defaults(func=cmd_screen)

    c = sub.add_parser('calibrate', help='fit the demand model to daily sales')
    c.add_argument('path', help='CSV with day, price_a, price_b, shoppers, units_a, units_b (and costs for the index)')
    c.add_argument('--truth', metavar='PATH', help='CSV of the hidden truth, to check the fit')
    c.add_argument('--csv', metavar='PATH', help='save one row per market as CSV')
    c.set_defaults(func=cmd_calibrate)

    o = sub.add_parser('report', help='build one offline HTML report from saved JSON results')
    o.add_argument('--out', required=True, metavar='PATH', help='HTML file to write')
    o.add_argument('--remedies', metavar='JSON', help='from remedies --json')
    o.add_argument('--sweep', metavar='JSON', help='from sweep --json')
    o.add_argument('--screen', metavar='JSON', help='from screen --json')
    o.set_defaults(func=cmd_report)
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ctx = {'start': time.time(), 'command': 'python -m quiet_cartel ' + ' '.join(shlex.quote(a) for a in argv)}
    try:
        args = make_parser().parse_args(argv)
        if getattr(args, 'jobs', None) is not None and args.jobs < 1:
            raise CliError('--jobs must be at least 1')
        status = args.func(args, ctx)
    except SystemExit as e:                 # --help
        return e.code if isinstance(e.code, int) else 0
    except BrokenPipeError:
        # The reader went away (for example "| head"): stop quietly, as other command-line tools do.
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError, AttributeError):
            pass
        return 1
    except ConfigErrors as e:
        for message in e.args[0]:
            err('error: ' + message)
        return 2
    except CliError as e:
        err('error: %s' % e)
        return 2
    except OSError as e:
        err('error: %s: %s' % (e.filename or 'file', e.strerror or e))
        return 2
    except UnicodeDecodeError:
        err('error: the file is not UTF-8 text')
        return 2
    except (ValueError, csv.Error) as e:
        err('error: %s' % e)
        return 2
    except KeyboardInterrupt:
        err('stopped')
        return 130
    err('Took %.1f s.' % (time.time() - ctx['start']))
    return status
