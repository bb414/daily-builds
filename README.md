# Crutch check

**Does an AI scam checker sharpen people's judgement, or stand in for it?**

A self-contained test that measures how someone uses an AI scam checker. You judge 28 realistic but fictional messages in three rounds: on your own, with a simulated AI checker that is right most of the time but not always, and on your own again. The results show how often you took good advice, how often you were talked out of a right answer, and whether your own judgement improved or slipped once the checker was taken away.

- **The browser app** (`app/index.html`) runs the test. Double-click it: no installs, no internet connection, nothing sent anywhere.
- **The Python package** (`crutch_check/`) scores the sessions the app exports and prints reports, using only the standard library.

## Open the app

Double-click `app/index.html`.

## Run the Python version

```bash
python -m crutch_check demo --persona leaner      # simulate one participant
python -m crutch_check score my-session.json      # report on a session exported from the app
python -m crutch_check csv sessions/ -o answers.csv
python -m unittest discover -s tests              # run the tests
```
