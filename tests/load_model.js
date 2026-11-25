// Loads the MODEL block from the browser app so Node.js tests run the exact
// code the page runs.
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

function loadModel() {
  const html = fs.readFileSync(path.join(__dirname, '..', 'app', 'index.html'), 'utf8');
  const start = html.indexOf('/* MODEL START */');
  const end = html.indexOf('/* MODEL END */');
  if (start < 0 || end < 0) throw new Error('MODEL markers not found in app/index.html');
  const code = html.slice(start, end + '/* MODEL END */'.length);
  const sandbox = { module: { exports: {} }, Math, Object, Array, Number, Set, String, JSON, Infinity };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox, { filename: 'app/index.html#model' });
  return sandbox.module.exports;
}

module.exports = { loadModel };
