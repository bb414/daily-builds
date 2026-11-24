// Runs the browser app's model block in Node.js for the Python tests.
// Reads a JSON list of calls on stdin, e.g. [{"fn": "buildSession", "args": [1]}],
// and prints a JSON list of results. With "catchErrors": true a call returns
// {"ok": true} or {"error": message} instead of its result.
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', 'app', 'index.html'), 'utf8');
const start = html.indexOf('/* MODEL START */');
const end = html.indexOf('/* MODEL END */');
if (start < 0 || end < 0) throw new Error('model markers not found');
const mod = {exports: {}};
new Function('module', html.slice(start, end))(mod);
const M = mod.exports;

const calls = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = calls.map(c => {
  if (c.get) return M[c.get];
  const fn = M[c.fn];
  if (typeof fn !== 'function') throw new Error('no such function: ' + c.fn);
  if (!c.catchErrors) return fn.apply(null, c.args || []);
  try {
    fn.apply(null, c.args || []);
    return {ok: true};
  } catch (e) {
    return {error: e.message};
  }
});
process.stdout.write(JSON.stringify(out));
