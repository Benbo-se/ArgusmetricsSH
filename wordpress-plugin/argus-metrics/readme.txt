=== Argusmetrics - Privacy-First Analytics ===
Contributors: argusmetrics
Tags: analytics, statistics, privacy, gdpr, tracking
Requires at least: 5.0
Tested up to: 6.7
Requires PHP: 7.4
Stable tag: 1.1.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

Privacy-first, GDPR-compliant analytics for WordPress. Simple, lightweight, and cookie-free.

== Description ==

Argusmetrics is a privacy-first analytics platform that provides powerful insights without compromising your visitors' privacy. No cookies, no personal data collection, and fully GDPR compliant.

### Why Argusmetrics?

* **Privacy-First:** No cookies, no fingerprinting, no personal data collection
* **GDPR Compliant:** Built with European privacy laws in mind
* **Lightweight:** Tracking script is less than 5KB (compared to 45KB+ for Google Analytics)
* **Fast:** Minimal impact on your site's performance
* **Accurate:** Advanced bot filtering for reliable data
* **Real-Time:** See visitor activity as it happens
* **No Cookie Banner Needed:** Since we don't use cookies, you don't need annoying cookie consent banners

### Features

* **Pageview Tracking** - Track all page visits automatically
* **Real-Time Analytics** - See current visitors on your site
* **Geographic Data** - Know where your visitors are from (country-level only)
* **Device Detection** - Desktop, mobile, tablet breakdown
* **Browser Statistics** - See which browsers your visitors use
* **Referrer Tracking** - Know where your traffic comes from
* **UTM Campaign Tracking** - Track marketing campaigns with UTM parameters
* **Outbound Link Tracking** - See which external links visitors click
* **File Download Tracking** - Track PDF, ZIP, and other file downloads
* **Custom Event Tracking** - Track any custom events you define
* **Scroll Depth Tracking** - See how far visitors scroll on your pages
* **Screen Size Tracking** - Understand your visitors' screen resolutions
* **Goal Tracking** - Define and track conversion goals
* **Email Reports** - Get automated analytics reports via email

### Simple Setup

1. Install and activate the plugin
2. Run an Argusmetrics instance of your own: https://github.com/Benbo-se/ArgusmetricsSH
3. Get your tracking code from your dashboard
4. Enter it in Settings → Argusmetrics
5. Save and start tracking!

No complex configuration needed. Analytics tracking begins immediately.

### Privacy Features

* **No cookies** - We don't use cookies or localStorage
* **No fingerprinting** - We don't use browser fingerprinting techniques
* **No cross-site tracking** - We only track visits to your site
* **Privacy-safe hashing** - IP addresses are truncated and hashed with a daily-rotating salt, domain-scoped, expiring every 24 hours
* **No personal data** - We don't collect emails, names, or other personal info
* **GDPR/CNIL compliant** - Fully compliant with European privacy laws
* **Data ownership** - Your data is your data, not ours

### Perfect For

* Privacy-conscious website owners
* European businesses needing GDPR compliance
* Publishers wanting lightweight analytics
* Anyone tired of Google Analytics complexity
* Sites that want to avoid cookie consent banners

== Installation ==

### Automatic Installation

1. Log in to your WordPress admin panel
2. Navigate to Plugins → Add New
3. Search for "Argusmetrics"
4. Click "Install Now" and then "Activate"
5. Go to Settings → Argusmetrics
6. Enter your tracking code and your instance URL
7. Save settings

### Manual Installation

1. Download the plugin ZIP file
2. Log in to your WordPress admin panel
3. Navigate to Plugins → Add New → Upload Plugin
4. Choose the ZIP file and click "Install Now"
5. Activate the plugin
6. Go to Settings → Argusmetrics
7. Enter your tracking code and your instance URL
8. Save settings

### Getting Your Tracking Code

1. Run an Argusmetrics instance of your own: https://github.com/Benbo-se/ArgusmetricsSH
2. Add your website
3. Copy the 8-character tracking code
4. Paste it in Settings → Argusmetrics in WordPress

== Frequently Asked Questions ==

= Do I need a cookie consent banner with Argusmetrics? =

No! Since Argusmetrics doesn't use cookies or collect personal data, you don't need cookie consent banners in most cases. However, always consult with a legal professional for your specific situation.

= Is Argusmetrics GDPR compliant? =

Yes! Argusmetrics is built with GDPR compliance as a core principle. We don't collect personal data, don't use cookies, and anonymize all visitor information.

= How does Argusmetrics compare to Google Analytics? =

Argusmetrics is much simpler, more privacy-friendly, and faster. The tracking script is under 5KB (vs 45KB+ for GA), loads faster, and doesn't require cookie consent. However, if you need advanced features like remarketing or detailed user flows, Google Analytics might be better suited.

= Will this slow down my website? =

No! The Argusmetrics tracking script is extremely lightweight (&lt;5KB) and loads asynchronously, so it has minimal impact on your page load times.

= Can I track multiple websites? =

Yes! You can add multiple websites to your Argusmetrics account. Each website gets its own tracking code.

= Does Argusmetrics work with caching plugins? =

Yes! Argusmetrics is fully compatible with caching plugins like WP Rocket, W3 Total Cache, and WP Super Cache.

= Can I exclude my own visits? =

Yes! The plugin has an option to exclude logged-in administrators from tracking. Enable this in Settings → Argusmetrics.

= Is there a free plan? =

Argusmetrics is self-hosted and open source (AGPL-3.0). There is nothing to pay and no hosted plan: you run it yourself. See https://github.com/Benbo-se/ArgusmetricsSH

= How do I view my analytics? =

Log in to the dashboard on your own Argusmetrics instance.

= Can I track custom events? =

Yes! Argusmetrics supports custom event tracking. Use the JavaScript API to track any custom events:

`window.argus.trackEvent('button_click', { button: 'signup', color: 'blue' });`

= Does it work with page builders? =

Yes! Argusmetrics works with all page builders including Elementor, Divi, Beaver Builder, and others.

= Can I export my data? =

Yes! You can export your analytics data in CSV or JSON format from your Argusmetrics dashboard.

== Screenshots ==

1. Clean and simple settings page
2. Argusmetrics dashboard showing real-time analytics
3. Geographic data and top pages view
4. Custom event tracking and goals

== Changelog ==

= 1.1.0 - 2026-02-22 =
* Updated all URLs from argusmetrics.se to argusmetrics.io
* Fixed API endpoint to include /track suffix (required by tracking script)
* Updated manual installation snippet with data-api-endpoint attribute
* Updated privacy descriptions to reflect daily-salt hash approach

= 1.0.0 - 2025-10-31 =
* Initial release
* Privacy-first analytics tracking
* GDPR compliant
* Lightweight script (&lt;5KB)
* Real-time analytics
* Outbound link tracking
* File download tracking
* Custom event tracking
* Scroll depth tracking
* Screen size tracking
* UTM campaign tracking
* Exclude administrators option
* Exclude outbound domains option

== Upgrade Notice ==

= 1.1.0 =
Critical update: fixes domain references and API endpoint. All users should upgrade.

= 1.0.0 =
Initial release of Argusmetrics WordPress plugin.

== Privacy Policy ==

Argusmetrics is designed with privacy as the top priority. The plugin:

* Does not use cookies or localStorage
* Does not use browser fingerprinting
* Does not collect personal data
* IP addresses are truncated and hashed with daily-rotating salts
* Visitor hashes are domain-scoped and expire every 24 hours
* Does not track visitors across sites
* Complies with GDPR, CNIL, and other European privacy laws

For more information, read our [Privacy Policy](https://github.com/Benbo-se/ArgusmetricsSH/privacy).

== Support ==

Need help? Visit our [documentation](https://github.com/Benbo-se/ArgusmetricsSH/docs) or [contact support](https://github.com/Benbo-se/ArgusmetricsSH/support).
