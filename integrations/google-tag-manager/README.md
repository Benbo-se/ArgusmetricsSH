# Argusmetrics - Google Tag Manager Integration

Add Argusmetrics privacy-first analytics to your website using Google Tag Manager.

## Table of Contents

- [Method 1: Custom Template (Recommended)](#method-1-custom-template-recommended)
- [Method 2: Custom HTML Tag](#method-2-custom-html-tag)
- [Method 3: Custom JavaScript Variable](#method-3-custom-javascript-variable)
- [Triggering Options](#triggering-options)
- [Custom Event Tracking](#custom-event-tracking)
- [Troubleshooting](#troubleshooting)

---

## Method 1: Custom Template (Recommended)

The custom template provides the easiest and most maintainable way to add Argusmetrics.

### Step 1: Import the Template

1. Download `template.tpl` from this directory
2. In Google Tag Manager, go to **Templates** in the left sidebar
3. Click **New** in the "Tag Templates" section
4. Click the **⋮** menu (top right) and select **Import**
5. Upload the `template.tpl` file
6. Click **Save**

### Step 2: Create a New Tag

1. Go to **Tags** → **New**
2. Click on **Tag Configuration**
3. Scroll down and select **Argusmetrics** (under Custom)
4. Configure the tag:
   - **Tracking Code**: Your 8-character code from the dashboard
   - **API Endpoint** (optional): Leave default unless self-hosting
   - **Exclude Outbound Domains** (optional): e.g., `paypal.com, stripe.com`
   - **Advanced Settings**:
     - ✅ Track initial pageview (recommended)
     - ✅ Enable outbound link tracking (recommended)
     - ✅ Enable scroll depth tracking (recommended)

### Step 3: Set the Trigger

1. Click on **Triggering**
2. Select **All Pages** (or **Initialization - All Pages** for faster loading)
3. Click **Save**
4. Name your tag (e.g., "Argusmetrics - Analytics")

### Step 4: Test and Publish

1. Click **Preview** to test
2. Visit your website in the preview mode
3. Verify the tag fires correctly
4. Click **Submit** to publish

**That's it!** Argusmetrics is now tracking your website.

---

## Method 2: Custom HTML Tag

If you prefer not to use custom templates, you can use a Custom HTML tag.

### Step 1: Create Custom HTML Tag

1. Go to **Tags** → **New**
2. Click **Tag Configuration**
3. Select **Custom HTML**
4. Paste this code:

```html
<script>
  (function() {
    // Configuration
    var config = {
      trackingCode: 'YOUR_CODE',  // Replace with your 8-character code
      apiEndpoint: 'https://analytics.your-domain.com/api/v1/analytics/track',
      excludeOutbound: '',  // Optional: 'example.com, another.com'
    };

    // Create script element
    var script = document.createElement('script');
    script.defer = true;
    script.setAttribute('data-tracking-code', config.trackingCode);
    script.setAttribute('data-api-endpoint', config.apiEndpoint);

    if (config.excludeOutbound) {
      script.setAttribute('data-exclude-outbound', config.excludeOutbound);
    }

    script.src = 'https://analytics.your-domain.com/static/tracker.min.js';

    // Inject script
    var firstScript = document.getElementsByTagName('script')[0];
    firstScript.parentNode.insertBefore(script, firstScript);
  })();
</script>
```

5. Replace `'YOUR_CODE'` with your actual tracking code
6. Configure options as needed

### Step 2: Configure Triggering

1. Click **Triggering**
2. Select **All Pages** (recommended)
3. Save and publish

---

## Method 3: Custom JavaScript Variable

For more advanced use cases or dynamic tracking codes.

### Step 1: Create JavaScript Variable

1. Go to **Variables** → **User-Defined Variables** → **New**
2. Select **Custom JavaScript**
3. Add this code:

```javascript
function() {
  return {
    trackingCode: 'YOUR_CODE',
    apiEndpoint: 'https://analytics.your-domain.com/api/v1/analytics/track'
  };
}
```

4. Name it `Argus Config`
5. Save

### Step 2: Create Custom HTML Tag

1. Create a new Custom HTML tag
2. Use this code:

```html
<script>
  (function() {
    var config = {{Argus Config}};

    var script = document.createElement('script');
    script.defer = true;
    script.setAttribute('data-tracking-code', config.trackingCode);
    script.setAttribute('data-api-endpoint', config.apiEndpoint);
    script.src = 'https://analytics.your-domain.com/static/tracker.min.js';

    document.head.appendChild(script);
  })();
</script>
```

3. Set trigger to **All Pages**
4. Save and publish

---

## Triggering Options

Choose the right trigger based on your needs:

### Option 1: All Pages (Recommended)
- **Trigger**: All Pages
- **When**: Page loads completely
- **Best for**: Most websites
- **Pros**: Simple, reliable
- **Cons**: Fires after DOM ready

### Option 2: Initialization - All Pages (Faster)
- **Trigger**: Initialization - All Pages
- **When**: As soon as GTM loads
- **Best for**: Performance-critical sites
- **Pros**: Fastest tracking
- **Cons**: DOM may not be ready

### Option 3: DOM Ready
- **Trigger**: DOM Ready
- **When**: DOM is fully loaded
- **Best for**: Dynamic content sites
- **Pros**: Balance of speed and reliability

### Option 4: Custom Trigger
Create custom triggers for:
- Specific pages only
- Logged-in users only
- Conditional tracking

**Example - Only track blog posts:**

1. Create trigger: Page Path contains `/blog/`
2. Apply to Argusmetrics tag

---

## Custom Event Tracking

Track custom events through Google Tag Manager.

### Method 1: Using GTM Data Layer

**Push events to Data Layer:**

```javascript
// In your website code
dataLayer.push({
  'event': 'argus_custom_event',
  'eventName': 'button_click',
  'eventProperties': {
    'button': 'signup',
    'color': 'blue'
  }
});
```

**Create GTM Custom HTML Tag:**

1. Go to **Tags** → **New**
2. Select **Custom HTML**
3. Add this code:

```html
<script>
  if (window.argus) {
    window.argus.trackEvent(
      {{Event Name}},
      {{Event Properties}}
    );
  }
</script>
```

4. Create variables for `{{Event Name}}` and `{{Event Properties}}`
5. Set trigger to custom event: `argus_custom_event`

### Method 2: Direct API Call

**In Custom HTML Tag:**

```html
<script>
  // Wait for Argus to load
  (function checkArgus() {
    if (window.argus) {
      window.argus.trackEvent('purchase_complete', {
        value: {{Transaction Total}},
        currency: 'USD',
        items: {{Transaction Items}}
      });
    } else {
      setTimeout(checkArgus, 100);
    }
  })();
</script>
```

### Example Use Cases

**1. Form Submissions**

```javascript
// On form submit
dataLayer.push({
  'event': 'form_submit',
  'formName': 'contact_form'
});
```

**2. Button Clicks**

```javascript
// On button click
dataLayer.push({
  'event': 'button_click',
  'buttonText': 'Get Started',
  'buttonLocation': 'hero'
});
```

**3. Video Events**

```javascript
// On video play
dataLayer.push({
  'event': 'video_play',
  'videoTitle': 'Product Demo',
  'videoPosition': '00:00'
});
```

---

## Advanced Configuration

### Excluding Admin Users

Add this to your Custom HTML tag to exclude logged-in admins:

```html
<script>
  // Check if user is admin (adjust based on your CMS)
  var isAdmin = document.body.classList.contains('logged-in');

  if (!isAdmin) {
    // Load Argusmetrics tracking code here
  }
</script>
```

### Multi-Domain Tracking

For tracking across multiple domains with the same tracking code:

1. Use the same tracking code in GTM on all domains
2. Ensure the same GTM container is on all domains
3. Argus automatically handles cross-domain tracking

### Custom API Endpoint (Self-Hosted)

If you're self-hosting Argusmetrics:

```javascript
var config = {
  trackingCode: 'YOUR_CODE',
  apiEndpoint: 'https://your-domain.com/api/v1/analytics'
};
```

---

## Troubleshooting

### Script Not Loading

**Check:**
1. GTM container is properly installed
2. Tag is set to fire on correct pages
3. No ad blockers are blocking GTM
4. Open browser console and look for errors

**Debug Mode:**
1. Click **Preview** in GTM
2. Visit your website
3. Check if Argusmetrics tag fires
4. Look at the **Tags Fired** section

### Tracking Not Working

**Verify:**
1. Tracking code is correct (8 characters)
2. Script loads successfully (check Network tab)
3. Check browser console for JavaScript errors
4. Verify API endpoint is correct

**Test with console:**

```javascript
// Check if Argus is loaded
console.log(window.argus);

// Manually trigger pageview
if (window.argus) {
  window.argus.track();
}
```

### Events Not Tracking

**Common issues:**
1. Event name is incorrect
2. Properties format is wrong (must be object)
3. Argus script hasn't loaded yet when event fires
4. Check if website is verified in Argus dashboard

**Solution:**
Add a wait check:

```javascript
function waitForArgus(callback) {
  if (window.argus) {
    callback();
  } else {
    setTimeout(function() {
      waitForArgus(callback);
    }, 100);
  }
}

waitForArgus(function() {
  window.argus.trackEvent('my_event', { key: 'value' });
});
```

### Multiple Pageviews

**Problem:** Pageviews tracked multiple times

**Solutions:**
1. Ensure tag only fires once per page
2. Check trigger configuration
3. Remove duplicate tags
4. Use **Initialization** trigger instead of **All Pages**

---

## Best Practices

### 1. Use Descriptive Tag Names
✅ Good: "Argusmetrics - Analytics Tracking"
❌ Bad: "Custom HTML Tag 1"

### 2. Organize with Folders
Create folders in GTM:
- Analytics
  - Argusmetrics
  - Custom Events
  - Goal Tracking

### 3. Use Naming Conventions
- Tags: `AM - [Purpose]`
- Triggers: `AM Trigger - [Condition]`
- Variables: `AM - [Variable Name]`

### 4. Test Before Publishing
Always use Preview mode to test changes before publishing.

### 5. Document Changes
Add notes when publishing:
- What changed
- Why it changed
- Expected impact

### 6. Version Control
Export your GTM container regularly for backup.

---

## FAQ

**Q: Can I use Argusmetrics with other analytics tools?**
A: Yes! Argus works alongside Google Analytics, Plausible, or any other tool.

**Q: Does this affect my GTM quota?**
A: Argusmetrics uses minimal GTM resources. One tag = minimal impact.

**Q: Can I track Single Page Applications (SPAs)?**
A: Yes! Use History Change trigger or implement custom pageview tracking.

**Q: Is there a way to test without affecting live data?**
A: Use GTM Preview mode. Data sent during preview won't affect production.

**Q: How do I track conversions?**
A: Use custom event tracking with meaningful event names like `purchase_complete`.

---

## Support

Need help?

- **Documentation**: this file, plus https://github.com/Benbo-se/ArgusmetricsSH
- **Issues**: https://github.com/Benbo-se/ArgusmetricsSH/issues

---

## License

This integration is provided as-is under the MIT License.

## Contributing

Have improvements? Open a pull request or an issue at https://github.com/Benbo-se/ArgusmetricsSH.
