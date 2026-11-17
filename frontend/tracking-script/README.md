# Argusmetrics Tracking Script

Privacy-first JavaScript tracking script for Argusmetrics analytics platform.

## Features

- **Privacy-First**: No cookies, no localStorage, no PII stored
- **Small**: 9.5KB minified, 3.4KB gzipped
- **Starts once**: a second copy of the script on the same page does nothing
- **Keeps secrets out of paths**: token-like path segments are sent as `:token`, and `data-exclude-paths` leaves pages out entirely
- **Reliable**: Uses `fetch` with `keepalive` for tracking (works even when page closes)
- **Respects DNT**: Automatically respects Do Not Track browser setting
- **SPA Support**: Automatically tracks route changes in Single Page Applications
- **Outbound Link Tracking**: Automatically tracks external link clicks
- **Custom Events**: Track goals and custom events with properties
- **UTM Tracking**: Automatic UTM parameter extraction
- **Easy Integration**: One line of code

## Installation

### Basic Usage

Point the script at your own instance. There is no hosted service, so the
domain below is always yours:

```html
<script
  src="https://analytics.your-domain.com/static/tracker.min.js"
  data-tracking-code="YOUR_TRACKING_CODE"
  defer
></script>
```

`YOUR_TRACKING_CODE` comes from the dashboard after you add a website. The
script posts back to the domain it was loaded from, so `data-api-endpoint` is
only needed when the two differ:

### A separate API endpoint

```html
<script
  src="https://your-analytics-domain.com/tracker.min.js"
  data-tracking-code="YOUR_TRACKING_CODE"
  data-api-endpoint="https://your-analytics-domain.com/api/v1/analytics/track"
  defer
></script>
```

### Local Development

For testing locally:

```html
<script
  src="http://localhost:8020/static/tracker.min.js"
  data-tracking-code="YOUR_TRACKING_CODE"
  data-api-endpoint="http://localhost:8020/api/v1/analytics/track"
  defer
></script>
```

## What Data is Collected?

The tracking script collects minimal data:

1. **Page Path**: The URL path being viewed (e.g., `/blog/post-1`)
2. **Referrer**: Where the visitor came from (e.g., `https://google.com`)
3. **Screen Width**: Used to determine device type (desktop/mobile/tablet)
4. **Language**: `navigator.language`, the first preferred language only. The
   server keeps language and region (`sv-SE`); `navigator.languages` is never read
5. **Hostname**: `location.hostname`, so subdomains can be told apart

### What is NOT collected:

- No cookies
- No IP addresses (hashed on server for unique visitor counting)
- No user identifiers
- No personal information
- No cross-site tracking

## Configuration Options

### Tracking Code (Required)

```html
data-tracking-code="a1b2c3d4"
```

Your unique 8-character tracking code from Argusmetrics dashboard.

### Custom API Endpoint (Optional)

```html
data-api-endpoint="https://analytics.example.com/api/v1/analytics/track"
```

Override the default API endpoint. Useful for self-hosted installations.

### Excluding Pages (Optional)

```html
<script
  src="https://analytics.your-domain.com/static/tracker.min.js"
  data-tracking-code="abc123"
  data-exclude-paths="/admin, /aktivera/*"
  defer
></script>
```

Nothing is sent from a matching page: no pageview, no event, no scroll depth.
A pattern without a star is that page and everything under it (`/admin` covers
`/admin/users`, not `/administrator`). A star stands for anything, slashes
included. This also works in a single-page app, where the script is already
loaded when the visitor reaches the page.

### Tokens in the Path

A path segment that looks like a secret (a UUID, a long hex or base64 string,
as in `/reset-password/<token>`) is sent as `:token`, both in the page's own
path and in the referrer. It is a guess made from the shape of the text, so it
is a safety net and not a guarantee: a short token can slip through. For pages
you know carry a token, use `data-exclude-paths`.

If your real page names look like that and you want them as they are, turn it
off with `data-mask-path-tokens="false"`.

### Loaded More Than Once

The script starts once per page. A second copy (a tag manager firing twice, a
router that renders the tag again on each navigation) does nothing.

## Advanced Usage

### Manual Tracking

You can manually trigger pageview tracking:

```javascript
// Track a pageview manually
window.argus.track();

// Track a custom event (goal)
window.argus.trackEvent('signup');

// Track a custom event with properties
window.argus.trackEvent('button_click', {
  button: 'cta',
  location: 'header',
  color: 'blue'
});

// Track ecommerce events
window.argus.trackEcommerce('purchase', {
  transaction_id: 'order-123',
  revenue: 99.99,
  currency: 'USD',
  product_name: 'Pro Plan',
  product_id: 'plan_pro',
});

// Track other ecommerce events: view_item, add_to_cart, begin_checkout, refund
window.argus.trackEcommerce('add_to_cart', {
  product_name: 'Starter Plan',
  product_id: 'plan_starter',
  quantity: 1,
  price: 29.99,
});
```

### Single Page Applications (SPAs)

The tracker automatically detects route changes in SPAs by monitoring:
- `history.pushState()`
- `history.replaceState()`
- `popstate` events (back/forward buttons)

No additional configuration needed for React, Vue, Angular, etc.

## Do Not Track (DNT)

The tracking script automatically respects the Do Not Track browser setting. If a user has DNT enabled, no tracking requests will be sent.

## Browser Support

- All modern browsers (Chrome, Firefox, Safari, Edge)
- IE11+ (with `fetch` polyfill if needed)
- Mobile browsers (iOS Safari, Android Chrome)

## Size

- **Original Source**: 13.2 KB
- **Optimized Source**: 5.7 KB (56% reduction)
- **Minified (Optimized)**: 2.9 KB (78% reduction)
- **Minified + Gzipped**: 1.4 KB (89% reduction)

**Comparison with competitors:**
- Plausible Analytics: ~1 KB
- Fathom Analytics: 1.5 KB
- **Argusmetrics: 2.9 KB (1.4 KB gzipped)** - Competitive while maintaining full features!

## Privacy & GDPR

Argusmetrics is designed to be GDPR/CNIL-compliant:
- No personal data stored
- No cookies or localStorage used
- No browser fingerprinting
- IP addresses are truncated (/24 IPv4, /48 IPv6) and hashed with a daily-rotating salt
- Visitor hashes are domain-scoped and expire every 24 hours
- Respects Do Not Track
- No data sold to third parties
- Privacy-first analytics focused on aggregate data only

## Troubleshooting

### Tracking not working?

1. **Check browser console**: Open DevTools and look for `[Argusmetrics]` messages
2. **Verify tracking code**: Make sure your tracking code is correct
3. **Check DNT**: Ensure Do Not Track is disabled in browser settings
4. **Check CORS**: If self-hosting, ensure CORS is configured for your domain
5. **Check ad blockers**: Some ad blockers may block analytics scripts

### How to verify tracking works?

1. Open your website in a browser
2. Open DevTools Console (F12)
3. In production, tracking is silent (no console messages for performance)
4. Check your Argusmetrics dashboard for the pageview
5. For testing, use `test.html` included in this repo which shows console output

## Examples

### Basic HTML Site

```html
<!DOCTYPE html>
<html>
<head>
  <title>My Website</title>
  <script 
    src="https://analytics.your-domain.com/static/tracker.min.js"
    data-tracking-code="a1b2c3d4"
    defer
  ></script>
</head>
<body>
  <h1>Hello World</h1>
</body>
</html>
```

### React App

```jsx
// In your index.html or App.js
useEffect(() => {
  const script = document.createElement('script');
  script.src = 'https://analytics.your-domain.com/static/tracker.min.js';
  script.setAttribute('data-tracking-code', 'a1b2c3d4');
  script.defer = true;
  document.head.appendChild(script);
}, []);
```

### Vue App

```vue
<!-- In your index.html or main component -->
<script
  src="https://analytics.your-domain.com/static/tracker.min.js"
  data-tracking-code="a1b2c3d4"
  defer
></script>
```

## Development

### Build from Source

```bash
# Install dependencies
npm install

# Build optimized production version
npm run build:script

# Build both versions (original + optimized)
npm run build

# Check file sizes
npm run size
```

### Testing Locally

1. Start Argusmetrics backend:
   ```bash
   cd backend
   docker-compose up
   ```

2. Open the included test file:
   ```bash
   # Open test.html in your browser
   open test.html  # macOS
   xdg-open test.html  # Linux
   ```

3. The test page includes comprehensive tests for:
   - Automatic pageview tracking
   - Manual pageview tracking
   - Custom event tracking (goals)
   - Custom events with properties
   - Outbound link tracking
   - UTM parameter tracking
   - SPA navigation
   - Dynamic link tracking

### Build Configuration

The build uses Terser with aggressive optimization settings:
- Multiple compression passes
- Console statement removal
- Unsafe optimizations enabled
- Top-level variable mangling
- See `terser.config.json` for details

## Support

- Documentation: https://github.com/Benbo-se/ArgusmetricsSH
- Issues: https://github.com/Benbo-se/ArgusmetricsSH/issues

## License

MIT License - See LICENSE file for details
