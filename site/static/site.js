// Search, topic filter, sort, grid or list view and "show more" for the project archive.
(function () {
  'use strict';
  var dataEl = document.getElementById('data');
  if (!dataEl) return;
  var projects = JSON.parse(dataEl.textContent);
  var cats = JSON.parse(document.getElementById('cats').textContent);
  var grid = document.getElementById('grid');
  var count = document.getElementById('count');
  var empty = document.getElementById('empty');
  var more = document.getElementById('more');
  var q = document.getElementById('q');
  var sort = document.getElementById('sort');
  var blurb = document.getElementById('cat-blurb');
  var viewGrid = document.getElementById('view-grid');
  var viewList = document.getElementById('view-list');
  var chips = Array.prototype.slice.call(document.querySelectorAll('.chip'));
  var PAGE = 24;
  var state = { q: '', cat: '', sort: 'new', shown: PAGE, view: 'grid' };

  try { if (localStorage.getItem('view') === 'list') state.view = 'list'; } catch (e) { /* storage may be blocked */ }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function shortDate(iso) {
    var p = iso.split('-');
    return Number(p[2]) + ' ' + MONTHS[Number(p[1]) - 1] + ' ' + p[0];
  }
  function pad(n) { return ('00' + n).slice(-3); }

  // Mirrors card_html() in site/build_site.py.
  function card(p) {
    var cat = cats[p.cat] || { name: 'Other', color: '#64748b' };
    var shot = p.cover ? '<img src="' + esc(p.cover) + '" alt="" loading="lazy" width="960" height="600">'
      : '<span class="no-shot" aria-hidden="true">' + esc(p.name.charAt(0)) + '</span>';
    return '<article class="card"><a class="card-link" href="' + esc(p.url) + '">' +
      '<div class="shot" style="--c:' + esc(cat.color) + '">' + shot + '</div><div class="card-body">' +
      '<p class="card-meta"><span class="num">No. ' + pad(p.n) + '</span><time datetime="' + esc(p.date) + '">' + esc(shortDate(p.date)) + '</time></p>' +
      '<h3>' + esc(p.name) + '</h3><p class="tag">' + esc(p.tag) + '</p>' +
      '<span class="topic"><span class="dot" style="--c:' + esc(cat.color) + '"></span>' + esc(cat.name) + '</span></div></a></article>';
  }

  // Every word must appear somewhere in the project's name, hook, summary, theme or topic.
  function matches(p, words) {
    if (!words.length) return true;
    var cat = cats[p.cat] ? cats[p.cat].name : '';
    var hay = (p.name + ' ' + p.tag + ' ' + p.what + ' ' + p.theme + ' ' + cat + ' no. ' + pad(p.n)).toLowerCase();
    return words.every(function (w) { return hay.indexOf(w) >= 0; });
  }

  function filtered() {
    var words = state.q.toLowerCase().split(/\s+/).filter(Boolean);
    var list = projects.filter(function (p) { return (!state.cat || p.cat === state.cat) && matches(p, words); });
    if (state.sort === 'old') list = list.slice().reverse();
    else if (state.sort === 'az') list = list.slice().sort(function (a, b) { return a.name.localeCompare(b.name, 'en-GB'); });
    return list;
  }

  function render() {
    var list = filtered();
    grid.innerHTML = list.slice(0, state.shown).map(card).join('');
    grid.classList.toggle('list', state.view === 'list');
    viewGrid.setAttribute('aria-pressed', String(state.view === 'grid'));
    viewList.setAttribute('aria-pressed', String(state.view === 'list'));
    var n = list.length;
    count.textContent = n === projects.length ? n + ' projects' : n + ' of ' + projects.length + ' projects';
    empty.hidden = n > 0;
    more.hidden = n <= state.shown;
    more.textContent = 'Show more (' + Math.max(0, n - state.shown) + ' more)';
    chips.forEach(function (c) { c.setAttribute('aria-pressed', String(c.getAttribute('data-cat') === state.cat)); });
    blurb.textContent = state.cat && cats[state.cat] ? cats[state.cat].blurb : '';
  }

  // The filter lives in the address, so a filtered view can be shared or bookmarked.
  function writeHash() {
    var parts = [];
    if (state.cat) parts.push('category=' + encodeURIComponent(state.cat));
    if (state.q) parts.push('q=' + encodeURIComponent(state.q));
    if (state.sort !== 'new') parts.push('sort=' + state.sort);
    try { history.replaceState(null, '', parts.length ? '#' + parts.join('&') : '#archive'); } catch (e) { /* local files */ }
  }

  function readHash() {
    var h = location.hash.replace(/^#/, '');
    if (!h || h === 'archive') return false;
    var found = false;
    h.split('&').forEach(function (kv) {
      var i = kv.indexOf('='), k = kv.slice(0, i), v = decodeURIComponent(kv.slice(i + 1));
      if (k === 'category' && (cats[v] || v === '')) { state.cat = v; found = true; }
      if (k === 'q') { state.q = v; found = true; }
      if (k === 'sort' && /^(new|old|az)$/.test(v)) { state.sort = v; found = true; }
    });
    return found;
  }

  var timer = null;
  q.addEventListener('input', function () {
    clearTimeout(timer);
    timer = setTimeout(function () { state.q = q.value.trim(); state.shown = PAGE; render(); writeHash(); }, 120);
  });
  sort.addEventListener('change', function () { state.sort = sort.value; state.shown = PAGE; render(); writeHash(); });
  chips.forEach(function (c) {
    c.addEventListener('click', function () { state.cat = c.getAttribute('data-cat'); state.shown = PAGE; render(); writeHash(); });
  });
  [viewGrid, viewList].forEach(function (b) {
    b.addEventListener('click', function () {
      state.view = b === viewList ? 'list' : 'grid';
      try { localStorage.setItem('view', state.view); } catch (e) { /* storage may be blocked */ }
      render();
    });
  });
  more.addEventListener('click', function () {
    var before = state.shown;
    state.shown += PAGE;
    render();
    var next = grid.children[before];
    if (next) { var link = next.querySelector('a'); if (link) link.focus(); }
  });

  if (readHash()) {
    q.value = state.q;
    sort.value = state.sort;
    render();
    document.getElementById('archive').scrollIntoView();
  } else {
    render();
  }
})();
