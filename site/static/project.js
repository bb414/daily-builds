// Tabs on a project page (Try it, How it works, Findings, Tour) and the step-through tour.
(function () {
  'use strict';
  var tabs = Array.prototype.slice.call(document.querySelectorAll('[role="tab"]'));
  if (!tabs.length) return;
  var keys = tabs.map(function (t) { return t.getAttribute('data-tab'); });

  function show(key, focus) {
    if (keys.indexOf(key) < 0) key = keys[0];
    tabs.forEach(function (t) {
      var on = t.getAttribute('data-tab') === key;
      t.setAttribute('aria-selected', String(on));
      t.tabIndex = on ? 0 : -1;
      document.getElementById('panel-' + t.getAttribute('data-tab')).hidden = !on;
      if (on && focus) t.focus();
    });
  }

  tabs.forEach(function (t, i) {
    t.addEventListener('click', function () {
      show(t.getAttribute('data-tab'));
      try { history.replaceState(null, '', '#' + t.getAttribute('data-tab')); } catch (e) { /* local files */ }
    });
    t.addEventListener('keydown', function (e) {
      var j = e.key === 'ArrowRight' ? i + 1 : e.key === 'ArrowLeft' ? i - 1 : e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : null;
      if (j === null) return;
      e.preventDefault();
      j = (j + tabs.length) % tabs.length;
      show(keys[j], true);
      try { history.replaceState(null, '', '#' + keys[j]); } catch (err) { /* local files */ }
    });
  });
  show(location.hash.replace('#', ''));
  window.addEventListener('hashchange', function () { show(location.hash.replace('#', '')); });

  // The tour shows one screenshot at a time once scripts are running.
  var tour = document.querySelector('.tour');
  if (!tour) return;
  var steps = Array.prototype.slice.call(tour.querySelectorAll('.tour-step'));
  var nav = tour.querySelector('.tour-nav');
  var pos = tour.querySelector('.tour-pos');
  var at = 0;
  function go(i) {
    at = (i + steps.length) % steps.length;
    steps.forEach(function (s, k) { s.hidden = k !== at; });
    pos.textContent = (at + 1) + ' of ' + steps.length;
  }
  if (steps.length > 1) {
    tour.classList.add('one-at-a-time');
    nav.hidden = false;
    nav.addEventListener('click', function (e) {
      var b = e.target.closest('[data-move]');
      if (b) go(at + Number(b.getAttribute('data-move')));
    });
    tour.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowRight') go(at + 1);
      if (e.key === 'ArrowLeft') go(at - 1);
    });
    go(0);
  }
})();
