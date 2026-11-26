# Findings: when pricing algorithms stop competing

## The question

Can two pricing algorithms that only try to maximise their own profit learn to keep prices high together, with no agreement and no way to communicate? If so, is the price held up by the reward-and-punishment pattern that makes a human cartel stable? Does a pilot reveal it, which rules would bring prices down, and could a competition authority that sees prices but not code tell which markets to investigate?

Pricing is one of the easiest places to build a business case for AI: margins rise and the pilot looks like a success. This note argues that the margin uplift is exactly the number that cannot be trusted.

## Method

The market is the standard logit price competition used in research on algorithmic collusion, rebuilt from scratch following the design of Calvano, Calzolari, Denicolò and Pastorello (American Economic Review, 2020). Two sellers offer similar products at a unit cost of £1. Shoppers pick a product, or nothing, by quality, price and personal taste. The competitive price, where neither seller can gain by changing its own price for one day, is £1.47; the monopoly price is £1.92.

Each seller runs tabular Q-learning over 15 prices, conditions on yesterday's prices and values tomorrow at 0.95. Experimenting fades over time; training stops when no best price has changed for 100,000 rounds (about 1.8 million rounds on average).

Every number below comes from the Python companion, which reproduces the browser app's model exactly (an automated test checks every value): `remedies --runs 20` (ten options, 20 seeds each, compared with the baseline seed by seed using a sign-flip permutation test with Holm's correction), `pilot --runs 20`, `tornado --runs 5`, `map --runs 2`, `watch --markets 40 --seeds 3` (120 markets watched for 60 to 730 days) and `screen` on the bundled dataset of 40 invented markets observed for a year.

**Profit gain** places profits on a scale from 0% (competitive) to 100% (monopoly); **shoppers' loss** does the same for consumer surplus.

## Result 1: the algorithms learn to stop competing, and a threat holds the price up

Across 20 runs of the textbook market the profit gain averaged **85%** (90% interval 81% to 88%; range 58% to 98%). Settled prices averaged **£1.80**, much nearer monopoly than competition, and shoppers lost **73%** of what a monopoly would take, in line with the research literature for the same design.

The punishment test forces one seller to make its most profitable one-day cut and lets both strategies play on. In **18 of 20** runs the cut was punished: the rival answered with lower prices, the cutter lost more than it gained, and prices returned to their old level within days. With seed 1, seller A gains £23.65 per 1,000 shoppers on the day and loses £165.15 over the next 24 days. That is the pattern a competition lawyer looks for in a cartel, and nobody programmed it.

An exact best-reply check adds a twist. Holding the rival's learned strategy fixed, the seller with more to gain could earn on average **17.7%** more over time with its best reply. So the high price is not a strict equilibrium: it survives because the algorithms only test one price at a time, and any single test is punished.

The result does not hang on one lucky setting. Moving each of seven assumptions to a low and a high value, one at a time, the gain stays at 50% or more at both ends for all seven. Patience matters most: 60% when the algorithms value tomorrow at 0.8, 94% at 0.99. On the loyalty-by-patience map, 13 of 25 combinations reach 50% or more, almost all where tomorrow is valued at 0.8 or above.

## Result 2: the pilot measures the rival's rule, not the algorithm

In the pilot design, both sellers start at the competitive price. Seller A then pilots an algorithm while B keeps a simple rule; after 1.5 million rounds B adopts an algorithm too. A's profit is compared with the status quo.

| B's rule during A's pilot | A in the pilot | A after B adopts | Change |
|---|---|---|---|
| Keeps the competitive price | 0% | +40% | +40 points |
| Matches the cheapest price | +53% | +40% | -12 points |
| Undercuts by one step | +64% | +41% | -23 points |

Once both sellers have algorithms, A ends up at about **+40%** whatever happened in the pilot (+46% if both adopt at once). Across all 60 runs, A's pilot uplift barely predicts its uplift at scale (Pearson r = **0.07**, Spearman rho = 0.12).

A board that approved roll-out on the pilot number would have been approving a guess about how rivals respond. Worse, the gain at scale comes from both sellers competing less hard: cuts were punished in 65% to 70% of runs after B adopted. The part of the return a pilot cannot see is the part a competition authority would ask about.

## Result 3: remedies differ hugely, and some popular ideas backfire

| Option | Profit gain | Change from baseline | Cuts punished |
|---|---|---|---|
| Both learn and see all prices (baseline) | 85% | | 90% |
| Rivals' prices banned as an input | -5% | -90 points | 0% |
| Rival keeps a fixed competitive price | 7% | -78 points | 0% |
| Rewarded on today's profit only | 16% | -68 points | 0% |
| Must keep testing prices (5% of days) | 45% | -40 points | 50% |
| A third seller enters | 65% | -20 points | 90% |
| Busy and quiet days | 73% | -12 points | 65% |
| Both buy the same pricing tool | 92% | +7 points | 90% |
| Rival matches the cheapest price | 94% | +9 points | 100% |
| No memory at all | 96% | +11 points | 0% |

Every difference is statistically clear after Holm's correction (largest adjusted p = 0.036, for the shared tool).

- **Input rules work best.** Stopping the algorithm from using rivals' prices removes what a punishment needs, and prices fall to competitive; rewarding today's profit only does almost as well. Both are design rules a regulator could audit.
- **More competitors and forced experimenting help only partly.** A third seller still leaves a 65% gain with cuts punished in 90% of runs.
- **Simple rules can make things worse.** A price-matching rival makes the high price an exact best reply (best-reply gain 0.0%): a price-match promise is a ready-made punishment. A shared pricing vendor that learns from both sellers' data adds 7 points.

## Result 4: high prices without a threat

Algorithms with **no memory at all** reached the highest prices (96%) while no cut was ever punished. They cannot punish, because they cannot see yesterday; they simply never learned that undercutting pays, because their estimate of a low price went stale once experimenting stopped. Shoppers lose 90% of the monopoly surplus, yet a conduct test based on reward and punishment would clear these markets. The harm does not depend on the mechanism; the legal theory does.

## Result 5: what a regulator can and cannot see

Each screen was scored by ROC area (0.5 is guessing, 1 is perfect) against two definitions of a case: "held up by a threat" (20 of the 40 dataset markets) and "high prices" (24).

| Screen | Threat | High prices |
|---|---|---|
| High margin | 0.83 | 0.92 |
| Stable prices | 0.51 | 0.57 |
| Rivals hit back the day after an unprovoked cut | 0.85 | 0.80 |
| Prices snap back within 10 days | 0.53 | 0.61 |
| Hit back, then back up | 0.72 | 0.75 |
| Price above the competitive price fitted from sales data | 0.85 | 1.00 |

On this dataset, margins rank threat markets almost as well as watching reactions (0.83 against 0.85) but rank high-price markets better still (0.92), so they cannot tell a threat from loyal shoppers or a memoryless algorithm. Price stability, a classic cartel marker, is no better than guessing. Watching how rivals react to cuts is the one screen that looks at the mechanism: with a permutation test and false-discovery control it flagged **11** markets, all real threat cases, but missed 9 of the 20. With sales data, the fitted competitive price ranks high-price markets perfectly but still cannot say why prices are high.

Watching longer does not fix the misses. Across 120 case-file markets, the reaction screen's AUC rises from 0.67 (60 days, sellers testing prices on 1% of days) to about 0.79 (730 days) and stalls; the flag's recall stops at about 50%, with precision steady at 81% to 89%. The reason is structural: 34 of the 65 threat markets settle into a price cycle, and 27 of those show no unprovoked cut even after two years with sellers testing prices on 6% of days. A cycle has no calm days, so a screen built on clean cuts never sees a test it can read. Learned collusion that cycles is close to invisible to this kind of screen. Across these case files the margin screen scores only 0.62 to 0.66.

## What this means

For **AI governance**, the most effective remedies regulate what goes into an algorithm (which data it may use, what objective it optimises) rather than what comes out. Price screens can prioritise investigations, but they cannot separate a learned threat from a learning failure without clean price cuts to watch, and they miss markets that cycle.

For **AI adoption**, a pricing pilot cannot tell "better pricing" apart from "learned to stop competing", and its uplift says more about rivals' current rules than about the algorithm. A responsible pilot needs a gate before scaling: a forced-cut test like the one in this app, scenarios for rivals adopting similar tools, and a record of which inputs the algorithm may use. Without them, the larger the projected uplift, the larger the legal exposure: an unclear benefit with a hard-to-measure risk, two of the barriers executives name when AI pilots fail to scale.

## Limitations

- The set-up is deliberately simple: tabular Q-learning, 15 prices, simultaneous daily moves and about two million rounds of experimenting. Real systems learn faster, from richer data and with other methods. The results show what is possible, not how common it is.
- The pilot design fixes the status quo at the competitive price and adoption at 1.5 million rounds; other choices shift the numbers.
- The screen results depend on the case-file mix and on 3% random price tests. With fewer tests there are fewer cuts to watch.
- The legal categories are simplified. Whether algorithmic tacit collusion is unlawful is unsettled in UK and EU law; nothing here is legal advice. Everything is synthetic.
