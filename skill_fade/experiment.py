"""A virtual randomised experiment: the study design the browser app cannot run.

Each simulated participant takes a short test on their own (pre-test), works
through the training cases with the AI under one workflow, then takes a second
test on their own (post-test). Test scores are noisy, as they would be in a real
study, so this shows how large the effects are once measured, and how many
participants a study would need to detect them.
"""

from . import model
from .stats import mean, welch

ARM_STRIDE = 100003  # keeps participant numbers in different arms apart
TEST_SALT = 0x5BD1E995
POWER_SALT = 0x27D4EB2F


def test_score(rng, skill, sd, items):
    """Share of ``items`` test cases answered correctly by someone with this skill, without the AI."""
    right = 0
    for _ in range(items):
        d = sd * rng.normal()
        if rng.uniform() < model.sigmoid(skill - d):
            right += 1
    return right / items


def run_participant(p, ctx, index, items):
    """Simulates one participant: pre-test, training with the AI, post-test."""
    k = model.new_counts()
    s0, s1, trust = model.run_person(p, ctx, model.mix_seed(p["seed"], index), k)
    test_rng = model.Rng(model.mix_seed(p["seed"] ^ TEST_SALT, index))
    pre = test_score(test_rng, s0, ctx["sd_d"], items)
    post = test_score(test_rng, s1, ctx["sd_d"], items)
    rounds = p["rounds"]
    return {
        "pre": pre,
        "post": post,
        "change": post - pre,
        "withAi": k["team"] / rounds,
        "deferral": k["deferred"] / rounds,
        "trust": trust,
        "trueBefore": model.expected_accuracy(s0, ctx["sd_d"]),
        "trueAfter": model.expected_accuracy(s1, ctx["sd_d"]),
    }


def simulate_arm(params, workflow, arm_index, n, items):
    p = model.normalise_params(dict(params, workflow=workflow))
    ctx = model.derived(p)
    return [run_participant(p, ctx, arm_index * ARM_STRIDE + j, items) for j in range(n)]


def run_experiment(params, arms=("none", "ai_first", "human_first"), n=60, items=20):
    """Runs every arm with ``n`` different participants and compares each AI arm with the control.

    The control is the "none" arm if it is included, otherwise the first arm.
    """
    params = model.normalise_params(params)
    arms = list(arms)
    if not arms:
        raise ValueError("Name at least one workflow")
    for arm in arms:
        if arm not in model.WORKFLOW_KEYS:
            raise ValueError("Unknown workflow: %s" % arm)
    if len(set(arms)) != len(arms):
        raise ValueError("Each workflow can only appear once")
    if n < 2:
        raise ValueError("Each arm needs at least two participants")
    if items < 1:
        raise ValueError("The tests need at least one item")
    data = {arm: simulate_arm(params, arm, i, n, items) for i, arm in enumerate(arms)}
    control = "none" if "none" in arms else arms[0]
    summary = {}
    for arm in arms:
        rows = data[arm]
        summary[arm] = {key: mean([r[key] for r in rows]) for key in
                        ("pre", "post", "change", "withAi", "deferral", "trust", "trueBefore", "trueAfter")}
    comparisons = {}
    for arm in arms:
        if arm == control:
            continue
        comparisons[arm] = {
            "change": welch([r["change"] for r in data[arm]], [r["change"] for r in data[control]]),
            "withAi": welch([r["withAi"] for r in data[arm]], [r["withAi"] for r in data[control]]),
        }
    return {"params": params, "arms": arms, "control": control, "n": n, "items": items,
            "data": data, "summary": summary, "comparisons": comparisons}


def power_curve(params, arm, control="none", sizes=(20, 40, 80, 160), reps=400, pool=800, items=20, alpha=0.05):
    """Estimates statistical power to detect the change-score difference between two arms.

    A large pool of participants is simulated once per arm; each replication then
    draws ``size`` participants per arm from the pools (with replacement) and runs
    Welch's t-test.
    """
    params = model.normalise_params(params)
    if arm == control:
        raise ValueError("Pick two different workflows to compare")
    for wf in (arm, control):
        if wf not in model.WORKFLOW_KEYS:
            raise ValueError("Unknown workflow: %s" % wf)
    sizes = sorted(set(int(s) for s in sizes))
    if not sizes or sizes[0] < 2:
        raise ValueError("Sample sizes must be at least 2")
    if reps < 1 or pool < 2:
        raise ValueError("Need at least one replication and a pool of two or more")
    if items < 1:
        raise ValueError("The tests need at least one item")
    treated = [r["change"] for r in simulate_arm(params, arm, 1, pool, items)]
    base = [r["change"] for r in simulate_arm(params, control, 0, pool, items)]
    true_effect = welch(treated, base)
    rng = model.Rng(model.mix_seed(params["seed"] ^ POWER_SALT, len(sizes)))
    results = []
    for size in sizes:
        significant = 0
        right_way = 0
        for _ in range(reps):
            a = [treated[int(rng.uniform() * pool)] for _ in range(size)]
            b = [base[int(rng.uniform() * pool)] for _ in range(size)]
            test = welch(a, b, alpha, interval=False)
            if test["p"] < alpha:
                significant += 1
                if (test["diff"] > 0) == (true_effect["diff"] > 0):
                    right_way += 1
        results.append({"n": size, "power": significant / reps, "rightWay": right_way / reps})
    needed = smallest_size_for(results, 0.8)
    return {"params": params, "arm": arm, "control": control, "items": items, "pool": pool, "reps": reps,
            "alpha": alpha, "effect": true_effect, "results": results, "needed": needed,
            "neededAtMost": needed is not None and results[0]["rightWay"] >= 0.8}


def smallest_size_for(results, target):
    """Interpolates the participants per arm needed to reach ``target`` power, or None if out of range.

    If the smallest size tested already reaches the target, that size is returned: the
    true requirement may be lower (``power_curve`` flags this as ``neededAtMost``).
    """
    prev = None
    for row in results:
        if row["rightWay"] >= target:
            if prev is None:
                return row["n"]
            span = row["rightWay"] - prev["rightWay"]
            frac = (target - prev["rightWay"]) / span if span > 0 else 1.0
            return int(round(prev["n"] + frac * (row["n"] - prev["n"])))
        prev = row
    return None
