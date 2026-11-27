# Findings: a warning light nobody can grade

## The question

Rugby clubs, like many organisations, are sold predictive dashboards that turn training data into a traffic light for each player's injury risk. The best known is the acute:chronic workload ratio (ACWR): the last week's load over the average week of the last month, with about 1.5 treated as a danger zone. Newer products wrap the same data in machine learning.

This project asks three questions about such a light, using a simulated club where, unlike any real one, the true cause of every injury is known:

1. How well can a workload light pick out the players about to be injured?
2. If the coach acts on it, what does the club gain and what does it give up?
3. Could the club ever tell, from its own seasons, whether the light was worth it?

The third matters most for anyone studying why AI stalls at the pilot stage: a tool whose benefit cannot be measured in a pilot has a business case that can always be argued either way.

## Method

Load bearing simulates an invented club (36 players, a 6-week pre-season, 22 league rounds, a cup semi-final and final) one day at a time. Each session's load is minutes times effort out of ten, and each carries a small chance of injury. Soft-tissue injuries are more likely when fatigue (a 7-day average of load) runs ahead of fitness (a 42-day average), or when a player is under-trained, older, recently back from injury or hiddenly frail. Contact injuries depend mostly on match minutes. A default season has about 30 injuries, 40% of them soft-tissue; every number is invented and illustrative.

Five lights are read every Thursday: the rolling ACWR in its coupled and uncoupled forms, the exponentially weighted (EWMA) version, a logistic regression "AI" that the club trains on its own previous two seasons, and a perfect-knowledge ceiling that knows the hidden mechanism and each player's frailty but not the luck.

Every random draw (each player's daily injury roll, effort noise, each match's bounce of the ball) is fixed by the season number, so the same season can be replayed under different policies with identical luck. The numbers below come from the companion's default runs on squad 7: 30 silent seasons for the lights, 30 paired seasons for the policies, 40 pilot pairs, and a pool of 32 clubs for the trial design.

## Result 1: the ceiling is low, and most injuries are out of reach

Scored against soft-tissue injuries in the following seven days, across 36,672 player-weeks in which nobody acted on any light:

| Light | AUC | One season (middle 80%) | Hits per 100 flags at its rule |
|---|---|---|---|
| Rolling ratio (coupled or uncoupled) | 0.604 | 0.52 to 0.77 | 2.5 (coupled), 2.1 (uncoupled) |
| EWMA ratio | 0.618 | 0.51 to 0.76 | 4.1 |
| Risk model (the AI) | 0.624 | 0.50 to 0.71 | 1.8 |
| Perfect knowledge | 0.666 | 0.52 to 0.81 | 2.3 |

An AUC of 0.5 is a coin toss. Even perfect knowledge only reaches 0.67, because luck still decides which risky player breaks down. Only 0.95% of player-weeks end in a soft-tissue injury, so the AI flags 12% of player-weeks and catches 24% of those injuries, yet 98 of every 100 flags are followed by nothing. And 62% of all injuries come from contact, which no load figure can foresee.

The AI learned from 2,507 player-weeks containing just 19 soft-tissue injuries. It scores about the same as a ratio a coach could work out on a calculator.

## Result 2: one season cannot grade a light, and the "1.5" means different things

A single season's score for the AI ranged from 0.50 to 0.71 across the middle 80% of seasons, on nothing but luck. A club judging its light on one season gets one draw from that range.

The coupled and uncoupled ratios produced exactly the same AUC. That is not a coincidence: the coupled ratio includes the latest week in its own baseline, which makes it a fixed, increasing function of the uncoupled one (uncoupled = 3c / (4 - c)). They rank every player identically. What differs is the scale: a coupled 1.5 equals an uncoupled 1.8, so at the same "1.5" rule the coupled light flagged 4.7% of player-weeks and the uncoupled 10.4%. The published debate about coupling is, in practice, a debate about where to put the threshold.

## Result 3: acting on the light works, mostly by playing less, and it costs matches

Over 30 seasons with identical luck, against picking the best team and ignoring the light:

- **Resting anyone the AI flags** cut injuries by 2.8 a season (95% interval 2.1 to 3.5): 1.6 soft-tissue and 1.3 contact. Days lost fell by 53. But the club lost 4.1 league points a season (2.9 to 5.6), finished a place lower on average, and had 2.3 fewer of its first-choice XV in the cup final: the light flagged about 2.8 of them in the week of the final.
- **Cutting training but still picking flagged players** saved 0.9 injuries for 1.2 points.
- **Planned rotation** (rest anyone with four starts in a row) saved 0.9 injuries and cost 5.3 points.
- **Picking on readiness** (ability times freshness) changed injuries by almost nothing and gained 0.3 points.

Which option is best depends on what a league point is worth to the club in player-days of injury, a judgement no simulation can make. Searching every action and flag level over 20 paired seasons, resting the AI's riskiest 10% pays only if a point is worth less than about 15 player-days; resting its riskiest 30% saves 114 days but costs 15 points. Picking on readiness beat doing nothing at any rate (8 fewer days lost and 0.5 more points), so it becomes the best choice once a point is worth 12 player-days or more.

The contact injuries avoided by resting are simply rugby not played. A surprise came from acting on the perfect-knowledge light: it saved the same 1.6 soft-tissue injuries as the AI but cost 6.5 points, because the players at genuinely high risk are mostly regular starters (89% of its flags went to someone who started the previous match, against 40% for the AI). Knowing the risk better does not make resting cheaper.

## Result 4: a pilot season cannot tell

The club plays a normal season, pilots the light the next, and compares. With the luck held fixed, the light's true effect was 2.4 fewer injuries a season (1.5 to 3.2). But a season's injury count varies by about 5.5 either way on luck alone, so a before-and-after comparison swings by 7.3. Across 40 simulated pilots:

- 57% showed fewer injuries, 42% showed more, and 38% showed at least 20% fewer, enough for a convincing slide.
- A fair comparison would need 84 seasons with the light and 84 without to detect the true effect four times in five. One season gives 6% power.
- 97% of acted-on flags were followed by a quiet fortnight. To a coach that looks like 138 successful interventions a season; in truth it took about 58 acted-on flags to prevent one injury.

Hindsight makes this worse. The inquest replays a season once for every injury with only that player rested that week. Over 20 silent seasons, a rest would have avoided 70% of soft-tissue and 97% of contact injuries, so almost every injury looks preventable after the event, yet the AI had flagged only 24% of the soft-tissue injuries beforehand (the EWMA ratio at 1.5, 6%).

The companion also designed a cluster-randomised trial: half of a group of clubs get the light at random. Running each club for one season, the power to detect the pooled effect (1.6 fewer injuries a club-season) was 0% with 4 clubs (no split of four can reach significance), 3% with 8, 6% with 16 and 13% with 32; three seasons per club lifted 32 clubs only to 18%. The evidence a sport would need is out of reach of any single club and most leagues.

## Result 5: the verdict depends on something nobody can see

How strongly load spikes cause injury is the contested scientific question, and it is hidden from every club. Pushing each assumption low and high over 24 paired seasons, the spike effect moved the answer most: from 0.5 to 3.5, the AI's AUC rose from 0.57 to 0.73, the soft-tissue injuries saved by resting flagged players from 1.0 to 4.0 a season, and the break-even worth of a league point from 10 to 32 player-days. Across a map of spike effect against contact rate, the break-even ran from 4 to 66 player-days a point. Can a club measure it from its own logbook? Fitting a hazard model to one simulated season (true value 2.0), the sample logbook's 95% interval ran from 1.6 to 5.8. Pooling seasons from different invented squads, the interval was about 7 wide for one season and ruled out "no effect" only a third of the time; eight seasons narrowed it to about 2 and always ruled it out; a width of 1 would need roughly 36 club-seasons. Whether the light is a good buy turns on a number no single club can pin down.

Data matters as much as the algorithm. Trained on one season (12 soft-tissue injuries), the risk model learned that a higher workload ratio means lower risk and scored 0.52, a coin toss; on two seasons it reached 0.63, and five seasons added nothing more.

A related measurement lesson came from the companion's calibration of the Banister fitness-fatigue model to weekly jump tests. Fitness parameters were recovered well (the time constant to within 3.8 days on a typical 39), but the fatigue time constant and weight were not identifiable: tests taken every Monday always follow the same weekly loading pattern, so fatigue and its decay trade off against each other. More data of the same shape does not help; a different testing schedule would.

## What it means for the themes

**AI adoption beyond the pilot.** This is the pilot-purgatory story in miniature. The benefit is a counterfactual (injuries that did not happen), the events are rare, and the signal is small next to season-to-season noise, so a pilot can be read as a success or a failure with roughly equal ease. Executives asked why AI pilots fail to scale often name unclear ROI and hard-to-measure benefits; this shows why those blockers can be structural rather than a failure of effort. The remedy is evaluation design, not more enthusiasm: run the light silently first and score it before acting on it, agree the comparison before the pilot starts, pool evidence across sites, and count the costs (points, the cup final) alongside the benefits.

**Human-AI interaction and over-reliance.** Quiet fortnight after quiet fortnight builds the coach's trust in the light whether or not it works. Confirmation comes free; disconfirmation is invisible.

**Team and sports leadership.** The policy that loses the fewest days is not the one that wins the most matches. A captain or coach weighing a load-management tool is making a selection trade-off, not a medical one.

## Limitations

Everything is invented: the club, the players, the injury mechanism and every effect size. Real injury causes are messier and more contested. The squad is fixed for the season, second-team injuries count alongside first-team ones, and results come from a simple strength model. The AI is a plain logistic regression on two seasons; a vendor's model trained on many clubs could do better, though the ceiling in Result 1 limits how much. The conclusions concern the shape of the evidence problem, which held across the settings tested, not the exact numbers. Nothing here is medical or coaching advice.
