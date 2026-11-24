# Reliance Lab

**Helper or crutch? What does AI advice do to people's own judgement?**

An interactive simulator of people making yes-or-no decisions (is this message a scam? is this invoice fraudulent?) with an AI adviser on hand. Choose how the AI is built into the work, set how good the people and the AI are, and watch accuracy, trust and each person's unaided judgement change case by case. Every run is compared with a matching group who practised without the AI, so the app can say whether the AI was a helper or a crutch.

- **The browser app** (`app/index.html`): open the file and it works. No installs, no internet connection, nothing sent anywhere.
- **The Python companion** (`reliance_lab/`): runs the same model from the command line, and adds a virtual randomised experiment with noisy tests and a power analysis.

![Reliance Lab on a desktop](docs/desktop.png)

## Why it exists

Over-reliance is one of the quieter reasons AI stalls after the pilot. A pilot measures how accurate people are *with* the tool. It rarely measures what happens to their own judgement, or how they cope when the tool is wrong, changes or is taken away. This model makes those effects visible and adjustable.

## Open the app

Double-click `app/index.html`.

## Run the Python version

Python 3.9 or later, standard library only.

```bash
python -m reliance_lab run
python -m reliance_lab experiment
python -m reliance_lab power
```

## Tests

```bash
node --test "tests/*.test.js"
python -m unittest discover -s tests
```
