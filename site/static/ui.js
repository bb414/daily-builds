// Site-wide touches: the header darkens once the page scrolls, and sections fade in as they arrive.
(function () {
  'use strict';
  function ready() {
    var head = document.querySelector('.site-head');
    function onScroll() { if (head) head.classList.toggle('scrolled', window.scrollY > 8); }
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });

    var items = Array.prototype.slice.call(document.querySelectorAll('.reveal'));
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!items.length || reduce || !('IntersectionObserver' in window)) return;
    items.forEach(function (el) { el.classList.add('pending'); });
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.remove('pending'); io.unobserve(e.target); }
      });
    }, { rootMargin: '0px 0px -8% 0px' });
    items.forEach(function (el) { io.observe(el); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready); else ready();
})();
