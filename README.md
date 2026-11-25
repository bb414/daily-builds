# Fit to train

**Is your CRM ready to train an AI win-probability model?**

A sales team wants an AI model that scores every new opportunity with its chance of winning. The pilot trains on the CRM's closed deals, tests on a random quarter of them, and reports a strong result. Then it goes live and disappoints.

Fit to train shows why. It builds a synthetic sales team with two years of deals where the true outcome of every deal is known, then lets you turn up six everyday CRM habits, one at a time or together, and compares three numbers:

- **the pilot's back-test**, measured the way most pilots measure it;
- **live performance**, the same model scoring new deals three weeks in, against how they really ended;
- **the clean-data ceiling**, the same method on a perfectly kept CRM.

There are two ways to use it, built on the same model:

- **The browser app** (`app/index.html`) is the lab. Double-click it: no installs, no internet connection, nothing sent anywhere.
- **The Python package** (`fittotrain/`) runs the same lab from the command line with identical numbers, writes synthetic CRM exports, and audits your own anonymised opportunity export for the same problems. Standard library only.

## Why it matters

The question behind this project is why AI so often stalls at the pilot stage. Executive interviews keep naming unclear ROI, benefits that are hard to measure and technical complexity. In sales, one concrete mechanism sits under all three: the CRM data that a pilot trains and tests on is not the data the model meets after go-live. Fields are filled in after the outcome is known, lost deals are never closed, stalled deals are re-entered, amounts are placeholders, and logging changes when new tools arrive. A back-test on that data can promise far more than the model will deliver, and the shortfall only shows up months later, after the budget decision.

That makes it a sales operations and CRM analytics problem as much as a data science one: the people who own the CRM's processes decide whether a pilot's result can be trusted.

## The six habits

| Habit | Kind of damage | What it does in the data |
|-------|----------------|--------------------------|
| Blank fields | Missing data | Scoring fields left empty at entry; the model fills them with the average |
| Fields edited after the outcome | Leakage | Win reviews set "champion identified" and stakeholder counts after a win; loss reasons set "competitor present" after a loss |
| Zombie deals | Missing labels | Lost deals never closed out, so they never reach the training set |
| Re-created deals | Wrong labels | A stalled deal is re-entered as a new opportunity and the old record is closed as lost: a fake loss that looks like a win |
| Placeholder amounts | Biased values | Round amounts entered early and corrected only when a deal is won |
| Meetings logged by hand | Drift | Hand logging missed meetings before go-live; calendar sync logs them all afterwards |

## How to run it

### The browser app

Download or clone this branch and double-click `app/index.html`. Or from a terminal:

```bash
git clone --branch build/2026-11-25-fit-to-train https://github.com/bb414/daily-builds.git fit-to-train
cd fit-to-train
open app/index.html        # macOS
xdg-open app/index.html    # Linux
start app\index.html       # Windows
```

### The Python companion

Python 3.9 or later, no packages to install. From the project folder:

```bash
python -m fittotrain lab --preset typical                   # the lab, same numbers as the app
python -m fittotrain lab --set retrofill=0.6 --seed 7 --json
python -m fittotrain generate --preset chaos -o crm.csv --truth truth.csv
python -m fittotrain audit crm.csv                          # audit an export (yours or a synthetic one)
python -m fittotrain lab --worlds 12 --preset typical       # what holds across 12 other worlds
python -m fittotrain sweep retrofill --out reports          # one habit from 0 to its maximum: CSV and HTML
python -m fittotrain lab --settings fit-to-train-settings.json   # a settings file saved from the app
```

`audit` reads a CSV with these columns. Only the first six are required; any scoring field can be missing or blank.

| Column | Meaning |
|--------|---------|
| `opportunity_id`, `account_name` | Any identifiers (anonymise before use) |
| `created_date`, `close_date` | YYYY-MM-DD; for open deals, the expected close date |
| `status` | won, lost or open (also "closed won" and "closed lost") |
| `amount` | Deal value; currency symbols and commas are fine |
| `owner`, `segment`, `source` | Optional; segment is SMB, Mid-market or Enterprise; source is Inbound, Outbound, Partner or Event |
| `stakeholders`, `meetings_first_3_weeks`, `champion`, `competitor`, `discount_pct`, `days_to_first_meeting` | Optional scoring fields; champion and competitor are yes or no |
| `edited_after_close` | Optional yes or no from field history; enables the leak check |

### Tests

```bash
python -m unittest discover -s tests -v    # Python, parity with the app, CLI, and the UI if Playwright is installed
node tests/test_model.js                   # the app's model in Node.js
```

## How it works

1. **A true world.** Seeded random numbers generate 12 reps and up to 8,000 deals over two years. Each deal has a segment, source, amount and six scoring fields, and wins or loses with a known probability. The model goes live after 18 months.
2. **The CRM as recorded.** Each habit has its own random stream, so changing one leaves the others exactly as they were.
3. **The pilot.** A ridge-penalised logistic regression is trained on closed deals in the history and tested on a random 25% of them.
4. **Go-live.** The same model scores every deal created in the last six months, three weeks after creation, using the fields as they stood then; the true outcomes judge it.
5. **The audit.** Six checks a CRM owner can run without knowing the truth, shown next to what really happened.
6. **Which habit to fix first.** The pilot is re-run with each habit fixed on its own, then with the habits fixed one after another in order of live gain, until the CRM is spotless and the live score lands exactly on the clean ceiling.
7. **An honest back-test.** Four repairs anyone can make from the CRM alone (blank the fields that can be edited after closing on records that were, close out deals long past their close date, drop lost deals that copy a win, treat round amounts as unknown), then the same back-test again.

## Limitations

- The world is synthetic and the habits are stylised. Real CRMs mix them in ways this model does not try to capture, and real win-probability models use far more signals.
- AUC on a few hundred test deals is noisy: on a single world the back-test can sit a few hundredths above or below live even with a spotless CRM.

## Next steps

See the report at the end of the build for ideas.
