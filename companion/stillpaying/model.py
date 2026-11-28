"""One call for the whole job, and the compact summary used to check agreement with the browser app."""

from .dates import iso
from .detect import find_regulars
from .merging import link_same_accounts, merge_statements
from .parsing import finish_range, parse_statement


def analyse(files=None, as_of=None, extra=None, aliases=None, names=None, manual=None, overrides=None):
    """Read every file, merge them, find the regular payments and describe them.

    files is a list of {'name', 'text'} with optional 'account' (a name the
    user chose, which stops the file being relabelled) and 'options' (see
    parse_csv). extra holds transactions from a saved review. as_of is a day
    number (default: the day after the latest transaction). Returns
    {'statements', 'merged', 'result'}.
    """
    statements = []
    for f in files or []:
        opts = dict(f.get('options') or {})
        if f.get('account'):
            opts['account'] = f['account']
        st = parse_statement(f.get('text'), f.get('name'), opts)
        st['accountGiven'] = bool(f.get('account'))
        statements.append(st)
    pseudo = []
    if extra:
        # Saved transactions can cover several accounts; split them so coverage stays per account.
        by_account = {}
        for t in extra:
            by_account.setdefault(t['account'], []).append(t)
        for account in sorted(by_account):
            st = {'name': 'saved review', 'account': account, 'transactions': by_account[account]}
            finish_range(st)
            pseudo.append(st)
    linked = link_same_accounts(pseudo + statements)
    merged = merge_statements(pseudo + statements)
    merged['linked'] = linked
    result = find_regulars(merged['transactions'], as_of=as_of, aliases=aliases, names=names, manual=manual,
                           overrides=overrides)
    return {'statements': statements, 'merged': merged, 'result': result}


def _pick(s):
    return {
        'id': s['id'], 'name': s['name'], 'cadence': s['cadence'], 'count': s['count'], 'first': iso(s['first']),
        'last': iso(s['last']), 'typical': s['typical'], 'monthly': s['monthly'], 'annual': s['annual'],
        'kind': s['amounts']['kind'], 'status': s['status'],
        'nextDue': None if s['nextDue'] is None else iso(s['nextDue']), 'method': s['method'],
        'category': s['category'], 'confidence': s['confidence'], 'flags': [f['id'] for f in s['flags']],
    }


def summary(result):
    """A compact, stable summary of a result, the same as the browser model's summary()."""
    payday = result['payday']
    return {
        'asOf': iso(result['asOf']), 'series': [_pick(s) for s in result['series']],
        'income': [_pick(s) for s in result['income']],
        'candidates': [{'id': c['id'], 'cadence': c['cadence'], 'amount': c['amount']} for c in result['candidates']],
        'payday': {'id': payday['seriesId'], 'next': iso(payday['next'])} if payday else None,
    }
