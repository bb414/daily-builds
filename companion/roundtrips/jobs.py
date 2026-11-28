"""Jobs the browser app cannot do: a team review across a folder of exports, and a weekly job that
merges an inbox of new exports into a running journal and writes a dated review."""

import copy
import os
import shutil

from .common import cmp, sort_by, to_iso, week_start
from .days import days_csv
from .matching import RULES, analyse, empty_state, import_files
from .outputs import breaches_csv, csv_lines, fills_csv, project_file, read_project, trades_csv
from .parsing import clean_account_name
from .report import team_report, weekly_report
from .review import review_text, week_review
from .stats import filter_trades, start_balance, stats, usable

EXPORT_TYPES = ('.csv', '.tsv', '.txt')


def read_text(path):
    with open(path, encoding='utf-8-sig', newline='') as fh:
        return fh.read()


def write_text(path, text):
    """Write a file in one step, so an interrupted run never leaves half a file."""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='') as fh:
        fh.write(text)
    os.replace(tmp, path)


def load_state(path):
    """A journal file as a state, or an empty journal when there is no file yet."""
    if path and os.path.exists(path):
        pr = read_project(read_text(path))
        if not pr['ok']:
            raise SystemExit('%s: %s' % (path, pr['error']))
        return pr['state']
    return empty_state()


def exports_in(folder):
    return sort_by([os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(EXPORT_TYPES) and not f.startswith('.')], cmp)


def latest_week(result, account=''):
    weeks = sorted({week_start(t['closeDay']) for t in result['closed'] if not account or t['account'] == account})
    return weeks[-1] if weeks else (result['weeks'][-1] if result['weeks'] else None)


def with_default_start(state, start):
    """Give every account without a starting balance the one given on the command line."""
    if not start:
        return state
    names = {a['name'] for a in state['settings']['accounts']}
    accounts = list(state['settings']['accounts'])
    for f in state['fills']:
        if f['account'] not in names:
            names.add(f['account'])
            accounts.append({'name': f['account'], 'start': str(start), 'currency': '', 'longOnly': False})
    state['settings']['accounts'] = accounts
    return state


# ---------- the team review ----------

def discover_members(folder):
    """Members of a team folder: each subfolder is one member (its exports and an optional journal file);
    each export directly in the folder is a member of its own."""
    members = []
    for entry in sort_by(os.listdir(folder), cmp):
        path = os.path.join(folder, entry)
        if entry.startswith('.'):
            continue
        if os.path.isdir(path):
            files = exports_in(path)
            journals = sort_by([os.path.join(path, f) for f in os.listdir(path) if f.lower().endswith('.json')], cmp)
            if files or journals:
                members.append({'name': entry.replace('_', ' ').replace('-', ' ').strip() or entry, 'files': files, 'journal': journals[0] if journals else None})
        elif entry.lower().endswith(EXPORT_TYPES):
            members.append({'name': clean_account_name(entry), 'files': [path], 'journal': None})
    return members


def team_review(folder, settings_path=None, week=None, default_start=None):
    shared = load_state(settings_path) if settings_path else None
    if shared is None and os.path.exists(os.path.join(folder, 'settings.json')):
        shared = load_state(os.path.join(folder, 'settings.json'))
    members, problems = [], []
    for mbr in discover_members(folder):
        state = load_state(mbr['journal']) if mbr['journal'] else empty_state()
        if shared is not None and not mbr['journal']:
            state['settings'] = copy.deepcopy(shared['settings'])
        files = [{'name': os.path.basename(p), 'text': read_text(p), 'account': mbr['name']} for p in mbr['files']]
        imp = import_files(state, files)
        for rep in imp['reports']:
            if not rep['ok']:
                problems.append('%s, %s: %s' % (mbr['name'], rep['name'], rep['error']))
            elif rep['counts']['skipped']:
                problems.append('%s, %s: %d rows set aside (%s)' % (mbr['name'], rep['name'], rep['counts']['skipped'],
                                                                     '; '.join(sorted({s['reason'] for s in rep['skipped']}))[:200]))
        st = with_default_start(imp['state'], default_start)
        res = analyse(st)
        members.append({'name': mbr['name'], 'result': res, 'state': st})
    if week is None:
        weeks = [latest_week(m['result']) for m in members if m['result']['closed']]
        week = max(weeks) if weeks else None
    base = members[0]['result']['settings']['base'] if members else 'USD'
    rows = []
    for m in members:
        res = m['result']
        start = start_balance(res, res['accounts'])
        s = stats(res['closed'], start)
        by_rule = {}
        for b in res['breaches']:
            by_rule[b['rule']] = by_rule.get(b['rule'], 0) + 1
        rv = week_review(res, week) if week is not None else None
        if res['settings']['base'] != base:
            problems.append('%s reports in %s, not %s: compare their money figures with care.' % (m['name'], res['settings']['base'], base))
        rows.append({
            'name': m['name'], 'accounts': res['accounts'], 'stats': s, 'closed': res['closed'], 'breachTotal': len(res['breaches']), 'breachByRule': by_rule,
            'week': rv['stats'] if rv else stats([]), 'weekBreaches': len(rv['breaches']) if rv else 0, 'weekNotes': rv['notes'] if rv else [],
            'warnings': [w['text'] for w in res['warnings']], 'start': start,
        })
        for w in res['warnings']:
            problems.append('%s: %s' % (m['name'], w['text']))
    return {'members': rows, 'week': week, 'base': base, 'rules': RULES, 'problems': problems}


def team_csv(team):
    head = ['Member', 'Accounts', 'Closed trades', 'Net P&L', 'Win rate', 'Expectancy', 'Profit factor', 'Average R', 'Trades with R', 'Fees', 'Largest drop',
            'Largest drop (%)', 'Net over largest drop', 'Daily Sharpe', 'Daily Sortino', 'Rule breaches'] + [r['label'] for r in team['rules']]
    rows = [head]

    def num(v, dp):
        return '' if v is None else ('%.' + str(dp) + 'f') % v

    for m in team['members']:
        s = m['stats']
        rows.append([m['name'], '; '.join(m['accounts']), s['n'], '%.2f' % (s['net'] / 100), num(s['winRate'], 4), num(None if s['expectancy'] is None else s['expectancy'] / 100, 2),
                     num(s['profitFactor'], 3), num(s['avgR'], 3), s['rCount'], '%.2f' % (s['fees'] / 100), '%.2f' % (s['maxDD'] / 100), num(s['maxDDPct'], 2),
                     num(s['recovery'], 3), num(s['sharpe'], 3), num(s['sortino'], 3), m['breachTotal']] + [m['breachByRule'].get(r['id'], 0) for r in team['rules']])
    return csv_lines(rows)


def write_team(team, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    html_path = os.path.join(out_dir, 'team-review.html')
    csv_path = os.path.join(out_dir, 'team-review.csv')
    write_text(html_path, team_report(team, team['base'], team['week']))
    write_text(csv_path, team_csv(team))
    return [html_path, csv_path]


# ---------- the weekly job ----------

def weekly_job(journal_path, inbox, out_dir, archive=None, week=None, account='', default_start=None, settings_path=None):
    """Merge every export in the inbox into the running journal, save it, and write a dated review.

    Running it again on the same inbox changes nothing: fills already in the journal are skipped.
    """
    state = load_state(journal_path)
    if settings_path and not os.path.exists(journal_path):
        state['settings'] = copy.deepcopy(load_state(settings_path)['settings'])
    before = len(state['fills'])
    closed_before = {t['id'] for t in analyse(state)['closed']} if state['fills'] else set()
    paths = exports_in(inbox) if inbox and os.path.isdir(inbox) else []
    files = [{'name': os.path.basename(p), 'text': read_text(p)} for p in paths]
    imp = import_files(state, files)
    new_state = with_default_start(imp['state'], default_start)
    res = analyse(new_state)
    if week is None:
        week = latest_week(res, account)
    summary = {'inbox': [], 'added': len(new_state['fills']) - before, 'newlyClosed': len([t for t in res['closed'] if t['id'] not in closed_before]), 'fills': len(new_state['fills']), 'week': week, 'written': [], 'archived': [], 'problems': []}
    for p, rep in zip(paths, imp['reports']):
        summary['inbox'].append({'file': os.path.basename(p), 'ok': rep['ok'], 'added': rep['added'], 'duplicates': rep['duplicates'], 'skipped': rep['counts']['skipped'],
                                 'error': rep['error']})
        if not rep['ok']:
            summary['problems'].append('%s: %s' % (os.path.basename(p), rep['error']))
    if os.path.exists(journal_path):
        shutil.copyfile(journal_path, journal_path + '.bak')
    folder = os.path.dirname(os.path.abspath(journal_path))
    os.makedirs(folder, exist_ok=True)
    write_text(journal_path, project_file(new_state, to_iso(week + 6) if week is not None else ''))
    summary['written'].append(journal_path)
    if week is not None:
        dated = os.path.join(out_dir, 'review-' + to_iso(week))
        os.makedirs(dated, exist_ok=True)
        rv = week_review(res, week, account)
        text = review_text(rv, res)
        in_week = filter_trades(res['trades'], account, week, week + 6)
        outputs = {
            'review.txt': text,
            'review.html': weekly_report(res, rv, text),
            'round-trips-week.csv': trades_csv(res, in_week),
            'round-trips-all.csv': trades_csv(res),
            'breaches-week.csv': breaches_csv(res, rv['breaches']),
            'fills.csv': fills_csv(res),
            'days.csv': days_csv(res, account),
        }
        for name, body in outputs.items():
            path = os.path.join(dated, name)
            write_text(path, body)
            summary['written'].append(path)
        summary['review'] = rv
        summary['text'] = text
    if archive:
        for p, rep in zip(paths, imp['reports']):
            if rep['ok']:
                dest_dir = os.path.join(archive, to_iso(week) if week is not None else 'undated')
                os.makedirs(dest_dir, exist_ok=True)
                dest = os.path.join(dest_dir, os.path.basename(p))
                n = 1
                while os.path.exists(dest):
                    n += 1
                    root, ext = os.path.splitext(os.path.basename(p))
                    dest = os.path.join(dest_dir, '%s-%d%s' % (root, n, ext))
                shutil.move(p, dest)
                summary['archived'].append(dest)
    summary['result'] = res
    summary['closedThisWeek'] = len(usable(filter_trades(res['closed'], account, week, week + 6))) if week is not None else 0
    return summary
