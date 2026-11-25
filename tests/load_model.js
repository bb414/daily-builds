// Loads the MODEL block out of app/index.html so Node.js can run it without a browser.
'use strict';
const fs = require('fs');
const path = require('path');

function loadModel() {
  const html = fs.readFileSync(path.join(__dirname, '..', 'app', 'index.html'), 'utf8');
  const start = html.indexOf('/* MODEL START */');
  const end = html.indexOf('/* MODEL END */');
  if (start < 0 || end < start) throw new Error('MODEL block not found in app/index.html');
  const module = { exports: {} };
  // Run in this realm so arrays and objects compare normally in tests.
  new Function('module', html.slice(start, end))(module);
  return module.exports;
}

module.exports = { loadModel };
