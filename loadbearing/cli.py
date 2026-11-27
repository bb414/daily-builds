"""The command line: `python -m loadbearing COMMAND`. Run `python -m loadbearing --help` for the commands.

This module is glue: it reads arguments and files, calls the model and the experiment modules, and prints
plain-text tables. The simulation commands share the browser app's settings and defaults (rest anyone flagged
by the risk model).
"""
import argparse
import json
import math
import os
import sys
import textwrap
from decimal import ROUND_HALF_UP, Decimal

from . import calibrate, experiments, model, report
from .report import FLAG_PHRASE, METRIC_LABELS, POLICY_SHORT, finite, fmt, interval, ordinal, pct, plural, signed

APP_SEASON_SEED = 6
LOGBOOK_HEADER = ['date', 'player', 'position', 'session', 'minutes', 'rpe', 'injury']
RATIOS_HEADER = ['date', 'player', 'acute_7d', 'chronic_weekly', 'ratio_coupled', 'ratio_uncoupled', 'ratio_ewma',
                 'monotony', 'strain']
WIDTH = 100
THURSDAY = 3  # the weekday the lights are read
POSITIONS = {g['id']: g['label'] for g in model.GROUPS}


class CommandError(Exception):
    """A problem with the input, reported as one line on standard error with exit code 2."""


# ---------- text output ----------
def text_table(headers, rows, right=None):
    """An aligned plain-text table; right holds the right-aligned columns (default all but the first)."""
    cells = [[str(c) for c in headers]] + [[str(c) for c in r] for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(headers))]
    right = set(range(1, len(headers))) if right is None else set(right)

    def line(r):
        return '  '.join(c.rjust(w) if i in right else c.ljust(w) for i, (c, w) in enumerate(zip(r, widths))).rstrip()

    return '\n'.join([line(cells[0]), '  '.join('-' * w for w in widths)] + [line(r) for r in cells[1:]])


def key_values(pairs):
    """Label and value pairs, the values lined up and wrapped beside their labels."""
    width = max(len(k) for k, _ in pairs) + 2
    return '\n'.join(textwrap.fill(str(v), WIDTH, initial_indent=k.ljust(width), subsequent_indent=' ' * width)
                     for k, v in pairs)


def heading(text):
    return f'\n{text}\n{"-" * len(text)}'


def wrap(text):
    return textwrap.fill(text, WIDTH)


def say(*blocks):
    """Prints blocks of text, one after the other."""
    for b in blocks:
        print(b)


# ---------- files ----------
def _ensure_parent(path):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)


def json_ready(obj):
    """A copy with NaN and the infinities as None (JSON has no such numbers) and tuples as lists."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): json_ready(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_ready(v) for v in obj]
    return obj


def write_text(path, text):
    """Writes text to path exactly as given, creating parent folders."""
    try:
        _ensure_parent(path)
        with open(path, 'w', encoding='utf-8', newline='') as fh:
            fh.write(text)
    except OSError as e:
        raise CommandError(f'could not write {path}: {e.strerror or e}') from e


def save(path, text, note=''):
    """write_text() and a line saying so."""
    write_text(path, text)
    print(f'Wrote {path}{note}')


def write_json(path, obj):
    if path:
        save(path, json.dumps(json_ready(obj), indent=1, allow_nan=False) + '\n')


def blank_if(*paths):
    """A blank line before the list of files written, when there are any."""
    if any(paths):
        print()


def read_csv(path, what):
    """The rows of a CSV file (commas, semicolons or tabs); unreadable files raise CommandError."""
    try:
        with open(path, 'rb') as fh:
            raw = fh.read()
    except OSError as e:
        raise CommandError(f'could not read the {what} {path}: {e.strerror or e}') from e
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = raw.decode('latin-1')
        print(f'warning: {path} is not UTF-8, so it was read as Latin-1', file=sys.stderr)
    return model.parse_csv(text)


def read_book(path):
    """A logbook read with model.read_logbook; its error becomes a CommandError, its warnings are printed."""
    book = model.read_logbook(read_csv(path, 'logbook'))
    if 'error' in book:
        raise CommandError(f'{path}: {book["error"]}')
    for w in book['warnings']:
        print(f'warning: {w}', file=sys.stderr)
    return book


def js_fixed(x, digits):
    """Number.prototype.toFixed: the exact binary value rounded half away from zero, as the app writes it."""
    if not finite(x):
        return 'NaN' if x != x else 'Infinity' if x > 0 else '-Infinity'
    return format(Decimal(x).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP), 'f')


# ---------- argument types ----------
def ranged(kind, lo, hi):
    """An argparse type: a number of the given kind between lo and hi."""
    def parse(text):
        try:
            v = kind(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f'{text!r} is not a {"whole " if kind is int else ""}number')
        if not lo <= v <= hi:
            raise argparse.ArgumentTypeError(f'{text} is outside {lo} to {hi}')
        return v
    return parse


def int_list(text):
    """An argparse type: whole numbers separated by commas."""
    try:
        return [int(t) for t in text.split(',') if t.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError(f'{text!r} is not a list of whole numbers such as 4,8,16')


def number_list(text):
    """An argparse type: numbers separated by commas."""
    try:
        values = [float(t) for t in text.split(',') if t.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError(f'{text!r} is not a list of numbers such as 1.3,1.5,1.8')
    if not values:
        raise argparse.ArgumentTypeError('give at least one value')
    return values


def sweep_param(text):
    """An argparse type: a sweepable setting, in camelCase (contactScale) or with hyphens (contact-scale)."""
    name = ''.join(part if k == 0 else part.capitalize() for k, part in enumerate(text.split('-')))
    if name not in experiments.SWEEP_PARAMS:
        raise argparse.ArgumentTypeError(f'{text!r} is not one of {", ".join(experiments.SWEEP_PARAMS)}')
    return name


SEEDS = ranged(int, 0, 2 ** 32 - 1)
COUNT = ranged(int, 1, 100000)


def settings_parser():
    """The settings every simulation command accepts."""
    D = model.DEFAULTS
    p = argparse.ArgumentParser(add_help=False)
    g = p.add_argument_group('season settings (defaults as in the browser app)')
    g.add_argument('--policy', choices=model.POLICIES, default='rest',
                   help='how the coach uses the light: none ignores it, rest sits flagged players out, modify cuts '
                        'their training, rotate and readiness ignore it and pick by other rules (default rest)')
    g.add_argument('--flag', choices=model.FLAGS, default='model',
                   help='which warning light: coupled, uncoupled or ewma workload ratios, the trained risk model, '
                        'or the perfect-knowledge oracle (default model)')
    g.add_argument('--threshold', type=ranged(float, 1, 3), metavar='RATIO',
                   help=f"ratio lights fire at this workload ratio, 1 to 3 (default {D['threshold']})")
    g.add_argument('--budget', type=ranged(float, 1, 50), metavar='PERCENT',
                   help=f"model and oracle lights flag the riskiest PERCENT of player-weeks, 1 to 50 "
                        f"(default {D['budget']})")
    g.add_argument('--preseason', choices=['gradual', 'steep'], help='how pre-season training builds up '
                                                                     '(default gradual)')
    g.add_argument('--intensity', type=ranged(float, 0.7, 1.3), metavar='X',
                   help=f"multiplies the effort of every training session, 0.7 to 1.3 (default {D['intensity']})")
    g.add_argument('--no-graded-return', action='store_true',
                   help='skip the ten days of modified training after an injury')
    g.add_argument('--spike', type=ranged(float, 0, 4), metavar='X',
                   help=f"the hidden truth: how strongly a load spike raises soft-tissue risk, 0 to 4 "
                        f"(default {D['spike']})")
    g.add_argument('--contact-scale', type=ranged(float, 0, 3), metavar='X',
                   help=f"the hidden truth: multiplies the contact injury rate, 0 to 3 (default {D['contactScale']})")
    g.add_argument('--squad-seed', type=SEEDS, metavar='N', help=f"which invented squad (default {D['squadSeed']})")
    g.add_argument('--history-seasons', type=ranged(int, 1, 6), metavar='N',
                   help=f"past seasons the risk model learns from, 1 to 6 (default {D['historySeasons']})")
    return p


def settings_from(args):
    """Full model settings from the parsed arguments."""
    return model.with_defaults({
        'policy': args.policy, 'flag': args.flag, 'threshold': args.threshold, 'budget': args.budget,
        'preseason': args.preseason, 'intensity': args.intensity,
        'gradedReturn': False if args.no_graded_return else None, 'spike': args.spike,
        'contactScale': args.contact_scale, 'squadSeed': args.squad_seed, 'historySeasons': args.history_seasons,
    })


def describe(S):
    """'rest anyone flagged, using the risk model (the AI)'."""
    policy, light = POLICY_SHORT[S['policy']].lower(), FLAG_PHRASE[S['flag']]
    if S['policy'] in ('rest', 'modify'):
        return f'{policy}, using the {light}'
    return f'{policy}; the {light} lights up but nobody acts on it'


# ---------- season ----------
def season_date(day):
    """The date of a season day (day 0 is the Monday of pre-season week 1)."""
    return model.format_day(model.SEASON_START + model.HIST + day)


def final_text(res):
    m = res['matches'][-1]
    return 'drew' if m['result'] == 'D' else f"{'won' if m['result'] == 'W' else 'lost'} by {abs(m['margin'])}"


def flag_record(res, S):
    """What happened to the flags of one season: raised, acted on, and followed by a soft-tissue injury."""
    hits = 0
    for wk in res['weekly']:
        start = wk['week'] * 7 + THURSDAY
        for pid in wk['flags']:
            if any(i['player'] == pid and i['type'] == 'nc' and start <= i['day'] <= start + 6
                   for i in res['injuries']):
                hits += 1
    coach = model.coach_view(res)
    acted = res['flagsRaised'] if S['policy'] in ('rest', 'modify') else 0
    return {'raised': res['flagsRaised'], 'fitPlayerWeeks': res['flagWeeks'], 'actedOn': acted,
            'followedBySoftTissue': hits, 'quietFortnights': coach['quiet'] if acted else 0,
            'matchesSatOut': res['rests'], 'forcedPlays': res['forcedPlays']}


def season_summary(res, squad):
    m = res['matches'][-1]
    out = {k: res[k] for k in ('injuriesTotal', 'nc', 'contact', 'inMatch', 'daysLost', 'position', 'points',
                               'wins', 'draws', 'losses', 'finalWon', 'finalBestXV', 'flagsRaised', 'rests',
                               'forcedPlays')}
    out.update(finalResult=m['result'], finalMargin=m['margin'],
               finalOpponent=squad['opponents'][m['opponent']]['name'])
    return out


def action_text(S):
    if S['policy'] == 'rest':
        return f"each flagged player sat out that week's match and kept {pct(S['restTraining'])} of his training"
    if S['policy'] == 'modify':
        return 'each flagged player trained at 60% that week but stayed available'
    if S['policy'] == 'none':
        return 'nobody acts on the light'
    return 'this policy picks by its own rule and ignores the light'


def cmd_season(args):
    S = settings_from(args)
    S['seasonSeed'] = args.seed
    ctx = model.prepare(S)
    squad, players = ctx['squad'], ctx['squad']['players']
    res = model.run_season(S)
    base = model.run_season(dict(S, policy='none')) if S['policy'] != 'none' else None
    flags = flag_record(res, S)
    say(f'Season {args.seed} at {model.CLUB}: {describe(S)}', wrap(f'Settings: {report.settings_line(S)}.'))

    def row(label, key, show=str, diff=lambda a, b: signed(a - b, 0)):
        cells = [label, show(res[key])]
        if base:
            cells += [show(base[key]), diff(res[key], base[key])]
        return cells

    def places(a, b):
        return 'same' if a == b else f"{plural(abs(a - b), 'place')} {'lower' if a > b else 'higher'}"

    def record(r):
        return f"{r['wins']}-{r['draws']}-{r['losses']}"

    rows = [row('Injuries', 'injuriesTotal'), row('  soft-tissue', 'nc'), row('  contact', 'contact'),
            row('Days lost', 'daysLost', lambda v: fmt(v, 0)), row('League position', 'position', ordinal, places),
            row('League points', 'points'),
            ['Won-drawn-lost', record(res)] + ([record(base), ''] if base else []),
            [f"Cup final v {squad['opponents'][res['matches'][-1]['opponent']]['name']}", final_text(res)] +
            ([final_text(base), ''] if base else []),
            row('First-choice XV in the final', 'finalBestXV', lambda v: f'{v} of 15'),
            row('Matches sat out', 'rests')]
    headers = ['', 'This season'] + (['Light ignored', 'Difference'] if base else [])
    say('', text_table(headers, rows))
    if base:
        say(wrap('Light ignored: the same season with the same luck, picking the best team and ignoring the light. '
                 'Only a simulation can replay a season like this.'))
    else:
        say('This season already ignores the light, so there is nothing to replay.')
    per100 = 100 * flags['followedBySoftTissue'] / flags['raised'] if flags['raised'] else math.nan
    say(heading('The light'), key_values([
        ('Flags raised', f"{fmt(flags['raised'], 0)} of {fmt(flags['fitPlayerWeeks'], 0)} fit player-weeks "
                         f"({pct(flags['raised'] / max(1, flags['fitPlayerWeeks']), 1)})"),
        ('Acted on', f"{fmt(flags['actedOn'], 0)}: {action_text(S)}"),
        ('Followed by a soft-tissue injury', f"{fmt(flags['followedBySoftTissue'], 0)} within the week "
                                             f"({fmt(per100, 1)} per 100 flags)"),
        ("Coach's view", f"{fmt(flags['quietFortnights'], 0)} of {fmt(flags['actedOn'], 0)} acted-on flags were "
                         'followed by a quiet fortnight' if flags['actedOn'] else 'no flags were acted on'),
        ('Flagged but had to play', f"{fmt(flags['forcedPlays'], 0)} (nobody else was fit)"),
    ]))
    injuries = [{'date': season_date(i['day']), 'player': players[i['player']]['name'],
                 'position': POSITIONS[players[i['player']]['group']],
                 'type': 'soft-tissue' if i['type'] == 'nc' else 'contact', 'setting': i['setting'],
                 'daysOut': i['days'], 'recurrence': i['recurrence']} for i in res['injuries']]
    say(heading(f"Injuries ({res['injuriesTotal']})"),
        text_table(['Date', 'Player', 'Position', 'Type', 'Setting', 'Days out', 'Recurrence'],
                   [[i['date'], i['player'], i['position'], i['type'], i['setting'], i['daysOut'],
                     'yes' if i['recurrence'] else ''] for i in injuries], right=[5]))
    say(heading('Final league table'),
        text_table(['Pos', 'Club', 'Points', 'Points diff'],
                   [[r['position'], r['name'] + (' <' if r['us'] else ''), r['points'], signed(r['diff'], 0)]
                    for r in res['table']], right=[0, 2, 3]))
    matches = [{'week': m['week'] + 1, 'date': season_date(m['day']), 'match': m['label'],
                'opponent': squad['opponents'][m['opponent']]['name'],
                'venue': 'neutral' if m['home'] is None else 'home' if m['home'] else 'away', 'result': m['result'],
                'margin': m['margin'], 'points': m['points'], 'rating': m['rating'], 'oppRating': m['oppRating'],
                'firstChoiceXV': m['bestXVPlaying']} for m in res['matches']]
    blank_if(args.matches_csv, args.logbook, args.json)
    if args.matches_csv:
        save(args.matches_csv, model.to_csv(
            ['week', 'date', 'match', 'opponent', 'venue', 'result', 'margin', 'points', 'our_rating',
             'opponent_rating', 'first_choice_xv'],
            [[m['week'], m['date'], m['match'], m['opponent'], m['venue'], m['result'], m['margin'], m['points'],
              f"{m['rating']:.2f}", f"{m['oppRating']:.2f}", m['firstChoiceXV']] for m in matches]))
    if args.logbook:
        lb = model.season_logbook(S, args.seed)
        save(args.logbook, model.to_csv(LOGBOOK_HEADER, [[r[k] for k in LOGBOOK_HEADER] for r in lb['rows']]),
             f' ({fmt(len(lb["rows"]), 0)} sessions)')
    summary, baseline = season_summary(res, squad), season_summary(base, squad) if base else None
    write_json(args.json, {
        'settings': S, 'seed': args.seed, 'summary': summary, 'flags': flags, 'baseline': baseline,
        'difference': {k: summary[k] - baseline[k] for k in ('injuriesTotal', 'nc', 'contact', 'daysLost',
                                                              'position', 'points', 'rests')} if base else None,
        'injuries': injuries, 'matches': matches, 'table': res['table']})
    return 0


# ---------- flags ----------
def cmd_inquest(args):
    S = settings_from(args)
    S['seasonSeed'] = args.seed
    out = model.inquest(S, args.seed)
    sm = out['summary']
    light = model.FLAG_LABELS[S['flag']]
    say(f'The inquest: every injury of season {args.seed} at {model.CLUB}',
        wrap(f'Settings: {report.settings_line(S)}. Each injury\'s true risk that day is split into its hidden '
             'factors (against an average player in a typical session); "the light" is what it said the Thursday '
             'before; "a rest" replays the season with only that player rested that week, on the same luck.'))
    rows = []
    for it in out['items']:
        lights = it['lights']
        said = ''
        if lights:
            said = ('flagged' if lights[S['flag']]['fired'] else 'quiet') + f", riskier than {pct(lights[S['flag']]['rank'])}"
        rest = '' if it['avoided'] is None else 'avoided' if it['avoided'] else 'still injured'
        rows.append([season_date(it['day']), it['name'], 'soft-tissue' if it['type'] == 'nc' else 'contact',
                     it['setting'], it['days'], model.FACTOR_LABELS.get(it['explain']['main'], 'luck'),
                     f"{fmt(it['explain']['personal'], 1)}x", said, rest])
    say('', text_table(['Date', 'Player', 'Type', 'Setting', 'Days out', 'Main factor', 'Personal risk',
                        f'The light ({light})', 'A rest that week'], rows, right=[4, 6]))
    say(heading('Summary'), key_values([
        ('Soft-tissue injuries', f"{sm['nc']}: the light flagged {sm['ncFlagged']} beforehand; a rest that week "
                                 f"would have avoided {sm['ncAvoidable']} of the {sm['ncChecked']} that had a Thursday before them"),
        ('Contact injuries', f"{sm['contact']}: flagged {sm['contactFlagged']}; a rest would have avoided "
                             f"{sm['contactAvoidable']} of {sm['contactChecked']}"),
        ('Main factors', ', '.join(f"{model.FACTOR_LABELS.get(k, 'luck').lower()} {v}"
                                   for k, v in sorted(sm['mainCauses'].items(), key=lambda kv: (-kv[1], kv[0])))),
    ]))
    say(wrap('In plain English: hindsight makes almost every injury look preventable, because resting a player for '
             'the week he was hurt nearly always avoids it. The light\'s job is to know which week in advance, and '
             f"it flagged {sm['ncFlagged'] + sm['contactFlagged']} of {sm['nc'] + sm['contact']} injuries beforehand."))
    blank_if(args.json)
    write_json(args.json, {'settings': S, **out})
    return 0


LIGHT_NAMES = {'coupled': 'coupled ratio', 'uncoupled': 'uncoupled ratio', 'ewma': 'EWMA ratio', 'model': 'risk model',
               'oracle': 'perfect knowledge'}


def option_label(r):
    """A plain name for one trade-off option."""
    if r['policy'] == 'none':
        return 'Pick the best, ignore the light'
    if r['policy'] in ('rest', 'modify'):
        level = fmt(r['level'], 1) if r['flag'] in ('coupled', 'uncoupled', 'ewma') else f"{r['level']}%"
        verb = 'Rest the flagged' if r['policy'] == 'rest' else 'Cut training'
        return f"{verb}, {LIGHT_NAMES[r['flag']]} at {level}"
    if r['policy'] == 'rotate':
        return f"Rotate after {r['level']} starts"
    return 'Pick on readiness'


def break_even_text(b, r):
    if r['policy'] == 'none':
        return 'reference'
    if b['kind'] in ('always', 'never'):
        return 'any rate' if b['kind'] == 'always' else 'never'
    return f"{'under' if b['kind'] == 'below' else 'over'} {plural(round(b['value']), 'day')} a point"


def cmd_optimise(args):
    S = settings_from(args)
    seeds = [100 + k for k in range(1, args.seasons + 1)]
    out = experiments.run_optimise(S, seeds, args.all_lights, args.workers)
    rows, lam = out['rows'], args.point_value
    what = 'all five lights' if args.all_lights else model.FLAG_LABELS[S['flag']].lower()
    say(f'The trade-off: every option for {what} over {len(seeds)} seasons (seeds {seeds[0]} to {seeds[-1]})',
        wrap(f'Settings: {report.settings_line(S)}. Each option plays the same seasons with the same luck; changes '
             f'are against picking the best and ignoring the light. Value = player-days saved + {fmt(lam, 0)} x '
             'points gained, a season (a league point taken as worth that many player-days lost).'))
    ranked = sorted(rows, key=lambda r: (-(-r['dDays'] + lam * r['dPoints']), option_label(r)))
    table = [[option_label(r), signed(-r['dDays'] + lam * r['dPoints'], 0), signed(r['dInjuries'], 1),
              signed(r['dDays'], 0), signed(r['dPoints'], 1), signed(r['dFinal'], 1),
              break_even_text(r['breakEven'], r), 'yes' if r['frontier'] else ''] for r in ranked]
    say('', text_table(['Option', 'Value', 'Injuries', 'Days lost', 'Points', 'Best XV in final', 'Pays when',
                        'Efficient'], table, right=[1, 2, 3, 4, 5]))
    best = ranked[0]
    switch = []
    previous = None
    for value in range(0, 61):
        idx = model.best_option(rows, value)['index']
        if idx != previous:
            switch.append((value, option_label(rows[idx])))
            previous = idx
    say(heading('Best option by the worth of a league point'),
        key_values([(f'From {v} player-days', label) for v, label in switch]))
    say(wrap(f'In plain English: if a league point is worth {fmt(lam, 0)} player-days of injury, the best option is '
             f'"{option_label(best).lower()}" ({signed(best["dDays"], 0)} days lost, {signed(best["dPoints"], 1)} '
             f'points a season). {sum(1 for r in rows if r["frontier"])} of {len(rows)} options are efficient.'))
    blank_if(args.csv, args.json)
    if args.csv:
        save(args.csv, model.to_csv(
            ['option', 'policy', 'flag', 'level', 'value', 'd_injuries', 'd_soft_tissue', 'd_days_lost', 'd_days_lo',
             'd_days_hi', 'd_points', 'd_points_lo', 'd_points_hi', 'd_first_choice_xv_in_final', 'break_even_kind',
             'break_even_days_per_point', 'efficient'],
            [[option_label(r), r['policy'], r['flag'] or '', '' if r['level'] is None else r['level'],
              f"{-r['dDays'] + lam * r['dPoints']:.2f}", f"{r['dInjuries']:.3f}", f"{r['dNC']:.3f}",
              f"{r['dDays']:.2f}", f"{r['daysCI'][0]:.2f}", f"{r['daysCI'][1]:.2f}", f"{r['dPoints']:.3f}",
              f"{r['pointsCI'][0]:.3f}", f"{r['pointsCI'][1]:.3f}", f"{r['dFinal']:.3f}", r['breakEven']['kind'],
              '' if r['breakEven']['value'] is None else f"{r['breakEven']['value']:.2f}",
              'yes' if r['frontier'] else 'no'] for r in ranked]))
    write_json(args.json, {'settings': S, 'pointValue': lam, **out})
    return 0


def setting_text(key, v):
    """A short phrase for one assumption's setting."""
    if key == 'spike':
        return f'spikes {fmt(v, 1)}'
    if key in ('contactScale', 'intensity', 'restTraining'):
        return f"{round(v * 100)}% {dict(contactScale='contact', intensity='effort', restTraining='kept')[key]}"
    if key == 'historySeasons':
        return plural(v, 'season')
    if key == 'preseason':
        return 'full load' if v == 'steep' else 'build up'
    if key == 'gradedReturn':
        return 'graded' if v else 'straight back'
    return str(v)


def pays_text(b):
    if b['kind'] in ('always', 'never'):
        return 'at any rate' if b['kind'] == 'always' else 'never'
    return f"{'under' if b['kind'] == 'below' else 'over'} {plural(round(b['value']), 'day')} a point"


def cmd_robustness(args):
    S = settings_from(args)
    seeds = [200 + k for k in range(1, args.seasons + 1)]
    rb = model.robustness(S, seeds)
    light = model.FLAG_LABELS[rb['flag']]
    say(f'The hidden truth: would the verdict survive? {light}, {POLICY_SHORT[rb["policy"]].lower()}, '
        f'{len(seeds)} seasons (seeds {seeds[0]} to {seeds[-1]})',
        wrap(f'Settings: {report.settings_line(S)}. Each assumption is pushed low and high, one at a time. Each '
             'version plays the seasons twice on the same luck, acting on the light and ignoring it; the AUC comes '
             'from the seasons that ignore it.'))

    def cells(e):
        return [fmt(e['auc'], 3), fmt(-e['dNC'], 1), fmt(-e['dDays'], 0), signed(e['dPoints'], 1), pays_text(e['breakEven'])]
    rows = [['As set', ''] + cells(rb['base'])]
    for r in rb['rows']:
        name = r['label'] + (' (hidden)' if r['hidden'] else '')
        rows.append([name, setting_text(r['key'], r['lowValue'])] + cells(r['low']))
        rows.append(['', setting_text(r['key'], r['highValue'])] + cells(r['high']))
    say('', text_table(['Assumption', 'Setting', 'AUC', 'Soft-tissue saved', 'Days saved', 'Points', 'Pays'], rows,
                       right=[2, 3, 4, 5]))
    lam = args.point_value
    variants = [rb['base']] + [e for r in rb['rows'] for e in (r['low'], r['high'])]
    pays = sum(1 for e in variants if -e['dDays'] + lam * e['dPoints'] > 0)

    def swing(r):
        a, b = r['low']['breakEven']['value'], r['high']['breakEven']['value']
        return abs((b or 0) - (a or 0))
    biggest = max(rb['rows'], key=swing)
    spike = next(r for r in rb['rows'] if r['key'] == 'spike')
    hist = next(r for r in rb['rows'] if r['key'] == 'historySeasons')
    out = {'settings': S, 'pointValue': lam, 'robustness': rb}
    if args.map:
        mp = model.robustness_map(S, seeds)
        out['map'] = mp
        grid = []
        for c in reversed(mp['contacts']):
            line = [f'{round(c * 100)}% contact']
            for sp in mp['spikes']:
                cell = next(x for x in mp['cells'] if x['spike'] == sp and x['contactScale'] == c)
                b = cell['breakEven']
                line.append(fmt(b['value'], 0) if b['kind'] == 'below' else b['kind'])
            grid.append(line)
        say(heading('Pays below (player-days a league point), by spike effect and contact rate'),
            text_table([''] + [f'spikes {fmt(sp, 0)}' for sp in mp['spikes']], grid,
                       right=list(range(1, len(mp['spikes']) + 1))))
    say(wrap(f"In plain English: the light's AUC runs from {fmt(spike['low']['auc'], 2)} to "
             f"{fmt(spike['high']['auc'], 2)} as load spikes matter less or more, and the soft-tissue injuries saved "
             f"from {fmt(-spike['low']['dNC'], 1)} to {fmt(-spike['high']['dNC'], 1)} a season. Trained on one season the "
             f"risk model scores {fmt(hist['low']['auc'], 2)}, on five {fmt(hist['high']['auc'], 2)}. The break-even "
             f"worth of a point moves most with: {biggest['label'].lower()}. Acting on the light beats doing nothing "
             f"at {fmt(lam, 0)} player-days a point in {pays} of {len(variants)} versions."))
    blank_if(args.json)
    write_json(args.json, out)
    return 0


def cmd_flags(args):
    S = settings_from(args)
    seeds = experiments.flag_seeds(args.seasons)
    ev = model.evaluate_flags(S, seeds)
    headers, rows = report.flags_table(ev, S)
    say(f"Warning lights over {plural(args.seasons, 'silent season')} (seeds {seeds[0]} to {seeds[-1]})",
        wrap(f'Settings: {report.settings_line(S)}. Nobody acts on any flag, so every light is scored against the '
             'same soft-tissue injuries.'), '', text_table(headers, rows),
        wrap(f"Rules: ratio lights fire at {fmt(S['threshold'], 2)}; the model and the oracle flag the riskiest "
             f"{fmt(S['budget'], 0)}% on past seasons. One season: the middle 80% of single-season AUCs. The last "
             f"column flags the riskiest {fmt(S['budget'], 0)}% for every light, a like-for-like comparison."), '')
    t = ev['totals']
    say(key_values([
        ('Player-weeks scored', fmt(ev['rows'], 0)),
        ('Soft-tissue injury within the week', pct(ev['baseRate'], 2)),
        ('Injuries', f"{fmt(t['injuries'], 0)} ({fmt(t['nc'], 0)} soft-tissue, {fmt(t['contact'], 0)} contact)"),
        ('Contact share', f"{pct(ev['contactShare'])}, which no load figure can foresee"),
        ('Risk model trained on', f"{fmt(ev['historyRows'], 0)} player-weeks from "
                                  f"{plural(S['historySeasons'], 'past season')}, with "
                                  f"{plural(ev['historyInjuries'], 'soft-tissue injury', 'soft-tissue injuries')}"),
    ]), '', wrap('In plain English: ' + report.flags_summary(ev, S)))
    blank_if(args.json)
    write_json(args.json, {'settings': S, 'result': ev})
    return 0


# ---------- compare ----------
COMPARE_METRICS = model.METRICS + ['finalWon']


def cmd_compare(args):
    S = settings_from(args)
    seeds = experiments.compare_seeds(args.seasons)
    cp = model.compare_policies(S, seeds)
    ref = cp['reference']
    rows = []
    for row in cp['table']:
        for k, m in enumerate(COMPARE_METRICS):
            v = row['metrics'][m]
            digits = 2 if m == 'finalWon' else 0 if m == 'daysLost' else 1
            rows.append([POLICY_SHORT[row['policy']] if k == 0 else '', METRIC_LABELS[m], fmt(v['mean'], digits),
                         ('reference' if k == 0 else '') if row['policy'] == ref else signed(v['diff'], digits),
                         '' if row['policy'] == ref else interval(v['lo'], v['hi'], digits)])
        rows.append([''] * 5)
    say(f"Five ways to manage the squad over {plural(args.seasons, 'season')} (seeds {seeds[0]} to {seeds[-1]})",
        wrap(f"Settings: {report.settings_line(S)}. Every policy plays the same seasons with the same luck; the "
             f"difference is paired with '{ref}' (pick the best, ignore the light) and its interval is a 95% "
             'bootstrap interval.'), '',
        text_table(['Policy', 'Metric', 'Mean', f'vs {ref}', '95% interval'], rows[:-1], right=[2, 3, 4]), '',
        wrap('In plain English: ' + report.compare_summary(cp)))
    blank_if(args.csv, args.json)
    if args.csv:
        out = []
        for row in cp['table']:
            for m in COMPARE_METRICS:
                v = row['metrics'][m]
                out.append([row['policy'], m, v['mean'], v['sd'], v['diff'], v['lo'], v['hi']])
        save(args.csv, model.to_csv(['policy', 'metric', 'mean', 'sd', 'diff', 'lo', 'hi'], out))
    write_json(args.json, {'settings': S, 'result': cp})
    return 0


# ---------- pilot ----------
def cmd_pilot(args):
    S = settings_from(args)
    ps = model.pilot_study(S, args.pairs)
    S = dict(S, policy=ps['policy'])
    needed = ps['seasonsNeeded']
    say(f"A one-season pilot: {describe(S)}; {plural(args.pairs, 'pair')} of seasons",
        wrap(f'Settings: {report.settings_line(S)}.'))
    if args.policy == 'none':
        say('Nobody acts on the light under policy none, so this pilots resting anyone flagged instead.')
    say('', key_values([
        ('Injuries in a normal season', f"{fmt(ps['baseMean'])}, varying by {fmt(ps['seasonSd'])} either way on luck"),
        ('True effect, same luck', f"{signed(ps['trueEffect'])} injuries a season "
                                   f"(95% interval {interval(*ps['trueEffectCI'])})"),
        ('  soft-tissue', signed(ps['trueNC'])),
        ('  days lost', signed(ps['trueDays'], 0)),
        ('What a pilot measures', f"{signed(ps['measuredMean'])} on average, spread (sd) {fmt(ps['measuredSd'])}"),
        ('Pilot looks better', f"{pct(ps['looksBetter'])} (fewer injuries than the season before)"),
        ('Pilot looks a big success', f"{pct(ps['looksGreat'])} (at least 20% fewer)"),
        ('Pilot looks worse', pct(ps['looksWorse'])),
        ('Seasons needed for 80% power', f"{fmt(needed, 0)} in each arm" if finite(needed) else 'never'),
        ('League points', f"{signed(ps['pointsEffect'])} a season (95% interval {interval(*ps['pointsCI'])})"),
        ('Matches sat out', f"{fmt(ps['matchesMissed'])} a season"),
    ]))
    marks = [p for p in ps['power'] if p['seasons'] in (1, 2, 5, 10, 20, 50, 100)]
    say(heading('Power of a fair comparison, by seasons in each arm'),
        text_table(['Seasons'] + [str(p['seasons']) for p in marks], [['Power'] + [pct(p['power']) for p in marks]]))
    say(heading("The coach's view"))
    if finite(ps['quietShare']):
        per = ps['actionsPerInjuryPrevented']
        say(key_values([
            ('Acted-on flags a season', fmt(ps['actionsPerSeason'], 0)),
            ('Followed by a quiet fortnight', pct(ps['quietShare'])),
            ('Acted-on flags per injury prevented', fmt(per, 0) if finite(per) else 'none prevented'),
        ]))
    else:
        say('This policy does not act on the light, so the coach sees nothing to credit.')
    say('', wrap('In plain English: ' + report.pilot_summary(ps)))
    blank_if(args.json)
    write_json(args.json, {'settings': S, 'result': ps})
    return 0


# ---------- trial ----------
def cmd_trial(args):
    S = settings_from(args)
    try:
        tr = experiments.run_trial(S, args.clubs, args.seasons_per_club, args.pool_clubs, args.pool_seasons,
                                   args.reps, args.seed, args.permutations, args.workers)
    except ValueError as e:
        raise CommandError(str(e)) from e
    S = dict(S, policy=tr['policy'])
    say(f'A cluster-randomised trial of {describe(S)}', wrap(f'Settings: {report.settings_line(S)}.'))
    if args.policy == 'none':
        say('Nobody acts on the light under policy none, so the trial tests resting anyone flagged instead.')
    q, s = tr['squadSeeds'], tr['seasonSeeds']
    say('', key_values([
        ('Pool', f"{plural(tr['poolClubs'], 'club')} (squad seeds {q[0]} to {q[-1]}) x "
                 f"{plural(tr['poolSeasons'], 'season')} (seeds {s[0]} to {s[-1]}), each club-season played "
                 'with and without the light on the same luck'),
        ('Without the light', f"{fmt(tr['meanWithout'])} injuries a club-season (sd {fmt(tr['sdWithout'])}; "
                              f"sd of club averages {fmt(tr['sdBetweenClubs'])})"),
        ('True pooled effect', f"{signed(tr['trueEffect'], 2)} injuries a club-season "
                               f"(95% interval {interval(*tr['trueEffectCI'], 2)})"),
        ('Each trial', f"half the clubs get the light at random for {plural(tr['seasonsPerClub'], 'season')}; "
                       'club mean injuries a season compared by a two-sided permutation test at 5%'),
        ('Trials per size', f"{fmt(tr['reps'], 0)} (seed {tr['seed']})"),
    ]), '')
    rows = [[r['clubs'], pct(r['power']), signed(r['meanEffect'], 2), fmt(r['sdEffect'], 2),
             f"exact, {fmt(r['assignments'], 0)} splits" if r['exact'] else f"{fmt(tr['permutations'], 0)} reshuffles",
             fmt(r['smallestP'], 3)] for r in tr['results']]
    say(text_table(['Clubs', 'Power', 'Mean estimate', 'Spread (sd)', 'Test', 'Smallest p'], rows,
                   right=[0, 1, 2, 3, 5]))
    never = [r['clubs'] for r in tr['results'] if r['smallestP'] > experiments.ALPHA]
    if never:
        say(wrap(f"With {', '.join(map(str, never))} clubs no split of the clubs can reach p = 0.05, so such a trial "
                 'can never succeed, whatever the light does.'))
    best = tr['results'][-1]
    say('', wrap(f"In plain English: the light changes injuries by {signed(tr['trueEffect'], 1)} a club-season. "
                 f"A trial of {best['clubs']} clubs for {plural(tr['seasonsPerClub'], 'season')} would detect that "
                 f"{pct(best['power'])} of the time, and its estimate would typically be off by "
                 f"{fmt(best['sdEffect'], 1)} either way."))
    blank_if(args.json)
    write_json(args.json, {'settings': S, 'result': tr})
    return 0


# ---------- sweep ----------
def cmd_sweep(args):
    S = settings_from(args)
    lo, hi = experiments.SWEEP_PARAMS[args.param]
    bad = [v for v in args.values if not lo <= v <= hi]
    if bad:
        raise CommandError(f"{args.param} must be between {lo} and {hi} (not {', '.join(fmt(v, 2) for v in bad)})")
    seeds = experiments.compare_seeds(args.seasons)
    sw = experiments.run_sweep(S, args.param, args.values, seeds, args.workers)
    S = dict(S, policy=sw['policy'])
    say(f'Sweep of {args.param}: {describe(S)}, against ignoring the light',
        wrap(f"Settings: {report.settings_line(S)}. {plural(args.seasons, 'season')} per value (seeds {seeds[0]} to "
             f"{seeds[-1]}), each played both ways on the same luck; differences are light minus no light, with 95% "
             'bootstrap intervals.'))
    inert = experiments.sweep_inert(args.param, S)
    if inert:
        say(f'Note: {inert}, so every row should match.')
    if args.policy == 'none':
        say('Nobody acts on the light under policy none, so the sweep tests resting anyone flagged instead.')
    metrics = experiments.SWEEP_METRICS
    names = {'injuriesTotal': 'Injuries', 'nc': 'Soft-tissue', 'daysLost': 'Days lost', 'points': 'Points'}
    rows = []
    for r in sw['rows']:
        cells = [fmt(r['value'], 2)]
        for m, _ in metrics:
            v, d = r['metrics'][m], 0 if m == 'daysLost' else 1
            cells.append(f"{signed(v['diff'], d)} [{signed(v['lo'], d)}, {signed(v['hi'], d)}]")
        rows.append(cells)
    say('', text_table([args.param] + [names[m] for m, _ in metrics], rows))
    say('', text_table([args.param] + [f'{names[m]}: none, light' for m, _ in metrics],
                       [[fmt(r['value'], 2)] + [f"{fmt(r['metrics'][m]['none'], 0 if m == 'daysLost' else 1)}, "
                                                f"{fmt(r['metrics'][m]['light'], 0 if m == 'daysLost' else 1)}"
                                                for m, _ in metrics] for r in sw['rows']]))
    blank_if(args.csv, args.json)
    if args.csv:
        header = ['param', 'value', 'seasons', 'policy', 'flag']
        for _, label in metrics:
            header += [f'{label}_none', f'{label}_light', f'{label}_diff', f'{label}_lo', f'{label}_hi']
        out = []
        for r in sw['rows']:
            cells = [args.param, r['value'], r['seasons'], sw['policy'], sw['flag']]
            for m, _ in metrics:
                v = r['metrics'][m]
                cells += [v['none'], v['light'], v['diff'], v['lo'], v['hi']]
            out.append(cells)
        save(args.csv, model.to_csv(header, out))
    write_json(args.json, {'settings': S, 'result': sw})
    return 0


# ---------- logbook ----------
def ratio_rows(an):
    """Every player's daily ratios as CSV rows, formatted as the app's download."""
    rows = []
    for se in an['series']:
        for t in range(an['span']):
            if not finite(se['coupled'][t]):
                continue
            rows.append([model.format_day(an['start'] + t), se['name'], js_fixed(se['acute'][t], 0),
                         js_fixed(se['chronic'][t], 0), js_fixed(se['coupled'][t], 3), js_fixed(se['uncoupled'][t], 3),
                         js_fixed(se['ewma'][t], 3), js_fixed(se['monotony'][t], 3), js_fixed(se['strain'][t], 0)])
    return rows


def cmd_logbook(args):
    book = read_book(args.path)
    opts = {'threshold': args.threshold, 'permutations': args.permutations, 'seed': args.seed}
    if args.only:
        opts['only'] = args.only
    an = model.analyse_logbook(book, opts)
    end = book['start'] + book['span'] - 1
    say(f'The logbook: {args.path}', key_values([
        ('Players', f"{fmt(len(book['names']), 0)}, {fmt(book['sessions'], 0)} sessions"),
        ('Dates', f"{model.format_day(book['start'])} to {model.format_day(end)} ({plural(book['span'], 'day')})"),
        ('Average week', f"{fmt(an['meanWeekly'], 0)} load per player (minutes x rpe)"),
        ('Injuries counted', f"{fmt(an['counted'], 0)} ({'all' if an['only'] == 'all' else 'soft-tissue only'}) of "
                             f"{fmt(an['injuries'], 0)} recorded"),
    ]))
    say(heading('Did the ratios see it coming?'),
        text_table(['Ratio', 'AUC', 'Chance by luck', f"Flagged at {fmt(an['threshold'], 2)}", 'Hits per 100 flags',
                    'Injuries caught'], report.scorecard_rows(an)),
        wrap(f"{fmt(an['rows'], 0)} player-weeks scored (one every seven days from day 28, leaving out a fortnight "
             f"after each injury), {plural(an['positives'], 'injured week')}. Chance by luck: the share of "
             f"{fmt(an['permutations'], 0)} reshuffles, each sliding every player's injuries round the season, that "
             'scored at least as well.' if an['permutations'] else
             f"{fmt(an['rows'], 0)} player-weeks scored, but fewer than three injured weeks: too few to test."))
    headers, rows = report.latest_rows(an)
    say(heading(f'Highest ratios on the last day ({model.format_day(end)})'), text_table(headers, rows))
    blank_if(args.report, args.ratios_csv, args.json)
    if args.report:
        save(args.report, report.logbook_report(os.path.basename(args.path), book, an))
    if args.ratios_csv:
        save(args.ratios_csv, model.to_csv(RATIOS_HEADER, ratio_rows(an)))
    write_json(args.json, {'file': args.path, 'warnings': book['warnings'], 'players': book['names'],
                           'sessions': book['sessions'], 'start': model.format_day(book['start']), 'span': book['span'],
                           'result': {k: v for k, v in an.items() if k != 'series'}})
    return 0


# ---------- calibrate ----------
def cmd_calibrate(args):
    book = read_book(args.logbook)
    tests = calibrate.read_tests(read_csv(args.tests, 'tests file'))
    if 'error' in tests:
        raise CommandError(f"{args.tests}: {tests['error']}")
    truth = None
    if args.truth:
        truth = calibrate.read_truth(read_csv(args.truth, 'truth file'))
        if 'error' in truth:
            raise CommandError(f"{args.truth}: {truth['error']}")
        truth = truth['truth']
    for w in tests['warnings']:
        print(f'warning: {w}', file=sys.stderr)
    cal = calibrate.calibrate_squad(book, tests['tests'], truth)
    if not cal['players']:
        raise CommandError('no player had both a logbook and at least '
                           f'{calibrate.MIN_TESTS} tests on or after its first day')

    def days(v):
        return 'never' if v is None else fmt(v, 1)

    def cells(p):
        return [fmt(p['p0'], 1), fmt(1000 * p['k1'], 2), fmt(1000 * p['k2'], 2), fmt(p['tau1'], 1),
                fmt(p['tau2'], 1), fmt(p['r2'], 2), fmt(p['rmse'], 2), days(p['t0']), days(p['tpeak'])]

    rows = [[p['player'], p['tests']] + cells(p) for p in cal['players']]
    rows.append(['Squad median', ''] + cells(cal['medians']))
    say(f"Fitness and fatigue: the Banister model fitted to {tests['column']} in {args.tests}",
        wrap(f'perf(t) = p0 + k1 * fitness - k2 * fatigue, fitness and fatigue being the logbook\'s daily loads '
             f'(minutes x rpe) before day t, fading over tau1 and tau2 days. k1 and k2 are per 1,000 units of load; '
             f't0 is the days until a hard session does more good than harm, t* the days until its benefit peaks.'),
        '', text_table(['Player', 'Tests', 'p0', 'k1', 'k2', 'tau1', 'tau2', 'R2', 'RMSE', 't0', 't*'], rows))
    for s in cal['skipped']:
        say(f"Not fitted: {s['player']} ({s['reason']})")
    if truth:
        t = cal['truth']
        say(heading(f"Against the truth ({plural(t['players'], 'player')})"),
            text_table(['Parameter', 'Median abs error', 'Median rel error', 'True median', 'True sd', 'Error / sd'],
                       [[k, fmt(v['medianAbsError'], 5 if k in ('k1', 'k2') else 2), pct(v['medianRelError']),
                         fmt(v['trueMedian'], 5 if k in ('k1', 'k2') else 2),
                         fmt(v['trueSd'], 5 if k in ('k1', 'k2') else 2),
                         fmt(v['medianAbsError'] / v['trueSd'], 2) if v['trueSd'] else 'n/a']
                        for k, v in t['params'].items()]),
            wrap('Error / sd compares the typical error with how much the true values differ between players: well '
                 'below 1 means the fit tells players apart.'))
    blank_if(args.json)
    write_json(args.json, cal)
    return 0


# ---------- report ----------
def cmd_report(args):
    S = settings_from(args)
    res = experiments.report_analyses(S, args.seasons, args.pairs, args.workers)
    ev, cp, ps = res['flags'], res['compare'], res['pilot']
    page = report.analysis_report(S, ev, cp, ps)
    write_text(args.out, page)
    by = {f['id']: f for f in ev['flags']}
    say(f"Wrote {args.out} ({fmt(len(page.encode('utf-8')) / 1024, 0)} KB)",
        wrap(f'Settings: {report.settings_line(S)}.'), '', key_values([
            ('Warning lights', f"{plural(args.seasons, 'silent season')}: risk model AUC {fmt(by['model']['auc'], 2)}, "
                               f"EWMA {fmt(by['ewma']['auc'], 2)}, ceiling {fmt(by['oracle']['auc'], 2)}"),
            ('Pilot', f"{plural(args.pairs, 'pair')} of seasons: true effect {signed(ps['trueEffect'])} injuries a "
                      f"season, pilot looks better {pct(ps['looksBetter'])}"),
            ('Policies', f"{plural(args.seasons, 'season')} each, five policies on the same luck"),
        ]))
    return 0


# ---------- the parser ----------
DESCRIPTION = """\
Load bearing on the command line. An invented rugby club plays its season day by day: training load,
injuries, team selection and a league. A workload "warning light" flags players at risk; these commands
ask whether it helps, and whether a club could ever prove it.

The simulation commands (season, flags, compare, pilot, trial, sweep, report) take the same settings as the
browser app, with its defaults: rest anyone flagged by the risk model. Results are reproducible: the
same command always prints the same numbers."""

EPILOG = """\
examples:
  python -m loadbearing season --seed 6
  python -m loadbearing inquest --seed 6
  python -m loadbearing optimise --point-value 12 --all-lights
  python -m loadbearing robustness --map
  python -m loadbearing flags --seasons 30 --json results/flags.json
  python -m loadbearing compare --flag ewma --csv results/policies.csv
  python -m loadbearing pilot --pairs 40
  python -m loadbearing trial --clubs 4,8,16,32
  python -m loadbearing sweep --param threshold --values 1.2,1.5,1.8 --flag ewma
  python -m loadbearing logbook data/club_logbook.csv --report results/logbook.html
  python -m loadbearing calibrate --logbook data/club_logbook.csv --tests data/jump_tests.csv
  python -m loadbearing report --out results/report.html"""


def build_parser():
    common = settings_parser()
    fmt_class = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(prog='python -m loadbearing', description=DESCRIPTION, epilog=EPILOG,
                                     formatter_class=fmt_class)
    parser.add_argument('--version', action='version', version=f'load bearing {model.VERSION}')
    sub = parser.add_subparsers(dest='command', metavar='COMMAND', required=True)

    def command(name, run, summary, details, parents=(common,)):
        p = sub.add_parser(name, parents=list(parents), help=summary, description=f'{summary}.\n\n{details}',
                           formatter_class=fmt_class)
        p.set_defaults(run=run)
        return p

    def json_option(p):
        p.add_argument('--json', metavar='PATH', help='also write the full results as JSON')

    def workers_option(p):
        p.add_argument('--workers', type=COUNT, metavar='N',
                       help='processes to use (default: one per core; 1 runs everything in this process)')

    p = command('season', cmd_season, 'Play one season and replay it with the light ignored',
                'Prints injuries (soft-tissue and contact), days lost, the league and the cup final, the flags\n'
                'raised and acted on, and the same season replayed with policy none on the same luck.')
    p.add_argument('--seed', type=SEEDS, default=APP_SEASON_SEED,
                   help=f'the season seed (default {APP_SEASON_SEED}, as in the app)')
    p.add_argument('--matches-csv', metavar='PATH', help='write every match to a CSV file')
    p.add_argument('--logbook', metavar='PATH', help='write the season as a club logbook CSV, one row per session')
    json_option(p)

    p = command('inquest', cmd_inquest, 'Explain every injury of one season',
                'For each injury: its hidden risk factors, what each light said the Thursday before, and whether\n'
                'resting that player that week would have avoided it (the season replayed on the same luck).')
    p.add_argument('--seed', type=SEEDS, default=APP_SEASON_SEED,
                   help=f'the season seed (default {APP_SEASON_SEED}, as in the app)')
    json_option(p)

    p = command('optimise', cmd_optimise, 'Find the best way to use the light for a given worth of a league point',
                'Plays every option (rest or cut training at each flag level, rotation at each streak length,\n'
                'picking on readiness) over the same seasons, ranks them by player-days saved plus the worth of\n'
                'the points gained, marks the efficient ones and shows where the best option changes.')
    p.add_argument('--seasons', type=COUNT, default=20, metavar='N', help='seasons, seeds 101 to 100+N (default 20)')
    p.add_argument('--point-value', type=float, default=12, metavar='DAYS',
                   help='player-days of injury one league point is worth (default 12, as in the app)')
    p.add_argument('--all-lights', action='store_true', help='compare all five lights at once (about five times slower)')
    p.add_argument('--csv', metavar='PATH', help='write every option to a CSV file')
    workers_option(p)
    json_option(p)

    p = command('robustness', cmd_robustness, 'Ask whether the verdict survives a different hidden truth',
                'Pushes each assumption (how much load spikes cause injury, the contact rate, the seasons the risk\n'
                'model learns from, training effort, training kept when rested, pre-season, graded return) low and\n'
                'high, one at a time, and scores the light and its value again. --map adds the grid of spike effect\n'
                'against contact rate.')
    p.add_argument('--seasons', type=COUNT, default=12, metavar='N', help='seasons, seeds 201 to 200+N (default 12)')
    p.add_argument('--point-value', type=float, default=12, metavar='DAYS',
                   help='player-days of injury one league point is worth (default 12)')
    p.add_argument('--map', action='store_true', help='also map spike effect against contact rate (slower)')
    json_option(p)

    p = command('flags', cmd_flags, 'Score every warning light over silent seasons',
                'Seasons are played with nobody acting on any flag, so each light is scored against the same\n'
                'soft-tissue injuries: AUC, the single-season range, share flagged, hits per 100 flags and recall.')
    p.add_argument('--seasons', type=COUNT, default=30, metavar='N', help='silent seasons, seeds 1 to N (default 30)')
    json_option(p)

    p = command('compare', cmd_compare, 'Play every policy on the same seasons',
                'All five policies play the same seasons with the same luck; each metric gets its mean and the\n'
                'paired difference from ignoring the light, with a 95% bootstrap interval.')
    p.add_argument('--seasons', type=COUNT, default=30, metavar='N',
                   help='seasons, seeds 101 to 100+N as in the app (default 30)')
    p.add_argument('--csv', metavar='PATH', help='write one row per policy and metric to a CSV file')
    json_option(p)

    p = command('pilot', cmd_pilot, 'Ask whether a one-season pilot could tell',
                'A club plays a normal season, then pilots the light the next and compares. The true effect comes\n'
                'from replaying the first season with the light on the same luck.')
    p.add_argument('--pairs', type=COUNT, default=40, metavar='N', help='pairs of seasons (default 40)')
    json_option(p)

    p = command('trial', cmd_trial, 'Estimate the power of a cluster-randomised trial across clubs',
                'A pool of clubs (squad seeds counting up from --squad-seed) plays its seasons with and without\n'
                'the light on the same luck. Each simulated trial draws distinct clubs and seasons from the pool,\n'
                'gives half the clubs the light at random, and tests the difference in club mean injuries with a\n'
                'two-sided permutation test at 5% (exact over every split when there are few enough). Power\n'
                'estimates lean on the pool being representative, so a larger pool is more trustworthy.')
    p.add_argument('--clubs', type=int_list, default=[4, 8, 16, 32], metavar='LIST',
                   help='trial sizes, even numbers of clubs (default 4,8,16,32)')
    p.add_argument('--seasons-per-club', type=COUNT, default=1, metavar='K', help='seasons each club plays (default 1)')
    p.add_argument('--pool-clubs', type=COUNT, default=32, metavar='P',
                   help='clubs in the pool, at least the largest trial (default 32)')
    p.add_argument('--pool-seasons', type=COUNT, default=3, metavar='Q', help='seasons per pool club (default 3)')
    p.add_argument('--reps', type=COUNT, default=400, metavar='R', help='simulated trials per size (default 400)')
    p.add_argument('--permutations', type=COUNT, default=499, metavar='N',
                   help='random reshuffles when exact enumeration is too big (default 499)')
    p.add_argument('--seed', type=SEEDS, default=1, help='seed for drawing the trials (default 1)')
    workers_option(p)
    json_option(p)

    p = command('sweep', cmd_sweep, 'Run the light against no light for each value of one setting',
                'For each value the chosen policy and the policy none play the same seasons on the same luck;\n'
                'prints mean differences with 95% intervals in injuries, soft-tissue injuries, days lost and\n'
                f"points. Settings: {', '.join(experiments.SWEEP_PARAMS)}.")
    p.add_argument('--param', type=sweep_param, required=True, metavar='NAME', help='the setting to vary')
    p.add_argument('--values', type=number_list, required=True, metavar='LIST', help='values, for example 1.2,1.5,1.8')
    p.add_argument('--seasons', type=COUNT, default=20, metavar='N', help='seasons per value, seeds 101 to 100+N '
                                                                          '(default 20)')
    p.add_argument('--csv', metavar='PATH', help='write one row per value to a CSV file')
    workers_option(p)
    json_option(p)

    p = command('logbook', cmd_logbook, "Analyse a club's own session logbook",
                'Reads a CSV of sessions (date, player, then minutes and rpe or a load column, and optionally\n'
                'injury), works out every player\'s workload ratios, and scores them against the injuries with a\n'
                'permutation test. Unreadable input exits with code 2.', parents=())
    p.add_argument('path', help='the logbook CSV, for example data/club_logbook.csv')
    p.add_argument('--threshold', type=ranged(float, 0.1, 10), default=1.5, metavar='RATIO',
                   help='flag level for the ratios (default 1.5)')
    p.add_argument('--only', choices=['non-contact', 'all'],
                   help='injuries to score against (default non-contact when any are logged, otherwise all)')
    p.add_argument('--permutations', type=ranged(int, 0, 100000), default=500, metavar='N',
                   help='reshuffles for the permutation test (default 500)')
    p.add_argument('--seed', type=SEEDS, default=1, help='seed for the reshuffles (default 1)')
    p.add_argument('--report', metavar='PATH', help='write an HTML report')
    p.add_argument('--ratios-csv', metavar='PATH', help="write every player's daily ratios to a CSV file")
    json_option(p)

    p = command('calibrate', cmd_calibrate, 'Fit the Banister fitness-fatigue model to performance tests',
                'Fits perf(t) = p0 + k1 * fitness(t) - k2 * fatigue(t) to each player\'s tests, with the daily\n'
                'loads (minutes x rpe) from the logbook, by least squares and a Nelder-Mead search over the two\n'
                'time constants. --truth compares the estimates with known parameters.', parents=())
    p.add_argument('--logbook', required=True, metavar='PATH', help='the session logbook CSV')
    p.add_argument('--tests', required=True, metavar='PATH', help='tests CSV with date, player and a result column')
    p.add_argument('--truth', metavar='PATH', help='CSV of true parameters: player, p0, k1, k2, tau1, tau2')
    json_option(p)

    p = command('report', cmd_report, 'Write one self-contained HTML report',
                'Runs the flags, compare and pilot analyses and writes one HTML page with inline charts (ROC\n'
                'curves, single-season AUCs, the pilot histogram, the power curve and the policies), a plain\n'
                'English summary of each, and the settings used. The page makes no external requests.')
    p.add_argument('--out', required=True, metavar='PATH', help='the HTML file to write')
    p.add_argument('--seasons', type=COUNT, default=30, metavar='N',
                   help='seasons for the flags and compare analyses (default 30)')
    p.add_argument('--pairs', type=COUNT, default=40, metavar='N', help='pairs of seasons for the pilot (default 40)')
    workers_option(p)
    return parser


def main(argv=None):
    """Runs one command; returns the exit code (0 for success, 2 for unusable input)."""
    args = build_parser().parse_args(argv)
    try:
        return args.run(args)
    except CommandError as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
