"""Writes the sample data files in this folder, reproducibly, from the load bearing model.

Run it from anywhere with `python3 data/generate_logbook.py` (add `--out DIR` to write somewhere else). The
same code always writes the same bytes, so the committed files can be checked by regenerating them.

The files
---------
club_logbook.csv
    One season of the invented club, Hollowmere, as its staff would log it: one row per player per session,
    with the columns date, player, position, session, minutes, rpe and injury. It is
    `model.season_logbook({}, 1)` (the model's own default settings, season seed 1) written with
    `model.to_csv`, byte for byte the sample logbook the browser app offers for download. The injury column
    names the session in which an injury happened ("non-contact" or "contact") and is empty otherwise.

jump_tests.csv
    A countermovement-jump test (columns date, player, jump_cm) on every Monday of that logbook for every
    player who is not injured that day, taken before the day's session.

jump_truth.csv
    The hidden parameters that produced each player's jumps (columns player, p0, k1, k2, tau1, tau2), so a
    fitting method such as `python -m loadbearing calibrate` can be checked against the truth.

The method
----------
Injury days come from the season itself: the model is run with its daily arrays kept, and a player whose
status on a Monday is 1 (injured) is not tested. Each player's daily load w(s) is the sum of minutes times
rpe over his logbook rows for that day, exactly as a club would compute it from the CSV. His jump on day t
follows the Banister fitness-fatigue model,

    jump(t) = p0 + k1 * sum_{s<t} w(s) exp(-(t-s)/tau1) - k2 * sum_{s<t} w(s) exp(-(t-s)/tau2) + noise,

with loads before the logbook's first day taken as zero. The hidden parameters are drawn per player from
the model's seeded mulberry32 generator (model.Rng), in squad order:

    p0    normal, mean 38 cm, sd 4 cm
    tau1  normal, mean 40 days, sd 6, clipped to 25 to 60 (fitness fades slowly)
    tau2  normal, mean 7 days, sd 1.5, clipped to 3 to 12 (fatigue fades quickly)
    k1    0.001 cm per unit of load times a log-normal factor (sd 0.25 on the log scale)
    k2    k1 times a fatigue ratio of 2.4 times a log-normal factor (sd 0.15), clipped to 1.5 to 4

so a typical in-season week of about 1,600 units costs about 2 cm of fresh fatigue the next Monday and, held
week after week, builds about 5 cm of net fitness. Measurement noise is normal with an sd of 0.8 cm, and
jumps are rounded to 0.1 cm. The parameters are rounded (p0, tau1 and tau2 to 0.01, k1 and k2 to 1e-7)
before they are used, so jump_truth.csv holds exactly the values that made the data. The exponentials come
from model.det_exp, so the files are the same on every platform.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loadbearing import model  # noqa: E402 (needs the path above)

HEADER = ['date', 'player', 'position', 'session', 'minutes', 'rpe', 'injury']
SEASON_SEED = 1
JUMP_SEED = 20261127
NOISE_SD = 0.8
MONDAY = 0  # day 0 of the logbook (22 June 2026) is a Monday


def logbook():
    """The sample season: its logbook rows and the simulated season behind them."""
    return model.season_logbook({}, SEASON_SEED)


def logbook_text(rows):
    """The logbook as CSV text, exactly as the browser app writes its sample."""
    return model.to_csv(HEADER, [[r[k] for k in HEADER] for r in rows])


def _rounded(x, places):
    """x rounded half up to the given number of decimal places."""
    scale = 10 ** places
    return model.round_half_up(x * scale) / scale


def draw_truth(rng):
    """One player's hidden Banister parameters (rounded, as stored in jump_truth.csv)."""
    p0 = 38 + 4 * rng.normal()
    tau1 = model.clamp(40 + 6 * rng.normal(), 25, 60)
    tau2 = model.clamp(7 + 1.5 * rng.normal(), 3, 12)
    k1 = 0.001 * model.det_exp(0.25 * rng.normal())
    k2 = k1 * model.clamp(2.4 * model.det_exp(0.15 * rng.normal()), 1.5, 4)
    return {'p0': _rounded(p0, 2), 'k1': _rounded(k1, 7), 'k2': _rounded(k2, 7), 'tau1': _rounded(tau1, 2),
            'tau2': _rounded(tau2, 2)}


def daily_loads(rows, names, days):
    """Each player's load per logbook day: minutes times rpe, summed over his rows for that day."""
    index = {n: k for k, n in enumerate(names)}
    loads = [[0.0] * days for _ in names]
    for r in rows:
        day = model.parse_day(r['date']) - model.SEASON_START
        loads[index[r['player']]][day] += r['minutes'] * r['rpe']
    return loads


def banister(truth, loads):
    """The noiseless jump on the morning of every day, from the loads of the days before."""
    d1 = model.det_exp(-1 / truth['tau1'])
    d2 = model.det_exp(-1 / truth['tau2'])
    fitness = fatigue = 0.0
    out = []
    for w in loads:
        out.append(truth['p0'] + truth['k1'] * fitness - truth['k2'] * fatigue)
        fitness = d1 * (fitness + w)
        fatigue = d2 * (fatigue + w)
    return out


def jump_data(lb):
    """Rows of jump_tests.csv and jump_truth.csv for a season from logbook()."""
    players = model.prepare({})['squad']['players']
    names = [p['name'] for p in players]
    status = lb['season']['status']
    loads = daily_loads(lb['rows'], names, model.TOTAL_DAYS)
    truth_rows, tests = [], []
    for p, name in enumerate(names):
        truth = draw_truth(model.Rng(model.hash_seed(JUMP_SEED, p, 1)))
        noise = model.Rng(model.hash_seed(JUMP_SEED, p, 2))
        truth_rows.append([name, f"{truth['p0']:.2f}", f"{truth['k1']:.7f}", f"{truth['k2']:.7f}",
                           f"{truth['tau1']:.2f}", f"{truth['tau2']:.2f}"])
        clean = banister(truth, loads[p])
        for day in range(MONDAY, model.TOTAL_DAYS, 7):
            if status[p][day] == 1:
                continue
            jump = model.round_half_up((clean[day] + NOISE_SD * noise.normal()) * 10)
            tests.append((day, p, [model.format_day(model.SEASON_START + day), name, f'{jump / 10:.1f}']))
    tests.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in tests], truth_rows


def write(path, text):
    """Writes text exactly (UTF-8, newlines as given)."""
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Write the sample logbook and jump-test files.')
    parser.add_argument('--out', default=os.path.dirname(os.path.abspath(__file__)),
                        help='folder to write into (default: the folder holding this script)')
    args = parser.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    lb = logbook()
    tests, truth = jump_data(lb)
    files = {
        'club_logbook.csv': logbook_text(lb['rows']),
        'jump_tests.csv': model.to_csv(['date', 'player', 'jump_cm'], tests),
        'jump_truth.csv': model.to_csv(['player', 'p0', 'k1', 'k2', 'tau1', 'tau2'], truth),
    }
    for name, text in files.items():
        write(os.path.join(args.out, name), text)
        print(f'{name}: {text.count(chr(10)) - 1} rows')
    return 0


if __name__ == '__main__':
    sys.exit(main())
