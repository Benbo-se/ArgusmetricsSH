# Argusmetrics Tracking Script

Privacy-first JavaScript tracking script for Argusmetrics analytics platform.

## Features

- **Privacy-First**: No cookies, no localStorage, no PII stored
- **Ultra-Lightweight**: 2.9KB minified (1.4KB gzipped) - 78% smaller than original!
- **Reliable**: Uses `fetch` with `keepalive` for tracking (works even when page closes)
- **Respects DNT**: Automatically respects Do Not Track browser setting
- **SPA Support**: Automatically tracks route changes in Single Page Applications
- **Outbound Link Tracking**: Automatically tracks external link clicks
- **Custom Events**: Track goals and custom events with properties
- **UTM Tracking**: Automatic UTM parameter extraction
- **Easy Integration**: One line of code

## Installation

### Basic Usage

Add this script tag to your website's `<head>` or before `</body>`:

```html
<script
  src="https://argusmetrics.io/static/tracker.prod.min.js"
  data-tracking-code="YOUR_TRACKING_CODE"
  defer
></script>
```

Replace `YOUR_TRACKING_CODE` with your unique tracking code from the Argusmetrics dashboard.

### Development/Self-Hosted

If you're running Argusmetrics on your own server or in development:

```html
<script
  src="https://your-analytics-domain.com/tracker.prod.min.js"
  data-tracking-code="YOUR_TRACKING_CODE"
  data-api-endpoint="https://your-analytics-domain.com/api/v1/analytics/track"
  defer
></script>
```

### Local Development

For testing locally:

```html
<script
  src="http://localhost:8020/static/tracker.prod.min.js"
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
    src="https://argusmetrics.io/static/tracker.min.js"
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
  script.src = 'https://argusmetrics.io/static/tracker.min.js';
  script.setAttribute('data-tracking-code', 'a1b2c3d4');
  script.defer = true;
  document.head.appendChild(script);
}, []);
```

### Vue App

```vue
<!-- In your index.html or main component -->
<script
  src="https://argusmetrics.io/static/tracker.min.js"
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

- Documentation: https://argusmetrics.io/docs
- Issues: https://github.com/Benbo-se/argusmetrics.io/issues
- Email: support@argusmetrics.io

## License

MIT License - See LICENSE file for details
