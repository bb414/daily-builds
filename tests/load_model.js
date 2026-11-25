// Loads the model block from app/index.html so Node can run exactly what the browser runs.
'use strict';
const fs = require('fs');
const path = require('path');

function loadModel() {
  const html = fs.readFileSync(path.join(__dirname, '..', 'app', 'index.html'), 'utf8');
  const start = html.indexOf('/* MODEL START */');
  const end = html.indexOf('/* MODEL END */');
  if (start < 0 || end < 0) throw new Error('MODEL START/END markers not found');
  const code = html.slice(start, end);
  const mod = { exports: {} };
  new Function('module', code)(mod);
  return mod.exports;
}

module.exports = { loadModel };
