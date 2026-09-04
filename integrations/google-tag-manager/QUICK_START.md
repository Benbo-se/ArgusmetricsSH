# Argusmetrics GTM - Quick Start Guide

Get Argusmetrics running on your website in 5 minutes using Google Tag Manager.

## Prerequisites

- ✅ Google Tag Manager container installed on your website
- ✅ Argusmetrics account ([sign up here](https://github.com/Benbo-se/ArgusmetricsSH))
- ✅ Your 8-character tracking code

## 5-Minute Setup

### Step 1: Create Custom HTML Tag (2 minutes)

1. Open Google Tag Manager
2. Click **Tags** → **New**
3. Click **Tag Configuration**
4. Select **Custom HTML**
5. Copy and paste this code:

```html
<script defer
  data-tracking-code="YOUR_CODE"
  data-api-endpoint="https://analytics.your-domain.com/api/v1/analytics/track"
  src="https://analytics.your-domain.com/static/tracker.min.js">
</script>
```

6. Replace `YOUR_CODE` with your actual tracking code
7. Click **Triggering**
8. Select **All Pages**
9. Save as "Argusmetrics - Analytics"

### Step 2: Test (2 minutes)

1. Click **Preview** in GTM
2. Visit your website
3. Check that "Argusmetrics - Analytics" appears in "Tags Fired"
4. Visit your [Argus dashboard](https://github.com/Benbo-se/ArgusmetricsSH/dashboard) and verify pageviews appear

### Step 3: Publish (1 minute)

1. Click **Submit** in GTM
2. Add description: "Added Argusmetrics analytics"
3. Click **Publish**

**Done!** Your website is now tracked.

---

## Verify It's Working

### Method 1: Real-Time Dashboard

1. Go to your instance dashboard
2. Check "Current Visitors" count
3. Visit your website in another tab
4. Count should increase

### Method 2: Browser Console

1. Open your website
2. Press F12 to open Developer Tools
3. Go to **Console** tab
4. Type: `window.argus`
5. Should see object with `track` and `trackEvent` functions

### Method 3: Network Tab

1. Open Developer Tools
2. Go to **Network** tab
3. Reload your page
4. Filter by "track"
5. Should see a request to `your-domain.com/api/v1/analytics/track`

---

## Common Configurations

### Exclude Specific Domains from Outbound Tracking

```html
<script defer
  data-tracking-code="YOUR_CODE"
  data-api-endpoint="https://analytics.your-domain.com/api/v1/analytics/track"
  data-exclude-outbound="paypal.com, stripe.com, example.com"
  src="https://analytics.your-domain.com/static/tracker.min.js">
</script>
```

### Self-Hosted Instance

```html
<script defer
  data-tracking-code="YOUR_CODE"
  data-api-endpoint="https://your-domain.com/api/v1/analytics"
  src="https://your-domain.com/static/tracker.min.js">
</script>
```

---

## Track Custom Events

Add event tracking anywhere in your website code or via GTM tags:

### Button Click Example

**HTML:**
```html
<button onclick="trackSignup()">Sign Up</button>
```

**JavaScript:**
```javascript
function trackSignup() {
  if (window.argus) {
    window.argus.trackEvent('signup_click', {
      button_location: 'hero',
      button_text: 'Sign Up'
    });
  }
}
```

### Form Submission Example

**GTM Tag (Custom HTML):**

```html
<script>
  document.querySelector('#contact-form').addEventListener('submit', function() {
    if (window.argus) {
      window.argus.trackEvent('form_submit', {
        form_name: 'contact',
        form_location: 'footer'
      });
    }
  });
</script>
```

**Trigger:** DOM Ready

---

## Troubleshooting

### Not Seeing Pageviews?

**Check:**
1. ✅ Tracking code is correct (exactly 8 characters)
2. ✅ GTM tag fires (use Preview mode)
3. ✅ No JavaScript errors in console
4. ✅ Website is verified in Argus dashboard

**Quick Test:**
```javascript
// Run in browser console
window.argus.track();
```

### Tag Not Firing?

1. Check trigger is set to "All Pages"
2. Verify GTM container is installed correctly
3. Check for JavaScript errors
4. Try "Initialization - All Pages" trigger instead

### Script Blocked?

Some ad blockers might block tracking scripts:
1. Test with ad blocker disabled
2. Argus respects Do Not Track (DNT) headers
3. Check browser console for blocked requests

---

## Next Steps

### 1. Set Up Goals

Track important events as goals:
- Newsletter signups
- Purchase completions
- Form submissions
- Button clicks

[Learn about goals →](https://github.com/Benbo-se/ArgusmetricsSH/goals)

### 2. Enable Email Reports

Get weekly analytics reports via email:
1. Go to website settings in Argus dashboard
2. Enable email reports
3. Choose frequency (daily/weekly/monthly)

### 3. Add Team Members

Share access with your team:
1. Go to website settings
2. Click "Team Members"
3. Invite by email
4. Set permission level

### 4. Explore Custom Events

Track user behavior with custom events:
- Video plays
- Scroll depth
- File downloads
- Outbound clicks
- And more...

[Custom events guide →](https://github.com/Benbo-se/ArgusmetricsSH/custom-events)

---

## Support

**Need help?**

- 📚 [Full Documentation](https://github.com/Benbo-se/ArgusmetricsSH)
- 💬 [Support Chat](https://github.com/Benbo-se/ArgusmetricsSH/support)
- Issues: https://github.com/Benbo-se/ArgusmetricsSH/issues
- 🐛 [Report Issues](https://github.com/argusmetrics/argus-metrics/issues)

---

## Tips for Best Results

### ✅ Do:
- Use meaningful event names
- Add context with properties
- Test in Preview mode before publishing
- Document your GTM changes
- Keep tracking code secure

### ❌ Don't:
- Track personally identifiable information (PII)
- Create too many custom events (be selective)
- Forget to test after making changes
- Publish without preview testing
- Share tracking codes publicly

---

## Example GTM Setups

### E-commerce Site

**Tags:**
1. Base tracking (All Pages)
2. Product view (Product Pages)
3. Add to cart (Click trigger)
4. Checkout (Form submit)
5. Purchase complete (Thank you page)

### Blog/Content Site

**Tags:**
1. Base tracking (All Pages)
2. Newsletter signup (Form submit)
3. Article read (Scroll depth 75%)
4. Social shares (Click trigger)
5. Comment submit (Form submit)

### SaaS Product

**Tags:**
1. Base tracking (All Pages)
2. Free trial signup (Form submit)
3. Feature usage (Custom triggers)
4. Upgrade click (Click trigger)
5. Documentation views (Page views)

---

## Resources

- [GTM Template File](./template.tpl)
- [Full Documentation](./README.md)
- [Argusmetrics Docs](https://github.com/Benbo-se/ArgusmetricsSH)
- [GTM Best Practices](https://github.com/Benbo-se/ArgusmetricsSH/gtm-best-practices)

---

**Ready to get started?** [Create your Argus account](https://github.com/Benbo-se/ArgusmetricsSH) and start tracking in 5 minutes!
