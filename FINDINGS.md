# Findings: when pricing algorithms stop competing

## The question

Can two pricing algorithms that only ever try to maximise their own profit learn to keep prices high together, with no agreement and no way to communicate? If they can, is the high price held up by the reward-and-punishment pattern that makes a human cartel stable? Which rule changes would bring prices down? And could a competition authority, which sees prices but not code, tell which markets to investigate?

These questions matter beyond competition law. Pricing is one of the easiest places to build a business case for AI: margins rise and the pilot looks like a success. This note argues that the margin uplift is exactly the number that cannot be trusted, and that the reasons why are the kind of hard-to-measure risk that stops AI from scaling.

## Method

The market is the standard logit price competition used in research on algorithmic collusion, rebuilt from scratch following the design of Calvano, Calzolari, Denicolò and Pastorello (American Economic Review, 2020). Two sellers offer similar products at a unit cost of £1. Shoppers pick a product, or nothing, by quality, price and personal taste. The competitive price is £1.47, where neither seller can gain by changing its own price for one day. The monopoly price is £1.92, where joint profit peaks.

Each seller runs tabular Q-learning over 15 prices from just below the competitive price to just above the monopoly price. It conditions on yesterday's prices and values tomorrow at 0.95. Experimenting starts on every day and fades. Training stops when no best price has changed in any situation for 100,000 rounds, which took 1.8 million rounds on average.

Every result below comes from the Python companion, which reproduces the browser app's model exactly (an automated test checks every number against the app). The remedies come from `python -m quiet_cartel remedies --runs 20`: ten options, 20 training runs each (seeds 1 to 20), 200 runs in all. Each option is compared with the baseline run on the same seed, using a sign-flip permutation test with Holm's correction. The screens come from `python -m quiet_cartel screen data/markets.csv --truth data/markets_truth.csv`. That is the bundled dataset of 40 invented markets observed for a year, in which each seller tests a random price on about 3% of days.

Two outcome measures recur. **Profit gain** places profits on a scale from 0% (competitive) to 100% (monopoly). **Shoppers' loss** does the same for consumer surplus.

## Result 1: the algorithms learn to stop competing

Across 20 runs of the textbook market, the profit gain averaged **85%** (90% interval 81% to 88%; range 58% to 98%). Settled prices averaged **£1.80**, much nearer the monopoly £1.92 than the competitive £1.47. Shoppers lost **73%** of the surplus a monopoly would take from them. This matches the order of magnitude reported in the research literature for the same design.

Nothing in the code mentions the rival's interests, and the sellers have no channel to coordinate. They learn high prices because, during the long experimenting phase, every price cut that one of them tried was followed by a period of lower profit.

## Result 2: in 9 runs out of 10 a threat holds the price up

The punishment test forces one seller to make its most profitable one-day cut and then lets both strategies play on. In **18 of 20** baseline runs the cut was punished: the rival answered with lower prices, the cutter lost more over the following days than it gained on the day, and prices returned to their old level within a few days. In the run with seed 1, for example, seller A gains £23.65 per 1,000 shoppers on the day of the cut and loses £165.15 over the next 24 days.

This is the pattern a competition lawyer would look for as evidence of a cartel, and nobody programmed it.

The exact best-reply check adds a twist. Holding the rival's learned strategy fixed and solving for the best possible reply, a seller could earn on average **17.7%** more over time than its own learned strategy delivers. So the high price is not an equilibrium in the strict sense. It survives because the algorithms only ever test one price at a time, and any single test is punished. A seller that worked out the full reply, or a better-designed algorithm, could break it. That fragility cuts both ways for policy: the outcome is less robust than a true cartel, but nothing inside the market will reliably end it.

## Result 3: remedies differ hugely, and some popular ideas backfire

| Option | Profit gain | Change from baseline | Cuts punished |
|---|---|---|---|
| Both learn and see all prices (baseline) | 85% | | 90% |
| Rivals' prices banned as an input | -5% | -90 points | 0% |
| Rival keeps a fixed competitive price | 7% | -78 points | 0% |
| Rewarded on today's profit only | 16% | -68 points | 0% |
| Must keep testing prices (5% of days) | 45% | -40 points | 50% |
| A third seller enters | 65% | -20 points | 90% |
| Busy and quiet days | 73% | -12 points | 55% |
| Both buy the same pricing tool | 92% | +7 points | 90% |
| Rival matches the cheapest price | 94% | +9 points | 100% |
| No memory at all | 96% | +11 points | 0% |

Every difference is statistically clear after Holm's correction (largest adjusted p = 0.036, for the shared tool).

Three findings stand out:

- **Input restrictions work best.** Stopping the algorithm from using rivals' prices removes the information a punishment needs, and prices fall to competitive (-5%). Telling the algorithm to optimise today's profit only does almost as well (16%). These are design rules a regulator could audit, unlike an outcome rule such as "do not collude".
- **More competitors and mandatory experimenting help, but only partly.** A third seller still leaves a 65% gain, with cuts punished in 90% of runs. Forcing 5% random testing halves the gain but leaves half the runs with a working threat.
- **Simple rules can make things worse.** A rival that matches the cheapest price drives the gain to 94% and makes the high price an *exact* best reply (best-reply gain 0.0%): a price-match promise is a perfect punishment. A shared pricing vendor, which learns from both sellers' data (the hub-and-spoke worry behind recent cases about shared pricing software), adds 7 points.

## Result 4: high prices without a threat

Algorithms with **no memory at all** reached the highest prices of all (96%) while **no** cut was ever punished. They cannot punish, because they cannot see what happened yesterday. They simply never learned that undercutting would pay: their estimates of a low price went stale once experimenting stopped. Shoppers lose 90% of the monopoly surplus. Yet a conduct test based on reward and punishment would clear these markets.

This is the core enforcement problem. The harm to consumers does not depend on the mechanism, but the legal theory does.

## Result 5: what a regulator can and cannot see

On the 40 dataset markets, each screen was scored by ROC area (0.5 is guessing, 1 is perfect) against two definitions of a case: "held up by a threat" (17 markets) and "high prices" (24 markets).

| Screen | Threat | High prices |
|---|---|---|
| High margin | 0.75 | 0.92 |
| Stable prices | 0.57 | 0.57 |
| Rivals hit back the day after an unprovoked cut | 0.85 | 0.80 |
| Prices snap back within 10 days | 0.56 | 0.61 |
| Hit back, then back up | 0.72 | 0.75 |
| Price above the competitive price fitted from sales data | 0.86 | 1.00 |

Margins find high prices well but find threats much less well, because high margins also come from loyal shoppers and from memoryless algorithms. Price stability, a classic cartel marker, is close to useless here. The screen that watches how rivals react to cuts does best on prices alone (0.85). Combined with a permutation test and false-discovery control, it flagged **11** markets: all 11 were real threat cases, but it missed 6. With daily sales data, fitting the demand model to estimate the competitive price ranks high-price markets perfectly, but it still cannot say why prices are high.

## What this means

For **AI governance**, the most effective remedies here regulate what goes into an algorithm (which data it may use, what objective it optimises) rather than what comes out. Outcome screens on prices can prioritise investigations. They cannot separate a learned threat from a learning failure without watching how rivals respond to cuts, and real markets rarely provide clean cuts to watch.

For **AI adoption**, a pricing pilot that reports a margin uplift cannot tell "better pricing" apart from "learned to stop competing". A responsible pilot needs a gate before scaling: a forced-cut test like the one in this app, run in simulation or on the live system, plus a record of which inputs the algorithm may use. Without one, the larger the uplift, the larger the legal exposure. Compliance teams are right to treat that as an unclear benefit with a hard-to-measure risk, the two things executives most often say block scaling.

## Limitations

- The set-up is deliberately simple: tabular Q-learning, 15 prices, simultaneous daily moves and about two million rounds of experimenting. Real systems learn from richer data, much faster and with other methods. The results show what is possible, not how common it is.
- The best-reply gain shows the learned strategies are not equilibria. With longer training or different learning rates they might get closer.
- The screen results depend on the case-file mix and on 3% random price tests. With fewer tests there are fewer cuts to watch, and every reaction-based screen gets weaker.
- The legal categories are simplified. Whether algorithmic tacit collusion is unlawful is unsettled in UK and EU law, and nothing here is legal advice.
- Everything is synthetic. The sellers, prices and shoppers are invented.
