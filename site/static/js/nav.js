/* The menu on a narrow screen. Every page loads this; nothing else needs it. */
(function () {
  'use strict';
  var nav = document.getElementById('site-nav');
  var toggle = document.getElementById('nav-toggle');
  var sheet = document.getElementById('nav-sheet');
  if (!nav || !toggle) return;
  function setOpen(open) {
    nav.classList.toggle('is-open', open);
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    document.body.style.overflow = open ? 'hidden' : '';
  }
  toggle.addEventListener('click', function () { setOpen(!nav.classList.contains('is-open')); });
  if (sheet) sheet.addEventListener('click', function (e) { if (e.target.closest('a')) setOpen(false); });
})();
