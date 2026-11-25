# Mislabelled

**How wrong is your budgeting app on day one, and which corrections fix it fastest?**

Budgeting apps use machine learning to sort card payments into pots such as groceries, eating out and bills. On day one the app has never seen your local caf&eacute; and cannot know that you count rent paid to a flatmate as a bill. Mislabelled simulates that cold start: an invented person's statement, a generic categoriser, and five ways for the app to choose which payments to ask the user about.

Educational simulation with invented people, shops and amounts. Not financial advice.

## Open the app

Double-click `app/index.html`. It runs offline in any modern browser.

## Run the Python companion

Standard library only (Python 3.9 or later):

```
python -m mislabelled sample --persona graduate -o sample.csv
python -m mislabelled compare --seeds 20 --out results
python -m mislabelled categorise sample.csv --replay
```

## Tests

```
node --test tests/js/*.test.js
python -m unittest discover -s tests
```
