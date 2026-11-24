// Loads the MODEL block from app/index.html so it can run in Node.js.
// Used by the Node tests directly, and by the Python parity tests as a
// command-line bridge: it reads a JSON request on stdin and prints JSON.
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

function loadModel() {
  const html = fs.readFileSync(path.join(__dirname, '..', 'app', 'index.html'), 'utf8');
  const match = html.match(/\/\* MODEL START \*\/([\s\S]*?)\/\* MODEL END \*\//);
  if (!match) throw new Error('MODEL START / MODEL END markers not found in app/index.html');
  const sandbox = { module: { exports: {} } };
  vm.runInNewContext(match[1], sandbox, { filename: 'app/index.html#model' });
  return sandbox.module.exports;
}

module.exports = { loadModel };

if (require.main === module) {
  const M = loadModel();
  const request = JSON.parse(fs.readFileSync(0, 'utf8'));
  const answer = request.calls.map(function (call) {
    const fn = call.fn.split('.').reduce(function (obj, key) { return obj[key]; }, M);
    return typeof fn === 'function' ? fn.apply(null, call.args || []) : fn;
  });
  process.stdout.write(JSON.stringify(answer));
}
