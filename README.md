# Range finder

**Size a market or a business case in honest ranges, and find the assumption worth checking first.**

Instead of one number per assumption, give a range you are 90% sure about. Range finder samples every combination, shows the likely range of the answer, and ranks which assumption drives the uncertainty.

- **The browser app** (`app/index.html`): double-click it. No installs, no internet connection.
- **The Python package** (`rangefinder/`): the same engine from the command line. Standard library only.

```bash
python -m rangefinder template meal-kits -o model.json
python -m rangefinder run model.json
python -m unittest discover -s tests
```
