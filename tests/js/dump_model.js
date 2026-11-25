// Prints the browser model's results as JSON so tests/test_agreement.py can compare them with Python.
'use strict';
const { loadModel } = require('./load_model');

const M = loadModel();
const cases = JSON.parse(process.argv[2]);
const out = {
  rng: (() => { const r = M.mulberry32(2026); return [r(), r(), r(), r()]; })(),
  ln: [0.37, 1, 2, 17, 4000.5].map(M.ln),
  exp: [-30.2, -2.5, -0.01, 0, 1.9].map(M.exp),
  population: M.buildPopulation().docs.map((d) => [d.desc, d.feats, d.cat]),
  cases: cases.map((c) => {
    const st = M.generateStatement(c.persona, c.weeks, c.seed);
    const session = new M.Session(st, { weight: c.weight });
    return {
      tx: st.tx.map((t) => [t.date, t.desc, t.pennies, t.cat, t.wd]),
      dayOne: { pred: session.model.pred, conf: session.model.conf },
      compare: M.compareStrategies(st, { checks: c.checks, target: c.target, slip: c.slip, weight: c.weight })
        .map((r) => ({ strategy: r.strategy, toTarget: r.toTarget, picks: r.picks, points: r.points }))
    };
  })
};
process.stdout.write(JSON.stringify(out));
