/**
 * Argusmetrics Dashboard JavaScript
 * Handles chart initialization, data formatting, and interactive features
 */

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
 * Initialize pageviews line chart
 */
function initPageviewsChart(timeseriesData, previousPeriodData = null) {
    const ctx = document.getElementById('pageviews-chart');
    if (!ctx) return;

    const labels = timeseriesData.map(d => {
        const date = new Date(d.date);
        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    });
    const data = timeseriesData.map(d => d.views);

    if (pageviewsChart) {
        pageviewsChart.destroy();
    }

    // Prepare datasets
    const datasets = [{
        label: 'Current Period',
        data: data,
        borderColor: 'rgb(59, 130, 246)',
        backgroundColor: 'rgba(59, 130, 246, 0.1)',
        borderWidth: 2,
        fill: true,
        tension: 0.4,
        pointRadius: 3,
        pointHoverRadius: 5,
        pointBackgroundColor: 'rgb(59, 130, 246)',
        pointBorderColor: '#fff',
        pointBorderWidth: 2,
    }];

    // Add previous period dataset if provided
    if (previousPeriodData && previousPeriodData.length > 0) {
        const previousData = previousPeriodData.map(d => d.views);
        datasets.push({
            label: 'Previous Period',
            data: previousData,
            borderColor: 'rgb(156, 163, 175)',
            backgroundColor: 'rgba(156, 163, 175, 0.05)',
            borderWidth: 2,
            borderDash: [5, 5],
            fill: false,
            tension: 0.4,
            pointRadius: 2,
            pointHoverRadius: 4,
            pointBackgroundColor: 'rgb(156, 163, 175)',
            pointBorderColor: '#fff',
            pointBorderWidth: 1,
        });
    }

    pageviewsChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: previousPeriodData && previousPeriodData.length > 0,
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
                    borderColor: 'rgba(59, 130, 246, 0.3)',
                    borderWidth: 1,
                    padding: 16,
                    titleFont: { size: 14, weight: 'bold' },
                    bodyFont: { size: 14 },
                    bodySpacing: 6,
                    cornerRadius: 8,
                    displayColors: true,
                    callbacks: {
                        title: function(tooltipItems) {
                            return tooltipItems[0].label;
                        },
                        label: function(context) {
                            const label = context.dataset.label || '';
                            const value = context.parsed.y.toLocaleString();
                            return label + ': ' + value + ' pageviews';
                        },
                        afterBody: function(tooltipItems) {
                            // Show comparison if both periods are present
                            if (tooltipItems.length === 2) {
                                const currentValue = tooltipItems[0].parsed.y;
                                const previousValue = tooltipItems[1].parsed.y;
                                const change = currentValue - previousValue;
                                const changePercent = previousValue > 0 ? ((change / previousValue) * 100).toFixed(1) : 0;

                                if (change > 0) {
                                    return '\n↑ +' + change.toLocaleString() + ' (+' + changePercent + '%) vs previous period';
                                } else if (change < 0) {
                                    return '\n↓ ' + change.toLocaleString() + ' (' + changePercent + '%) vs previous period';
                                } else {
                                    return '\n→ No change vs previous period';
                                }
                            }
                            return '';
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return formatNumber(value);
                        }
                    },
                    grid: { color: 'rgba(0, 0, 0, 0.05)' }
                },
                x: {
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
        desktop: 'rgb(59, 130, 246)',
        mobile: 'rgb(16, 185, 129)',
        tablet: 'rgb(245, 158, 11)',
        unknown: 'rgb(156, 163, 175)'
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
                borderColor: '#fff'
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
                    borderColor: 'rgba(59, 130, 246, 0.3)',
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
document.addEventListener('DOMContentLoaded', () => {
    document.body.addEventListener('htmx:afterSwap', (event) => {
        console.log('HTMX swap completed:', event.detail.target.id);
    });

    document.body.addEventListener('htmx:responseError', (event) => {
        console.error('HTMX request failed:', event.detail);
        showToast('Failed to load data. Please try again.');
    });

    const statsCards = document.querySelectorAll('#stats-cards > div');
    statsCards.forEach((card, index) => {
        card.style.animationDelay = (index * 0.1) + 's';
        card.classList.add('fade-in');
    });
});

// Export functions for global use
window.formatNumber = formatNumber;
window.initPageviewsChart = initPageviewsChart;
window.initDevicesChart = initDevicesChart;
window.copyTrackingCode = copyTrackingCode;
window.showToast = showToast;
window.getCountryFlag = getCountryFlag;

/**
 * Make table sortable
 * Usage: Add x-data="sortableTable()" to table wrapper div
 */
function sortableTable() {
    return {
        sortColumn: null,
        sortDirection: 'asc',
        
        sortTable(columnIndex, isNumeric = false) {
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
        
        getSortIcon(columnIndex) {
            if (this.sortColumn !== columnIndex) {
                return '↕️'; // Both arrows when not sorted
            }
            return this.sortDirection === 'asc' ? '↑' : '↓';
        }
    };
}

// Export for global use
window.sortableTable = sortableTable;
