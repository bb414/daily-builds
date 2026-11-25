# Assurance mix: CV shortlister

Simplified and illustrative, not legal advice. Costs, durations and coverages are illustrative judgements.

## The system

| Question | Answer |
|---|---|
| What does its output decide? | Decides access to jobs, credit or services |
| How much does a person check? | A person signs off each output |
| What kind of model is it? | A machine-learning model |
| What data does it use? | Personal data |
| Who is affected? | The public, including vulnerable people |
| Where does it come from? | Bought in, outputs only |
| Does it change after go-live? | Retrained from time to time |
| How far is it being rolled out? | Limited roll-out |

Appetite 8.0, budget £150k, deadline 20 weeks. 7,680 valid combinations of 15 usable techniques searched.

## Risk before assurance

| Principle | Likelihood | Impact | Score | Band |
|---|---:|---:|---:|---|
| Safety, security and robustness | 3.0 | 2.5 | 7.5 | Medium |
| Appropriate transparency and explainability | 4.5 | 4.5 | 20.3 | Very high |
| Fairness | 4.5 | 4.5 | 20.3 | Very high |
| Accountability and governance | 3.5 | 3.5 | 12.3 | High |
| Contestability and redress | 1.5 | 4.5 | 6.8 | Medium |

## Plans

### Cheapest plan that meets your appetite: £105k, 11 techniques, live in 9 weeks (meets appetite, within budget)

| Technique | Stage | Cost | Why it is there |
|---|---|---:|---|
| Risk assessment | Design | £4k | Without it, Transparency rises to 8.7, above appetite |
| Algorithmic impact assessment | Design | £9k | Without it, Transparency rises to 9.0, above appetite |
| Data protection impact assessment | Design | £6k | Required: the system uses personal data |
| Model and data documentation | Design | £6k | Without it, Transparency rises to 9.1, above appetite |
| Supplier due diligence | Design | £5k | Without it, Transparency rises to 9.2, above appetite |
| Internal bias audit | Before go-live | £10k | Without it, Transparency rises to 8.0, above appetite |
| Independent bias audit | Before go-live | £24k | Without it, Fairness rises to 8.8, above appetite |
| Performance and robustness testing | Before go-live | £12k | Without it, Transparency rises to 8.1, above appetite |
| Explainability testing | Before go-live | £9k | Without it, Transparency rises to 9.2, above appetite |
| Compliance audit | Before go-live | £14k | Without it, Transparency rises to 8.7, above appetite |
| Appeal and redress test | Before go-live | £6k | Without it, Transparency rises to 8.4, above appetite |

| Principle | Before | After | Band | Problem slips through | Within appetite |
|---|---:|---:|---|---|---|
| Safety | 7.5 | 4.0 | Low | 35% to 8% | yes |
| Transparency | 20.3 | 7.9 | Medium | 78% to 10% | yes |
| Fairness | 20.3 | 6.7 | Medium | 78% to 7% | yes |
| Accountability | 12.3 | 4.3 | Medium | 50% to 5% | yes |
| Contestability | 6.8 | 1.4 | Low | 8% to <1% | yes |

### Lowest risk within £150k: £148k, 12 techniques, live in 12 weeks (meets appetite, within budget)

| Technique | Stage | Cost | Why it is there |
|---|---|---:|---|
| Risk assessment | Design | £4k | Not needed: dropping it saves £4k and still meets appetite |
| Algorithmic impact assessment | Design | £9k | Without it, Fairness rises to 8.3, above appetite |
| Data protection impact assessment | Design | £6k | Required: the system uses personal data |
| Model and data documentation | Design | £6k | Without it (and independent conformity assessment), Transparency rises to 9.1, above appetite |
| Supplier due diligence | Design | £5k | Without it, Transparency rises to 8.3, above appetite |
| Independent bias audit | Before go-live | £24k | Without it, Fairness rises to 8.5, above appetite |
| Performance and robustness testing | Before go-live | £12k | Not needed: dropping it saves £12k and still meets appetite |
| Explainability testing | Before go-live | £9k | Without it, Transparency rises to 8.4, above appetite |
| Compliance audit | Before go-live | £14k | Not needed: dropping it saves £14k and still meets appetite |
| Independent conformity assessment | Before go-live | £38k | Not needed: dropping it saves £38k and still meets appetite |
| Appeal and redress test | Before go-live | £6k | Not needed: dropping it saves £6k and still meets appetite |
| Live monitoring and incident response | In operation | £15k | Not needed: dropping it saves £15k and still meets appetite |

| Principle | Before | After | Band | Problem slips through | Within appetite |
|---|---:|---:|---|---|---|
| Safety | 7.5 | 3.1 | Low | 35% to 5% | yes |
| Transparency | 20.3 | 7.1 | Medium | 78% to 8% | yes |
| Fairness | 20.3 | 6.5 | Medium | 78% to 7% | yes |
| Accountability | 12.3 | 3.7 | Low | 50% to 3% | yes |
| Contestability | 6.8 | 1.0 | Low | 8% to <1% | yes |

## What each extra pound buys

Every plan that no cheaper plan beats, and how it differs from the one before:

| Cost | Worst score | Change from the plan above |
|---:|---:|---|
| £6k | 17.6 | adds Data protection impact assessment |
| £10k | 15.7 | adds Risk assessment |
| £15k | 14.6 | adds Supplier due diligence |
| £19k | 13.8 | adds Algorithmic impact assessment; drops Supplier due diligence |
| £20k | 13.4 | adds Supplier due diligence; drops Risk assessment |
| £24k | 12.0 | adds Risk assessment |
| £30k | 11.5 | adds Appeal and redress test |
| £36k | 11.1 | adds Model and data documentation |
| £40k | 10.6 | adds Internal bias audit; drops Appeal and redress test |
| £43k | 10.4 | adds Explainability testing; drops Model and data documentation |
| £46k | 10.2 | adds Model and data documentation, Appeal and redress test; drops Explainability testing |
| £49k | 10.0 | adds Explainability testing; drops Appeal and redress test |
| £54k | 9.9 | adds Compliance audit; drops Explainability testing |
| £55k | 9.6 | adds Explainability testing, Appeal and redress test; drops Compliance audit |
| £60k | 9.6 | adds Compliance audit; drops Explainability testing |
| £63k | 9.5 | adds Explainability testing; drops Appeal and redress test |
| £64k | 9.3 | adds Live monitoring and incident response; drops Compliance audit |
| £67k | 9.3 | adds Performance and robustness testing, Appeal and redress test; drops Live monitoring and incident response |
| £69k | 9.2 | adds Compliance audit; drops Performance and robustness testing |
| £70k | 9.1 | adds Live monitoring and incident response; drops Compliance audit |
| £77k | 9.0 | adds Independent bias audit, Compliance audit; drops Internal bias audit, Appeal and redress test, Live monitoring and incident response |
| £78k | 8.8 | adds Internal bias audit, Live monitoring and incident response; drops Independent bias audit |
| £81k | 8.8 | adds Performance and robustness testing, Appeal and redress test; drops Live monitoring and incident response |
| £83k | 8.5 | adds Independent bias audit; drops Internal bias audit, Performance and robustness testing |
| £84k | 8.3 | adds Internal bias audit, Live monitoring and incident response; drops Independent bias audit |
| £93k | 8.1 | adds Independent bias audit; drops Live monitoring and incident response |
| £95k | 8.0 | adds Performance and robustness testing; drops Internal bias audit |
| £96k | 8.0 | adds Internal bias audit, Live monitoring and incident response; drops Independent bias audit |
| £105k | 7.9 | adds Independent bias audit; drops Live monitoring and incident response |
| £110k | 7.9 | adds Live monitoring and incident response; drops Internal bias audit |
| £120k | 7.7 | adds Internal bias audit |
| £122k | 7.5 | adds Independent conformity assessment; drops Independent bias audit, Performance and robustness testing |
| £131k | 7.3 | adds Independent bias audit; drops Live monitoring and incident response |
| £134k | 7.2 | adds Performance and robustness testing, Live monitoring and incident response; drops Independent bias audit |
| £143k | 7.1 | adds Independent bias audit; drops Live monitoring and incident response |
| £148k | 7.1 | adds Live monitoring and incident response; drops Internal bias audit |
| £158k | 6.9 | adds Internal bias audit |
| £171k | 6.9 | adds Independent red teaming; drops Live monitoring and incident response |
| £176k | 6.9 | adds Live monitoring and incident response; drops Internal bias audit |
| £186k | 6.8 | adds Internal bias audit |

## How sure is this plan?

400 draws, each scaling every technique's coverage by up to 25% either way (40% for independent assurers).

| Plan | Cost | Draws within appetite | Worst score, middle 80% | Techniques |
|---|---:|---:|---|---|
| Cheapest that meets appetite | £105k | 59% | 7.2 to 8.5 | Risk assessment, Algorithmic impact assessment, Data protection impact assessment, Model and data documentation, Supplier due diligence, Internal bias audit, Independent bias audit, Performance and robustness testing, Explainability testing, Compliance audit, Appeal and redress test |
| Lowest risk within budget | £148k | 97% | 6.5 to 7.7 | Risk assessment, Algorithmic impact assessment, Data protection impact assessment, Model and data documentation, Supplier due diligence, Independent bias audit, Performance and robustness testing, Explainability testing, Compliance audit, Independent conformity assessment, Appeal and redress test, Live monitoring and incident response |
| Cheapest that clears 80% of draws | £131k | 92% | 6.7 to 7.9 | Risk assessment, Algorithmic impact assessment, Data protection impact assessment, Model and data documentation, Supplier due diligence, Internal bias audit, Independent bias audit, Explainability testing, Compliance audit, Independent conformity assessment, Appeal and redress test |

Clearing 80% of draws costs £26k more than the cheapest plan.

## From pilot to scale

| Stage | Adds | Total so far | Worst after | Techniques added |
|---|---:|---:|---:|---|
| Pilot | +£46k | £46k | 7.9 | Risk assessment, Algorithmic impact assessment, Data protection impact assessment, Model and data documentation, Supplier due diligence, Internal bias audit, Appeal and redress test |
| Limited roll-out (now) | +£59k | £105k | 7.9 | Independent bias audit, Performance and robustness testing, Explainability testing, Compliance audit |
| Full scale | +£38k | £143k | 7.9 | Independent conformity assessment |

The pilot needs £46k of assurance; full scale needs £143k in all, 3.1 times as much.
Planning each stage on its own costs nothing extra here.

## Techniques that cannot be used here

- Formal verification: Needs full access to the model.
