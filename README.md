# Save or sink

**Does automatic saving leave a student better off, or just push them into their overdraft?**

Stress-tests automatic saving rules (round-ups, a fixed amount every week, a share of every payment, and a "smart" saver that forecasts what is safe to save) against hundreds of synthetic student years.

- **The browser app** (`app/index.html`): double-click it. No installs, no internet connection.
- **The Python package** (`saveorsink/`): the same engine from the command line. Standard library only.

```bash
python -m saveorsink run
python -m unittest discover -s tests
```
