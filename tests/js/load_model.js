// Loads the MODEL block from app/index.html so it can be tested in Node.js.
'use strict';
const fs = require('fs');
const path = require('path');

const APP = path.join(__dirname, '..', '..', 'app', 'index.html');

function modelSource() {
  const html = fs.readFileSync(APP, 'utf8');
  const start = html.indexOf('/* MODEL START */');
  const end = html.indexOf('/* MODEL END */');
  if (start < 0 || end < 0) throw new Error('MODEL markers not found in app/index.html');
  return html.slice(start, end);
}

function loadModel() {
  const mod = { exports: {} };
  new Function('module', modelSource())(mod);
  return mod.exports;
}

module.exports = { loadModel, modelSource, APP };
