# Assurance mix

**Simplified and illustrative. Not legal advice.**

How much AI assurance is enough? The UK regulates AI through existing regulators applying five cross-sector principles, and expects organisations to show their systems are trustworthy through *assurance*: risk and impact assessments, bias audits, testing, audits, certification. The government's own guidance says assurance should be proportionate, with low-risk uses relying on a few techniques and high-risk uses on "a more robust combination". It does not say which combination, or what it costs.

Assurance mix answers that for one AI system. Describe the system and your limits (risk appetite, budget, weeks to go-live) and it searches every combination of 16 assurance techniques to find:

- the **cheapest plan that brings every principle within your appetite**, and why each technique is in it;
- the **lowest-risk plan within your budget**;
- **what each extra pound buys**: every plan that no cheaper plan beats;
- **when it happens**: a timeline from design to go-live against your deadline.

![The app with the CV shortlister example](docs/desktop.png)

## How to run it

**The app.** Download or clone this branch and double-click `app/index.html`. It runs offline in any modern browser, makes no network requests, and needs nothing installed.

**The Python companion** (standard library only, Python 3.9 or later):

```
python3 -m assurance_mix plan --example shortlister
python3 -m assurance_mix portfolio examples/inventory.csv --budget 400
python3 -m assurance_mix techniques
```

**Tests:**

```
node --test tests/*.test.js
python3 -m unittest discover -s tests
```
