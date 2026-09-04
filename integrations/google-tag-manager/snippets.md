# Argusmetrics GTM - Code Snippets

Ready-to-use code snippets for common tracking scenarios.

## Table of Contents

- [Basic Setup](#basic-setup)
- [Pageview Tracking](#pageview-tracking)
- [Custom Events](#custom-events)
- [E-commerce Tracking](#e-commerce-tracking)
- [Form Tracking](#form-tracking)
- [Button Click Tracking](#button-click-tracking)
- [Video Tracking](#video-tracking)
- [Download Tracking](#download-tracking)
- [Scroll Tracking](#scroll-tracking)

---

## Basic Setup

### Standard Script Tag

**GTM Tag Type:** Custom HTML
**Trigger:** All Pages

```html
<script defer
  data-tracking-code="YOUR_CODE"
  data-api-endpoint="https://analytics.your-domain.com/api/v1/analytics/track"
  src="https://analytics.your-domain.com/static/tracker.min.js">
</script>
```

### With Excluded Domains

```html
<script defer
  data-tracking-code="YOUR_CODE"
  data-api-endpoint="https://analytics.your-domain.com/api/v1/analytics/track"
  data-exclude-outbound="paypal.com, stripe.com, google.com"
  src="https://analytics.your-domain.com/static/tracker.min.js">
</script>
```

---

## Pageview Tracking

### Manual Pageview (SPA)

**GTM Tag Type:** Custom HTML
**Trigger:** History Change

```html
<script>
  if (window.argus) {
    window.argus.track();
  }
</script>
```

### Conditional Pageview

Only track specific sections:

```html
<script>
  // Only track blog posts
  if (window.location.pathname.startsWith('/blog/')) {
    if (window.argus) {
      window.argus.track();
    }
  }
</script>
```

---

## Custom Events

### Simple Event

```html
<script>
  window.argus.trackEvent('newsletter_signup');
</script>
```

### Event with Properties

```html
<script>
  window.argus.trackEvent('button_click', {
    button_text: 'Get Started',
    button_location: 'hero',
    button_color: 'blue'
  });
</script>
```

### Wait for Argus to Load

```html
<script>
  function trackWhenReady(eventName, properties) {
    if (window.argus) {
      window.argus.trackEvent(eventName, properties);
    } else {
      setTimeout(function() {
        trackWhenReady(eventName, properties);
      }, 100);
    }
  }

  trackWhenReady('page_interaction', {
    action: 'click',
    element: 'cta_button'
  });
</script>
```

---

## E-commerce Tracking

### Product View

**GTM Tag Type:** Custom HTML
**Trigger:** Page View - Product Pages

```html
<script>
  window.argus.trackEvent('product_view', {
    product_id: {{Product ID}},
    product_name: {{Product Name}},
    product_price: {{Product Price}},
    product_category: {{Product Category}}
  });
</script>
```

### Add to Cart

**GTM Tag Type:** Custom HTML
**Trigger:** Click - Add to Cart Button

```html
<script>
  window.argus.trackEvent('add_to_cart', {
    product_id: {{Product ID}},
    product_name: {{Product Name}},
    quantity: {{Quantity}},
    price: {{Product Price}}
  });
</script>
```

### Purchase Complete

**GTM Tag Type:** Custom HTML
**Trigger:** Page View - Thank You Page

```html
<script>
  window.argus.trackEvent('purchase', {
    transaction_id: {{Transaction ID}},
    value: {{Transaction Total}},
    currency: 'USD',
    items: {{Transaction Products}},
    payment_method: {{Payment Method}}
  });
</script>
```

### Begin Checkout

```html
<script>
  window.argus.trackEvent('begin_checkout', {
    value: {{Cart Total}},
    currency: 'USD',
    items_count: {{Cart Item Count}}
  });
</script>
```

---

## Form Tracking

### Generic Form Submit

**GTM Tag Type:** Custom HTML
**Trigger:** Form Submit - All Forms

```html
<script>
  window.argus.trackEvent('form_submit', {
    form_id: {{Form ID}},
    form_name: {{Form Name}},
    form_location: window.location.pathname
  });
</script>
```

### Contact Form

**GTM Tag Type:** Custom HTML
**Trigger:** Form Submit - Contact Form

```html
<script>
  window.argus.trackEvent('contact_form_submit', {
    form_type: 'contact',
    page: window.location.pathname,
    timestamp: new Date().toISOString()
  });
</script>
```

### Newsletter Signup

```html
<script>
  window.argus.trackEvent('newsletter_signup', {
    source: 'footer',
    page: window.location.pathname
  });
</script>
```

### Lead Capture

```html
<script>
  window.argus.trackEvent('lead_captured', {
    lead_source: 'landing_page',
    campaign: {{URL Parameter - utm_campaign}},
    medium: {{URL Parameter - utm_medium}}
  });
</script>
```

---

## Button Click Tracking

### CTA Button

**GTM Tag Type:** Custom HTML
**Trigger:** Click - CTA Buttons

```html
<script>
  window.argus.trackEvent('cta_click', {
    button_text: {{Click Text}},
    button_url: {{Click URL}},
    page_location: window.location.pathname
  });
</script>
```

### Social Share

**GTM Tag Type:** Custom HTML
**Trigger:** Click - Social Share Buttons

```html
<script>
  window.argus.trackEvent('social_share', {
    platform: {{Click Classes}}, // e.g., 'facebook', 'twitter'
    content_type: 'blog_post',
    content_title: document.title
  });
</script>
```

### Download Button

```html
<script>
  window.argus.trackEvent('download_click', {
    file_name: {{Click URL}},
    file_type: {{Click URL}}.split('.').pop(),
    download_location: window.location.pathname
  });
</script>
```

---

## Video Tracking

### Video Start

**GTM Tag Type:** Custom HTML
**Trigger:** Custom - Video Play Event

```html
<script>
  window.argus.trackEvent('video_start', {
    video_title: {{Video Title}},
    video_provider: 'youtube', // or 'vimeo', 'custom'
    video_url: {{Video URL}},
    page_location: window.location.pathname
  });
</script>
```

### Video Complete

```html
<script>
  window.argus.trackEvent('video_complete', {
    video_title: {{Video Title}},
    video_duration: {{Video Duration}},
    video_provider: 'youtube'
  });
</script>
```

### Video Progress (25%, 50%, 75%)

```html
<script>
  window.argus.trackEvent('video_progress', {
    video_title: {{Video Title}},
    video_percent: {{Video Percent}}, // 25, 50, 75, or 100
    video_current_time: {{Video Current Time}}
  });
</script>
```

---

## Download Tracking

### PDF Download

**GTM Tag Type:** Custom HTML
**Trigger:** Click - PDF Links

```html
<script>
  window.argus.trackEvent('pdf_download', {
    file_name: {{Click URL}}.split('/').pop(),
    file_url: {{Click URL}},
    download_location: window.location.pathname
  });
</script>
```

### File Download (Generic)

```html
<script>
  var fileUrl = {{Click URL}};
  var fileName = fileUrl.split('/').pop();
  var fileExtension = fileName.split('.').pop();

  window.argus.trackEvent('file_download', {
    file_name: fileName,
    file_type: fileExtension,
    file_url: fileUrl,
    page: window.location.pathname
  });
</script>
```

---

## Scroll Tracking

### Scroll to Specific Element

**GTM Tag Type:** Custom HTML
**Trigger:** Element Visibility - Target Element

```html
<script>
  window.argus.trackEvent('element_view', {
    element_id: {{Element ID}},
    element_class: {{Element Classes}},
    scroll_depth: 'visible',
    page: window.location.pathname
  });
</script>
```

### Time on Page

**GTM Tag Type:** Custom HTML
**Trigger:** Timer - Every 30 seconds

```html
<script>
  var timeSpent = {{Timer Duration}} / 1000; // Convert to seconds

  if (timeSpent === 30 || timeSpent === 60 || timeSpent === 120) {
    window.argus.trackEvent('time_on_page', {
      seconds: timeSpent,
      page: window.location.pathname,
      page_title: document.title
    });
  }
</script>
```

---

## Advanced Snippets

### User Engagement Score

Track multiple engagement signals:

```html
<script>
  (function() {
    var engagement = {
      page_views: 0,
      time_spent: 0,
      interactions: 0,
      scroll_depth: 0
    };

    // Track page view
    engagement.page_views++;

    // Track time (update every 30s)
    setInterval(function() {
      engagement.time_spent += 30;
    }, 30000);

    // Track interactions
    document.addEventListener('click', function() {
      engagement.interactions++;
    });

    // Send engagement data when user leaves
    window.addEventListener('beforeunload', function() {
      if (window.argus) {
        window.argus.trackEvent('session_engagement', engagement);
      }
    });
  })();
</script>
```

### A/B Test Tracking

```html
<script>
  // Assuming you have a variable {{AB Test Variant}}
  window.argus.trackEvent('ab_test_view', {
    test_name: 'homepage_hero',
    variant: {{AB Test Variant}},
    page: window.location.pathname
  });
</script>
```

### Error Tracking

```html
<script>
  window.addEventListener('error', function(e) {
    if (window.argus) {
      window.argus.trackEvent('javascript_error', {
        message: e.message,
        filename: e.filename,
        line: e.lineno,
        column: e.colno,
        page: window.location.pathname
      });
    }
  });
</script>
```

### Exit Intent

```html
<script>
  var exitIntentShown = false;

  document.addEventListener('mouseout', function(e) {
    if (!exitIntentShown && e.clientY < 0) {
      exitIntentShown = true;
      window.argus.trackEvent('exit_intent', {
        page: window.location.pathname,
        time_on_page: performance.now() / 1000
      });
    }
  });
</script>
```

---

## GTM Variables to Create

For better tracking, create these GTM variables:

### 1. Tracking Code Variable

**Type:** Constant
**Name:** Argus Tracking Code
**Value:** YOUR_8_CHAR_CODE

### 2. API Endpoint Variable

**Type:** Constant
**Name:** Argus API Endpoint
**Value:** https://analytics.your-domain.com/api/v1/analytics/track

### 3. Exclude Domains Variable

**Type:** Constant
**Name:** Argus Exclude Domains
**Value:** paypal.com, stripe.com

### Using Variables in Tags

```html
<script defer
  data-tracking-code="{{Argus Tracking Code}}"
  data-api-endpoint="{{Argus API Endpoint}}"
  data-exclude-outbound="{{Argus Exclude Domains}}"
  src="https://analytics.your-domain.com/static/tracker.min.js">
</script>
```

---

## Best Practices

### ✅ Do:
- Use descriptive event names
- Include relevant properties
- Test in Preview mode first
- Document your tracking plan
- Use GTM variables for reusability

### ❌ Don't:
- Track PII (emails, names, addresses)
- Create too many events
- Forget to check for `window.argus`
- Publish without testing
- Use sensitive data in properties

---

## Need More Examples?

Check out:
- [Full GTM Documentation](./README.md)
- [Quick Start Guide](./QUICK_START.md)
- [Argus Docs](https://github.com/Benbo-se/ArgusmetricsSH)
- [Custom Events Guide](https://github.com/Benbo-se/ArgusmetricsSH/custom-events)
