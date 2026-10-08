/**
 * Argusmetrics Dashboard JavaScript
 * Handles chart initialization, data formatting, and interactive features
 */

/**
 * Read a design token from the theme layer so charts follow the palette and
 * the light/dark switch instead of hardcoding one blue.
 */
function themeColor(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
}

/** Same color at a given alpha (tokens are hex). */
function themeAlpha(name, alpha, fallback) {
    const hex = themeColor(name, fallback);
    const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex.replace('#', '#'));
    if (!m) return hex;
    return `rgba(${parseInt(m[1], 16)}, ${parseInt(m[2], 16)}, ${parseInt(m[3], 16)}, ${alpha})`;
}

// Categorical series palette: distinct hues that stay legible on both themes.
const SERIES_COLORS = ['#4550c8', '#06a9c9', '#7b4fd0', '#12855f', '#c2701a', '#b32739'];

// Global chart instances
let pageviewsChart = null;
let devicesChart = null;
let browsersChart = null;

/**
 * Format number with K/M suffix
 */
function formatNumber(num) {
    if (num >= 1000000) {
        return (num / 1000000).toFixed(1) + 'M';
    }
    if (num >= 1000) {
        return (num / 1000).toFixed(1) + 'K';
    }
    return num.toString();
}

/**
 * The line draws itself from left to right, point by point, the first time
 * the chart appears. Chart.js's "progressive line" recipe: each point starts
 * where the previous one is and is released after the one before it. Off
 * with prefers-reduced-motion.
 */
function drawInAnimation(points) {
    // Not in a hidden tab: Chart.js animates on requestAnimationFrame, which a
    // hidden tab never runs, so the chart stayed empty until it was shown, and
    // forever for anything that renders the page without showing it.
    if (REDUCED_MOTION || !points || document.hidden) return false;
    const total = 900;
    const each = total / points;
    const previousY = (ctx) => ctx.index === 0
        ? ctx.chart.scales.y.getPixelForValue(0)
        : ctx.chart.getDatasetMeta(ctx.datasetIndex).data[ctx.index - 1].getProps(['y'], true).y;
    return {
        x: {
            type: 'number', easing: 'linear', duration: each, from: NaN,
            delay(ctx) {
                if (ctx.type !== 'data' || ctx.xStarted) return 0;
                ctx.xStarted = true;
                return ctx.index * each;
            },
        },
        y: {
            type: 'number', easing: 'linear', duration: each, from: previousY,
            delay(ctx) {
                if (ctx.type !== 'data' || ctx.yStarted) return 0;
                ctx.yStarted = true;
                return ctx.index * each;
            },
        },
    };
}

/**
 * A dashed vertical line through the hovered day, so the eye can follow the
 * tooltip down to the axis and across to the previous period's line.
 */
const crosshairPlugin = {
    id: 'argusCrosshair',
    afterDatasetsDraw(chart) {
        const active = chart.tooltip && chart.tooltip.getActiveElements
            ? chart.tooltip.getActiveElements() : [];
        if (!active.length) return;
        const x = active[0].element.x;
        const { top, bottom } = chart.chartArea;
        const c = chart.ctx;
        c.save();
        c.beginPath();
        c.moveTo(x, top);
        c.lineTo(x, bottom);
        c.lineWidth = 1;
        c.setLineDash([4, 4]);
        c.strokeStyle = themeAlpha('--brand-500', 0.45, '#4550c8');
        c.stroke();
        c.restore();
    },
};

/** A fill that fades from the line down to nothing, instead of a flat tint. */
function fadingFill(context) {
    const { chart } = context;
    const area = chart.chartArea;
    if (!area) return themeAlpha('--brand-500', 0.12, '#4550c8');
    const g = chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
    g.addColorStop(0, themeAlpha('--brand-500', 0.28, '#4550c8'));
    g.addColorStop(1, themeAlpha('--brand-500', 0, '#4550c8'));
    return g;
}

const CHART_METRICS = {
    visitors: { key: 'visitors', noun: 'visitors' },
    views: { key: 'views', noun: 'pageviews' },
};

/**
 * The main chart: one metric over the period, and the previous period dashed
 * beside it when comparing. `metric` is 'visitors' or 'views'; series written
 * before visitors were counted per day fall back to views.
 */
function initPageviewsChart(timeseriesData, previousPeriodData = null, metric = 'views') {
    const ctx = document.getElementById('pageviews-chart');
    if (!ctx) return;

    const m = CHART_METRICS[metric] || CHART_METRICS.views;
    const pick = (d) => (d[m.key] !== undefined ? d[m.key] : d.views);
    const labels = timeseriesData.map(d => {
        const date = new Date(d.date);
        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    });
    const data = timeseriesData.map(pick);
    const brand = themeColor('--brand-500', '#4550c8');

    if (pageviewsChart) {
        pageviewsChart.destroy();
    }

    const datasets = [{
        label: 'This period',
        data: data,
        borderColor: brand,
        backgroundColor: fadingFill,
        borderWidth: 2.5,
        fill: true,
        tension: 0.35,
        // Points only where the pointer is: thirty dots in a row are noise.
        pointRadius: data.length > 1 ? 0 : 4,
        pointHoverRadius: 5,
        pointBackgroundColor: brand,
        pointBorderColor: themeColor('--surface-card', '#ffffff'),
        pointBorderWidth: 2,
    }];

    const comparing = previousPeriodData && previousPeriodData.length > 0;
    if (comparing) {
        datasets.push({
            label: 'Previous period',
            data: previousPeriodData.map(pick),
            borderColor: themeAlpha('--text-muted', 0.8, '#767ea0'),
            borderWidth: 1.5,
            borderDash: [5, 5],
            fill: false,
            tension: 0.35,
            pointRadius: 0,
            pointHoverRadius: 4,
            pointBackgroundColor: themeColor('--text-muted', '#767ea0'),
        });
    }

    pageviewsChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: datasets
        },
        plugins: [crosshairPlugin],
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: drawInAnimation(data.length),
            plugins: {
                legend: {
                    display: comparing,
                    position: 'top',
                    align: 'end',
                    labels: {
                        boxWidth: 12,
                        usePointStyle: true,
                        padding: 15,
                        font: { size: 12 }
                    }
                },
                tooltip: {
                    enabled: true,
                    backgroundColor: 'rgba(17, 24, 39, 0.95)',
                    titleColor: '#fff',
                    bodyColor: '#fff',
                    borderColor: themeAlpha('--brand-500', 0.3, '#4550c8'),
                    borderWidth: 1,
                    padding: 12,
                    titleFont: { size: 13, weight: 'bold' },
                    bodyFont: { size: 13 },
                    bodySpacing: 6,
                    cornerRadius: 8,
                    displayColors: comparing,
                    callbacks: {
                        title: function(tooltipItems) {
                            return tooltipItems[0].label;
                        },
                        label: function(context) {
                            const value = context.parsed.y.toLocaleString() + ' ' + m.noun;
                            return comparing ? context.dataset.label + ': ' + value : value;
                        },
                        afterBody: function(tooltipItems) {
                            if (tooltipItems.length !== 2) return '';
                            const currentValue = tooltipItems[0].parsed.y;
                            const previousValue = tooltipItems[1].parsed.y;
                            const change = currentValue - previousValue;
                            const changePercent = previousValue > 0 ? ((change / previousValue) * 100).toFixed(1) : 0;
                            if (change > 0) return '\n↑ +' + change.toLocaleString() + ' (+' + changePercent + '%) vs previous period';
                            if (change < 0) return '\n↓ ' + change.toLocaleString() + ' (' + changePercent + '%) vs previous period';
                            return '\n→ No change vs previous period';
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    border: { display: false },
                    ticks: {
                        color: themeColor('--text-muted', '#767ea0'),
                        maxTicksLimit: 5,
                        precision: 0,
                        callback: function(value) {
                            return formatNumber(value);
                        }
                    },
                    grid: { color: themeAlpha('--border-subtle', 0.7, '#e3e6ef') }
                },
                x: {
                    border: { display: false },
                    ticks: {
                        color: themeColor('--text-muted', '#767ea0'),
                        maxRotation: 0,
                        autoSkip: true,
                        maxTicksLimit: 8,
                    },
                    grid: { display: false }
                }
            },
            interaction: {
                intersect: false,
                mode: 'index'
            }
        }
    });
}

/**
 * The Visitors / Pageviews switch above the main chart. Buttons carry
 * data-chart-metric; the one shown is marked aria-pressed.
 */
function bindChartMetricSwitch(timeseriesData, previousPeriodData) {
    const buttons = document.querySelectorAll('[data-chart-metric]');
    const show = (metric) => {
        buttons.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.chartMetric === metric)));
        initPageviewsChart(timeseriesData, previousPeriodData, metric);
    };
    buttons.forEach((b) => b.addEventListener('click', () => show(b.dataset.chartMetric)));
    show('visitors');
}

/**
 * A progress bar's width, from data-fill (percent). The template used to
 * write it as style="width: ..." in the markup, which style-src 'self'
 * refuses, so the monthly usage bar on the websites list was always empty.
 */
function applyFills(root) {
    root.querySelectorAll('[data-fill]').forEach((el) => {
        const fill = Math.max(0, Math.min(100, parseFloat(el.dataset.fill) || 0));
        el.style.width = fill + '%';
    });
}

/**
 * The row of section links on the settings page marks the section in view.
 * The section counted as in view is the last one whose top has passed a
 * line a little below the sticky row, so a short section between two long
 * ones still gets its turn.
 */
function sectionNav() {
    const nav = document.querySelector('[data-section-nav]');
    if (!nav) return;
    const links = [...nav.querySelectorAll('a[href^="#"]')];
    const sections = links.map((a) => document.getElementById(a.getAttribute('href').slice(1)));
    const mark = () => {
        const line = nav.getBoundingClientRect().bottom + 24;
        let current = 0;
        sections.forEach((section, i) => {
            if (section && section.getBoundingClientRect().top <= line) current = i;
        });
        // At the very bottom the last section may never reach the line.
        if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) {
            current = sections.length - 1;
        }
        links.forEach((a, i) => a.setAttribute('aria-current', i === current ? 'true' : 'false'));
    };
    // A folded section opened from its link: open it, then let the browser jump.
    links.forEach((a, i) => a.addEventListener('click', () => {
        if (sections[i] && sections[i].tagName === 'DETAILS') sections[i].open = true;
    }));
    window.addEventListener('scroll', mark, { passive: true });
    window.addEventListener('resize', mark);
    mark();
}

/**
 * Ranked rows rendered on the server say how big their share is in
 * data-share; the bar behind them is drawn from a custom property, set here
 * because a style attribute in the markup would be blocked by style-src.
 *
 * The bars are drawn against the largest row in the same list, so the first
 * row is full width and the rest read as "this much of the top one". Against
 * the total, six pages of 15% each were six slivers the width of their own
 * text. The true share is still printed beside each row.
 */
function applyShareBars(root) {
    const lists = new Map();
    root.querySelectorAll('[data-share]').forEach((el) => {
        const share = Math.max(0, parseFloat(el.dataset.share) || 0);
        if (!lists.has(el.parentElement)) lists.set(el.parentElement, []);
        lists.get(el.parentElement).push([el, share]);
    });
    lists.forEach((rows) => {
        const top = Math.max(...rows.map(([, share]) => share));
        rows.forEach(([el, share]) => {
            el.style.setProperty('--share', (top ? (share / top) * 100 : 0) + '%');
        });
    });
}

/**
 * Initialize devices pie chart
 */
function initDevicesChart(devicesData) {
    const ctx = document.getElementById('devices-chart');
    if (!ctx) return;

    const labels = Object.keys(devicesData).map(key =>
        key.charAt(0).toUpperCase() + key.slice(1)
    );
    const data = Object.values(devicesData);

    const colors = {
        desktop: SERIES_COLORS[0],
        mobile: SERIES_COLORS[1],
        tablet: SERIES_COLORS[2],
        unknown: themeColor('--text-muted', '#767ea0')
    };

    const backgroundColors = Object.keys(devicesData).map(key =>
        colors[key] || colors.unknown
    );

    if (devicesChart) {
        devicesChart.destroy();
    }

    devicesChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: backgroundColors,
                borderWidth: 2,
                borderColor: themeColor('--surface-card', '#ffffff')
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    enabled: true,
                    backgroundColor: 'rgba(17, 24, 39, 0.95)',
                    titleColor: '#fff',
                    bodyColor: '#fff',
                    borderColor: themeAlpha('--brand-500', 0.3, '#4550c8'),
                    borderWidth: 1,
                    padding: 16,
                    titleFont: { size: 14, weight: 'bold' },
                    bodyFont: { size: 14 },
                    bodySpacing: 6,
                    cornerRadius: 8,
                    displayColors: true,
                    callbacks: {
                        label: function(context) {
                            const label = context.label || '';
                            const value = context.parsed || 0;
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
                            return label + ': ' + value.toLocaleString() + ' visitors (' + percentage + '%)';
                        },
                        afterLabel: function(context) {
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            return 'Total: ' + total.toLocaleString() + ' visitors';
                        }
                    }
                }
            }
        }
    });
}

/**
 * Copy tracking code to clipboard
 */
function copyTrackingCode() {
    const code = document.getElementById('tracking-code');
    if (!code) return;

    const textarea = document.createElement('textarea');
    textarea.value = code.textContent;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);

    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);

    showToast('Tracking code copied to clipboard!');
}

/**
 * Show toast notification
 */
function showToast(message) {
    window.dispatchEvent(new CustomEvent('toast', {
        detail: { message: message }
    }));
}

/**
 * Get country flag emoji from country code
 */
function getCountryFlag(countryCode) {
    if (!countryCode || countryCode.length !== 2) return '🌍';

    const codePoints = countryCode
        .toUpperCase()
        .split('')
        .map(char => 127397 + char.charCodeAt());

    return String.fromCodePoint(...codePoints);
}

/**
 * Debounce function for performance
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * Handle responsive chart resizing
 */
window.addEventListener('resize', debounce(() => {
    if (pageviewsChart) pageviewsChart.resize();
    if (devicesChart) devicesChart.resize();
    if (browsersChart) browsersChart.resize();
}, 250));

/**
 * Initialize HTMX event listeners
 */
/**
 * Headline numbers count up to their value, and count from the old value to
 * the new one when a refresh changes them.
 *
 * The tiles are rendered on the server as finished text ("1,234", "42%",
 * "1.5") and swapped by HTMX every few seconds. The number is read back out
 * of that text, so the server stays the only place that formats it, and only
 * text that parses back exactly is animated: a duration like "1m 23s" is left
 * as it is. A refresh that changes nothing animates nothing, which matters
 * on a five-second cycle. With prefers-reduced-motion the numbers just appear.
 */
const REDUCED_MOTION = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
const shownStatValues = new Map();

// The cards rise in on arrival (.dash-page in theme.css). Set here, while the
// page is still being parsed, so nothing is painted and then hidden again;
// never in a hidden tab, where the animation would not run and the cards
// would stay invisible.
if (!REDUCED_MOTION && !document.hidden) document.documentElement.classList.add('dash-motion');

function parseStatValue(text) {
    const match = (text || '').trim().match(/^([\d,]+(?:\.\d+)?)(%?)$/);
    if (!match) return null;
    const raw = match[1].replace(/,/g, '');
    return { value: parseFloat(raw), decimals: (raw.split('.')[1] || '').length, suffix: match[2] };
}

function formatStatValue(value, decimals, suffix) {
    return value.toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    }) + suffix;
}

function countUpStats(root) {
    const tiles = [];
    if (root.matches && root.matches('.stat-tile')) tiles.push(root);
    root.querySelectorAll('.stat-tile').forEach((tile) => tiles.push(tile));

    tiles.forEach((tile) => {
        const label = tile.querySelector('.stat-label');
        const el = tile.querySelector('.stat-value');
        if (!label || !el) return;
        const target = parseStatValue(el.textContent);
        if (!target) return;

        const key = label.textContent.trim();
        const refresh = shownStatValues.has(key);
        const from = refresh ? shownStatValues.get(key) : 0;
        shownStatValues.set(key, target.value);
        // A hidden tab runs no animation frames, so a count started there
        // froze on its first frame: the public dashboard read 0 visitors, or
        // 0.6 views per visit halfway to 1.0, until someone looked at it, and
        // a link preview or a crawler never does. Show the number instead.
        if (REDUCED_MOTION || document.hidden || from === target.value) return;

        if (refresh) {
            // A refresh changed it: say so, briefly.
            tile.classList.remove('stat-bump');
            void tile.offsetWidth;
            tile.classList.add('stat-bump');
        }

        const finalText = el.textContent;
        const start = performance.now();
        const duration = 700;
        const step = (now) => {
            const k = Math.min(1, (now - start) / duration);
            const eased = 1 - Math.pow(1 - k, 3);
            el.textContent = k < 1
                ? formatStatValue(from + (target.value - from) * eased, target.decimals, target.suffix)
                : finalText;
            if (k < 1) requestAnimationFrame(step);
        };
        el.textContent = formatStatValue(from, target.decimals, target.suffix);
        requestAnimationFrame(step);
        // And if the tab is hidden mid-count, the server's text still lands:
        // timers run in a hidden tab, animation frames do not.
        setTimeout(() => { el.textContent = finalText }, duration + 200);
    });
}

document.addEventListener('DOMContentLoaded', () => {
    // No log line per swap: the stats refresh every few seconds, and that
    // put a message in the console every five seconds for as long as the
    // dashboard was open.
    document.body.addEventListener('htmx:afterSwap', (event) => {
        countUpStats(event.detail.target);
        applyShareBars(event.detail.target);
    });

    document.body.addEventListener('htmx:responseError', (event) => {
        console.error('HTMX request failed:', event.detail);
        showToast('Failed to load data. Please try again.');
    });

    countUpStats(document);
    applyShareBars(document);
    applyFills(document);
    sectionNav();
});

// Export functions for global use
window.formatNumber = formatNumber;
window.initPageviewsChart = initPageviewsChart;
window.bindChartMetricSwitch = bindChartMetricSwitch;
window.initDevicesChart = initDevicesChart;
window.copyTrackingCode = copyTrackingCode;
window.showToast = showToast;
window.getCountryFlag = getCountryFlag;

/**
 * Make table sortable
 * Usage: x-data="sortableTable" on the wrapper, and on each <th>:
 *   @click="sortTable" data-column="3" data-numeric="true"
 *   <span x-text="sortIcon"></span>
 */
function sortableTable() {
    return {
        sortColumn: null,
        sortDirection: 'asc',
        
        /**
         * Sorts by the column named in the clicked header's data attributes.
         *
         * The column index and numeric flag used to be arguments in the
         * template (`sortTable(3, true)`). A CSP-build expression cannot carry
         * arguments, so the header carries them instead: data-column and
         * data-numeric.
         */
        sortTable(event) {
            const header = event ? event.currentTarget : null;
            const columnIndex = header ? Number(header.dataset.column) : 0;
            const isNumeric = header ? header.dataset.numeric === 'true' : false;

            const table = this.$el.querySelector('table');
            if (!table) return;
            
            const tbody = table.querySelector('tbody');
            const rows = Array.from(tbody.querySelectorAll('tr'));
            
            // Toggle sort direction if same column
            if (this.sortColumn === columnIndex) {
                this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
            } else {
                this.sortColumn = columnIndex;
                this.sortDirection = 'asc';
            }
            
            // Sort rows
            rows.sort((a, b) => {
                const aCell = a.cells[columnIndex];
                const bCell = b.cells[columnIndex];
                
                if (!aCell || !bCell) return 0;
                
                let aValue = aCell.textContent.trim();
                let bValue = bCell.textContent.trim();
                
                // Handle numeric sorting
                if (isNumeric) {
                    // Remove commas and % signs
                    aValue = parseFloat(aValue.replace(/[,%]/g, '')) || 0;
                    bValue = parseFloat(bValue.replace(/[,%]/g, '')) || 0;
                    return this.sortDirection === 'asc' ? aValue - bValue : bValue - aValue;
                }
                
                // String sorting
                if (this.sortDirection === 'asc') {
                    return aValue.localeCompare(bValue);
                } else {
                    return bValue.localeCompare(aValue);
                }
            });
            
            // Re-append sorted rows
            rows.forEach(row => tbody.appendChild(row));
        },
        
        /**
         * The arrow for whichever header is asking.
         *
         * A getter rather than a method, and it reads the column from $el,
         * which Alpine injects per element. One definition, a different answer
         * on each header.
         */
        get sortIcon() {
            const columnIndex = Number(this.$el.dataset.column);
            if (this.sortColumn !== columnIndex) {
                return '↕️'; // Both arrows when not sorted
            }
            return this.sortDirection === 'asc' ? '↑' : '↓';
        }
    };
}

// Registered as an Alpine component: x-data="sortableTable()" is a call
// expression, which the CSP build cannot evaluate.
window.sortableTable = sortableTable;
document.addEventListener('alpine:init', () => {
    Alpine.data('sortableTable', sortableTable);
});
