# Reliance lab

**When a person checks an AI's advice, does the pair do better than either alone?**

"A human will review it" is the standard answer to AI risk. But a reviewer only adds value if they know *when* to trust the AI. Someone who agrees with everything adds nothing, and someone who overrules the AI too often makes things worse. This project lets you measure that on yourself, then shows exactly when a person-plus-AI team can beat both of its members.

There are two parts, built on the same logic:

- **The browser app** (`app/index.html`). Review 12 to 30 synthetic flagged card payments with an AI advisor, see how well you used its advice, and explore the model behind it. One file, no installs, works offline.
- **The Python companion** (`reliance_lab/`). Scores a whole class's downloaded session files at once, prints model reports from the command line, and generates synthetic classes for demos. Standard library only.

## Why it matters

- **AI adoption beyond the pilot.** Pilots usually measure the AI on its own. The deployed system is a person plus the AI, and if the person rubber-stamps or second-guesses it, the promised gain never appears. That is a quiet, under-measured reason pilots fail to scale.
- **Human-AI interaction and over-reliance.** The exercise uses the two-step design from research on AI advice (decide, see the advice, decide again) and reports the two standard measures of appropriate reliance.
- **AI governance.** Article 14 of the EU AI Act asks that people overseeing high-risk AI stay aware of automation bias. This shows what "effective oversight" has to mean in numbers.

## Open the app

Double-click `app/index.html`, or from a terminal:

```bash
open app/index.html        # macOS
xdg-open app/index.html    # Linux
start app\index.html       # Windows
```

## Run the Python companion

Requires Python 3.9 or later. Nothing to install.

```bash
python -m reliance_lab model                          # every reliance rule under the default assumptions
python -m reliance_lab model --human 0.8 --ai 0.8     # change any assumption
python -m reliance_lab score examples/sessions/*.json # score a (synthetic) class
python -m reliance_lab demo-class --out my-class      # make a new synthetic class
```

## Tests

```bash
python -m unittest discover -s tests -t .   # everything (Node.js and Playwright parts skip if missing)
node --test tests/app_model.test.js          # just the browser app's model
```
