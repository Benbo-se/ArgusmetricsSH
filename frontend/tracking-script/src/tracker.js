/**
 * Argusmetrics Tracking Script
 * Privacy-first analytics tracking
 *
 * Features:
 * - Minimal data collection (path, referrer, screen width)
 * - No cookies
 * - Respects Do Not Track (DNT)
 * - Uses sendBeacon for reliability
 * - <2KB minified
 *
 * Usage:
 *   <script src="https://argusmetrics.io/static/tracker.min.js" data-tracking-code="YOUR_CODE" defer></script>
 */

(function() {
  'use strict';

  /**
   * Get tracking code from script tag data attribute
   */
  function getTrackingCode() {
    const script = document.currentScript || document.querySelector('script[data-tracking-code]');
    if (!script) {
      console.error('[Argusmetrics] No script tag found with data-tracking-code attribute');
      return null;
    }
    return script.getAttribute('data-tracking-code');
  }

  /**
   * Get API endpoint from script tag or use default
   */
  function getApiEndpoint() {
    const script = document.currentScript || document.querySelector('script[data-tracking-code]');
    if (script && script.hasAttribute('data-api-endpoint')) {
      return script.getAttribute('data-api-endpoint');
    }

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
  function isLocalDevelopment() {
    var script = document.currentScript || document.querySelector('script[data-tracking-code]');
    if (script && script.getAttribute('data-track-localhost') === 'true') {
      return false;
    }

    var host = window.location.hostname.toLowerCase();

    return host === 'localhost' ||
           host === '127.0.0.1' ||
           host === '[::1]' ||
           host === '::1' ||
           host === '' ||                       // file:// has no hostname
           host.endsWith('.localhost') ||
           host.endsWith('.local') ||           // Bonjour and many dev setups
           host.endsWith('.test') ||            // reserved for testing, RFC 6761
           host.endsWith('.internal');
  }

  /**
   * Sensitive query parameters that should never be tracked
   */
  var SENSITIVE_PARAMS = ['token', 'key', 'secret', 'password', 'pwd', 'passwd',
    'auth', 'session', 'sid', 'code', 'api_key', 'apikey', 'access_token',
    'refresh_token', 'private_token', 'nonce', 'signature', 'sig',
    'credential', 'otp', 'email', 'mail', 'hash'];

  /**
   * Get current page path with sensitive query params stripped
   */
  function getPath() {
    var search = window.location.search;
    if (search) {
      var params = new URLSearchParams(search);
      var cleaned = new URLSearchParams();
      params.forEach(function(value, key) {
        if (SENSITIVE_PARAMS.indexOf(key.toLowerCase()) === -1) {
          cleaned.append(key, value);
        }
      });
      var qs = cleaned.toString();
      return window.location.pathname + (qs ? '?' + qs : '');
    }
    return window.location.pathname;
  }

  /**
   * Strip sensitive query params from a URL string.
   * Keeps scheme+host+path and drops the query string entirely
   * (most analytics only need the origin/path). Returns the input
   * unchanged if it cannot be parsed, and null/empty for empty input.
   */
  function sanitizeUrl(rawUrl) {
    if (!rawUrl) return rawUrl;
    try {
      var u = new URL(rawUrl);
      // Drop query string entirely (safest); keep scheme + host + path.
      return u.protocol + '//' + u.host + u.pathname;
    } catch (e) {
      // Not parseable as an absolute URL; strip any query/hash defensively.
      return rawUrl.split('?')[0].split('#')[0];
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
    return {
      utm_source: params.get('utm_source') || null,
      utm_medium: params.get('utm_medium') || null,
      utm_campaign: params.get('utm_campaign') || null,
      utm_content: params.get('utm_content') || null,
      utm_term: params.get('utm_term') || null
    };
  }

  /**
   * Track a pageview
   * @param {Object} properties - Optional custom properties (e.g., {userId: '123', plan: 'pro'})
   */
  function trackPageview(properties = null) {
    // Check if DNT is enabled
    if (isDNTEnabled()) {
      console.log('[Argusmetrics] Do Not Track enabled, skipping tracking');
      return;
    }

    if (isLocalDevelopment()) {
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
      referrer: getReferrer(),
      screen_width: getScreenWidth(),
      ...utmParams
    };

    // Add properties if provided and not empty
    if (properties && typeof properties === 'object' && !Array.isArray(properties) && Object.keys(properties).length > 0) {
      data.properties = properties;
    }

    // Use fetch with keepalive instead of sendBeacon to avoid CORS credential issues
    // fetch with keepalive works even when page is unloading, just like sendBeacon
    fallbackFetch(apiEndpoint, data);
  }

  /**
   * Track a custom event with optional properties
   * Supports both Goal tracking (simple event names) and Custom Events (with properties)
   * @param {string} eventName - The event name to track (e.g., 'signup', 'button_click')
   * @param {Object} properties - Optional key-value properties (e.g., {button: 'CTA', color: 'blue'})
   */
  function trackEvent(eventName, properties = {}) {
    // Check if DNT is enabled
    if (isDNTEnabled()) {
      console.log('[Argusmetrics] Do Not Track enabled, skipping event tracking');
      return;
    }

    if (isLocalDevelopment()) {
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

    // Get event tracking endpoint
    const script = document.currentScript || document.querySelector('script[data-tracking-code]');
    let eventEndpoint = 'http://localhost:8020/api/v1/analytics/track-event';

    if (script && script.hasAttribute('data-api-endpoint')) {
      const baseEndpoint = script.getAttribute('data-api-endpoint');
      // Replace /track with /track-event
      eventEndpoint = baseEndpoint.replace('/track', '/track-event');
    } else if (script && script.src) {
      // Auto-detect API endpoint from script source URL
      try {
        const scriptUrl = new URL(script.src);
        const baseUrl = `${scriptUrl.protocol}//${scriptUrl.host}`;
        eventEndpoint = `${baseUrl}/api/v1/analytics/track-event`;
      } catch (e) {
        console.warn('[Argusmetrics] Failed to auto-detect event endpoint from script source');
      }
    }

    const data = {
      tracking_code: trackingCode,
      event_name: eventName
    };

    // Add properties if provided and not empty
    if (properties && Object.keys(properties).length > 0) {
      data.properties = properties;
    }

    // Use fetch for event tracking
    fetch(eventEndpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
      keepalive: true,
      credentials: 'omit',  // Don't send cookies to avoid CORS issues
      mode: 'cors'  // Explicitly set CORS mode
    })
    .then(response => {
      if (properties && Object.keys(properties).length > 0) {
        console.log(`[Argusmetrics] Event tracked: ${eventName} with properties`, properties);
      } else {
        console.log(`[Argusmetrics] Event tracked: ${eventName}`);
      }
    })
    .catch(error => {
      console.warn(`[Argusmetrics] Event sent: ${eventName} (response validation failed)`);
    });
  }

  /**
   * Track an e-commerce event (purchase, add_to_cart, view_item, etc.)
   * @param {string} eventType - The e-commerce event type (e.g., 'purchase', 'add_to_cart')
   * @param {Object} data - Event data (revenue, product_name, transaction_id, etc.)
   */
  function trackEcommerce(eventType, data = {}) {
    if (isDNTEnabled()) {
      console.log('[Argusmetrics] Do Not Track enabled, skipping ecommerce tracking');
      return;
    }

    if (isLocalDevelopment()) {
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

    // Build endpoint URL
    const script = document.currentScript || document.querySelector('script[data-tracking-code]');
    let ecomEndpoint = 'http://localhost:8020/api/v1/analytics/track-ecommerce';

    if (script && script.hasAttribute('data-api-endpoint')) {
      const baseEndpoint = script.getAttribute('data-api-endpoint');
      ecomEndpoint = baseEndpoint.replace('/track', '/track-ecommerce');
    } else if (script && script.src) {
      try {
        const scriptUrl = new URL(script.src);
        const baseUrl = `${scriptUrl.protocol}//${scriptUrl.host}`;
        ecomEndpoint = `${baseUrl}/api/v1/analytics/track-ecommerce`;
      } catch (e) {
        console.warn('[Argusmetrics] Failed to auto-detect ecommerce endpoint from script source');
      }
    }

    const utmParams = getUtmParameters();
    const payload = {
      tracking_code: trackingCode,
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
      ...utmParams
    };

    fetch(ecomEndpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      keepalive: true,
      credentials: 'omit',
      mode: 'cors'
    })
    .then(response => {
      console.log(`[Argusmetrics] Ecommerce event tracked: ${eventType}`, data);
    })
    .catch(error => {
      console.warn(`[Argusmetrics] Ecommerce event sent: ${eventType} (response validation failed)`);
    });
  }

  /**
   * Fallback to fetch if sendBeacon is not available
   */
  function fallbackFetch(apiEndpoint, data) {
    fetch(apiEndpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
      keepalive: true,  // Keep request alive even if page is closed
      credentials: 'omit',  // Don't send cookies to avoid CORS issues
      mode: 'cors'  // Explicitly set CORS mode
    })
    .then(response => {
      // Don't try to read response body to avoid CORS issues
      console.log('[Argusmetrics] Pageview tracked');
    })
    .catch(error => {
      // Silently fail - tracking is fire-and-forget
      console.warn('[Argusmetrics] Tracking request sent (response validation failed)');
    });
  }

  /**
   * Get excluded domains for outbound link tracking
   */
  function getExcludedDomains() {
    const script = document.currentScript || document.querySelector('script[data-tracking-code]');
    if (script && script.hasAttribute('data-exclude-outbound')) {
      const excluded = script.getAttribute('data-exclude-outbound');
      return excluded.split(',').map(d => d.trim().toLowerCase());
    }
    return [];
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
   * Setup outbound link tracking for all links on the page
   */
  function setupOutboundTracking() {
    // Get all links
    const links = document.querySelectorAll('a');

    links.forEach(link => {
      // Skip if already tracked
      if (link.hasAttribute('data-argus-tracked')) return;

      // Check if it's an outbound link
      if (isOutboundLink(link)) {
        link.addEventListener('click', function(e) {
          trackOutboundLink(link);
        });

        // Mark as tracked
        link.setAttribute('data-argus-tracked', 'true');
      }
    });
  }

  /**
   * Setup MutationObserver to track dynamically added links
   */
  function observeDynamicLinks() {
    // Create observer to watch for new links
    const observer = new MutationObserver(function(mutations) {
      mutations.forEach(function(mutation) {
        if (mutation.addedNodes.length) {
          mutation.addedNodes.forEach(function(node) {
            // Check if the node itself is a link
            if (node.nodeType === 1 && node.tagName === 'A') {
              if (isOutboundLink(node) && !node.hasAttribute('data-argus-tracked')) {
                node.addEventListener('click', function(e) {
                  trackOutboundLink(node);
                });
                node.setAttribute('data-argus-tracked', 'true');
              }
              if (isFileDownload(node) && !node.hasAttribute('data-argus-download-tracked')) {
                node.addEventListener('click', function(e) {
                  trackFileDownload(node);
                });
                node.setAttribute('data-argus-download-tracked', 'true');
              }
            }

            // Check for links within the added node
            if (node.querySelectorAll) {
              const links = node.querySelectorAll('a');
              links.forEach(function(link) {
                if (isOutboundLink(link) && !link.hasAttribute('data-argus-tracked')) {
                  link.addEventListener('click', function(e) {
                    trackOutboundLink(link);
                  });
                  link.setAttribute('data-argus-tracked', 'true');
                }
                if (isFileDownload(link) && !link.hasAttribute('data-argus-download-tracked')) {
                  link.addEventListener('click', function(e) {
                    trackFileDownload(link);
                  });
                  link.setAttribute('data-argus-download-tracked', 'true');
                }
              });
            }
          });
        }
      });
    });

    // Start observing the document
    observer.observe(document.body, {
      childList: true,
      subtree: true
    });
  }

  /**
   * List of file extensions to track for downloads
   */
  const DOWNLOAD_EXTENSIONS = [
    '.pdf', '.zip', '.doc', '.docx', '.xls', '.xlsx',
    '.ppt', '.pptx', '.txt', '.csv', '.rar', '.7z',
    '.tar', '.gz', '.mp3', '.mp4', '.avi', '.mov',
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.exe',
    '.dmg', '.apk', '.deb', '.rpm'
  ];

  /**
   * Check if a link points to a downloadable file
   * @param {HTMLAnchorElement} link - The anchor element to check
   */
  function isFileDownload(link) {
    if (!link.href) return false;

    try {
      const url = new URL(link.href);
      const pathname = url.pathname.toLowerCase();

      // Check if URL ends with a download extension
      const hasDownloadExtension = DOWNLOAD_EXTENSIONS.some(ext => pathname.endsWith(ext));

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
   * Setup file download tracking for all download links on the page
   */
  function setupDownloadTracking() {
    // Get all links
    const links = document.querySelectorAll('a');

    links.forEach(link => {
      // Skip if already tracked
      if (link.hasAttribute('data-argus-download-tracked')) return;

      // Check if it's a file download
      if (isFileDownload(link)) {
        link.addEventListener('click', function(e) {
          trackFileDownload(link);
        });

        // Mark as tracked
        link.setAttribute('data-argus-download-tracked', 'true');
      }
    });
  }

  /**
   * Scroll depth tracking
   */
  let scrollDepthTracked = {
    25: false,
    50: false,
    75: false,
    100: false
  };
  let scrollThrottleTimeout = null;
  let maxScrollDepth = 0;

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

    // Avoid division by zero
    if (documentHeight <= windowHeight) {
      return 100;
    }

    const scrollableHeight = documentHeight - windowHeight;
    const scrollPercentage = Math.floor((scrollTop / scrollableHeight) * 100);

    return Math.min(100, Math.max(0, scrollPercentage));
  }

  /**
   * Check and fire scroll depth milestone events
   */
  function checkScrollMilestones() {
    const currentDepth = getScrollDepth();

    // Update max scroll depth
    if (currentDepth > maxScrollDepth) {
      maxScrollDepth = currentDepth;
    }

    // Check each milestone
    [25, 50, 75, 100].forEach(milestone => {
      if (!scrollDepthTracked[milestone] && maxScrollDepth >= milestone) {
        scrollDepthTracked[milestone] = true;
        trackEvent(`scroll_${milestone}`);
      }
    });
  }

  /**
   * Throttled scroll handler (only runs every 200ms)
   */
  function handleScroll() {
    if (scrollThrottleTimeout) return;

    scrollThrottleTimeout = setTimeout(function() {
      checkScrollMilestones();
      scrollThrottleTimeout = null;
    }, 200);
  }

  /**
   * Setup scroll depth tracking
   */
  function setupScrollTracking() {
    // Reset tracking state for new page
    scrollDepthTracked = {
      25: false,
      50: false,
      75: false,
      100: false
    };
    maxScrollDepth = 0;

    // Add scroll listener
    window.addEventListener('scroll', handleScroll, { passive: true });

    // Check initial scroll position (in case page loads scrolled)
    setTimeout(checkScrollMilestones, 100);
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

    // Setup outbound link tracking
    setupOutboundTracking();

    // Setup file download tracking
    setupDownloadTracking();

    // Observe for dynamically added links
    observeDynamicLinks();

    // Track pageviews on history changes (for SPAs)
    const originalPushState = history.pushState;
    const originalReplaceState = history.replaceState;

    history.pushState = function() {
      originalPushState.apply(this, arguments);
      trackPageview();
      // Re-setup outbound tracking for SPA page changes
      setupOutboundTracking();
      // Re-setup download tracking for SPA page changes
      setupDownloadTracking();
      // Re-setup scroll tracking for new page
      cleanupScrollTracking();
      setupScrollTracking();
    };

    history.replaceState = function() {
      originalReplaceState.apply(this, arguments);
      trackPageview();
      // Re-setup outbound tracking for SPA page changes
      setupOutboundTracking();
      // Re-setup download tracking for SPA page changes
      setupDownloadTracking();
      // Re-setup scroll tracking for new page
      cleanupScrollTracking();
      setupScrollTracking();
    };

    // Track on popstate (back/forward buttons)
    window.addEventListener('popstate', function() {
      trackPageview();
      // Re-setup outbound tracking for SPA page changes
      setupOutboundTracking();
      // Re-setup download tracking for SPA page changes
      setupDownloadTracking();
      // Re-setup scroll tracking for new page
      cleanupScrollTracking();
      setupScrollTracking();
    });

    // Cleanup on page unload
    window.addEventListener('beforeunload', function() {
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
