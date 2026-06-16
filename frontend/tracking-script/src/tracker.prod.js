/**
 * Argusmetrics - Privacy-first analytics
 * Minified for production (<5KB target)
 */
(function() {
  'use strict';

  // Get script element once
  const getScript = () => document.currentScript || document.querySelector('script[data-tracking-code]');

  // Get tracking code
  const getCode = () => {
    const s = getScript();
    return s ? s.getAttribute('data-tracking-code') : null;
  };

  // Get API endpoint
  const getEndpoint = (path = '/track') => {
    const s = getScript();
    if (s?.hasAttribute('data-api-endpoint')) {
      return s.getAttribute('data-api-endpoint').replace('/track', path);
    }
    if (s?.src) {
      try {
        const u = new URL(s.src);
        return `${u.protocol}//${u.host}/api/v1/analytics${path}`;
      } catch {}
    }
    return `http://localhost:8020/api/v1/analytics${path}`;
  };

  // Check DNT
  const isDNT = () =>
    navigator.doNotTrack === '1' ||
    navigator.doNotTrack === 'yes' ||
    navigator.msDoNotTrack === '1' ||
    window.doNotTrack === '1';

  // Get path with sensitive query params stripped
  const getPath = () => {
    if (!location.search) return location.pathname;
    const p = new URLSearchParams(location.search);
    'token key secret password pwd passwd auth session sid code api_key apikey access_token refresh_token private_token nonce signature sig credential otp email mail hash'.split(' ').forEach(k => p.delete(k));
    const q = p.toString();
    return location.pathname + (q ? '?' + q : '');
  };

  // Strip sensitive query params from a URL (keep scheme+host+path, drop query)
  const sanitizeUrl = (raw) => {
    if (!raw) return raw;
    try {
      const u = new URL(raw);
      return u.protocol + '//' + u.host + u.pathname;
    } catch {
      return raw.split('?')[0].split('#')[0];
    }
  };

  // Get sanitized referrer
  const getReferrer = () => sanitizeUrl(document.referrer) || null;

  // Get UTM params
  const getUTM = () => {
    const p = new URLSearchParams(location.search);
    return {
      utm_source: p.get('utm_source'),
      utm_medium: p.get('utm_medium'),
      utm_campaign: p.get('utm_campaign'),
      utm_content: p.get('utm_content'),
      utm_term: p.get('utm_term')
    };
  };

  // Send tracking request
  const send = (endpoint, data) => {
    fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
      keepalive: true,
      credentials: 'omit',
      mode: 'cors'
    }).catch(() => {});
  };

  // Track pageview
  const trackPage = () => {
    if (isDNT()) return;
    const code = getCode();
    if (!code) return;

    send(getEndpoint(), {
      tracking_code: code,
      path: getPath(),
      referrer: getReferrer(),
      screen_width: screen.width || null,
      screen_height: screen.height || null,
      ...getUTM()
    });
  };

  // Track custom event
  const trackEvt = (name, props = {}) => {
    if (isDNT() || !name || typeof name !== 'string') return;
    const code = getCode();
    if (!code) return;

    const data = { tracking_code: code, event_name: name };
    if (props && typeof props === 'object' && !Array.isArray(props) && Object.keys(props).length > 0) {
      data.properties = props;
    }

    send(getEndpoint('/track-event'), data);
  };

  // Track ecommerce event
  const trackEcom = (eventType, data = {}) => {
    if (isDNT()) return;
    const code = getCode();
    if (!code) return;

    send(getEndpoint('/track-ecommerce'), {
      tracking_code: code,
      event_type: eventType,
      event_name: data.event_name || eventType,
      transaction_id: data.transaction_id || null,
      revenue: data.revenue || null,
      currency: data.currency || 'USD',
      tax: data.tax || null,
      shipping: data.shipping || null,
      product_id: data.product_id || null,
      product_name: data.product_name || null,
      product_category: data.product_category || null,
      product_brand: data.product_brand || null,
      product_variant: data.product_variant || null,
      quantity: data.quantity || 1,
      price: data.price || null,
      properties: data.properties || null,
      ...getUTM()
    });
  };

  // Get excluded domains
  const getExcluded = () => {
    const s = getScript();
    if (s?.hasAttribute('data-exclude-outbound')) {
      return s.getAttribute('data-exclude-outbound').split(',').map(d => d.trim().toLowerCase());
    }
    return [];
  };

  // Check if outbound link
  const isOutbound = (link) => {
    if (!link.href) return false;
    try {
      const u = new URL(link.href);
      const host = location.hostname.toLowerCase();
      const linkHost = u.hostname.toLowerCase();
      const isExt = linkHost !== host;
      const isBlank = link.target === '_blank';
      const isHttp = u.protocol === 'http:' || u.protocol === 'https:';
      const excluded = getExcluded();
      const isExc = excluded.some(d => linkHost === d || linkHost.endsWith('.' + d));
      return isHttp && (isExt || isBlank) && !isExc;
    } catch {
      return false;
    }
  };

  // Get link text
  const getLinkText = (link) => {
    let text = link.textContent.trim();
    if (!text) {
      const img = link.querySelector('img');
      if (img?.alt) text = img.alt;
    }
    if (!text) text = sanitizeUrl(link.href);
    return text.length > 100 ? text.substring(0, 97) + '...' : text;
  };

  // Track outbound link
  const trackOut = (link) => {
    trackEvt('Outbound Link', {
      url: sanitizeUrl(link.href),
      text: getLinkText(link),
      from_page: getPath()
    });
  };

  // Setup outbound tracking
  const setupOut = () => {
    document.querySelectorAll('a').forEach(link => {
      if (!link.hasAttribute('data-argus-tracked') && isOutbound(link)) {
        link.addEventListener('click', () => trackOut(link));
        link.setAttribute('data-argus-tracked', 'true');
      }
    });
  };

  // Track single link (for mutation observer)
  const trackLink = (link) => {
    if (isOutbound(link) && !link.hasAttribute('data-argus-tracked')) {
      link.addEventListener('click', () => trackOut(link));
      link.setAttribute('data-argus-tracked', 'true');
    }
  };

  // Observe dynamic links
  const observeLinks = () => {
    new MutationObserver(mutations => {
      mutations.forEach(m => {
        m.addedNodes.forEach(node => {
          if (node.nodeType === 1) {
            if (node.tagName === 'A') trackLink(node);
            if (node.querySelectorAll) {
              node.querySelectorAll('a').forEach(trackLink);
            }
          }
        });
      });
    }).observe(document.body, { childList: true, subtree: true });
  };

  // Track scroll depth
  const trackScroll = () => {
    let maxDepth = 0;
    let sent = { 25: false, 50: false, 75: false, 100: false };

    const check = () => {
      const h = document.documentElement.scrollHeight - window.innerHeight;
      if (h <= 0) return;

      const depth = Math.min(100, Math.round((window.scrollY / h) * 100));
      maxDepth = Math.max(maxDepth, depth);

      // Send events at milestones
      if (depth >= 25 && !sent[25]) {
        sent[25] = true;
        trackEvt('Scroll Depth', { depth: 25, path: getPath() });
      }
      if (depth >= 50 && !sent[50]) {
        sent[50] = true;
        trackEvt('Scroll Depth', { depth: 50, path: getPath() });
      }
      if (depth >= 75 && !sent[75]) {
        sent[75] = true;
        trackEvt('Scroll Depth', { depth: 75, path: getPath() });
      }
      if (depth >= 100 && !sent[100]) {
        sent[100] = true;
        trackEvt('Scroll Depth', { depth: 100, path: getPath() });
      }
    };

    // Throttle: only run check() at most once per 200ms (matches dev tracker)
    let throttle = null;
    addEventListener('scroll', () => {
      if (throttle) return;
      throttle = setTimeout(() => { check(); throttle = null; }, 200);
    }, { passive: true });
  };

  // Initialize
  const init = () => {
    trackPage();
    setupOut();
    observeLinks();
    trackScroll();

    // Track SPA navigation
    const origPush = history.pushState;
    const origReplace = history.replaceState;

    history.pushState = function() {
      origPush.apply(this, arguments);
      trackPage();
      setupOut();
    };

    history.replaceState = function() {
      origReplace.apply(this, arguments);
      trackPage();
      setupOut();
    };

    addEventListener('popstate', () => {
      trackPage();
      setupOut();
    });
  };

  // Start when ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Public API
  window.argus = {
    track: trackPage,
    trackEvent: trackEvt,
    trackEcommerce: trackEcom
  };
})();
