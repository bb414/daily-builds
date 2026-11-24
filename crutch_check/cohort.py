"""Synthetic cohorts: simulated participants for trying out a study design.

Each simulated participant has a skill level, a tendency to say "definitely",
and a reliance level (how readily they switch to the checker's answer when
they disagree). What happens to their own judgement by round 3 depends on the
scenario:

    learning = helper - crutch * reliance    (with the checker)
    learning = practice                      (without it)

So "helper" is what people pick up from the checker's explanations, and
"crutch" is how much heavy reliance erodes their own judgement.
"""

import random

from .model import build_session, clamp, participant_seed, simulate_responses

SCENARIOS = {
    "mixed": {"helper": 0.10, "crutch": 0.16, "practice": 0.02,
              "about": "Helps people who think for themselves, erodes those who lean on it; "
                       "the average effect is close to zero."},
    "helper": {"helper": 0.10, "crutch": 0.0, "practice": 0.02,
               "about": "Everyone picks up skills from the checker's explanations."},
    "crutch": {"helper": 0.0, "crutch": 0.16, "practice": 0.02,
               "about": "The more people lean on the checker, the more their own judgement slips."},
    "none": {"helper": 0.02, "crutch": 0.0, "practice": 0.02,
             "about": "The checker makes no difference beyond practice."},
}


def sample_persona(rng, arm, effects):
    skill = clamp(rng.gauss(0.72, 0.08), 0.5, 0.95)
    sure_bias = rng.uniform(0.3, 0.75)
    reliance = rng.betavariate(2, 2)
    if arm == "checker":
        learning = effects["helper"] - effects["crutch"] * reliance
    else:
        learning = effects["practice"]
    return {"skill": skill, "sureBias": sure_bias, "reliance": reliance, "learning": learning}


def simulate_cohort(n_per_arm=60, scenario="mixed", seed=1, design=None, study="simulated-study",
                    effects=None):
    """Return a list of completed sessions, n_per_arm in each arm.

    Arms are balanced and shuffled. Each participant's messages come from the
    same seed the browser app would use for that study name and ID, so any
    simulated participant can be rerun in the app.
    """
    if effects is None:
        if scenario not in SCENARIOS:
            raise ValueError("unknown scenario %r (choose from %s)" % (scenario, ", ".join(SCENARIOS)))
        effects = SCENARIOS[scenario]
    if n_per_arm < 1:
        raise ValueError("n_per_arm must be at least 1")
    rng = random.Random(seed)
    arms = ["checker"] * n_per_arm + ["control"] * n_per_arm
    rng.shuffle(arms)
    width = max(3, len(str(2 * n_per_arm)))
    sessions = []
    for i, arm in enumerate(arms, start=1):
        pid = "S%0*d" % (width, i)
        persona = sample_persona(rng, arm, effects)
        session = build_session(participant_seed(study, pid), arm, design, pid, study)
        filled = simulate_responses(session, persona, rng.getrandbits(32))
        filled["simulated"] = {"scenario": scenario if effects is SCENARIOS.get(scenario) else "custom",
                               "persona": {k: round(v, 4) for k, v in persona.items()}}
        sessions.append(filled)
    return sessions
