// Loads the model block from app/index.html so Node can run and test it.
'use strict';
const fs = require('fs');
const path = require('path');

function loadModel() {
  const html = fs.readFileSync(path.join(__dirname, '..', 'app', 'index.html'), 'utf8');
  const start = html.indexOf('/* MODEL START */');
  const end = html.indexOf('/* MODEL END */');
  if (start < 0 || end < 0) throw new Error('Model markers not found in app/index.html');
  const src = html.slice(start, end);
  const mod = { exports: {} };
  new Function('module', src)(mod);
  return mod.exports;
}

module.exports = { loadModel };
