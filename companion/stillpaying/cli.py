"""The companion's command line: scan, monthly, budget and template.

Run  python companion/still_paying.py <command> --help  for the options of
each command. Exit codes: 0 when the job is done, 2 when no export could be
read (or an option or saved review is not usable).
"""

import argparse
import os
import re
import sys
import textwrap

from .common import money
from .dates import from_iso, iso, long_date
from .model import analyse
from .outputs import budget_csv, build_ics, project_file, read_project, register_csv, template_csv
from .planning import since_last_review
from .present import changes_markdown, flag_label, headline, price_history_csv, status_label
from .report import render_report

WIDTH = 100
EXTENSIONS = ('.csv', '.tsv', '.txt', '.ofx', '.qfx', '.qif')
OWN_OUTPUTS = re.compile(r'^(regular-payments|price-history|budget-\d+-months)\.csv$', re.IGNORECASE)
REVIEW_NAME = re.compile(r'^review-(\d{4}-\d{2}-\d{2})\.json$')


class Problem(Exception):
    """Something the user needs to fix before the job can run; the message says what."""


# ---------------------------------------------------------------------------
# Reading the inputs
# ---------------------------------------------------------------------------

def read_text(path):
    """A file's text and a note: UTF-8 when it is, otherwise Windows-1252 (how older bank sites save CSV)."""
    with open(path, 'rb') as fh:
        data = fh.read()
    try:
        return data.decode('utf-8'), None
    except UnicodeDecodeError:
        return (data.decode('cp1252', errors='replace'),
                os.path.basename(path) + ' was not saved as UTF-8, so it was read as Windows-1252.')


def collect_exports(paths):
    """The exports named on the command line, plus notes about anything left out.

    A folder gives every .csv, .tsv, .txt, .ofx, .qfx and .qif file directly inside it, sorted
    by name, apart from the files this tool writes and the blank template.
    """
    files, notes = [], []
    template = template_csv()

    def add(path, name, from_folder):
        try:
            text, note = read_text(path)
        except OSError as err:
            notes.append(name + ' could not be opened: ' + (err.strerror or str(err)) + '.')
            return
        if from_folder and text == template:
            notes.append(name + ' was left out: it is the blank layout template, not a statement.')
            return
        files.append({'name': name, 'text': text})
        notes.extend([note] if note else [])

    for path in paths:
        if os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                full = os.path.join(path, name)
                if not os.path.isfile(full) or not name.lower().endswith(EXTENSIONS):
                    continue
                if OWN_OUTPUTS.match(name):
                    notes.append(name + ' was left out: it is a file this tool writes, not a statement.')
                    continue
                add(full, name, True)
        elif os.path.isfile(path):
            add(path, os.path.basename(path), False)
        else:
            notes.append(path + ' was not found.')
    return files, notes


def load_review(path):
    """A saved review (from the app or an earlier run), read back; raises Problem if it cannot be used."""
    try:
        text, _ = read_text(path)
    except OSError as err:
        raise Problem('Could not open the saved review %s: %s.' % (path, err.strerror or err))
    review = read_project(text)
    if 'error' in review:
        raise Problem(os.path.basename(path) + ': ' + review['error'])
    return review


def run_analysis(files, as_of, review):
    """analyse() with a saved review's transactions and choices carried over."""
    review = review or {}
    return analyse(files, as_of=as_of, extra=review.get('transactions'), aliases=review.get('aliases'),
                   names=review.get('names'), manual=review.get('manual'), overrides=review.get('overrides'))


def save_state(analysis, review, decisions, reviewed_on=None):
    """Everything project_file() needs to write the review the app can reopen."""
    review = review or {}
    merged = analysis['merged']
    return {'transactions': merged['transactions'], 'result': analysis['result'], 'decisions': decisions,
            'accounts': merged['accounts'], 'aliases': review.get('aliases'), 'names': review.get('names'),
            'manual': review.get('manual'), 'overrides': review.get('overrides'), 'details': review.get('details'),
            'reviewedOn': reviewed_on}


def write_text(path, text):
    """Write text exactly as given (UTF-8, line ends untouched)."""
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(text)


def write_output(text, path=None):
    """Write to a file, or to standard output when no file is given."""
    if path:
        write_text(path, text)
    else:
        sys.stdout.flush()
        sys.stdout.buffer.write(text.encode('utf-8'))
        sys.stdout.buffer.flush()


# ---------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------

def wrap(text, indent=0):
    """Wrap a paragraph to the terminal width, indenting follow-on lines a little further."""
    return textwrap.wrap(text, WIDTH, initial_indent=' ' * indent, subsequent_indent=' ' * (indent + 2),
                         break_on_hyphens=False, break_long_words=False) or ['']


def wrap_markdown(text):
    """Markdown wrapped to the terminal width, with list items kept indented under their bullet."""
    lines = []
    for line in text.splitlines():
        indent = '  ' if line.startswith('- ') else ''
        lines += textwrap.wrap(line, WIDTH, subsequent_indent=indent, break_on_hyphens=False,
                               break_long_words=False) or ['']
    return lines


def table(columns, rows, gap=2):
    """Rows of text as aligned columns no wider than WIDTH.

    columns holds (heading, align, cap) for each column: align is '<' or '>',
    cap the widest the column may be (None for no limit). The last column
    takes whatever width is left, and cells too wide for their column wrap
    onto extra lines.
    """
    widths = []
    for i, (heading, _, cap) in enumerate(columns):
        natural = max([len(heading)] + [len(r[i]) for r in rows])
        widths.append(min(natural, cap) if cap else natural)
    room = WIDTH - sum(widths[:-1]) - gap * (len(columns) - 1)
    widths[-1] = max(8, min(widths[-1], room))

    def lay_out(cells):
        wrapped = [textwrap.wrap(c, w) or [''] for c, w in zip(cells, widths)]
        out = []
        for k in range(max(len(w) for w in wrapped)):
            parts = []
            for (_, align, _), w, lines in zip(columns, widths, wrapped):
                text = lines[k] if k < len(lines) else ''
                parts.append(text.rjust(w) if align == '>' else text.ljust(w))
            out.append((' ' * gap).join(parts).rstrip())
        return out

    lines = lay_out([c[0] for c in columns])
    lines.append((' ' * gap).join('-' * w for w in widths))
    for r in rows:
        lines += lay_out(r)
    return lines


def _about(s):
    return 'about ' if s['amounts']['kind'] == 'variable' else ''


def scan_text(analysis, decisions, notes):
    """The terminal report for a scan: headline, regular payments, possible ones and the files read."""
    result = analysis['result']
    merged = analysis['merged']
    h = headline(result, decisions)
    lines = ['Still paying? Review for ' + long_date(result['asOf'])]
    read = [st for st in analysis['statements'] if st['ok']]
    lines += wrap('Statements from %s to %s: %d file%s read, %d account%s.' % (
        long_date(result['dataStart']), long_date(result['dataEnd']), len(read), '' if len(read) == 1 else 's',
        len(merged['accounts']), '' if len(merged['accounts']) == 1 else 's'))
    lines.append('')
    lines += wrap('Committed spending: %s a month, %s a year (not counting savings or money moved between your own '
                  'accounts). %d regular payments are active and %d have checks to look at.'
                  % (money(h['monthly']), money(h['annual']), h['regulars'], h['checks']))
    payday = h['payday']
    if payday:
        lines += wrap('Next payday: %s (%s, about %s).' % (long_date(payday['next']), payday['name'],
                                                            money(payday['typical'])))
    lines += ['', 'Regular payments']
    if result['series']:
        rows = [[s['name'], s['cadence'], _about(s) + money(s['typical']), money(s['monthly']),
                 long_date(s['nextDue']) if s['nextDue'] is not None else '', status_label(s),
                 ', '.join(flag_label(f) for f in s['flags'])] for s in result['series']]
        lines += table([('Name', '<', 24), ('How often', '<', None), ('Typical', '>', None), ('Monthly', '>', None),
                        ('Next due', '<', None), ('Status', '<', None), ('Checks', '<', None)], rows)
        lines += wrap('Full wording of every check is in regular-payments.csv and report.html.')
    else:
        lines.append('None found yet. A payment needs to repeat a few times before it counts.')
    for s in result['income']:
        lines += wrap('Money in: %s, %s, %s%s, next expected %s.' % (
            s['name'], s['cadence'], _about(s), money(s['typical']),
            long_date(s['nextDue']) if s['nextDue'] is not None else 'not known'))
    lines += ['', 'Possible regular payments']
    if result['candidates']:
        rows = [[c['name'], money(c['amount']), long_date(c['lastDay']), c['reason']] for c in result['candidates']]
        lines += table([('Name', '<', 24), ('Amount', '>', None), ('Last seen', '<', None), ('Why', '<', None)], rows)
    else:
        lines.append('None.')
    lines += ['', 'Files'] + file_lines(analysis, notes)
    return '\n'.join(lines)


def file_lines(analysis, notes):
    """Per file: rows read, rows skipped with line numbers and reasons, warnings and links to other files."""
    lines = []
    linked = {n['file']: n for n in analysis['merged']['linked']}
    for st in analysis['statements']:
        skipped = len(st['skipped'])
        if st['ok']:
            head = '%s: %s, %d rows read, %d payments, %s.' % (
                st['name'], st['account'], st['rowCount'], len(st['transactions']),
                'nothing skipped' if not skipped else '%d row%s skipped' % (skipped, '' if skipped == 1 else 's'))
        else:
            head = '%s: not read. %s' % (st['name'], st.get('error', ''))
        lines += wrap(head)
        link = linked.get(st['name'])
        if link:
            lines += wrap('Same account as %s: %d%% of its payments are also there, so the overlap is counted once.'
                          % (link['other'], link['share']), 2)
        for w in st['warnings']:
            lines += wrap('Note: ' + w, 2)
        for k in st['skipped']:
            lines += wrap('Line %d: %s' % (k['line'], k['reason']), 2)
    duplicates = analysis['merged']['duplicates']
    if duplicates:
        lines += wrap('%d payments were in more than one file and were counted once.' % duplicates)
    for note in notes:
        lines += wrap(note)
    return lines


def nothing_read(analysis, notes):
    """True (after explaining why) when no export could be read."""
    if any(st['ok'] for st in analysis['statements']):
        return False
    print('No bank export could be read, so there is nothing to review.', file=sys.stderr)
    for line in file_lines(analysis, notes):
        print(line, file=sys.stderr)
    return True


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_scan(args):
    """Scan exports, print what was found and write the five output files."""
    files, notes = collect_exports(args.paths)
    review = load_review(args.review) if args.review else None
    analysis = run_analysis(files, args.as_of, review)
    if nothing_read(analysis, notes):
        return 2
    result = analysis['result']
    decisions = review['decisions'] if review else {}
    os.makedirs(args.out, exist_ok=True)
    outputs = [
        ('regular-payments.csv', register_csv(result, decisions)),
        ('budget-12-months.csv', budget_csv(result, decisions, 12)),
        ('upcoming.ics', build_ics(result, decisions, days=92)['text']),
        ('review.json', project_file(save_state(analysis, review, decisions))),
        ('report.html', render_report(analysis, decisions, notes=notes)),
    ]
    for name, text in outputs:
        write_text(os.path.join(args.out, name), text)
    if not args.quiet:
        print(scan_text(analysis, decisions, notes))
        print('')
        for line in wrap('Wrote to %s: %s.' % (args.out, ', '.join(name for name, _ in outputs))):
            print(line)
    return 0


def find_reviews(folder):
    """Saved reviews named review-YYYY-MM-DD.json in a folder, oldest first, as (day, name) pairs."""
    found = []
    for name in os.listdir(folder):
        m = REVIEW_NAME.match(name)
        if m and from_iso(m.group(1)) is not None and os.path.isfile(os.path.join(folder, name)):
            found.append((from_iso(m.group(1)), name))
    return sorted(found)


def cmd_monthly(args):
    """The monthly job: scan a folder of exports and compare with the last saved review in the history folder.

    The run's date is --as-of, or else the day after the latest transaction
    (never earlier than the latest saved review). The latest review dated
    before the run is "your last review". A review with the same date comes
    from an earlier run for the same month: it is replaced, keeping its
    decisions.
    """
    files, notes = collect_exports([args.folder])
    reviews = find_reviews(args.history) if os.path.isdir(args.history) else []
    usable = [r for r in reviews if args.as_of is None or r[0] <= args.as_of]
    carried = usable[-1] if usable else None
    review = load_review(os.path.join(args.history, carried[1])) if carried else None
    analysis = run_analysis(files, args.as_of, review)
    if nothing_read(analysis, notes):
        return 2
    if args.as_of is None and carried and analysis['result']['asOf'] < carried[0]:
        analysis = run_analysis(files, carried[0], review)
    result = analysis['result']
    run_day = result['asOf']
    decisions = review['decisions'] if review else {}
    earlier = [r for r in reviews if r[0] < run_day]
    previous = earlier[-1] if earlier else None
    since = None
    if previous:
        old = review if previous == carried else load_review(os.path.join(args.history, previous[1]))
        since = since_last_review(result, {'reviewedOn': old['reviewedOn'], 'known': old['known'],
                                           'decisions': decisions})
    stamp = long_date(run_day)
    print('Still paying? Monthly review for ' + stamp)
    for line in wrap('Read %d export%s from %s.' % (len(files), '' if len(files) == 1 else 's', args.folder)):
        print(line)
    if carried and carried[0] == run_day:
        message = ('%s is from an earlier run for the same date. It will be replaced, keeping its decisions.'
                   % carried[1])
    elif carried:
        message = ('Last review: %s. Carried over its decisions and its %d saved transactions.'
                   % (carried[1], len(review['transactions'])))
    else:
        message = 'No earlier review in %s, so this is the first one.' % args.history
    for line in wrap(message):
        print(line)
    if previous and since is None:
        for line in wrap('%s has no review date, so there is nothing to compare with.' % previous[1]):
            print(line)
    iso_day = iso(run_day)
    changes = changes_markdown(result, decisions, since, previous[1] if since else None)
    outputs = [
        ('review-%s.json' % iso_day, project_file(save_state(analysis, review, decisions, run_day))),
        ('report-%s.html' % iso_day, render_report(analysis, decisions, since=since, show_since=True,
                                                   previous_file=previous[1] if since else None, notes=notes)),
        ('changes-%s.md' % iso_day, changes),
        ('price-history.csv', price_history_csv(result)),
    ]
    os.makedirs(args.history, exist_ok=True)
    for name, text in outputs:
        write_text(os.path.join(args.history, name), text)
    print('')
    for line in wrap_markdown(changes):
        print(line)
    for line in wrap('Wrote to %s: %s.' % (args.history, ', '.join(name for name, _ in outputs))):
        print(line)
    return 0


def cmd_budget(args):
    """Write the budget spreadsheet for the coming months."""
    files, notes = collect_exports(args.paths)
    analysis = run_analysis(files, args.as_of, None)
    if nothing_read(analysis, notes):
        return 2
    write_output(budget_csv(analysis['result'], {}, args.months), args.out)
    return 0


def cmd_template(args):
    """Write the template that shows the layout that always reads cleanly."""
    write_output(template_csv(), args.out)
    return 0


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------

def iso_date(value):
    """An --as-of value as a day number."""
    day = from_iso(value)
    if day is None:
        raise argparse.ArgumentTypeError('use a real date written YYYY-MM-DD, for example 2026-11-28')
    return day


def positive_whole(value):
    """A --months value."""
    if not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError('use a whole number of months, 1 or more')
    return int(value)


def build_parser():
    """The argument parser for every command."""
    parser = argparse.ArgumentParser(
        prog='still_paying.py',
        description='Find every regular payment in your bank exports, check them and plan ahead. '
                    'Everything stays on your computer.')
    commands = parser.add_subparsers(dest='command', metavar='command', required=True)

    scan = commands.add_parser('scan', help='read exports and write the register, budget, calendar, review and report',
                               description='Read bank exports (CSV, TSV, OFX or QIF files, or folders of them) and '
                                           'write regular-payments.csv, budget-12-months.csv, upcoming.ics, '
                                           'review.json and report.html.')
    scan.add_argument('paths', nargs='+', metavar='PATH', help='an export file or a folder of them')
    scan.add_argument('--out', default='still-paying-output', metavar='DIR',
                      help='where to write the files (default: ./still-paying-output)')
    scan.add_argument('--as-of', type=iso_date, metavar='YYYY-MM-DD',
                      help='the review date (default: the day after the latest payment)')
    scan.add_argument('--review', metavar='REVIEW.json',
                      help='a saved review whose transactions, decisions, names and corrections are carried over')
    scan.add_argument('--quiet', action='store_true', help='write the files without printing the report')
    scan.set_defaults(run=cmd_scan)

    monthly = commands.add_parser('monthly', help='the monthly job: compare with your last review',
                                  description='Scan a folder of exports, compare with the latest saved review in the '
                                              'history folder, and write review-, report- and changes- files for '
                                              'this month plus price-history.csv.')
    monthly.add_argument('folder', metavar='FOLDER', help='the folder holding this month\'s exports')
    monthly.add_argument('--history', required=True, metavar='DIR', help='the folder that keeps your reviews')
    monthly.add_argument('--as-of', type=iso_date, metavar='YYYY-MM-DD',
                         help='the review date (default: the day after the latest payment)')
    monthly.set_defaults(run=cmd_monthly)

    budget = commands.add_parser('budget', help='write the month-by-month budget spreadsheet',
                                 description='Write committed spending by category for the coming months as CSV.')
    budget.add_argument('paths', nargs='+', metavar='PATH', help='an export file or a folder of them')
    budget.add_argument('--months', type=positive_whole, default=12, metavar='N', help='how many months (default 12)')
    budget.add_argument('--out', metavar='FILE', help='where to write it (default: the terminal)')
    budget.add_argument('--as-of', type=iso_date, metavar='YYYY-MM-DD',
                        help='the review date (default: the day after the latest payment)')
    budget.set_defaults(run=cmd_budget)

    template = commands.add_parser('template', help='write a CSV template in the layout that always reads cleanly')
    template.add_argument('--out', metavar='FILE', help='where to write it (default: the terminal)')
    template.set_defaults(run=cmd_template)
    return parser


def main(argv=None):
    """Run a command and return its exit code."""
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    args = build_parser().parse_args(argv)
    try:
        return args.run(args)
    except Problem as problem:
        print(problem, file=sys.stderr)
        return 2
