# Clean hours

**When should the AI run? Carbon-aware scheduling for AI compute, and the gap between the saving you can report and the saving the grid actually sees.**

Clean hours takes a fleet of AI compute jobs (fine-tunes, retrains, nightly embedding refreshes, evaluation suites) and an invented electricity grid with a year of hourly weather, demand and power stations. It moves the flexible jobs into "cleaner" hours using five different schedulers, then scores every choice twice:

- **Reported saving:** what a carbon report would show, using the grid's *average* intensity in each hour (the location-based method most company reports use).
- **Real saving:** what changes in the atmosphere, using the *marginal* intensity: the emissions of the power station that actually ramps up to serve the extra load.

The two can disagree in size and even in sign, and the three example grids are chosen to show each case.

There are two parts built on the same model:

- **The browser app** (`app/index.html`): one self-contained file. Double-click it and it runs offline, with no installs and nothing sent anywhere.
- **The Python companion** (`cleanhours/`): a command-line tool that runs a year on your own jobs file, exports the full hourly grid and per-job results as CSV, and sweeps hundreds of combinations of grid, weather year and settings. Standard library only.

## Why it matters

AI's electricity use is growing fast, and "carbon-aware computing" (running flexible jobs when the grid is cleanest) is a popular pilot. It is also a neat example of why AI-related initiatives stall between pilot and scale: **the benefit is hard to measure, and the obvious measure can be wrong.** A team that schedules on the published average-intensity signal can report a healthy cut while the real effect is much smaller, or even negative. A sceptical finance or sustainability lead who asks "what did it actually change?" will not get a straight answer from the reported number.

It links to two of the brief's themes: sustainability and carbon (green forecasting, as covered at the Mannheim summer school), and AI adoption beyond the pilot (unclear ROI and hard-to-measure benefits block scaling).

## How to open the app

1. Download the branch (on GitHub: **Code**, then **Download ZIP**) and unzip it.
2. Double-click `app/index.html`. It opens in any modern browser and works offline.

## How to run the Python companion

Needs Python 3.9 or later and nothing else. From the folder that contains `cleanhours/`:

```sh
python -m cleanhours run                       # the windy grid and the example fleet
python -m cleanhours run --preset coal --out results
python -m cleanhours template --out jobs.csv   # write the example fleet, then edit it
python -m cleanhours run --jobs jobs.csv --slack 2 --out results
python -m cleanhours sweep --seeds 1-10 --wind 0.5,1,2 --out sweep-output
```

`run --out` writes `summary.md`, `schedulers.csv`, `jobs.csv` (each job under each scheduler) and `grid_hours.csv` (all 8,736 hours). `sweep` writes `sweep.csv` and a Markdown summary of medians across every combination. Use `--help` on any command for every option.

## Tests

```sh
node --test                              # the browser app's model in Node.js
python -m unittest discover -s tests     # Python model, CLI, parity with the app, and the UI in headless Chromium
```

The parity test runs the app's model in Node.js and checks that the Python companion gives bit-for-bit identical numbers. The UI tests need Playwright for Python and are skipped without it.

## Limitations

- Simplified and illustrative. The grids, weather and jobs are invented and not calibrated to any real country or company.
- Short-run marginal emissions only. Longer-run effects, such as flexible demand making it easier to build more renewables, are left out.
- The jobs are treated as small next to the grid, so they never change which plant runs.
- No interconnectors, storage, network constraints, or switching between coal and gas as carbon prices change.
