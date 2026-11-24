# Second opinion

**A scam-spotting test that measures how well you use an AI checker's advice, not just how many you get right.**

You judge 28 messages as scams or genuine. For sixteen of them you give your own answer first, then see a simulated AI checker's verdict, then give your final answer. At the end you get a reliance profile: when the checker was right and you were not, did you switch? When you were right and it was wrong, did you hold firm?

- **The browser app** (`app/index.html`) runs the test and explains your results. Double-click it: no installs, no internet, nothing sent anywhere.
- **The Python toolkit** (`second_opinion/`) pools many people's results files, compares groups with bootstrap intervals and permutation tests, and writes an HTML report.

## Open the app

Double-click `app/index.html`. It takes about ten minutes.

## Run the Python toolkit

Python 3.9 or later, standard library only.

```bash
python -m second_opinion synth --n 40 --advice verdict --advice reason --out sessions
python -m second_opinion cohort sessions --html report.html
python -m second_opinion score sessions/<file>.json
```

## Run the tests

```bash
node --test                               # the app's model, in Node.js
python -m unittest discover -s tests      # Python, agreement with the app, and the UI
```
