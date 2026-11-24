# Leaderboard luck

**Run a trading challenge thousands of times. How much of the leaderboard is skill, who usually wins, and how much risk should your team take?**

- **The browser app** (`app/index.html`): set your team's skill and risk, the field and the rules, and see your chances, the risk that maximises them, who usually wins, and any single simulated challenge in full. One file, works offline.
- **The Python companion** (`leaderboard_luck/`): the same simulation from the command line, tested to give identical results.

## Open the app

Double-click `app/index.html`.

## Run the Python companion

```bash
python -m leaderboard_luck simulate
python -m leaderboard_luck sample --index 0
```

## Tests

```bash
python -m unittest discover -s tests -t .
node --test tests/app_model.test.js
```
