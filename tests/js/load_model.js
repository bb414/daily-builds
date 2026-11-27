// Loads the model block from app/index.html so it can be tested in Node.js.
'use strict';
const fs = require('fs');
const path = require('path');

function loadModel() {
  const file = path.join(__dirname, '..', '..', 'app', 'index.html');
  const html = fs.readFileSync(file, 'utf8');
  const start = html.indexOf('/* MODEL START */');
  const end = html.indexOf('/* MODEL END */');
  if (start < 0 || end < 0) throw new Error('model markers not found in app/index.html');
  const mod = { exports: {} };
  new Function('module', html.slice(start, end))(mod);
  return mod.exports;
}

module.exports = { loadModel };
