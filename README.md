# Stairstep

**Does the AI forecast earn its place?**

A forecast value added (FVA) tool for a synthetic Singapore confectionery chain: eight stores, twelve products, three years of weekly sales. Six ways of forecasting next week's sales are lined up from the simplest to the most elaborate, and each step is judged by one question: *did it cut the error of the step before it?* The answer is shown product by product, festival by festival, override by override, and for the kind of short pilot most firms would run before deciding.

There are two parts, built on the same model:

- **The browser app** (`app/index.html`). Double-click it: no installs, no internet connection, every number calculated in the page.
- **The Python companion** (`stairstep/`). The same model in the standard library, with a command line that runs on your own sales CSV, checks the conclusions across many synthetic worlds, and writes text, CSV, JSON and HTML reports.

![The answer and the stairstep under the default settings](docs/overview.png)

## Why it matters

Research interviews on AI transformation keep returning to the same barriers to scaling: **unclear ROI and benefits that are hard to measure**. Demand forecasting is one of the most common AI pilots in retail, and it is a place where the benefit *can* be measured properly. Forecast value added is the standard way to do it: compare every step of the forecasting process with a naive baseline and with the step before, and keep only the steps that earn their place.

The model makes three things about AI pilots concrete:

- **The value is concentrated.** The AI earns its keep on festival products and promotions, where simple methods are blind. On steady products a moving average is nearly as good.
- **People can give the value back.** Planners who override the AI with an optimistic lean make it worse on average, while their downward overrides help.
- **A pilot can measure the wrong thing.** A short pilot that misses the big festivals measures a fraction of the real gain; one that covers Chinese New Year can overstate it. Choosing where to use the AI on the months before the test year picks it for only a third of the products, and does worse than using it everywhere.

It also connects to running a confectionery business on demand-forecasting and ROI models, and to forecasting and explainable-AI work from the Mannheim summer school.

## Open the app

Download or clone this branch, then double-click `app/index.html`. Or from a terminal:

```bash
open app/index.html        # macOS
xdg-open app/index.html    # Linux
start app\index.html       # Windows
```

What you can do in it:

- **Change the world.** Festival strength, promotion lift, random noise, growth, and the world number (seed) for a different random chain.
- **Change the forecasting and the people.** How many weeks ahead forecasts are made; how often planners override the AI, how optimistic they are, and how much real local knowledge they have; how much safety stock is ordered; and how big a gain the AI must show to be worth using.
- **Read the answer.** A headline, the stairstep chart with each step's change in error, stock wasted and sales met for each step, and a verdict for every product.
- **See the honest decision.** "Deciding in advance" compares the verdicts made with hindsight against choices made on the 28 weeks before the test year, and names the festivals those weeks did and did not include.
- **Test a pilot.** Pick a pilot length (8, 13 or 26 weeks) and which stores, and see what a pilot starting in each week of the year would have measured.
- **Look at one product** in one store or all stores, with festival weeks shaded and promotions marked.
- **Share and keep.** Settings live in the page address, so "Copy a link to these settings" reopens the same world. Download every forecast as CSV or the results as JSON, and load a results file's settings back in.

On a phone the settings fold away so the answer comes first, and every control works from the keyboard.

![Deciding in advance, and what a pilot would have measured](docs/pilot.png)

![The app on a phone](docs/phone.png)

## Run the Python companion

Requires Python 3.9 or later. No packages to install. Run these from the folder that contains `stairstep/`.

```bash
# The synthetic chain under the default settings, as a text report
python -m stairstep run

# The same, plus an HTML report, every forecast as CSV, and the results as JSON
python -m stairstep run --html report.html --csv forecasts.csv --json results.json

# Change the world or the planners (every option is listed by --help)
python -m stairstep run --holidays 0 --promo-lift 0
python -m stairstep run --override-rate 0.6 --optimism 0.2

# Reuse the settings from a results file downloaded from the app
python -m stairstep run --settings stairstep-results-world-7.json

# Run on your own weekly sales (format below), or try it on a synthetic export first
python -m stairstep simulate --out sales.csv
python -m stairstep run --data sales.csv

# How often do the conclusions hold across 30 different worlds?
python -m stairstep sweep --worlds 30 --csv worlds.csv
```

Pre-generated outputs: [`examples/report.html`](examples/report.html) (the default world), and [`examples/sweep-30-worlds.txt`](examples/sweep-30-worlds.txt) with one row per world in [`examples/sweep-30-worlds.csv`](examples/sweep-30-worlds.csv) (from the last command above).

**Your own data.** A CSV with one row per product, store and week: `week,store,product,units`, plus an optional `promo` column (1 in promotion weeks) and any number of `event_<name>` columns (1 in weeks affected by that festival or event), each of which becomes a feature of the AI model. Weeks run from 1 with no gaps, and at least 120 are needed; the last 52 are the test year. Details are at the top of [`stairstep/data.py`](stairstep/data.py). A synthetic chain written out with `simulate` and read back with `--data` gives exactly the same numbers.

## Run the tests

```bash
node --test                               # the app's model, run in Node.js
python -m unittest discover -s tests      # Python, agreement with the app, and the app itself in a browser
```

The browser tests need Playwright with Chromium (`pip install -r requirements-dev.txt`, then `python -m playwright install chromium`) and are skipped without it; the agreement tests need Node.js and are skipped without it.

## Which language does what

| Part | Language | Roughly | What it does |
|---|---|---|---|
| `app/index.html` | HTML, CSS, JavaScript | 1,500 lines: 200 of styles, 650 of model, 620 of interface | The whole analysis for the synthetic chain, interactive, in one offline file |
| `stairstep/` | Python | 1,150 lines | The same model line for line, CSV input for real data, the robustness sweep, and text, CSV, JSON and HTML reports |
| `tests/` | Python and JavaScript | 840 lines | Unit tests for both, agreement tests, and browser tests |

The app is for exploring one world at a time. Python does what a page cannot do well: run on a company's own sales file, run dozens of worlds in a batch, and write reports to keep. Because the model exists in both languages, `tests/test_agreement.py` runs the app's own model block in Node.js and checks that it produces **exactly** the same sales, the same forecasts from every method (bit for bit), the same pilot windows and the same results as Python across four very different scenarios. The browser test also checks that the forecasts CSV downloaded from the app is byte-for-byte the same file Python writes.

## How it works

**The chain** (`simulate`). Twelve products with their own base sales, festival peaks and promotion habits: pineapple tarts and kueh bangkit peak before Chinese New Year, kueh lapis and almond londons for Hari Raya Puasa, murukku for Deepavali, gingerbread for Christmas, truffles for Valentine's Day and Christmas; gummy bears and butter mints have no festival. Eight stores differ in size. Weekly sales combine a school-holiday pattern, growth, festival effects, chain-wide promotions with a dip the week after, and noise. Chinese New Year, Hari Raya and Deepavali move from year to year, as they do in real life. Everything uses only addition, multiplication, division and rounding, so Python can reproduce it exactly.

**The six steps**, each forecasting week *t* from what was known *h* weeks earlier:

| Step | Forecast |
|---|---|
| Naive | Sales *h* weeks ago |
| Moving average | The average of the eight weeks up to *h* weeks ago |
| Seasonal naive | The same week last year |
| Seasonal smoothing | Exponential smoothing of the level with a weekly seasonal pattern (Holt-Winters without a trend), started from the first year |
| AI model | A ridge regression per product, trained on every store, refitted every four weeks on everything known by then. Its features are recent sales, the same week last year, promotions, the festival calendar and whether last year's week was a festival week, all as ratios to the store's own average |
| AI + planners | The AI forecast after planners' overrides. A planner overrides a share of forecasts; each override moves the forecast towards the true figure by the planner's insight, adds their own noise, and leans upwards by their optimism. Their random draws come from a separate stream, so changing the planners never changes the sales |

A test checks that no step can see the future: changing sales after a forecast is made leaves that forecast unchanged. The planners' insight is the exception by design: it stands for local knowledge, such as a school event, that the data does not hold.

**Scoring** (`evaluate`), over the 52 weeks of the third year: error is WAPE, the total absolute error as a share of total sales; bias is the total error with its sign; value added is the fall in WAPE from the naive step, or from the step before. Stock is ordered at the forecast plus a safety buffer and anything unsold is wasted after a week, which turns errors into unsold units, lost sales and the share of demand met. Each product's verdict compares the AI with its best simple method; "chosen in advance" makes the same choice on the 28 weeks before the test year instead. A pilot window is the same comparison restricted to some stores and some weeks.

## What it finds

Under the default settings (world 7):

| Step | Error | Unsold units | Sales met |
|---|---|---|---|
| Naive | 37.4% | 24,767 | 85.2% |
| Moving average | 29.8% | 20,304 | 88.7% |
| Seasonal naive | 37.3% | 21,131 | 82.4% |
| Seasonal smoothing | 30.8% | 22,153 | 89.1% |
| AI model | 21.4% | 15,423 | 93.0% |
| AI + planners | 21.8% | 18,231 | 94.1% |

- **The AI earns its place, mostly on festivals and promotions.** It cuts error by 8.4 points against the best simple method (the moving average) and is worth using on 11 of 12 products. In festival weeks it takes error from 33.4% to 22.4%, and in promotion weeks from 34.9% to 19.7%; in ordinary weeks the gain is under 3 points. Butter mints, which have no festival, keep the moving average. Turn festivals and promotions off and the AI clears the 3-point bar on none of the products.
- **Planners give some of it back.** Their 1,157 upward overrides add 2.2 points of error on the forecasts they touch; their 365 downward overrides remove 3.3 points. Keeping only the downward overrides would give 21.2%, better than the AI alone. The optimistic lean also shows up as stock: the planners' step wastes 2,808 more units than the AI alone.
- **Deciding in advance is harder than it looks.** The 28 weeks before the test year include Deepavali and Christmas but not Chinese New Year, Valentine's Day or Hari Raya. Judged on those weeks the AI is picked for only 4 products (pineapple tarts, murukku, gummy bears and mochi), and that mix scores 24.8%, worse than the AI everywhere.
- **A short pilot is a lottery on timing.** A 13-week pilot in all eight stores would have measured the AI's gain at anywhere from 3.2 points (starting in week 37) to 14.0 points (starting in week 4, over Chinese New Year), against 8.4 for the whole year.

Across 30 worlds ([`examples/sweep-30-worlds.txt`](examples/sweep-30-worlds.txt)) the conclusions hold almost every time: the AI beats the best simple method by 6.8 to 9.3 points in all 30; planners make it worse, and keeping only downward overrides beats it, in all 30; choosing in advance does worse than the AI everywhere in all 30; and in 29 of 30 some 13-week pilot would measure under half the full-year gain while another would measure over one and a half times it.

These are properties of a synthetic chain built on stated assumptions, not evidence about any real business. The point is the method, and how much the answer depends on what you measure and when.

## Limitations

- **Synthetic data.** The chain, its festivals and its planners are invented. The planner model in particular is a simple stand-in for real behaviour, although the pattern it produces (upward adjustments hurt, downward ones help) is the one forecasting research has reported in real companies.
- **One kind of AI.** The "AI model" is a regularised regression with good features. A gradient-boosted or neural model might do better or worse; the method for judging it would be the same.
- **Point forecasts only.** There are no prediction intervals, and stock is set with a simple percentage buffer rather than an optimised safety stock.
- **One error measure.** WAPE weights big products more than small ones. Other measures (scaled errors, or errors weighted by margin) can change verdicts for small products such as the gift box.
- **The validation window is fixed** at up to 28 weeks before the test year; a rolling or full-year validation would choose differently.

## What could come next

- Prediction intervals and a newsvendor stock rule, so each step's value is measured in waste and lost sales at the best buffer for that step.
- A pilot design helper that recommends the length and timing a pilot needs to estimate the gain within a chosen margin.
- A store that opens part-way through the history, to show how each method copes with a short record.
