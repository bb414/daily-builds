// Loads the model block from the browser app so Node.js can test it.
'use strict';
const fs = require('fs');
const path = require('path');

const APP = path.join(__dirname, '..', 'app', 'index.html');

function modelSource() {
  const html = fs.readFileSync(APP, 'utf8');
  const start = html.indexOf('/* MODEL START */');
  const end = html.indexOf('/* MODEL END */');
  if (start < 0 || end < 0 || end < start) {
    throw new Error('Could not find the MODEL START and MODEL END markers in app/index.html');
  }
  return html.slice(start, end);
}

function loadModel() {
  const module = { exports: {} };
  // eslint-disable-next-line no-new-func
  new Function('module', modelSource())(module);
  return module.exports;
}

module.exports = { loadModel, modelSource, APP };

// When run directly, act as a tiny bridge for the Python agreement test:
//   node tests/load_model.cjs score < sessions.json   prints a JSON list of scores
//   node tests/load_model.cjs build < seeds.json      prints a JSON list of sessions
//   node tests/load_model.cjs items                   prints the item design
//   node tests/load_model.cjs csv < sessions.json     prints each session as CSV text
//   node tests/load_model.cjs validate < objs.json    prints the problems found in each
//   node tests/load_model.cjs condition < args.json   prints each normalised condition
if (require.main === module) {
  const M = loadModel();
  const command = process.argv[2];
  const input = command === 'items' ? '' : fs.readFileSync(0, 'utf8');
  let out;
  if (command === 'score') {
    out = JSON.parse(input).map((s) => M.score(s));
  } else if (command === 'build') {
    out = JSON.parse(input).map((args) => M.buildSession(args.seed, args.condition));
  } else if (command === 'items') {
    out = M.ITEMS.map((it) => ({
      id: it.id, role: it.role, pair: it.pair || null, truth: it.truth, difficulty: it.difficulty,
      ai_verdict: it.ai ? it.ai.verdict : null, ai_confidence: it.ai ? it.ai.confidence : null
    }));
  } else if (command === 'csv') {
    out = JSON.parse(input).map((s) => M.sessionToCsv(s));
  } else if (command === 'condition') {
    out = JSON.parse(input).map((args) => M.normaliseCondition(args.condition, args.seed));
  } else if (command === 'validate') {
    out = JSON.parse(input).map((s) => M.validateSession(s));
  } else {
    process.stderr.write('Unknown command: ' + command + '\n');
    process.exit(2);
  }
  process.stdout.write(JSON.stringify(out));
}
