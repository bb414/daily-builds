// Loads the model block from the browser app so Node.js can test it.
'use strict';
const fs = require('fs');
const path = require('path');

const APP = path.join(__dirname, '..', 'app', 'index.html');

function loadModel() {
  const html = fs.readFileSync(APP, 'utf8');
  const start = html.indexOf('/* MODEL START */');
  const end = html.indexOf('/* MODEL END */');
  if (start < 0 || end < start) { throw new Error('MODEL START and MODEL END markers not found in app/index.html'); }
  const module = { exports: {} };
  // eslint-disable-next-line no-new-func
  new Function('module', html.slice(start, end))(module);
  return module.exports;
}

module.exports = { loadModel };

// Bridge for the Python agreement tests. Reads JSON from standard input:
//   node tests/load_model.cjs run < settings-list.json     results and every forecast
//   node tests/load_model.cjs data < datasets.json         forecasts and results for given datasets
//   node tests/load_model.cjs pilot < jobs.json            pilot windows for given settings
//   node tests/load_model.cjs settings < inputs.json       normalised settings
if (require.main === module) {
  const M = loadModel();
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  let out;
  if (process.argv[2] === 'run') {
    out = input.map((s) => {
      const r = M.run(s);
      return { sales: r.data.sales, promo: r.data.promo, events: r.data.events, forecasts: r.forecasts.forecasts,
        overridden: r.forecasts.overridden, coefficients: r.forecasts.coefficients, results: r.results };
    });
  } else if (process.argv[2] === 'data') {
    out = input.map((job) => {
      const fc = M.forecastAll(job.data, job.settings);
      return { forecasts: fc.forecasts, results: M.evaluate(job.data, fc) };
    });
  } else if (process.argv[2] === 'pilot') {
    out = input.map((job) => {
      const r = M.run(job.settings);
      return M.pilotWindows(r.data, r.forecasts, job.settings, job.length, job.stores);
    });
  } else if (process.argv[2] === 'settings') {
    out = input.map((s) => M.normaliseSettings(s));
  } else {
    process.stderr.write('Unknown command\n');
    process.exit(2);
  }
  process.stdout.write(JSON.stringify(out));
}
