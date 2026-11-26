"""Generate the bundled synthetic dataset: a year of daily prices and sales in 40 invented markets.

Each market has two invented online sellers of a similar chocolate gift box. Its hidden set-up (how
the sellers price, how loyal shoppers are) is drawn by the same case-file recipe the browser app uses,
so building a case file in the app with seed 2026 and 40 markets gives exactly these markets.

For every market the script
  1. trains the sellers' pricing (Q-learning or a fixed rule) until their strategies settle,
  2. records 365 days of prices, with each seller testing a random price on about 3% of days,
  3. simulates every shopper's choice each day from the logit demand model (buy A, buy B or neither).

Outputs
  data/markets.csv        one row per market and day: what a regulator could ask the sellers for
  data/markets_truth.csv  one row per market: the hidden truth, for scoring screens
  app/index.html          the sample markets offered on the "Your prices" tab (unless --no-samples)

Usage
  python data/generate_markets.py [--markets 40] [--seed 2026] [--days 365] [--test-rate 0.03] [--out data]
                                  [--no-samples]

Everything is seeded, so the same arguments always give the same files.
"""

import argparse
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from quiet_cartel import model as M  # noqa: E402

WEEKDAY = [0.9, 0.95, 0.95, 1.0, 1.1, 1.25, 1.2]   # Monday to Sunday: weekends are busier
BASE_SHOPPERS = 1000
SAMPLE_SETUPS = ['baseline', 'vendor', 'none', 'myopic', 'fixedrival', 'matcher', 'own', 'noisy']
LABELS = {sc['id']: sc['label'] for sc in M.SCENARIOS}


def shoppers_on(rng, day):
    """Shoppers visiting the market on a given day (0 = a Monday)."""
    base = BASE_SHOPPERS * WEEKDAY[day % 7]
    return int(base * (0.9 + 0.2 * rng.next()))


def sell(rng, shoppers, share_a, share_b):
    """Each shopper buys from A, from B or from neither, with the logit probabilities."""
    a = b = 0
    cut = share_a + share_b
    for _ in range(shoppers):
        u = rng.next()
        if u < share_a:
            a += 1
        elif u < cut:
            b += 1
    return a, b


def build_market(k, seed, days, test_rate):
    meta = M.case_config(M.default_config(), k, seed)
    tr = M.train(meta['cfg'])
    case = M.finish_case(tr, meta, {'days': days, 'experiment': test_rate})
    mk = tr.market
    rng = M.Rng(meta['cfg']['seed'] * 31 + 7)
    noise = meta['cfg']['demandNoise']
    rows = []
    for d in range(days):
        pa, pb = case['prices'][0][d], case['prices'][1][d]
        quality = list(mk['quality'])
        if noise > 0:
            shock = M.SHOCKS[rng.int(len(M.SHOCKS))] * noise
            quality = [q + shock for q in quality]
        sa, sb = M.shares([pa, pb], quality, mk['outside'], mk['mu'])
        n = shoppers_on(rng, d)
        ua, ub = sell(rng, n, sa, sb)
        rows.append({
            'market': case['id'], 'day': d + 1, 'shoppers': n,
            'price_a': round(pa, 4), 'price_b': round(pb, 4),
            'units_a': ua, 'units_b': ub,
            'cost_a': mk['cost'][0], 'cost_b': mk['cost'][1],
        })
    t = case['truth']
    truth = {
        'market': case['id'], 'setup': case['scenario'], 'setup_label': LABELS[case['scenario']],
        'mu': case['mu'], 'training_seed': case['seed'],
        'profit_gain': round(t['gain'], 4), 'punished': int(bool(t['punished'])),
        'coordinated': int(bool(t['coordinated'])), 'high_price': int(bool(t['highPrice'])),
        'competitive_price': round(case['competitive'][0], 4), 'monopoly_price': round(case['monopoly'][0], 4),
    }
    return rows, truth, case


def truth_sentence(truth):
    words = truth['setup_label'] + '; profit gain ' + str(round(truth['profit_gain'] * 100)) + '%; '
    words += 'a cut is punished' if truth['punished'] else 'a cut is not punished'
    if truth['coordinated']:
        words += '. A case under the "held up by a threat" definition.'
    elif truth['high_price']:
        words += '. High prices, but nothing holds them up: not a case under the threat definition.'
    else:
        words += '. Not a case under either definition.'
    return words


def write_samples(cases, truths, html_path):
    picked, used = [], set()
    for setup in SAMPLE_SETUPS:
        for case, truth in zip(cases, truths):
            if truth['setup'] == setup and case['id'] not in used:
                picked.append((case, truth))
                used.add(case['id'])
                break
    picked.sort(key=lambda ct: ct[0]['id'])
    samples = [{
        'label': 'Market ' + str(case['id']) + ' from the dataset',
        'market': case['id'],
        'cost': [1, 1],
        'price_a': [round(p, 4) for p in case['prices'][0]],
        'price_b': [round(p, 4) for p in case['prices'][1]],
        'truth': truth_sentence(truth),
    } for case, truth in picked]
    with open(html_path, encoding='utf-8') as f:
        html = f.read()
    start, end = '/* SAMPLES START */', '/* SAMPLES END */'
    i, j = html.index(start) + len(start), html.index(end)
    block = '\nwindow.QC_SAMPLES = ' + json.dumps(samples, separators=(',', ':')) + ';\n'
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html[:i] + block + html[j:])
    return len(samples)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--markets', type=int, default=40)
    ap.add_argument('--seed', type=int, default=2026)
    ap.add_argument('--days', type=int, default=365)
    ap.add_argument('--test-rate', type=float, default=0.03, help='share of days each seller tests a random price')
    ap.add_argument('--out', default=HERE, help='folder for the CSV files (default: data/)')
    ap.add_argument('--no-samples', action='store_true', help='do not refresh the samples in app/index.html')
    args = ap.parse_args(argv)
    if not 1 <= args.markets <= 500 or not 30 <= args.days <= 3650:
        ap.error('use 1 to 500 markets and 30 to 3650 days')
    if not 0 <= args.test_rate <= 1:
        ap.error('--test-rate is a share of days, from 0 to 1')

    all_rows, truths, cases = [], [], []
    for k in range(args.markets):
        rows, truth, case = build_market(k, args.seed, args.days, args.test_rate)
        all_rows.extend(rows)
        truths.append(truth)
        cases.append(case)
        print('market %2d  %-38s gain %5.1f%%  %s' % (truth['market'], truth['setup_label'], truth['profit_gain'] * 100,
                                                    'threat' if truth['coordinated'] else ''), flush=True)

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, 'markets.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0]))
        w.writeheader()
        w.writerows(all_rows)
    with open(os.path.join(args.out, 'markets_truth.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(truths[0]))
        w.writeheader()
        w.writerows(truths)
    print('wrote %d rows for %d markets' % (len(all_rows), len(truths)))
    if not args.no_samples:
        n = write_samples(cases, truths, os.path.join(ROOT, 'app', 'index.html'))
        print('refreshed %d sample markets in app/index.html' % n)


if __name__ == '__main__':
    main()
