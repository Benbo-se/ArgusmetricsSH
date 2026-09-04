# Argusmetrics - WordPress Plugin

Privacy-first, GDPR-compliant analytics for WordPress. Sends pageviews to an
Argusmetrics instance that you run: there is no hosted service, so the plugin
tracks nothing until you tell it where your instance is.

![WordPress Plugin Version](https://img.shields.io/badge/version-1.1.0-blue)
![WordPress Compatibility](https://img.shields.io/badge/wordpress-5.0%2B-green)
![License](https://img.shields.io/badge/license-GPLv2-orange)

## Features

- ✅ **Privacy-First** - No cookies, no fingerprinting, no personal data collection
- ✅ **GDPR Compliant** - Built with European privacy laws in mind
- ✅ **Lightweight** - The tracking script is 2.5KB gzipped
- ✅ **Real-Time Analytics** - See visitor activity as it happens
- ✅ **No Cookie Banner Needed** - Since we don't use cookies
- ✅ **One-Click Setup** - Install, enter tracking code, done!

### Tracking Features

- Pageview tracking
- Real-time visitor monitoring
- Geographic data (country-level)
- Device detection (desktop/mobile/tablet)
- Browser statistics
- Referrer tracking
- UTM campaign tracking
- Outbound link tracking
- File download tracking
- Custom event tracking
- **NEW:** Scroll depth tracking (25/50/75/100%)
- **NEW:** Screen size tracking

## Installation

### From WordPress Admin

1. Download the latest release ZIP file
2. Go to **Plugins → Add New → Upload Plugin**
3. Choose the ZIP file and click **Install Now**
4. Click **Activate Plugin**
5. Go to **Settings → Argusmetrics**
6. Enter the tracking code and the address of your own Argusmetrics instance
7. Save settings

### Manual Installation

1. Upload the `argus-metrics` folder to `/wp-content/plugins/`
2. Activate the plugin through the **Plugins** menu in WordPress
3. Go to **Settings → Argusmetrics**
4. Enter your tracking code
5. Save settings

## Getting Your Tracking Code

1. Run an Argusmetrics instance of your own (https://github.com/Benbo-se/ArgusmetricsSH)
2. Add your website
3. Copy the 8-character tracking code
4. Paste it in **Settings → Argusmetrics** in WordPress

## Configuration

### Settings

- **Tracking Code** (Required) - Your 8-character code from Argusmetrics
- **API Endpoint** (Optional) - Custom endpoint for self-hosted instances
- **Exclude Outbound Domains** (Optional) - Domains to exclude from outbound link tracking
- **Exclude Administrators** (Recommended) - Don't track logged-in administrators

### Advanced Usage

#### Custom Event Tracking

Track custom events using JavaScript:

```javascript
// Simple event
window.argus.trackEvent('button_click');

// Event with properties
window.argus.trackEvent('signup', {
  plan: 'pro',
  source: 'landing_page'
});
```

#### Manual Pageview Tracking

For SPAs or when you need manual control:

```javascript
window.argus.track();
```

## Plugin Structure

```
argus-metrics/
├── argus-metrics.php       # Main plugin file
├── uninstall.php           # Cleanup on uninstall
├── readme.txt              # WordPress.org readme
├── README.md               # This file
├── LICENSE                 # GPL v2 license
├── includes/
│   └── admin-settings.php  # Admin settings page template
└── assets/
    └── css/
        └── admin.css       # Admin styles
```

## Privacy & GDPR Compliance

Argusmetrics is designed with privacy as the top priority:

- No cookies or localStorage
- No browser fingerprinting
- No personal data collection
- No cross-site tracking
- IP addresses truncated (/24 IPv4, /48 IPv6) and hashed with a daily-rotating salt
- Visitor hashes are domain-scoped and expire every 24 hours
- GDPR/CNIL compliant by design
- No cookie consent banner needed

## Requirements

- **WordPress:** 5.0 or higher
- **PHP:** 7.4 or higher
- **An Argusmetrics instance you run.** There is no hosted service; see https://github.com/Benbo-se/ArgusmetricsSH

## Compatibility

- ✅ Works with all WordPress themes
- ✅ Compatible with page builders (Elementor, Divi, Beaver Builder, etc.)
- ✅ Works with caching plugins (WP Rocket, W3 Total Cache, etc.)
- ✅ Multisite compatible

## Support

- **Documentation:** https://github.com/Benbo-se/ArgusmetricsSH
- **Issues:** https://github.com/Benbo-se/ArgusmetricsSH/issues

## Frequently Asked Questions

### Do I need a cookie consent banner?

No! Since Argusmetrics doesn't use cookies or collect personal data, you don't need cookie consent banners in most cases. Always consult with a legal professional for your specific situation.

### Will this slow down my website?

No! The tracking script is extremely lightweight (&lt;5KB) and loads asynchronously.

### Can I track multiple websites?

Yes! Each website gets its own tracking code in your Argusmetrics account.

### How is this different from Google Analytics?

Argusmetrics is:
- More privacy-friendly (no cookies, no personal data)
- Simpler to use
- Much faster (5KB vs 45KB+ script)
- GDPR compliant by design
- Doesn't require cookie consent

## Changelog

### 1.1.0 - 2026-02-22

- Updated all URLs from argusmetrics.se to argusmetrics.io (both since retired; the plugin now points at whatever instance you run)
- Fixed API endpoint to include /track suffix (required by tracking script)
- Updated manual installation snippet with data-api-endpoint attribute
- Updated privacy descriptions to reflect daily-salt hash approach (no fingerprinting)

### 1.0.0 - 2025-10-31

**Initial Release**

- Privacy-first analytics tracking
- GDPR compliant
- Lightweight script (&lt;5KB)
- Real-time analytics
- Outbound link tracking
- File download tracking
- Custom event tracking
- Scroll depth tracking
- Screen size tracking
- UTM campaign tracking
- Admin exclusion option
- Outbound domain exclusion

## License

This plugin is licensed under the GPL v2 or later.

```
Copyright (C) 2025 Argusmetrics

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.
```

## Credits

Part of Argusmetrics, self-hosted privacy-first analytics: https://github.com/Benbo-se/ArgusmetricsSH
