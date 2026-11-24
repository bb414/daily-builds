# Range finder

**Size a market or a business case in honest ranges, and find the assumption worth checking first.**

Most market sizes and business cases are a chain of single numbers multiplied together: so many customers, times a share who buy, times how often, times a price. Each number is a guess, and multiplying guesses hides how uncertain the answer really is. Range finder asks for a range you are 90% sure about for every assumption instead, works through 10,000 combinations, and tells you three things:

1. **How wide the honest answer is**, and how far a midpoint-only estimate would have misled you.
2. **Which assumptions drive the uncertainty**, exactly, including how much comes from assumptions moving together.
3. **Which assumption is worth checking before you decide**, and roughly what checking it is worth: a guide to what a pilot or a piece of research should measure.

There are two ways to use it, built on the same engine:

- **The browser app** (`app/index.html`). Double-click it: no installs, no internet connection, every number calculated in the page.
- **The Python package** (`rangefinder/`). The same engine from the command line, with sample and analysis exports, and heavier checks that would be slow in a browser. Standard library only.

![Range finder with the meal-kit market example](docs/app.png)

## Why it exists

Two of the barriers that keep AI pilots from scaling are an unclear return on investment and benefits that are hard to measure. Both are really statements about uncertainty, and both are usually handled badly: a business case gets a single headline number, and the pilot then measures whatever is easiest rather than whatever would change the decision.

Range finder is a small tool for doing that properly. The "AI assistant for a support team" example is a typical case. On reasonable ranges it most likely loses money, but there is a 32% chance it pays, and the assumption worth pinning down first is the share of contacts the assistant resolves on its own. That is the number a pilot should be built to measure, not the number of happy users.

It is also a consulting toolkit. Market sizing is the first thing a case interview or a strategy project asks for, and the same method works for any estimate that multiplies and adds a few drivers.

## Open the app

Double-click `app/index.html`, or from a terminal:

```bash
open app/index.html        # macOS
xdg-open app/index.html    # Linux
start app\index.html       # Windows
```

What you can do in it:

- **Start from an example**: the student meal-kit market, an AI assistant for a support team, or a campus e-bike share. Or open [`examples/textile-reuse.json`](examples/textile-reuse.json) with "Open a model", which measures carbon in tonnes rather than money.
- **Build your own estimate.** Each term multiplies its drivers, and terms are added or taken away. Every driver gets a low and a high value and a kind of range: skewed (for counts, prices and volumes), symmetric, a percentage, even (hard limits), or known exactly.
- **Read the answer**: the most likely range (10th to 90th percentile), the median, the average, the chance of clearing your threshold, and a warning when plugging in midpoints would mislead.
- **See which ranges matter**: a tornado chart and the exact share of the spread from each driver.
- **Decide what to check first**: the expected value of perfect information for each driver, and how often learning it would change the call.
- **Try narrowing a range**: halve a range, cut it to a quarter or pin it down, and see what that does to the answer and to the chance of making the wrong call.
- **Save and share**: download the model as JSON, open it again later, or copy a link that carries the whole estimate. Your last estimate is also kept in the browser.

It works on a phone as well as a desktop, in light and dark mode, and every control can be used with a keyboard. The charts redraw at the screen's real width, so their labels stay readable on a phone.

<img src="docs/phone.png" alt="Range finder on a phone" width="300">

## Run the Python version

Requires Python 3.9 or later. No packages to install. Run these from the folder that contains `rangefinder/`.

```bash
# List the examples, and write one out as a model file you can edit
python -m rangefinder template
python -m rangefinder template ai-assistant -o ai.json

# Analyse a model (from the app's "Download model", or from 'template')
python -m rangefinder run ai.json
python -m rangefinder run ai.json --samples 50000 --threshold 25000 --csv samples.csv --json analysis.json

# What would narrowing each range do? A guide to what a pilot should measure
python -m rangefinder plan ai.json
python -m rangefinder plan ai.json --factor 0      # pin each one down in turn

# Heavier checks: Sobol indices (including interactions) and stability across seeds
python -m rangefinder deep examples/textile-reuse.json

# Run all the tests (the app tests need Node.js; the browser tests need Playwright)
python -m unittest discover -s tests
```

`run` prints the same numbers the app shows. `--csv` writes every sampled combination, one row each, for a spreadsheet or for R. `--json` writes the full analysis.

## What the examples show

These come from the bundled examples, with their invented ranges. They show what the tool does, not facts about any real market.

| Example | Most likely range | Median | Plugging in midpoints | Chance of clearing the threshold | Check first |
|---|---|---|---|---|---|
| Meal kits for students | £109k to £742k a year | £286k | £513k | 58% (of £250k) | Share who would try a meal kit |
| An AI assistant for a support team | -£211k to £132k a year | -£59.2k | -£58.3k | 32% (of £0) | Share it resolves without a person |
| A campus e-bike share | -£59.9k to £159k a year | £25.9k | £60.5k | 63% (of £0) | Rides per bike per day |
| A textile reuse scheme (file in `examples/`) | 17.9 to 79 t CO2e a year | 38.5 t CO2e | 54.6 t CO2e | 47% (of 40 t CO2e) | Emissions avoided per reused item |

Three things stand out:

- **Midpoint estimates overstate.** When several skewed quantities are multiplied, the product of their midpoints sits well above the median. For the meal-kit market it is 79% higher: £513k against a median of £286k. A single-number business case built that way is optimistic by construction.
- **What matters for the range is not always what matters for the decision.** In the AI assistant example, "complaints caused per year" moves the estimate a lot (14% of the spread), but no likely value of it would change the decision much, so pinning it down is worth only about £279. The share of contacts the assistant resolves on its own is worth up to £17.8k, and learning it would change the call 26% of the time.
- **The expected value can favour a call that is more likely to be wrong.** For the textile scheme the average saving (44.9 t) clears the 40-tonne bar, so the call is to scale it up, even though the median (38.5 t) does not and there is a 53% chance of falling short. The upside is bigger than the downside. The app says so in words rather than leaving a contradictory pair of numbers.

`python -m rangefinder deep` on the meal-kit model checks the app's exact variance shares against a separate Sobol calculation (they agree within two percentage points), and shows that about a fifth of the spread (22%) comes from drivers moving together: the share who try and the order frequency matter more in combination than on their own.

## How it works

**The estimate.** A model is a list of terms. Each term is +1 or -1 times the product of its drivers, and the estimate is the sum of the terms. Every driver appears exactly once.

**The ranges.** A driver's low and high values are its 5th and 95th percentiles (a 90% range):

| Kind | Distribution | Good for |
|---|---|---|
| Skewed | Lognormal, fitted so that 90% of values fall between low and high | Counts, prices, volumes: anything positive where being out by a factor is as likely as being out by an amount |
| Symmetric | Normal, fitted the same way | Quantities that can go either way equally |
| Percentage | Logit-normal, so values stay between 0 and 100% | Shares and conversion rates |
| Even | Uniform between low and high (hard limits) | When any value in the range is as likely as any other |
| Known exactly | Fixed at the low value | Fixed numbers and unit conversions |

**Sampling.** 10,000 Latin hypercube samples with a fixed seed: each driver's probability scale is cut into 10,000 equal slices, every slice is used once, and the slices are shuffled independently for each driver. This gives steadier percentiles than plain random sampling, and the fixed seed means the same inputs always give the same answer.

**The tornado.** Each bar is the estimate with one driver at its 10th and then its 90th percentile, and every other driver at its median.

**The share of the spread.** Because every driver appears once and terms only multiply and add, the estimate is a straight line in any single driver once the others are averaged out: E[estimate | driver i] = base + slope_i x (driver i - its mean), where slope_i is the term's sign times the average of the other drivers in that term. So each driver's first-order share of the variance is exactly slope_i² x Var(driver i) / Var(estimate). Whatever is left is the share from drivers moving together.

**The value of information.** With a threshold, going ahead pays (estimate - threshold) and holding off pays nothing. Today's call is whichever has the higher expected payoff. The expected value of perfect information (EVPI) is the average loss from the cases where that call turns out wrong. For a single driver (EVPPI), the same straight-line result gives the expected estimate once that driver is known, so its value is a one-dimensional average over the driver's samples, with no nested simulation. The app also reports how often learning the driver would flip the call.

**Narrowing a range** shrinks one driver's range around its median, on the scale the range is defined on (so a skewed range stays skewed), and reruns everything.

**The Python extras.** `deep` estimates first-order Sobol indices with the Saltelli (2010) estimator and total-effect indices with the Jansen (1999) estimator, from (drivers + 2) x 20,000 runs, and reruns the headline numbers under 20 seeds. `plan` narrows each range in turn and tabulates the effect on the answer and on the decision.

## Which language does what

| Part | Language | What it does | Roughly |
|---|---|---|---|
| Browser app model | JavaScript | Validation, distributions, Latin hypercube sampling, analysis, value of information, narrowing and number formatting, inside `app/index.html` | 390 lines |
| Examples in the app | JavaScript (data) | A copy of `templates.json`, written in by `tools/embed_templates.py` | 220 lines |
| Browser app interface | JavaScript | The editor, the results cards and charts, saving, opening, share links | 590 lines |
| Browser app styling and layout | CSS and HTML | Layout, typography, light and dark colours, phone layout | 250 lines |
| Python package | Python (standard library only) | The same engine, plus text, CSV and JSON reports, the narrowing plan, Sobol indices, seed stability and the command line | 870 lines |
| Examples | JSON | The three built-in examples and the textile reuse model | 140 lines |
| Tests | Python (and a small Node.js runner) | Engine tests, statistical checks against brute force, browser tests in headless Chromium, and tests that run the app's model in Node.js and check it agrees with Python | 780 lines |

The two versions never call each other. What Python adds is the part a browser tab is not built for: Sobol indices from hundreds of thousands of runs, repeated runs under many seeds, a full narrowing plan, and files to feed into other tools.

## How the app and the Python version stay in step

The app's model lives between `/* MODEL START */` and `/* MODEL END */` in `app/index.html`. `tests/test_app.py` runs exactly that code in Node.js (through `tests/run_model.js`) and checks it against the Python package for every example and for edge cases covering every kind of range, negative terms, fixed drivers, odd sample sizes and extreme seeds:

- the examples, constants and labels are identical;
- every sampled value of every driver agrees;
- every number in the analysis agrees, including the value of information and the narrowed ranges;
- validation gives the same problems in the same words, and number formatting gives the same text.

The random number generator and the sampling use the same integer arithmetic in both languages. The only differences come from `exp` and `log`, which different maths libraries can round differently in the last binary digit, so the tests allow a relative difference of one part in a billion.

## Changing the examples

Edit `rangefinder/templates.json`, then run `python tools/embed_templates.py` to copy them into the app. The tests fail if the two copies differ.

## Limitations

- **Drivers are treated as independent.** If two assumptions really move together (a high price and low demand, say), the range will be too narrow or too wide. A future version could let you link drivers.
- **Each driver appears once, and terms only multiply and add.** There is no division and no reuse of a driver in two terms. That restriction is what makes the variance shares and the value of information exact; to divide, enter the reciprocal (for example "per year" instead of "years").
- **The 90% ranges are only as good as the person giving them.** Most people's 90% ranges are too narrow. The tool shows the consequences of the ranges, not whether they are honest.
- **The value of information assumes a simple payoff**: going ahead earns the estimate minus the threshold. Real decisions have staged investments, options to stop, and costs of delay.
- **Share links can get long** for big models, and a link only works for someone who has the app file too.

## What could come next

- Correlated drivers, entered as "these two tend to move together".
- A calibration warm-up: ten questions with known answers so people can see whether their 90% ranges really catch the truth 90% of the time.
- Side-by-side triangulation of a top-down and a bottom-up estimate of the same market.
- An R version of the `deep` checks using the `sensitivity` package, as a cross-check on the Python estimators.

## Files

```
app/index.html                the browser app (open this)
rangefinder/                  the Python package
  templates.json              the built-in examples, shared by both versions
  model.py                    validation, distributions, sampling, analysis, value of information, formatting
  deep.py                     Sobol indices and seed stability
  report.py                   the text report
  __main__.py                 the command line (run, plan, deep, template)
tools/embed_templates.py      copies the examples into the app
tests/                        all the tests
examples/textile-reuse.json   a fourth example, to open in the app or run in Python
docs/                         screenshots
```
