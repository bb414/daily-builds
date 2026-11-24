# Stairstep

**Does the AI forecast earn its place?** A forecast value added (FVA) tool for a synthetic eight-store confectionery chain, plus a Python companion that runs the same analysis on your own sales data.

- **The browser app** (`app/index.html`): double-click it. Six forecasting steps, from "same as last week" to an AI model with planners' overrides, are compared on a year of weekly sales, and each step is judged by how much it cuts the error of the step before it.
- **The Python companion** (`stairstep/`): the same model in the standard library, with a command line, CSV input (see `stairstep/data.py`), and text, CSV, JSON and HTML reports.

## Run it

```bash
python -m stairstep run                       # the synthetic chain
python -m stairstep simulate --out sales.csv  # write its sales as CSV
python -m stairstep run --data sales.csv      # run on a CSV of weekly sales
```

## Tests

```bash
node --test
python -m unittest discover -s tests
```

The tests are in `tests/`; `tests/test_agreement.py` checks that the app and the Python version give the same numbers.
