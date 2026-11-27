# Findings: a warning light nobody can grade

## The question

Rugby clubs, like many organisations, are sold dashboards that turn training data into a traffic light for each player's injury risk. The best known is the acute:chronic workload ratio (ACWR): the last week's load over the average week of the last month, with about 1.5 treated as a danger zone. Newer products wrap the same data in machine learning.

In a simulated club where, unlike any real one, the true cause of every injury is known, this project asks how well such a light picks out the players about to be injured, what acting on it gains and costs, and whether a club could ever tell from its own seasons that it was worth it. The last question matters most for anyone studying why AI stalls at the pilot stage: a tool whose benefit cannot be measured in a pilot has a business case that can always be argued either way.

## Method

Load bearing simulates an invented club (36 players, a six-week pre-season, 22 league rounds and a cup) one day at a time. A session's load is minutes times effort out of ten, and each session carries a small chance of injury. Soft-tissue injuries are more likely when fatigue (a 7-day average of load) runs ahead of fitness (a 42-day average), or when a player is under-trained, older, recently back from injury or hiddenly frail; contact injuries depend mostly on match minutes. A default season has about 30 injuries, 40% of them soft-tissue. Every number is invented and illustrative.

Five lights are read every Thursday: the rolling ACWR in its coupled and uncoupled forms, the exponentially weighted (EWMA) version, a logistic regression "AI" the club trains on its previous two seasons, and a perfect-knowledge ceiling that knows the hidden mechanism but not the luck. Every random draw is fixed by the season number, so a season can be replayed under different policies with identical luck. Each analysis uses its own set of seasons (listed at the end), so the same policy's effect differs slightly between sections, always within its interval.

## Result 1: the ceiling is low, and most injuries are out of reach

Scored against soft-tissue injuries in the following seven days, over 36,672 player-weeks of 30 seasons in which nobody acted on any light:

| Light | AUC | One season (middle 80%) | Hits per 100 flags at its rule |
|---|---|---|---|
| Rolling ratio (coupled or uncoupled) | 0.604 | 0.52 to 0.77 | 2.5 (coupled), 2.1 (uncoupled) |
| EWMA ratio | 0.618 | 0.51 to 0.76 | 4.1 |
| Risk model (the AI) | 0.624 | 0.50 to 0.71 | 1.8 |
| Perfect knowledge | 0.666 | 0.52 to 0.81 | 2.3 |

An AUC of 0.5 is a coin toss. Even perfect knowledge reaches only 0.67, because luck still decides which risky player breaks down. Only 0.95% of player-weeks end in a soft-tissue injury, so the AI flags 12% of player-weeks, catches 24% of those injuries, and 98 of every 100 flags are followed by nothing. And 62% of all injuries come from contact, which no load figure can foresee.

The AI learned from 2,507 player-weeks containing just 19 soft-tissue injuries. Its AUC matches a ratio a coach could work out on a calculator, and when every light flags the same riskiest 10% it catches slightly fewer injuries (19% against 22 to 23%).

## Result 2: one season cannot grade a light, and "1.5" means different things

A single season's AUC for the AI ranged from 0.50 to 0.71 on luck alone. A club judging its light on one season gets one draw from that range.

The coupled and uncoupled ratios scored exactly the same: because the coupled ratio includes the latest week in its own baseline, it is a fixed, increasing function of the uncoupled one (uncoupled = 3c / (4 - c)), so both rank players identically. Only the scale differs: a coupled 1.5 is an uncoupled 1.8, so at the same "1.5" rule they flagged 4.7% and 10.4% of player-weeks. The coupling debate is, in practice, a debate about where to put the threshold.

## Result 3: acting on the light works, mostly by playing less, and it costs matches

Over 30 seasons with identical luck, against picking the best team and ignoring the light:

- **Resting anyone the AI flags** cut injuries by 2.8 a season (95% interval 2.1 to 3.5): 1.6 soft-tissue, 1.3 contact. Days lost fell by 53. But the club lost 4.1 league points (2.9 to 5.6), finished a place lower, and started its last cup tie with 2.3 fewer of its first-choice XV.
- **Cutting training but still picking flagged players** saved 0.9 injuries for 1.2 points; **planned rotation** saved 0.9 for 5.3 points; **picking on readiness** changed injuries by almost nothing and gained 0.3 points.

The contact injuries avoided are simply rugby not played. Acting on the perfect-knowledge light saved the same 1.6 soft-tissue injuries but cost 6.5 points, because genuinely high-risk players are mostly regulars: once the league was under way, 87% of its flags fell on someone who had started the latest match, against 37% for the AI. Knowing the risk better does not make resting cheaper.

The right choice depends on what a league point is worth in player-days of injury, which only the club can judge. Over 20 paired seasons, resting the AI's riskiest 10% pays only if a point is worth under about 15 player-days; resting its riskiest 30% saves 114 days but costs 15 points. On the point estimates, picking on readiness is best once a point is worth 12 player-days or more, though its effect on days lost is uncertain (-37 to +18).

## Result 4: a pilot season cannot tell

The club plays a normal season, pilots the light the next, and compares. With luck held fixed, the true effect was 2.4 fewer injuries a season (1.5 to 3.3). But a season's count varies by about 5.5 either way on luck alone, so a before-and-after comparison swings by 7.3. Across 40 simulated pilots, 57% showed fewer injuries, 43% more, and 38% at least 20% fewer, enough for a convincing slide. A fair comparison would need 84 seasons with the light and 84 without; one season gives 6% power.

Meanwhile 97% of acted-on flags were followed by a quiet fortnight: to a coach, 138 successful interventions a season, when in truth it took about 58 to prevent one injury. Hindsight makes it worse. Replaying each injury with only that player rested that week, over 20 silent seasons, a rest would have avoided 70% of soft-tissue and 97% of contact injuries; the AI had flagged only 24% of the soft-tissue ones beforehand.

Pooling clubs does not rescue the evaluation. Randomising half of a group of clubs to the light for one season, the power to detect the pooled effect (1.6 fewer injuries a club-season) was 0% with 4 clubs (no split of four can reach significance), 3% with 8, 6% with 16 and 13% with 32; three seasons per club lifted 32 clubs only to 18%.

## Result 5: the verdict depends on something nobody can see

How strongly load spikes cause injury is contested and hidden from every club. Pushing each assumption low and high over 24 paired seasons, the spike effect moved the answer most: from 0.5 to 3.5, the AI's AUC rose from 0.57 to 0.73, the soft-tissue injuries saved from 1.0 to 4.0 a season, and the break-even worth of a point from 10 to 32 player-days. Across spike effect and contact rate together, the break-even ran from 4 to 66.

Nor can a club measure it. A hazard model fitted to the sample logbook (true value 2.0) gave a 95% interval of 1.6 to 5.8. Pooling seasons from different invented squads, one season's interval was about 7 wide and ruled out "no effect" only a third of the time; eight seasons narrowed it to about 2; a width of 1 would need roughly 36 club-seasons.

Data matters as much as the algorithm: trained on one season (12 soft-tissue injuries), the risk model learned that higher workload means lower risk and scored 0.52; on two seasons it reached 0.63, and five added nothing.

## What it means for the themes

**AI adoption beyond the pilot.** The benefit is a counterfactual, the events are rare and the signal is small next to the noise, so a pilot reads as success or failure with nearly equal ease. Unclear ROI and hard-to-measure benefits, commonly cited blockers to scaling AI, can be structural rather than a failure of effort. The remedy is evaluation design: score the light silently before acting on it, agree the comparison in advance, pool evidence across sites, and count the costs alongside the benefits.

**Human-AI interaction.** Quiet fortnights build the coach's trust whether or not the light works: confirmation comes free, disconfirmation is invisible.

**Team and sports leadership.** The policy that loses the fewest days is not the one that wins the most matches; a load-management tool is a selection trade-off, not only a medical one.

## Limitations

Everything is invented, and real injury causes are messier and more contested. The squad is fixed for the season, second-team injuries count alongside first-team ones, and results come from a simple strength model. A vendor's model trained on many clubs could beat this two-season regression, though the ceiling in Result 1 limits how much. The conclusions concern the shape of the evidence problem, which held across the settings tested, not the exact numbers. Nothing here is medical or coaching advice.

## Reproducing these numbers

All figures come from the companion with the app's defaults: `flags` (Results 1 and 2); `compare`, `compare --flag oracle` and `optimise` (Result 3); `pilot`, `inquest --seasons 20 --policy none`, `trial` and `trial --seasons-per-club 3` (Result 4); `robustness --seasons 24 --map`, `fit data/club_logbook.csv` and `fit --simulate 1,2,4,8,16 --reps 6` (Result 5).
