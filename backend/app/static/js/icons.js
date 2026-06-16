/**
 * Icon mappings for browsers and sources
 * Argusmetrics - Analytics Dashboard
 */

// Browser icons (using emoji for simplicity)
const browserIcons = {
    'Chrome': '🌐',
    'Firefox': '🦊',
    'Safari': '🧭',
    'Edge': 'ⓔ',
    'Opera': 'ⓞ',
    'Brave': '🦁',
    'Samsung Internet': '📱',
    'UC Browser': 'ⓤ',
    'Mobile Safari': '📱',
    'Chrome Mobile': '📱',
    'Firefox Mobile': '📱',
    'Android Browser': '🤖',
    'default': '🌐'
};

// Source/Referrer icons
const sourceIcons = {
    'google': '🔍',
    'facebook': '📘',
    'twitter': '🐦',
    'linkedin': '💼',
    'github': '⚙️',
    'reddit': '🤖',
    'youtube': '📺',
    'instagram': '📷',
    'pinterest': '📌',
    'tiktok': '🎵',
    'direct': '➡️',
    't.co': '🐦',  // Twitter short links
    'fb.com': '📘',  // Facebook short links
    'default': '🌐'
};

/**
 * Get browser icon
 */
function getBrowserIcon(browserName) {
    if (!browserName) return browserIcons.default;

    // Check for exact match
    if (browserIcons[browserName]) {
        return browserIcons[browserName];
    }

    // Check for partial match
    const lowerName = browserName.toLowerCase();
    for (const [key, icon] of Object.entries(browserIcons)) {
        if (lowerName.includes(key.toLowerCase())) {
            return icon;
        }
    }

    return browserIcons.default;
}

/**
 * Get source/referrer icon
 */
function getSourceIcon(sourceName) {
    if (!sourceName || sourceName === '(Direct)' || sourceName === 'Direct') {
        return sourceIcons.direct;
    }

    const lowerName = sourceName.toLowerCase();

    // Check for exact match
    if (sourceIcons[lowerName]) {
        return sourceIcons[lowerName];
    }

    // Check for partial match (e.g., "google.com" matches "google")
    for (const [key, icon] of Object.entries(sourceIcons)) {
        if (lowerName.includes(key)) {
            return icon;
        }
    }

    return sourceIcons.default;
}

// Export for use in templates
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { getBrowserIcon, getSourceIcon, browserIcons, sourceIcons };
}
