/*
 * The home page. The data is the ornament here: the iris of every mark is a
 * 24-hour chart, the edge between two bands is a traffic curve, and the panel
 * in the hero shows this site's own numbers, read from its own public
 * dashboard (data-pulse on the panel). Nothing is requested from another
 * origin.
 *
 * If the numbers cannot be read (no network, a local build, a browser that
 * refuses), everything is drawn from the invented series below and the panel
 * says so. With prefers-reduced-motion everything is drawn once, finished.
 */
(function () {
  'use strict';

  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var SVG = 'http://www.w3.org/2000/svg';
  var $ = function (id) { return document.getElementById(id); };
  var all = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  var el = function (name, attrs) {
    var node = document.createElementNS(SVG, name);
    for (var k in attrs) node.setAttribute(k, attrs[k]);
    return node;
  };
  var fmt = function (n) { return Math.round(n).toLocaleString('en-US'); };

  /* ---------------------------------------------------------------- data */
  /* Invented, and labelled as such wherever it is shown. */
  var DEMO_HOURS = [9, 7, 5, 4, 5, 9, 18, 34, 52, 61, 118, 96, 84, 79, 88, 71];
  var DEMO_DAYS = [212, 248, 236, 254, 201, 143, 151, 262, 281, 270, 296, 240, 162, 158, 301, 322, 310, 334, 288, 176, 181, 344, 590, 402, 371, 329, 204, 199, 362, 381];
  var state = {
    real: false,
    hours: DEMO_HOURS.slice(),        /* today so far, one value per hour */
    days: DEMO_DAYS,                  /* thirty days of visitors */
    views: DEMO_DAYS.map(function (v, i) { return Math.round(v * (2.6 + (i % 5) * .12)); }),
    hourNow: DEMO_HOURS.length - 1
  };

  /* A smooth line through evenly spaced values, in a box w by h. */
  function curve(values, w, h, top) {
    var max = Math.max.apply(null, values.concat([1]));
    var n = values.length, pts = [];
    for (var i = 0; i < n; i++) pts.push([n === 1 ? w : i / (n - 1) * w, h - (values[i] / max) * (h - top)]);
    var d = 'M' + pts[0][0].toFixed(1) + ' ' + pts[0][1].toFixed(1);
    for (var k = 1; k < n; k++) {
      var a = pts[k - 1], b = pts[k], mx = (a[0] + b[0]) / 2;
      d += ' C' + mx.toFixed(1) + ' ' + a[1].toFixed(1) + ' ' + mx.toFixed(1) + ' ' + b[1].toFixed(1) + ' ' + b[0].toFixed(1) + ' ' + b[1].toFixed(1);
    }
    return { line: d, pts: pts };
  }

  /* ------------------------------------------------------------ arrivals */
  var seen = function (node) { node.classList.add('is-seen'); };
  var rises = all('.rise');
  if (reduced || !('IntersectionObserver' in window)) {
    rises.forEach(seen);
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) { seen(entry.target); io.unobserve(entry.target); }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    rises.forEach(function (node) { io.observe(node); });
  }

  /* ------------------------------------------------------------ the mark */
  /* An eye whose iris is the day: twenty-four bars, midnight at the top,
     the hour that is still filling in gold. */
  var CX = 32, CY = 20, R0 = 5.6, RMIN = 2.6, RMAX = 7.6;
  function buildMark(host) {
    host.textContent = '';
    var svg = el('svg', { viewBox: '0 0 64 40', 'aria-hidden': 'true' });
    svg.appendChild(el('path', { 'class': 'mark-lid', d: 'M3 20Q32-8 61 20Q32 48 3 20Z' }));
    var bars = [];
    for (var i = 0; i < 24; i++) {
      var bar = el('line', { 'class': 'mark-bar' });
      svg.appendChild(bar);
      bars.push(bar);
    }
    svg.appendChild(el('circle', { 'class': 'mark-pupil', cx: CX, cy: CY, r: 3.4 }));
    host.appendChild(svg);
    host._bars = bars;
  }
  function paintMark(host, grow) {
    var bars = host._bars;
    if (!bars) return;
    var hours = state.hours, max = Math.max.apply(null, hours.concat([1]));
    for (var i = 0; i < 24; i++) {
      var has = i < hours.length;
      /* Square root, so one busy hour does not flatten the rest of the day. */
      var len = has ? RMIN + Math.sqrt(hours[i] / max) * (RMAX - RMIN) : 1.3;
      len *= grow;
      var a = (i / 24) * Math.PI * 2 - Math.PI / 2;
      var cos = Math.cos(a), sin = Math.sin(a);
      bars[i].setAttribute('x1', (CX + cos * R0).toFixed(2));
      bars[i].setAttribute('y1', (CY + sin * R0).toFixed(2));
      bars[i].setAttribute('x2', (CX + cos * (R0 + len)).toFixed(2));
      bars[i].setAttribute('y2', (CY + sin * (R0 + len)).toFixed(2));
      bars[i].setAttribute('class', 'mark-bar' + (!has ? ' is-ahead' : i === state.hourNow ? ' is-now' : ''));
    }
  }
  var marks = all('[data-mark]');
  marks.forEach(buildMark);
  function paintMarks(animate) {
    if (!animate || reduced) { marks.forEach(function (m) { paintMark(m, 1); }); return; }
    var start = null;
    requestAnimationFrame(function frame(t) {
      if (start === null) start = t;
      var p = Math.min(1, (t - start) / 900), eased = 1 - Math.pow(1 - p, 3);
      marks.forEach(function (m) { paintMark(m, eased); });
      if (p < 1) requestAnimationFrame(frame);
    });
  }

  /* ----------------------------------------------------------- the seams */
  /* The edge between two bands is the traffic curve itself: the band below
     rises into the one above by as much as that day had visitors. */
  var seams = all('.seam');
  function paintSeams() {
    seams.forEach(function (seam, index) {
      var band = seam.parentNode;
      var fill = getComputedStyle(band).backgroundColor;
      var source = index % 2 ? state.views : state.days;
      /* Each seam reads the month from a different day, so no two match. */
      var shift = (index * 7) % source.length;
      var values = source.slice(shift).concat(source.slice(0, shift));
      var c = curve(values, 1000, 60, 6);
      seam.textContent = '';
      var svg = el('svg', { viewBox: '0 0 1000 60', preserveAspectRatio: 'none', 'aria-hidden': 'true' });
      svg.appendChild(el('path', { d: c.line + ' L1000 61 L0 61 Z', fill: fill }));
      svg.appendChild(el('path', { 'class': 'seam-line', d: c.line, 'vector-effect': 'non-scaling-stroke' }));
      seam.appendChild(svg);
    });
  }

  /* ----------------------------------------------- the reading, as a curve */
  var progress = $('progress');
  function paintProgress() {
    if (!progress) return;
    var c = curve(state.days, 1000, 14, 2);
    progress.textContent = '';
    /* The read part is the same line, shown through a window that widens.
       Not a dash offset: with a stroke that does not scale, dashes are
       measured on the screen and the line came out part drawn at the top. */
    var clip = el('clipPath', { id: 'progress-clip' });
    clip.appendChild(el('rect', { id: 'progress-window', x: '0', y: '-10', width: '0', height: '40' }));
    progress.appendChild(clip);
    progress.appendChild(el('path', { 'class': 'progress-rail', d: c.line, 'vector-effect': 'non-scaling-stroke' }));
    progress.appendChild(el('path', { 'class': 'progress-done', d: c.line, 'clip-path': 'url(#progress-clip)', 'vector-effect': 'non-scaling-stroke' }));
    onScroll();
  }
  function onScroll() {
    var pane = $('progress-window');
    if (!pane) return;
    var room = document.documentElement.scrollHeight - window.innerHeight;
    var f = room > 0 ? Math.min(1, Math.max(0, window.scrollY / room)) : 0;
    pane.setAttribute('width', (f * 1000).toFixed(1));
  }
  window.addEventListener('scroll', onScroll, { passive: true });

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
        var svg = document.createElementNS(SVG, 'svg');
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
  var resizeTimer, lastWidth = window.innerWidth;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      if (window.innerWidth !== lastWidth) { lastWidth = window.innerWidth; buildEyes(); }
      onScroll();
    }, 180);
  });

  /* ---------------------------------------------------------- the panel */
  var PAGES = [['/', 1204], ['/pricing', 866], ['/blog/cookieless', 512], ['/docs/install', 377], ['/checkout', 148]];
  var ARRIVALS = [
    ['SE', '/'], ['NO', '/pricing'], ['DE', '/blog/cookieless'], ['SE', '/checkout'], ['US', '/'],
    ['FI', '/docs/install'], ['DK', '/pricing'], ['SE', '/blog/cookieless'], ['GB', '/'], ['NL', '/pricing'],
    ['SE', '/docs/install'], ['DE', '/'], ['FR', '/pricing'], ['SE', '/']
  ];
  var W = 400, BASE = 131, NOTE_AT = 10;

  function drawChart() {
    var line = $('p-line'), area = $('p-area');
    if (!line) return;
    var values = state.real ? state.days : state.hours;
    var span = state.real ? W : (state.hours.length - 1) / 23 * W;
    var c = curve(values, span, BASE, 10);
    var last = c.pts[c.pts.length - 1];
    line.setAttribute('d', c.line);
    area.setAttribute('d', c.line + ' L' + last[0].toFixed(1) + ' ' + BASE + ' L0 ' + BASE + ' Z');
    var note = $('p-note'), dot = $('p-note-dot'), label = $('p-note-label');
    var showNote = !state.real;
    note.style.display = dot.style.display = label.style.display = showNote ? '' : 'none';
    if (showNote) {
      var nx = NOTE_AT / 23 * W;
      note.setAttribute('x1', nx); note.setAttribute('x2', nx);
      dot.setAttribute('cx', nx);
      label.style.left = 'calc(18px + (100% - 36px) * ' + (nx / W).toFixed(4) + ')';
    }
    var now = $('p-now');
    if (!now) {
      now = el('circle', { id: 'p-now', 'class': 'now', r: '3.6' });
      line.parentNode.appendChild(now);
    }
    now.setAttribute('cx', last[0]); now.setAttribute('cy', last[1]);
  }

  function drawPages() {
    var box = $('p-pages');
    if (!box) return;
    box.textContent = '';
    var top = PAGES.length ? PAGES[0][1] : 1;
    PAGES.forEach(function (page) {
      var row = document.createElement('div');
      row.className = 'rowbar';
      row.innerHTML = '<span></span><b></b>';
      row.firstChild.textContent = page[0];
      row.lastChild.textContent = fmt(page[1]);
      row.style.setProperty('--w', Math.max(6, page[1] / top * 100) + '%');
      box.appendChild(row);
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
  function setText(id, text) { var node = $(id); if (node) node.textContent = text; }

  var visitors = 1284, views = 3902, step = 0, demoTimer = null;
  function startDemo() {
    drawChart();
    drawPages();
    for (var a = 4; a >= 0; a--) arrive(ARRIVALS[a], true);
    step = 5;
    if (reduced) return;
    demoTimer = setInterval(function () {
      if (document.hidden) return;
      var entry = ARRIVALS[step % ARRIVALS.length];
      step++;
      arrive(entry);
      views += 1;
      if (step % 3 !== 0) visitors += 1;
      setText('p-views', fmt(views));
      setText('p-visitors', fmt(visitors));
      setText('p-online', String(10 + ((step * 7) % 6)));
      for (var i = 0; i < PAGES.length; i++) if (PAGES[i][0] === entry[1]) PAGES[i][1] += 1;
      drawPages();
      state.hours[state.hours.length - 1] += 1;
      drawChart();
      marks.forEach(function (m) { paintMark(m, 1); });
    }, 2100);
  }

  /* This site's own numbers, from its own public dashboard. */
  function showPulse(pulse) {
    var days = pulse.month.days, hours = pulse.today.hours;
    if (!days.length) return false;
    state.real = true;
    state.days = days.map(function (d) { return d.visitors; });
    state.views = days.map(function (d) { return d.views; });
    state.hours = hours.map(function (h) { return h.views; });
    state.hourNow = Math.max(0, hours.length - 1);
    if (demoTimer) { clearInterval(demoTimer); demoTimer = null; }
    if (panel) {
      panel.classList.add('is-real');
      setText('p-title', 'This site · last 30 days');
      setText('p-visitors', fmt(pulse.month.visitors));
      setText('p-views', fmt(pulse.month.pageviews));
      setText('p-online', fmt(pulse.online));
      setText('p-chart-sub', 'visitors by day, ' + pulse.timezone);
      setText('p-foot', 'Live, from this site’s own public dashboard.');
      setText('p-foot-link', 'Open it →');
      PAGES = pulse.top_pages.map(function (p) { return [p.path, p.views]; });
      drawPages();
      drawChart();
    }
    paintMarks(false);
    paintSeams();
    paintProgress();
    return true;
  }
  function readPulse() {
    var url = panel && panel.getAttribute('data-pulse');
    if (!url || !window.fetch) return;
    /* A local build has no dashboard behind it, and a request that fails is a
       line in the console. The tracker skips localhost for the same reason.
       Add ?live to the address to read the numbers anyway. */
    if (/^(localhost|127\.|\[::1\])/.test(location.hostname) && !/[?&]live\b/.test(location.search)) return;
    fetch(url, { credentials: 'omit' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (pulse) { if (pulse && pulse.month && pulse.today) showPulse(pulse); })
      .catch(function () { /* the invented series stays, and says what it is */ });
  }

  paintMarks(true);
  paintSeams();
  paintProgress();
  if (panel) {
    startDemo();
    readPulse();
    if (!reduced) setInterval(function () { if (!document.hidden) readPulse(); }, 60000);
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
    all('[data-who]').forEach(function (b) { b.setAttribute('aria-pressed', b.getAttribute('data-who') === who ? 'true' : 'false'); });
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
  all('[data-who]').forEach(function (b) {
    b.addEventListener('click', function () { show(b.getAttribute('data-who')); });
  });

  /* ---------------------------------------------------------- tour tabs */
  var tour = $('tour');
  if (tour) {
    tour.addEventListener('click', function (ev) {
      var tab = ev.target.closest('[role="tab"]');
      if (!tab) return;
      var name = tab.getAttribute('data-pane');
      all('[role="tab"]', tour).forEach(function (t) { t.setAttribute('aria-pressed', t === tab ? 'true' : 'false'); });
      all('.tour-pane', tour).forEach(function (p) { p.hidden = p.getAttribute('data-pane') !== name; });
      /* The scene engine sizes a scene when it can see it. */
      window.dispatchEvent(new Event('resize'));
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
