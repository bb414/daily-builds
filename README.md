# Champion Seeding

**You have a handful of champions for a new AI tool. Where should they sit?**

A simulator of how use of a new tool spreads (and fades) through an organisation's network of working relationships, comparing five ways of choosing champions.

- **The browser app** (`app/index.html`): double-click it. No installs, no internet connection.
- **The Python companion** (`champion_seeding/`): the same model from the command line, plus running it on your own anonymised network from CSV files.

## Run

```bash
python -m champion_seeding compare
python -m champion_seeding load --edges examples/edges.csv --teams examples/teams.csv
```

## Tests

```bash
node --test "tests/*.test.js"
python -m unittest discover -s tests
```
