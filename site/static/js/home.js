/*
 * The home page: the field of eyes, the live panel, the visit reduction, the
 * tour tabs and the arrivals. No library and no request to anywhere.
 *
 * With prefers-reduced-motion everything is drawn once, in its finished state,
 * and nothing moves. Without JavaScript the page is complete apart from the
 * panel's numbers and the eyes, which are decoration.
 */
(function () {
  'use strict';

  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var $ = function (id) { return document.getElementById(id); };

  /* ---------------------------------------------------------------- nav */
  var nav = $('site-nav'), toggle = $('nav-toggle'), sheet = $('nav-sheet');
  if (nav && toggle) {
    var setOpen = function (open) {
      nav.classList.toggle('is-open', open);
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      document.body.style.overflow = open ? 'hidden' : '';
    };
    toggle.addEventListener('click', function () { setOpen(!nav.classList.contains('is-open')); });
    if (sheet) sheet.addEventListener('click', function (e) { if (e.target.closest('a')) setOpen(false); });
  }

  /* ------------------------------------------------------------ arrivals */
  var seen = function (el) { el.classList.add('is-seen'); };
  var rises = document.querySelectorAll('.rise');
  if (reduced || !('IntersectionObserver' in window)) {
    rises.forEach(seen);
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) { seen(entry.target); io.unobserve(entry.target); }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    rises.forEach(function (el) { io.observe(el); });
  }

  /* ---------------------------------------------------------- eye field */
  /* The eyes watch the traffic, which is the panel. Wherever the pointer is,
     which is the visitor, they close. */
  var field = $('eyefield'), panel = $('live-panel');
  var eyes = [];
  var EYE = '<g class="lids"><path class="eye-lid" d="M2 12Q20-5 38 12Q20 29 2 12Z"/></g>' +
            '<g class="ball"><circle class="eye-iris" cx="20" cy="12" r="6.2"/><circle class="eye-pupil" cx="20" cy="12" r="2.6"/></g>';

  function buildEyes() {
    if (!field) return;
    field.textContent = '';
    eyes = [];
    var box = field.getBoundingClientRect();
    var stepX = box.width < 700 ? 64 : 84, stepY = box.width < 700 ? 50 : 58;
    var rows = Math.ceil(box.height / stepY) + 1, cols = Math.ceil(box.width / stepX) + 1;
    var target = panel ? panel.getBoundingClientRect() : null;
    var tx = target ? target.left + target.width / 2 - box.left : box.width * 0.75;
    var ty = target ? target.top + target.height * 0.42 - box.top : box.height * 0.4;
    var frag = document.createDocumentFragment();
    for (var r = 0; r < rows; r++) {
      for (var c = 0; c < cols; c++) {
        var x = c * stepX + (r % 2 ? stepX / 2 : 0) - 10, y = r * stepY + 6;
        var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('viewBox', '0 0 40 24');
        svg.innerHTML = EYE;
        svg.style.left = x + 'px';
        svg.style.top = y + 'px';
        var cx = x + 20, cy = y + 12;
        var dx = tx - cx, dy = ty - cy, d = Math.sqrt(dx * dx + dy * dy) || 1;
        svg.querySelector('.ball').style.transform = 'translate(' + (dx / d * 3.6).toFixed(2) + 'px,' + (dy / d * 2.2).toFixed(2) + 'px)';
        frag.appendChild(svg);
        eyes.push({ el: svg, x: cx, y: cy, shut: false });
      }
    }
    field.appendChild(frag);
  }

  var pointer = null, queued = false;
  function lookAway() {
    queued = false;
    for (var i = 0; i < eyes.length; i++) {
      var e = eyes[i], shut = false;
      if (pointer) {
        var dx = e.x - pointer.x, dy = e.y - pointer.y;
        shut = dx * dx + dy * dy < 150 * 150;
      }
      if (shut !== e.shut) { e.shut = shut; e.el.classList.toggle('is-shut', shut); }
    }
  }
  if (field) {
    buildEyes();
    var resizeTimer;
    window.addEventListener('resize', function () { clearTimeout(resizeTimer); resizeTimer = setTimeout(buildEyes, 180); });
    if (!reduced) {
      var hero = field.parentNode;
      hero.addEventListener('pointermove', function (ev) {
        var box = field.getBoundingClientRect();
        pointer = { x: ev.clientX - box.left, y: ev.clientY - box.top };
        if (!queued) { queued = true; requestAnimationFrame(lookAway); }
      });
      hero.addEventListener('pointerleave', function () { pointer = null; lookAway(); });
      /* Never all closed at once: a few blink on their own. */
      setInterval(function () {
        if (document.hidden || !eyes.length) return;
        var e = eyes[Math.floor(Math.random() * eyes.length)];
        if (e.shut) return;
        e.el.classList.add('is-shut');
        setTimeout(function () { if (!e.shut) e.el.classList.remove('is-shut'); }, 190);
      }, 520);
    }
  }

  /* --------------------------------------------------------- live panel */
  var HOURS = [9, 7, 5, 4, 5, 9, 18, 34, 52, 61, 118, 96, 84, 79, 88, 71, 0, 0, 0, 0, 0, 0, 0, 0];
  var NOW = 15;            /* the hour that is still filling */
  var NOTE_AT = 10;        /* the hour the newsletter went out */
  var PAGES = [['/', 1204], ['/pricing', 866], ['/blog/cookieless', 512], ['/docs/install', 377], ['/checkout', 148]];
  var ARRIVALS = [
    ['SE', '/'], ['NO', '/pricing'], ['DE', '/blog/cookieless'], ['SE', '/checkout'], ['US', '/'],
    ['FI', '/docs/install'], ['DK', '/pricing'], ['SE', '/blog/cookieless'], ['GB', '/'], ['NL', '/pricing'],
    ['SE', '/docs/install'], ['DE', '/'], ['FR', '/pricing'], ['SE', '/']
  ];
  var W = 400, H = 132, TOP = 10, BASE = 131;

  function chartPath() {
    var max = 130, pts = [];
    for (var i = 0; i <= NOW; i++) pts.push([i / 23 * W, BASE - (HOURS[i] / max) * (BASE - TOP)]);
    var d = 'M' + pts[0][0].toFixed(1) + ' ' + pts[0][1].toFixed(1);
    for (var k = 1; k < pts.length; k++) {
      var p0 = pts[k - 1], p1 = pts[k], mx = (p0[0] + p1[0]) / 2;
      d += ' C' + mx.toFixed(1) + ' ' + p0[1].toFixed(1) + ' ' + mx.toFixed(1) + ' ' + p1[1].toFixed(1) + ' ' + p1[0].toFixed(1) + ' ' + p1[1].toFixed(1);
    }
    return { line: d, area: d + ' L' + pts[pts.length - 1][0].toFixed(1) + ' ' + BASE + ' L0 ' + BASE + ' Z', last: pts[pts.length - 1] };
  }

  function drawChart() {
    var line = $('p-line'), area = $('p-area');
    if (!line) return;
    var p = chartPath();
    line.setAttribute('d', p.line);
    area.setAttribute('d', p.area);
    var nx = NOTE_AT / 23 * W;
    $('p-note').setAttribute('x1', nx); $('p-note').setAttribute('x2', nx);
    $('p-note-dot').setAttribute('cx', nx);
    $('p-note-label').style.left = 'calc(18px + (100% - 36px) * ' + (nx / W).toFixed(4) + ')';
    var dot = $('p-now');
    if (!dot) {
      dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      dot.setAttribute('id', 'p-now'); dot.setAttribute('class', 'now'); dot.setAttribute('r', '3.6');
      line.parentNode.appendChild(dot);
    }
    dot.setAttribute('cx', p.last[0]); dot.setAttribute('cy', p.last[1]);
  }

  function drawPages() {
    var box = $('p-pages');
    if (!box) return;
    var top = PAGES[0][1];
    if (!box.children.length) {
      PAGES.forEach(function () {
        var row = document.createElement('div');
        row.className = 'rowbar';
        row.innerHTML = '<span></span><b></b>';
        box.appendChild(row);
      });
    }
    PAGES.forEach(function (page, i) {
      var row = box.children[i];
      row.firstChild.textContent = page[0];
      row.lastChild.textContent = page[1].toLocaleString('en-US');
      row.style.setProperty('--w', Math.max(6, page[1] / top * 100) + '%');
    });
  }

  var HEX = '0123456789abcdef';
  function hash() {
    var s = '';
    for (var i = 0; i < 4; i++) s += HEX[Math.floor(Math.random() * 16)];
    return s + '…';
  }
  function arrive(entry, quiet) {
    var feed = $('p-feed');
    if (!feed) return;
    var li = document.createElement('li');
    if (quiet) li.style.animation = 'none';
    li.innerHTML = '<span class="cc"></span><span class="path"></span><span class="hash"></span>';
    li.children[0].textContent = entry[0];
    li.children[1].textContent = entry[1];
    li.children[2].textContent = hash();
    feed.insertBefore(li, feed.firstChild);
    while (feed.children.length > 5) feed.removeChild(feed.lastChild);
  }

  var visitors = 1284, views = 3902, step = 0;
  function setNumber(id, n) { var el = $(id); if (el) el.textContent = n.toLocaleString('en-US'); }

  if (panel) {
    drawChart();
    drawPages();
    for (var a = 4; a >= 0; a--) arrive(ARRIVALS[a], true);
    step = 5;
    if (!reduced) {
      setInterval(function () {
        if (document.hidden) return;
        var entry = ARRIVALS[step % ARRIVALS.length];
        step++;
        arrive(entry);
        views += 1;
        if (step % 3 !== 0) visitors += 1;
        setNumber('p-views', views);
        setNumber('p-visitors', visitors);
        setNumber('p-online', 10 + ((step * 7) % 6));
        for (var i = 0; i < PAGES.length; i++) if (PAGES[i][0] === entry[1]) PAGES[i][1] += 1;
        drawPages();
        HOURS[NOW] += 1;
        drawChart();
      }, 2100);
    }
  }

  /* ------------------------------------------------- the visit, reduced */
  var WHO = {
    anna: {
      when: 'today, 14:02', ip: '81.224.17.<s>42</s>', extraK: 'Cookie', extraV: 'none sent, none set',
      hash: '7c1e…a94f', note: 'a hash that is only good until midnight',
      verdict: 'The address is cut down, hashed together with the browser, your domain and today’s salt, and discarded. There is no column to keep it in.'
    },
    tomorrow: {
      when: 'tomorrow, 09:40', ip: '81.224.17.<s>42</s>', extraK: 'Cookie', extraV: 'none sent, none set',
      hash: 'd02b…5e17', note: 'same person, same browser, new salt, new hash',
      verdict: 'Nothing links this visit to yesterday’s. Anna is a new visitor every day, so there is no history of her to build, sell or leak.'
    },
    colleague: {
      when: 'today, 14:05', ip: '81.224.17.<s>97</s>', extraK: 'Cookie', extraV: 'none sent, none set',
      hash: '7c1e…a94f', note: 'same network and browser as Anna: the same hash',
      verdict: 'Two people on one office network with the same browser count as one visitor. Argusmetrics undercounts on purpose rather than learn to tell them apart.'
    },
    dnt: {
      when: 'today, 14:07', ip: '92.35.201.<s>8</s>', extraK: 'DNT', extraV: '<mark>1</mark>',
      empty: true
    }
  };
  var xout = $('x-out');
  function show(who) {
    var w = WHO[who];
    if (!w || !xout) return;
    document.querySelectorAll('[data-who]').forEach(function (b) { b.setAttribute('aria-pressed', b.getAttribute('data-who') === who ? 'true' : 'false'); });
    $('x-when').textContent = w.when;
    $('x-ip').innerHTML = w.ip;
    $('x-cut').textContent = w.empty ? 'read to answer the request, and never written down' : 'cut to 81.224.17.0/24, hashed, then thrown away';
    $('x-extra-k').textContent = w.extraK;
    $('x-extra-v').innerHTML = w.extraV;
    xout.classList.toggle('is-empty', !!w.empty);
    if (w.empty) return;
    var code = $('x-hash');
    var changed = code.textContent !== w.hash;
    code.textContent = w.hash;
    $('x-hash-note').textContent = w.note;
    $('x-verdict').textContent = w.verdict;
    code.classList.remove('flash');
    if (!reduced) {
      void code.offsetWidth;
      code.classList.add('flash');
      setTimeout(function () { code.classList.remove('flash'); }, changed ? 900 : 500);
    }
  }
  document.querySelectorAll('[data-who]').forEach(function (b) {
    b.addEventListener('click', function () { show(b.getAttribute('data-who')); });
  });

  /* ---------------------------------------------------------- tour tabs */
  var tour = $('tour');
  if (tour) {
    tour.addEventListener('click', function (ev) {
      var tab = ev.target.closest('[role="tab"]');
      if (!tab) return;
      var name = tab.getAttribute('data-pane');
      tour.querySelectorAll('[role="tab"]').forEach(function (t) { t.setAttribute('aria-pressed', t === tab ? 'true' : 'false'); });
      tour.querySelectorAll('.tour-pane').forEach(function (p) { p.hidden = p.getAttribute('data-pane') !== name; });
    });
  }

  /* ------------------------------------------------------------ terminal */
  var copy = $('term-copy');
  if (copy && navigator.clipboard) {
    copy.addEventListener('click', function () {
      var text = 'git clone https://github.com/Benbo-se/ArgusmetricsSH\ncd ArgusmetricsSH/docker\ncp .env.example .env\ndocker compose up -d postgres backend\n';
      navigator.clipboard.writeText(text).then(function () {
        copy.textContent = 'Copied';
        setTimeout(function () { copy.textContent = 'Copy'; }, 1500);
      });
    });
  } else if (copy) {
    copy.hidden = true;
  }
})();
