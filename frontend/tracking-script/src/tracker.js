/**
 * Argusmetrics Tracking Script
 * Privacy-first analytics tracking
 *
 * Features:
 * - Minimal data collection (path, referrer, screen width, language, hostname)
 * - No cookies
 * - Respects Do Not Track (DNT)
 * - fetch with keepalive, so reports survive the page being left
 * - Tokens in a path are masked, and paths can be left out entirely
 * - About 7.4 KB minified, 3.1 KB gzipped
 *
 * Usage:
 *   <script src="https://argusmetrics.io/static/tracker.min.js" data-tracking-code="YOUR_CODE" defer></script>
 */

(function() {
  'use strict';

  /**
   * Start once per page, however many times the script is run (#279).
   *
   * A second copy used to start a second tracker: its own pageview, and its
   * own wrappers around history.pushState, so every later page change was
   * counted once per copy. A single-page app that put the tag back in on each
   * navigation gained a copy per page, and a visit to 7 pages was recorded as
   * 46 pageviews. A tag manager firing twice, or the snippet pasted in two
   * places, did the same on a smaller scale.
   *
   * The first copy keeps running and already follows the page changes, so the
   * extra one has nothing to add and stops here, silently: the build removes
   * every console call, so that the script never writes in a visitor's console.
   *
   * The name has no leading underscore on purpose. The build shortens
   * properties that start with one, and a flag that is renamed between two
   * builds does not stop an old cached copy and a new one from both starting.
   */
  if (window.argusTrackerLoaded) {
    return;
  }
  window.argusTrackerLoaded = true;

  /**
   * Settings, from the script tag's data attributes or from window.argusConfig.
   *
   * The tag is the normal way. window.argusConfig is for Google Tag Manager:
   * its sandbox loads this script with injectScript, which cannot put
   * attributes on the tag, so the GTM template passes the same settings as an
   * object (#109). Before this the template wrote argusConfig and nothing read
   * it, so a GTM install started without a tracking code and sent nothing.
   *
   * The tag is the one carrying data-tracking-code, not simply
   * document.currentScript: argus.trackEvent called synchronously from some
   * other script made currentScript that other script, and the code was lost.
   */
  var CONFIG_KEYS = {
    'data-tracking-code': 'trackingCode',
    'data-api-endpoint': 'apiEndpoint',
    'data-exclude-outbound': 'excludeOutbound',
    'data-exclude-paths': 'excludePaths',
    'data-mask-path-tokens': 'maskPathTokens',
    'data-track-localhost': 'trackLocalhost'
  };

  function settingsTag() {
    var current = document.currentScript;
    if (current && current.hasAttribute && current.hasAttribute('data-tracking-code')) return current;
    return document.querySelector('script[data-tracking-code]');
  }

  function setting(attr) {
    var tag = settingsTag();
    if (tag && tag.hasAttribute(attr)) return tag.getAttribute(attr);
    var config = window.argusConfig;
    var value = config && typeof config === 'object' ? config[CONFIG_KEYS[attr]] : undefined;
    return value === undefined || value === null || value === '' ? null : String(value);
  }

  /** This script's own element, for working out where it was loaded from. */
  function ownScript() {
    return settingsTag() || document.querySelector('script[src*="/static/tracker.min.js"]');
  }

  /**
   * Get tracking code
   */
  function getTrackingCode() {
    var code = setting('data-tracking-code');
    if (!code) {
      console.error('[Argusmetrics] No tracking code: set data-tracking-code on the script tag');
    }
    return code;
  }

  /**
   * The pageview endpoint: configured, or worked out from where this script
   * was loaded, which is the instance.
   */
  function getApiEndpoint() {
    var configured = setting('data-api-endpoint');
    if (configured) {
      return configured;
    }

    const script = ownScript();
    // Auto-detect API endpoint from script source URL
    if (script && script.src) {
      try {
        const scriptUrl = new URL(script.src);
        const baseUrl = `${scriptUrl.protocol}//${scriptUrl.host}`;
        return `${baseUrl}/api/v1/analytics/track`;
      } catch (e) {
        console.warn('[Argusmetrics] Failed to auto-detect API endpoint from script source');
      }
    }

    // Fallback to localhost for development
    return 'http://localhost:8020/api/v1/analytics/track';
  }

  /**
   * Check if Do Not Track is enabled
   */
  function isDNTEnabled() {
    return navigator.doNotTrack === '1' || 
           navigator.doNotTrack === 'yes' ||
           navigator.msDoNotTrack === '1' ||
           window.doNotTrack === '1';
  }

  /**
   * Whether this browser is a crawler or under automation.
   *
   * Crawlers that run JavaScript run this script too. Meta's
   * meta-externalagent alone sent about 175,000 pageviews to one instance in
   * nine days in late September 2026. The server refused every one by its
   * user agent, but each was still a request, and the refusal rested on the
   * word "crawler" happening to be in Meta's URL.
   *
   * navigator.webdriver is the standard flag a browser sets when it is being
   * driven by automation (Selenium, Puppeteer, Playwright, headless Chrome).
   * A scraper can hide it, so this is a first filter rather than proof, but a
   * person never has it set.
   */
  var BOT_UA = /bot|crawl|spider|slurp|externalagent|headless|lighthouse|preview|scrap|fetcher/i;

  function isAutomated() {
    try {
      if (navigator.webdriver === true) return true;
    } catch (e) {
      // Reading it cannot fail in a real browser; never let it stop a pageview.
    }
    return BOT_UA.test(navigator.userAgent || '');
  }

  /**
   * Whether this page is running on a developer's own machine.
   *
   * Local development used to be counted as real traffic, and it showed up
   * as referrals: `http://localhost:8202/` sitting in Top Referrers next to
   * Bing. On a site with thirteen pageviews, four of them the developer's,
   * a third of the statistics was noise. It hurts the newest sites hardest,
   * which are exactly the ones where every visit moves the percentages.
   *
   * Deliberately checked in the browser rather than on the server: the server
   * only sees the referrer, and a visit to a local page with no referrer at
   * all would still be counted.
   *
   * Set `data-track-localhost="true"` on the script tag to override, which is
   * what you want while testing the tracker itself.
   */
  var LOCAL_HOST = /^(localhost|127\.0\.0\.1|\[::1\]|::1|)$|\.(localhost|local|test|internal)$/i;

  function isLocalDevelopment() {
    if (setting('data-track-localhost') === 'true') {
      return false;
    }

    // localhost, the loopback addresses, no hostname at all (file://), and
    // the endings used for development: .localhost, .local (Bonjour), .test
    // (reserved for testing, RFC 6761) and .internal.
    return LOCAL_HOST.test(window.location.hostname);
  }

  /**
   * Sensitive query parameters that should never be tracked
   */
  var SENSITIVE_PARAM = /^(token|key|secret|password|pwd|passwd|auth|session|sid|code|api_?key|(access|refresh|private)_token|nonce|signature|sig|credential|otp|e?mail|hash)$/i;

  /**
   * Whether nothing at all may be sent: the visitor asked not to be tracked,
   * the page is on a developer's machine, or the browser is a crawler.
   */
  function isRefused() {
    return isDNTEnabled() || isLocalDevelopment() || isAutomated();
  }

  /**
   * Pages the site has asked to be left out, with data-exclude-paths (#280).
   *
   *     data-exclude-paths="/admin, /aktivera/*"
   *
   * A pattern without a star is that page and everything under it: /admin is
   * /admin and /admin/users, not /administrator. A star stands for anything,
   * slashes included. A trailing slash makes no difference on either side.
   *
   * Nothing is sent from a matching page: no pageview, no event, no scroll
   * depth. Before this the only way to keep staff's own clicks in an admin
   * area out of the statistics was to not load the script there, which a
   * single-page app cannot do once it has loaded.
   */
  function isExcludedPath() {
    var raw = setting('data-exclude-paths');
    if (!raw) return false;

    var path = window.location.pathname.replace(/\/+$/, '') || '/';
    return raw.split(',').some(function(pattern) {
      pattern = pattern.trim();
      if (!pattern) return false;
      if (pattern.charAt(0) !== '/' && pattern.charAt(0) !== '*') pattern = '/' + pattern;
      pattern = pattern.replace(/\/+$/, '') || '/';

      if (pattern.indexOf('*') === -1) {
        return path === pattern || path.indexOf(pattern + '/') === 0;
      }
      var source = pattern.split('*').map(function(piece) {
        return piece.replace(/[.+?^${}()|[\]\\]/g, '\\$&');
      }).join('.*');
      return new RegExp('^' + source + '$').test(path);
    });
  }

  /**
   * Whether one piece of a path looks like a secret rather than a name.
   *
   * Many applications put a one-time token in the path: /reset-password/<token>,
   * /invite/<token>, /aktivera/<token>. The query string was cleaned of such
   * things and the path was sent as it stood, so the token was stored as a
   * page name (#280). This is the protection for a site that has configured
   * nothing; data-exclude-paths is the deliberate one.
   *
   * A name is made of words, so its letters and digits come in runs. A random
   * string changes between them all the time. Three shapes are caught:
   *
   * - a UUID;
   * - a stretch of 16 or more letters and digits that goes between letters
   *   and digits at least four times (hex digests, password-reset tokens);
   * - 20 or more characters of the URL-safe base64 alphabet where at least
   *   every other character is of another kind than the one before it
   *   (lower case, upper case, digit), which is what token_urlsafe, nanoid
   *   and a JWT part look like.
   *
   * "iphone-15-pro-max-256gb", "World_War_2_Eastern_Front_1941" and
   * "blackfridaysale2024" are none of these. A 19-digit numeric id is not
   * either: it has no letters to change to.
   */
  var UUID = /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;

  /** How many characters are of another kind than the one before. */
  function kindChanges(text, caseMatters) {
    var changes = 0;
    var previous = -1;
    for (var i = 0; i < text.length; i++) {
      var code = text.charCodeAt(i);
      var kind = code < 58 ? 0 : (code < 91 && caseMatters ? 1 : 2);
      if (i && kind !== previous) changes++;
      previous = kind;
    }
    return changes;
  }

  function looksLikeToken(segment) {
    if (UUID.test(segment)) return true;

    var runs = segment.split(/[^A-Za-z0-9]+/);
    for (var i = 0; i < runs.length; i++) {
      if (runs[i].length >= 16 && kindChanges(runs[i], false) >= 4) return true;
    }

    if (/^[\w-]{20,}$/.test(segment)) {
      var bare = segment.replace(/[_-]/g, '');
      return kindChanges(bare, true) * 2 >= bare.length - 1;
    }
    return false;
  }

  /**
   * A path with anything that looks like a token replaced by ":token".
   * data-mask-path-tokens="false" turns it off, for a site whose real page
   * names happen to look like that.
   */
  function maskPath(pathname) {
    if (!pathname || setting('data-mask-path-tokens') === 'false') return pathname;
    return pathname.split('/').map(function(segment) {
      return looksLikeToken(segment) ? ':token' : segment;
    }).join('/');
  }

  /**
   * Get current page path with sensitive query params stripped and tokens in
   * the path itself masked
   */
  function getPath() {
    var pathname = maskPath(window.location.pathname);
    var search = window.location.search;
    if (search) {
      var params = new URLSearchParams(search);
      var cleaned = new URLSearchParams();
      params.forEach(function(value, key) {
        if (!SENSITIVE_PARAM.test(key)) {
          cleaned.append(key, value);
        }
      });
      var qs = cleaned.toString();
      return pathname + (qs ? '?' + qs : '');
    }
    return pathname;
  }

  /**
   * Strip sensitive query params from a URL string.
   * Keeps scheme+host+path and drops the query string entirely
   * (most analytics only need the origin/path), and masks tokens in the
   * path the same way as for the page's own address. Returns the input
   * unchanged if it cannot be parsed, and null/empty for empty input.
   */
  function sanitizeUrl(rawUrl) {
    if (!rawUrl) return rawUrl;
    try {
      var u = new URL(rawUrl);
      // Drop query string entirely (safest); keep scheme + host + path.
      return u.protocol + '//' + u.host + maskPath(u.pathname);
    } catch (e) {
      // Not parseable as an absolute URL; strip any query/hash defensively.
      return maskPath(rawUrl.split('?')[0].split('#')[0]);
    }
  }

  /**
   * Get referrer (where visitor came from), sanitized of sensitive query params
   */
  function getReferrer() {
    return sanitizeUrl(document.referrer) || null;
  }

  /**
   * Get screen width for device type detection
   */
  function getScreenWidth() {
    return window.screen.width || null;
  }

  /**
   * Extract UTM parameters from URL
   */
  function getUtmParameters() {
    const params = new URLSearchParams(window.location.search);
    const utm = {};
    ['source', 'medium', 'campaign', 'content', 'term'].forEach(function(name) {
      utm['utm_' + name] = params.get('utm_' + name) || null;
    });
    return utm;
  }

  let pageviewsSent = 0;
  let lastTrackedPath = null;

  /**
   * Track a pageview
   * @param {Object} properties - Optional custom properties (e.g., {userId: '123', plan: 'pro'})
   */
  function trackPageview(properties = null) {
    if (isRefused()) {
      return;
    }

    // An excluded page is still a page the visitor went to. Remembering it
    // means coming back from it to the page before is counted as a new view,
    // as coming back from any other page is.
    if (isExcludedPath()) {
      lastTrackedPath = getPath();
      return;
    }

    const trackingCode = getTrackingCode();
    if (!trackingCode) {
      return;
    }

    const apiEndpoint = getApiEndpoint();

    const utmParams = getUtmParameters();
    const data = {
      tracking_code: trackingCode,
      path: getPath(),
      // document.referrer is the page the visit came from and does not change
      // in a single-page app, so only the first pageview carries it. Sent on
      // every page it counted one referral per page read (#177).
      referrer: pageviewsSent === 0 ? getReferrer() : null,
      screen_width: getScreenWidth(),
      // The first preferred language only, never navigator.languages: the
      // whole list is a fingerprint. The server cuts it to language and
      // region. The hostname tells subdomains apart (#204).
      language: navigator.language || null,
      hostname: window.location.hostname || null,
      ...utmParams
    };

    // Add properties if provided and not empty
    if (properties && typeof properties === 'object' && !Array.isArray(properties) && Object.keys(properties).length > 0) {
      data.properties = properties;
    }

    pageviewsSent++;
    lastTrackedPath = data.path;

    send(apiEndpoint, data);
  }

  /**
   * Track a custom event with optional properties
   * Supports both Goal tracking (simple event names) and Custom Events (with properties)
   * @param {string} eventName - The event name to track (e.g., 'signup', 'button_click')
   * @param {Object} properties - Optional key-value properties (e.g., {button: 'CTA', color: 'blue'})
   */
  function trackEvent(eventName, properties = {}) {
    if (isRefused() || isExcludedPath()) {
      return;
    }

    const trackingCode = getTrackingCode();
    if (!trackingCode) {
      console.error('[Argusmetrics] Cannot track event: no tracking code found');
      return;
    }

    // Validate eventName
    if (!eventName || typeof eventName !== 'string') {
      console.error('[Argusmetrics] Event name is required and must be a string');
      return;
    }

    // Validate properties (must be object if provided, not array)
    if (properties !== null && properties !== undefined) {
      if (typeof properties !== 'object' || Array.isArray(properties)) {
        console.error('[Argusmetrics] Properties must be an object (not an array)');
        return;
      }
    }

    // The same instance as pageviews, so derived from the same place.
    const eventEndpoint = getApiEndpoint().replace(/\/track$/, '/track-event');

    const data = {
      tracking_code: trackingCode,
      event_name: eventName
    };

    // Add properties if provided and not empty
    if (properties && Object.keys(properties).length > 0) {
      data.properties = properties;
    }

    send(eventEndpoint, data);
  }

  /**
   * Track an e-commerce event (purchase, add_to_cart, view_item, etc.)
   * @param {string} eventType - The e-commerce event type (e.g., 'purchase', 'add_to_cart')
   * @param {Object} data - Event data (revenue, product_name, transaction_id, etc.)
   */
  function trackEcommerce(eventType, data = {}) {
    if (isRefused() || isExcludedPath()) {
      return;
    }

    const trackingCode = getTrackingCode();
    if (!trackingCode) {
      console.error('[Argusmetrics] Cannot track ecommerce event: no tracking code found');
      return;
    }

    if (!eventType || typeof eventType !== 'string') {
      console.error('[Argusmetrics] Event type is required and must be a string');
      return;
    }

    const ecomEndpoint = getApiEndpoint().replace(/\/track$/, '/track-ecommerce');

    const utmParams = getUtmParameters();
    const payload = {
      tracking_code: trackingCode,
      event_type: eventType,
      event_name: data.event_name || eventType,
      currency: data.currency || 'USD',
      quantity: data.quantity || 1,
      ...utmParams
    };
    ['transaction_id', 'revenue', 'tax', 'shipping', 'product_id', 'product_name',
     'product_category', 'product_brand', 'product_variant', 'price', 'properties'].forEach(function(field) {
      payload[field] = data[field] || null;
    });

    send(ecomEndpoint, payload);
  }

  /**
   * The one place a report leaves from.
   *
   * fetch with keepalive, so it survives the page being left, and without
   * credentials: sendBeacon with a JSON body always sends them, which the
   * server's wildcard origin refuses (#166). Fire and forget: a report that
   * never arrives is a missing value, not something to show a visitor.
   */
  function send(endpoint, data) {
    try {
      fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
        keepalive: true,
        credentials: 'omit',
        mode: 'cors'
      }).catch(function() {});
    } catch (e) {
      // Nothing to do, and nobody to tell.
    }
  }

  /**
   * Get excluded domains for outbound link tracking
   */
  function getExcludedDomains() {
    const excluded = setting('data-exclude-outbound');
    return excluded ? excluded.split(',').map(d => d.trim().toLowerCase()).filter(Boolean) : [];
  }

  /**
   * Check if a link is an outbound link
   * @param {HTMLAnchorElement} link - The anchor element to check
   */
  function isOutboundLink(link) {
    if (!link.href) return false;

    try {
      const linkUrl = new URL(link.href);
      const currentHostname = window.location.hostname.toLowerCase();
      const linkHostname = linkUrl.hostname.toLowerCase();

      // Check if it's an external link
      const isExternal = linkHostname !== currentHostname;

      // Check if it has target="_blank"
      const hasTargetBlank = link.target === '_blank';

      // Check if it's http or https
      const isHttpProtocol = linkUrl.protocol === 'http:' || linkUrl.protocol === 'https:';

      // Check if domain is excluded
      const excludedDomains = getExcludedDomains();
      const isExcluded = excludedDomains.some(domain => linkHostname === domain || linkHostname.endsWith('.' + domain));

      return isHttpProtocol && (isExternal || hasTargetBlank) && !isExcluded;
    } catch (e) {
      return false;
    }
  }

  /**
   * Get link text (truncated to 100 chars)
   * @param {HTMLAnchorElement} link - The anchor element
   */
  function getLinkText(link) {
    let text = link.textContent.trim();
    if (!text) {
      // Try to get alt text from images
      const img = link.querySelector('img');
      if (img && img.alt) {
        text = img.alt;
      }
    }
    if (!text) {
      text = sanitizeUrl(link.href);
    }
    // Truncate to 100 chars
    return text.length > 100 ? text.substring(0, 97) + '...' : text;
  }

  /**
   * Track an outbound link click
   * @param {HTMLAnchorElement} link - The clicked link
   */
  function trackOutboundLink(link) {
    const destinationUrl = sanitizeUrl(link.href);
    const linkText = getLinkText(link);
    const fromPage = getPath();

    // Use a stable, low-cardinality event name; sanitized URL goes in properties only.
    const properties = {
      url: destinationUrl,
      text: linkText,
      from_page: fromPage
    };

    // Track using custom event with properties
    trackEvent('Outbound Link', properties);
  }

  /**
   * List of file extensions to track for downloads
   */
  const DOWNLOAD_EXTENSION = /\.(pdf|zip|docx?|xlsx?|pptx?|txt|csv|rar|7z|tar|gz|mp[34]|avi|mov|png|jpe?g|gif|svg|exe|dmg|apk|deb|rpm)$/i;

  /**
   * Check if a link points to a downloadable file
   * @param {HTMLAnchorElement} link - The anchor element to check
   */
  function isFileDownload(link) {
    if (!link.href) return false;

    try {
      const url = new URL(link.href);
      // Check if URL ends with a download extension
      const hasDownloadExtension = DOWNLOAD_EXTENSION.test(url.pathname);

      // Check if link has download attribute
      const hasDownloadAttribute = link.hasAttribute('download');

      return hasDownloadExtension || hasDownloadAttribute;
    } catch (e) {
      return false;
    }
  }

  /**
   * Extract filename from URL or link
   * @param {HTMLAnchorElement} link - The link element
   */
  function getFilename(link) {
    // First check if download attribute specifies a filename
    const downloadAttr = link.getAttribute('download');
    if (downloadAttr && downloadAttr !== 'true' && downloadAttr !== '') {
      return downloadAttr;
    }

    // Extract from URL
    try {
      const url = new URL(link.href);
      const pathname = url.pathname;
      const parts = pathname.split('/');
      const filename = parts[parts.length - 1];

      // Decode URL encoding
      return decodeURIComponent(filename);
    } catch (e) {
      return sanitizeUrl(link.href);
    }
  }

  /**
   * Extract file extension from filename
   * @param {string} filename - The filename
   */
  function getFileExtension(filename) {
    const match = filename.match(/\.([^.]+)$/);
    return match ? match[1].toLowerCase() : 'unknown';
  }

  /**
   * Track a file download
   * @param {HTMLAnchorElement} link - The clicked download link
   */
  function trackFileDownload(link) {
    const downloadUrl = sanitizeUrl(link.href);
    const filename = getFilename(link);
    const fileExtension = getFileExtension(filename);
    const fromPage = getPath();

    const properties = {
      filename: filename,
      file_type: fileExtension,
      url: downloadUrl,
      from_page: fromPage
    };

    // Track using custom event with properties
    trackEvent('file_download', properties);
  }

  /**
   * One listener for every link on the page, now and later.
   *
   * There used to be a listener on each link, put there by a pass over the
   * page at start, another after every single-page navigation, and a
   * MutationObserver for links added in between. A click is looked at when it
   * happens instead, which needs none of that and cannot miss a link.
   *
   * In the capture phase, so a site's own handler that stops the event from
   * bubbling does not hide the click.
   */
  function onLinkClick(event) {
    var link = event.target && event.target.closest ? event.target.closest('a') : null;
    if (!link) return;
    if (isOutboundLink(link)) trackOutboundLink(link);
    if (isFileDownload(link)) trackFileDownload(link);
  }

  /**
   * Scroll depth tracking
   */
  let scrollThrottleTimeout = null;
  let maxScrollDepth = 0;

  /**
   * The page the current depth belongs to, kept from when measuring started.
   *
   * The report goes out when the page is left, and in a single-page app the
   * URL has already changed by then: the history wrappers call pushState
   * first, and popstate fires after the back button has changed it. Reading
   * the URL at that moment sent "75% of /old" as "75% of /new", a page not yet
   * read (#107). Moving the report before pushState would not fix popstate.
   */
  let scrollPath = null;

  /** Whether that page is one the site excluded, decided at the same moment
   *  and for the same reason: the URL has changed by the time it is needed. */
  let scrollExcluded = false;

  /**
   * Calculate the current scroll depth percentage
   */
  function getScrollDepth() {
    const windowHeight = window.innerHeight;
    const documentHeight = Math.max(
      document.body.scrollHeight,
      document.body.offsetHeight,
      document.documentElement.clientHeight,
      document.documentElement.scrollHeight,
      document.documentElement.offsetHeight
    );
    const scrollTop = window.pageYOffset || document.documentElement.scrollTop;

    // A page that fits in the window was never scrolled, so there is no
    // depth to report. This used to return 100, which meant every short page
    // claimed the visitor read all the way down, and it dragged the average
    // upward for every site that has any. null is a missing value, which the
    // column and the dashboard already handle: they show a dash.
    if (documentHeight <= windowHeight) {
      return null;
    }

    const scrollableHeight = documentHeight - windowHeight;
    const scrollPercentage = Math.floor((scrollTop / scrollableHeight) * 100);

    return Math.min(100, Math.max(0, scrollPercentage));
  }

  /**
   * Remember how far down the visitor has been.
   *
   * Nothing is sent here. This used to fire an event at each of 25, 50, 75
   * and 100 per cent, which cost four requests and four events against the
   * monthly limit for one pageview, and on a page shorter than the window all
   * four fired at once because the depth was reported as 100 immediately.
   *
   * The maximum is reported once when the visitor leaves, which is both
   * cheaper and truer: it describes the whole visit rather than its first
   * second.
   */
  function recordScrollDepth() {
    const currentDepth = getScrollDepth();
    if (currentDepth === null) return;

    if (currentDepth > maxScrollDepth) {
      maxScrollDepth = currentDepth;
    }
  }

  /**
   * Send the deepest point reached, once, as the visitor leaves.
   *
   * Guarded so the same depth is not sent twice: pagehide and
   * visibilitychange both fire in some navigations, and a browser that
   * discards the page after visibilitychange never reaches pagehide, so both
   * are needed.
   */
  let reportedScrollDepth = 0;

  function reportScrollDepth() {
    // Only when the depth has grown since the last report. A visitor who
    // switches tab at 20 per cent and then reads to the end reports again,
    // and the server keeps the larger value (#167).
    if (maxScrollDepth <= reportedScrollDepth) return;

    reportedScrollDepth = maxScrollDepth;
    sendScrollDepth(maxScrollDepth);
  }

  /**
   * Completes the pageview that was already recorded, rather than adding an
   * event of its own.
   *
   * It goes to its own endpoint for two reasons. It fills the scroll_depth
   * column the dashboard reads, which a custom event does not, and it is not
   * counted against the monthly limit: the visit was counted when the page
   * loaded, and a visitor who reads to the bottom should not cost more than
   * one who leaves at once.
   *
   * fetch with keepalive, because this fires as the page is going away and a
   * normal fetch is cancelled with it. Not sendBeacon: with a JSON body it
   * needs a CORS preflight and always sends credentials, which the server's
   * wildcard origin refuses, and it still returns true. On any site on
   * another origin than the instance the report was dropped silently (#166).
   * The pageview uses the same call for the same reason.
   */
  function sendScrollDepth(depth) {
    // The same two refusals as a pageview. Without them a visitor with Do
    // Not Track on, or a developer on localhost, sent no pageview but still
    // sent the path and depth the moment the page was hidden (#106).
    if (isRefused() || scrollExcluded) return;

    var trackingCode = getTrackingCode();
    if (!trackingCode) return;

    var endpoint = getApiEndpoint().replace(/\/track$/, '/track-scroll');
    send(endpoint, {
      tracking_code: trackingCode,
      path: scrollPath || getPath(),
      depth: depth
    });
  }

  /**
   * Throttled scroll handler (only runs every 200ms)
   */
  function handleScroll() {
    if (scrollThrottleTimeout) return;

    scrollThrottleTimeout = setTimeout(function() {
      recordScrollDepth();
      scrollThrottleTimeout = null;
    }, 200);
  }

  /**
   * Setup scroll depth tracking
   */
  function setupScrollTracking() {
    // Reset for the new page. Single-page apps reuse the same document, so
    // without this the second page would inherit the first one's depth.
    maxScrollDepth = 0;
    scrollPath = getPath();
    scrollExcluded = isExcludedPath();
    reportedScrollDepth = 0;

    // Add scroll listener
    window.addEventListener('scroll', handleScroll, { passive: true });

    // Take one reading shortly after setup, for a page that is already
    // scrolled when it loads: an anchor link, a restored position on back
    // navigation. The listener only fires on movement, so without this a
    // visitor who lands halfway down and reads without scrolling reports
    // nothing at all.
    //
    // This called checkScrollMilestones until now, which is the name
    // recordScrollDepth had when it still fired an event at 25, 50, 75 and
    // 100 per cent. The rename missed this one caller, and JavaScript only
    // resolves a free variable when it is reached, so nothing complained
    // until the timer fired in a visitor's browser: a ReferenceError on every
    // page load of every site running the tracker.
    setTimeout(recordScrollDepth, 100);
  }

  /**
   * Cleanup scroll tracking listeners
   */
  function cleanupScrollTracking() {
    window.removeEventListener('scroll', handleScroll);
    if (scrollThrottleTimeout) {
      clearTimeout(scrollThrottleTimeout);
      scrollThrottleTimeout = null;
    }
  }

  /**
   * Track pageview on load
   */
  function init() {
    // Track initial pageview
    trackPageview();

    // Setup scroll depth tracking
    setupScrollTracking();

    // Outbound links and downloads
    document.addEventListener('click', onLinkClick, true);

    // Track pageviews on history changes (for SPAs)
    const originalPushState = history.pushState;
    const originalReplaceState = history.replaceState;

    // One place for what a single-page navigation does. Nothing happens if
    // the path is the same: routers call replaceState to save a scroll
    // position or tidy the URL, and that is not a new page (#177).
    function onNavigate() {
      if (getPath() === lastTrackedPath) return;

      trackPageview();
      // Re-setup scroll tracking for new page
      reportScrollDepth();
      cleanupScrollTracking();
      setupScrollTracking();
    }

    history.pushState = function() {
      originalPushState.apply(this, arguments);
      onNavigate();
    };

    history.replaceState = function() {
      originalReplaceState.apply(this, arguments);
      onNavigate();
    };

    // Track on popstate (back/forward buttons)
    window.addEventListener('popstate', onNavigate);

    // Report on the way out. visibilitychange covers the case a browser
    // discards the page without ever firing pagehide, which is most mobile
    // navigations, and beforeunload is unreliable on mobile entirely.
    document.addEventListener('visibilitychange', function() {
      if (document.visibilityState === 'hidden') {
        reportScrollDepth();
      }
    });
    window.addEventListener('pagehide', reportScrollDepth);

    window.addEventListener('beforeunload', function() {
      reportScrollDepth();
      cleanupScrollTracking();
    });
  }

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Export for manual tracking if needed
  window.argus = {
    track: trackPageview,
    trackEvent: trackEvent,
    trackEcommerce: trackEcommerce
  };

})();
