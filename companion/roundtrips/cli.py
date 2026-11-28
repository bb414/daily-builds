"""The command line: python companion/round_trips.py <command> ...

Commands
  trades    exports (and an optional journal) to round-trip, breach, fills and days CSVs
  review    print the weekly review for the team chat, and optionally write it as HTML
  weekly    merge an inbox of new exports into a running journal and write a dated review
  team      a team review across a folder of members' exports (HTML and CSV)
  period    a report for a month or any span of days (HTML), with weeks, days, setups and rules
  size      position size for a planned trade
  check     show how each export was read: columns, dates and every row set aside
  template  write the CSV template
"""

import argparse
import os
import sys

from .days import days_csv
from .common import fmt_num, fmt_pct, fmt_units, fmt_price, fmt_r, from_iso, money, plural, rnd, to_iso, week_start
from .jobs import latest_week, load_state, read_text, team_review, weekly_job, with_default_start, write_team, write_text
from .matching import analyse, import_files
from .outputs import breaches_csv, fills_csv, position_size, template_csv, trades_csv
from .parsing import read_export
from .report import period_report, weekly_report
from .review import review_text, week_review
from .stats import start_balance, stats


def _files(paths, account=None):
    out = []
    for p in paths:
        if os.path.isdir(p):
            for f in sorted(os.listdir(p)):
                if f.lower().endswith(('.csv', '.tsv', '.txt')):
                    out.append({'name': f, 'text': read_text(os.path.join(p, f)), 'account': account})
        else:
            out.append({'name': os.path.basename(p), 'text': read_text(p), 'account': account})
    return out


def _week(text):
    if not text or text == 'latest':
        return None
    day = from_iso(text)
    if day is None:
        raise SystemExit('Give the week as a date such as 2026-11-23 (any day in the week), or "latest".')
    return week_start(day)


def _load(args):
    state = load_state(args.journal)
    if getattr(args, 'date_order', None):
        state['settings']['dateOrder'] = args.date_order
    imp = import_files(state, _files(args.exports, getattr(args, 'account', None)))
    for rep in imp['reports']:
        if not rep['ok']:
            print('Could not read %s: %s' % (rep['name'], rep['error']), file=sys.stderr)
        elif rep['counts']['skipped']:
            print('%s: %s set aside (run "check" to see why)' % (rep['name'], plural(rep['counts']['skipped'], 'row')), file=sys.stderr)
    st = with_default_start(imp['state'], getattr(args, 'start', None))
    return st, analyse(st)


def cmd_trades(args):
    st, res = _load(args)
    os.makedirs(args.out, exist_ok=True)
    for name, body in (('round-trips.csv', trades_csv(res)), ('rule-breaches.csv', breaches_csv(res)), ('fills-matched.csv', fills_csv(res)), ('days.csv', days_csv(res))):
        write_text(os.path.join(args.out, name), body)
    s = stats(res['closed'], start_balance(res, res['accounts']))
    base = res['settings']['base']
    print('%s closed, %d still open, from %s.' % (plural(s['n'], 'trade'), len(res['open']), plural(len(res['fills']), 'fill')))
    if s['n']:
        print('Net after fees %s (fees %s). Win rate %s, expectancy %s a trade, profit factor %s.' % (
            money(s['net'], base, sign=True), money(s['fees'], base), fmt_pct(s['winRate']), money(rnd(s['expectancy']), base, sign=True),
            'n/a' if s['profitFactor'] is None else fmt_num(s['profitFactor'], 2)))
    print('%s.' % plural(len(res['breaches']), 'rule breach', 'rule breaches'))
    for w in res['warnings']:
        print('Check: ' + w['text'])
    print('Wrote round-trips.csv, rule-breaches.csv, fills-matched.csv and days.csv to %s' % args.out)
    return 0


def cmd_review(args):
    st, res = _load(args)
    week = _week(args.week)
    if week is None:
        week = latest_week(res, args.account_filter or '')
    if week is None:
        print('No trades in these exports.')
        return 1
    rv = week_review(res, week, args.account_filter or '')
    text = review_text(rv, res)
    sys.stdout.write(text)
    if args.html:
        write_text(args.html, weekly_report(res, rv, text))
        print('\nWrote ' + args.html)
    return 0


def cmd_weekly(args):
    summary = weekly_job(args.journal, args.inbox, args.out, archive=args.archive, week=_week(args.week), account=args.account_filter or '',
                         default_start=args.start, settings_path=args.settings)
    print('Inbox: %s.' % (plural(len(summary['inbox']), 'export') if summary['inbox'] else 'nothing new'))
    for f in summary['inbox']:
        if f['ok']:
            print('  %s: %s, %d already in the journal, %s set aside' % (f['file'], plural(f['added'], 'new fill'), f['duplicates'], plural(f['skipped'], 'row')))
        else:
            print('  %s: not read (%s)' % (f['file'], f['error']))
    print('Journal now holds %s (%d new); %s closed since the last run.' % (plural(summary['fills'], 'fill'), summary['added'], plural(summary['newlyClosed'], 'trade')))
    if summary['week'] is None:
        print('No closed trades yet, so no review was written.')
        return 0
    print('Week of %s: %s closed.' % (to_iso(summary['week']), plural(summary['closedThisWeek'], 'trade')))
    for p in summary['written']:
        print('Wrote ' + p)
    for p in summary['archived']:
        print('Moved to ' + p)
    if args.print:
        print()
        sys.stdout.write(summary['text'])
    return 1 if summary['problems'] else 0


def cmd_period(args):
    st, res = _load(args)
    if args.month:
        parts = args.month.split('-')
        try:
            y, mo = int(parts[0]), int(parts[1])
            start = from_iso('%04d-%02d-01' % (y, mo))
            end = (from_iso('%04d-01-01' % (y + 1)) if mo == 12 else from_iso('%04d-%02d-01' % (y, mo + 1))) - 1
        except (ValueError, IndexError, TypeError):
            raise SystemExit('Give the month as YYYY-MM, for example 2026-10.')
    else:
        days = [t['closeDay'] for t in res['closed']]
        start = from_iso(args.start_date) if args.start_date else (min(days) if days else None)
        end = from_iso(args.end_date) if args.end_date else (max(days) if days else None)
    if start is not None and end is not None and end < start:
        raise SystemExit('The --from date is after the --to date.')
    if start is None or end is None:
        raise SystemExit('Give a month (--month 2026-10) or dates (--from 2026-10-01 --to 2026-10-31) with closed trades in between.')
    write_text(args.out, period_report(res, start, end, args.account_filter or ''))
    print('Wrote %s for %s to %s' % (args.out, to_iso(start), to_iso(end)))
    return 0


def cmd_team(args):
    team = team_review(args.folder, args.settings, _week(args.week), args.start)
    if not team['members']:
        print('No exports found in %s.' % args.folder)
        return 1
    paths = write_team(team, args.out)
    base = team['base']
    print('%-24s %7s %14s %8s %9s %8s %9s' % ('Member', 'Trades', 'Net', 'Win', 'Avg R', 'Sharpe', 'Breaches'))
    for m in team['members']:
        s = m['stats']
        print('%-24s %7d %14s %8s %9s %8s %9d' % (m['name'][:24], s['n'], money(s['net'], base, sign=True), fmt_pct(s['winRate']), fmt_r(s['avgR']) or 'n/a',
                                                  'n/a' if s['sharpe'] is None else fmt_num(s['sharpe'], 2), m['breachTotal']))
    for p in team['problems']:
        print('Check: ' + p)
    for p in paths:
        print('Wrote ' + p)
    return 0


def cmd_size(args):
    out = position_size({'equity': args.equity, 'riskPct': args.risk, 'entry': args.entry, 'stop': args.stop, 'mult': args.mult, 'fee': args.fee,
                         'step': args.step, 'allowance': args.allowance, 'currency': args.currency})
    if not out['ok']:
        print(out['msg'])
        return 1
    units = fmt_units(out['units'])
    print('%s %s (loss at the stop with fees %s, %s%% of the account)' % ('Buy' if out['direction'] == 'long' else 'Sell short', units,
                                                                         money(out['risk'], args.currency), fmt_num(out['riskPct'], 2)))
    print('Position value %s (%s%% of the account)%s' % (money(out['value'], args.currency), fmt_num(out['valuePct'], 1),
                                                        ', capped by the loss allowed today' if out['limitedBy'] == 'allowance' else ''))
    print('Targets: ' + ', '.join('%dR at %s' % (t['r'], fmt_price(t['price'])) for t in out['targets']))
    return 0


def cmd_check(args):
    bad = 0
    for f in _files(args.exports, args.account):
        rep = read_export(f['name'], f['text'], {'dateOrder': args.date_order or 'auto', 'account': f['account']})
        print('== %s' % f['name'])
        if not rep['ok']:
            print('  Not read: ' + rep['error'])
            bad += 1
            continue
        print('  Account: %s; %s, %s, %s set aside' % (rep['account'], plural(rep['counts']['fills'], 'fill'), plural(rep['counts']['fees'], 'fee row'),
                                                     plural(rep['counts']['skipped'], 'row')))
        print('  Columns: ' + ', '.join('%s = %s' % (k, v) for k, v in rep['columns'].items()))
        for n in ([rep['dateNote']] if rep['dateNote'] else []) + rep['notes']:
            print('  Note: ' + n)
        for s in rep['skipped']:
            print('  Line %d: %s | %s' % (s['line'], s['reason'], s['text']))
    return 1 if bad else 0


def cmd_template(args):
    write_text(args.out, template_csv())
    print('Wrote ' + args.out)
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog='round_trips.py', description='Round trips: turn fills exports into round-trip trades and an honest weekly review. Not financial advice.')
    sub = p.add_subparsers(dest='command', required=True)

    def common(sp, exports=True):
        if exports:
            sp.add_argument('exports', nargs='*', help='fills exports (CSV, TSV or text) or folders of them')
        sp.add_argument('--journal', help='a saved journal file to start from (its fills, notes and settings)')
        sp.add_argument('--date-order', choices=['auto', 'DMY', 'MDY'], help='how numeric dates are written (default: work it out)')
        sp.add_argument('--account', help='account name for exports with no account column')
        sp.add_argument('--start', help='starting balance for any account without one, for the %% rules and drawdown')

    sp = sub.add_parser('trades', help='write round-trip, breach and fills CSVs')
    common(sp)
    sp.add_argument('--out', default='round-trips-out', help='folder for the CSVs (default: round-trips-out)')
    sp.set_defaults(func=cmd_trades)

    sp = sub.add_parser('review', help='print the weekly review for the team chat')
    common(sp)
    sp.add_argument('--week', help='any date in the week, or "latest" (the default)')
    sp.add_argument('--for-account', dest='account_filter', help='review one account only')
    sp.add_argument('--html', help='also write the review as a printable HTML page')
    sp.set_defaults(func=cmd_review)

    sp = sub.add_parser('weekly', help='merge an inbox of exports into a running journal and write a dated review')
    sp.add_argument('--journal', required=True, help='the running journal file (created if missing)')
    sp.add_argument('--inbox', required=True, help='folder of new exports')
    sp.add_argument('--out', default='reviews', help='folder for the dated reviews (default: reviews)')
    sp.add_argument('--archive', help='move exports that were read into this folder')
    sp.add_argument('--week', help='any date in the week to review, or "latest" (the default)')
    sp.add_argument('--for-account', dest='account_filter', help='review one account only')
    sp.add_argument('--start', help='starting balance for any account without one')
    sp.add_argument('--settings', help='a journal file whose settings a new running journal starts with')
    sp.add_argument('--print', action='store_true', help='print the review text when done')
    sp.set_defaults(func=cmd_weekly)

    sp = sub.add_parser('team', help='team review across a folder of members\' exports')
    sp.add_argument('folder', help='one subfolder per member (exports and an optional journal file), or one export per member')
    sp.add_argument('--settings', help='a journal file whose settings (rules, multipliers, balances, rates) everyone shares')
    sp.add_argument('--week', help='any date in the week to compare, or "latest" (the default)')
    sp.add_argument('--start', help='starting balance for any account without one')
    sp.add_argument('--out', default='team-review', help='folder for team-review.html and team-review.csv')
    sp.set_defaults(func=cmd_team)

    sp = sub.add_parser('period', help='a report for a month or any span of days')
    common(sp)
    sp.add_argument('--month', help='a month, as YYYY-MM')
    sp.add_argument('--from', dest='start_date', help='first day, YYYY-MM-DD')
    sp.add_argument('--to', dest='end_date', help='last day, YYYY-MM-DD')
    sp.add_argument('--for-account', dest='account_filter', help='one account only')
    sp.add_argument('--out', default='period-report.html')
    sp.set_defaults(func=cmd_period)

    sp = sub.add_parser('size', help='position size for a planned trade')
    sp.add_argument('--equity', required=True, help='account size')
    sp.add_argument('--risk', required=True, help='risk per trade, as a percentage of the account')
    sp.add_argument('--entry', required=True)
    sp.add_argument('--stop', required=True)
    sp.add_argument('--mult', default='1', help='contract multiplier (default 1)')
    sp.add_argument('--fee', default='', help='fees per share or contract, round trip')
    sp.add_argument('--step', default='1', help='size in steps of (default 1)')
    sp.add_argument('--allowance', default='', help='loss still allowed today')
    sp.add_argument('--currency', default='USD')
    sp.set_defaults(func=cmd_size)

    sp = sub.add_parser('check', help='show how each export was read')
    sp.add_argument('exports', nargs='+')
    sp.add_argument('--date-order', choices=['auto', 'DMY', 'MDY'])
    sp.add_argument('--account')
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser('template', help='write the CSV template')
    sp.add_argument('--out', default='round-trips-template.csv')
    sp.set_defaults(func=cmd_template)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)
