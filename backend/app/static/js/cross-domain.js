/**
 * The cross-domain dashboard.
 *
 * Lived as six hundred lines inside a <script nonce> in the template, where it
 * could not be cached and where two Jinja values were interpolated straight
 * into JavaScript with |safe. The data now arrives as JSON islands, which the
 * rest of this codebase already does, and which cannot break out of a string
 * literal because it is not in one.
 *
 * Every template expression is a bare name: see alpine-components.js for why.
 */
function crossDomainDashboard() {
    return {
        range: '7d',
        // Derived values the template used to compute inline. The CSP build
        // evaluates one bare name, so anything with an operator lives here.
        get websiteCount() { return Object.keys(this.websites).length },
        get siteEntries() {
            return Object.keys(this.websites).map((id) => ({
                id,
                name: this.websites[id].name,
                selected: this.selectedWebsites.includes(id),
            }))
        },
        get isLoading() { return this.loading },
        get isLoaded() { return !this.loading },
        get selectedCount() { return this.selectedWebsites.length },
        get totalPageviews() { return this.formatNumber(this.aggregatedStats.totalPageviews) },
        get uniqueVisitors() { return this.formatNumber(this.aggregatedStats.uniqueVisitors) },
        get avgViews() { return this.aggregatedStats.avgViewsPerVisitor.toFixed(1) },
        get allSelected() {
            return this.selectedWebsites.length === Object.keys(this.websites).length
        },
        get allSitesClass() {
            return this.allSelected
                ? 'bg-blue-600 text-white'
                : 'bg-gray-200 text-gray-700'
        },
        get rangeClass() {
            return this.$el.dataset.value === this.range
                ? 'bg-blue-50 text-blue-700 border-blue-300'
                : 'bg-white text-gray-700 border-gray-300'
        },
        chooseRange(event) { this.changeRange(event.currentTarget.dataset.value) },
        get noSites() { return this.websiteStats.length === 0 },
        get noPages() { return this.combinedTopPages.length === 0 },
        get noSources() { return this.combinedTrafficSources.length === 0 },
        get noCountries() { return this.combinedCountries.length === 0 },

        /** Each row precomputed, so no template expression walks the arrays. */
        get siteRows() {
            const total = this.aggregatedStats.totalPageviews
            return this.websiteStats.map((site) => ({
                raw: site,
                id: site.id,
                width: total ? (site.pageviews / total * 100).toFixed(1) : '0',
                name: site.name,
                domain: site.domain,
                pageviews: this.formatNumber(site.pageviews),
                visitors: this.formatNumber(site.visitors),
                ratio: site.visitors
                    ? (site.pageviews / site.visitors).toFixed(1)
                    : '0.0',
            }))
        },
        get topSiteRows() {
            const total = this.aggregatedStats.totalPageviews
            return this.topPerformingSites.map((site, index) => ({
                id: site.id,
                rank: index + 1,
                name: site.name,
                pageviews: `${this.formatNumber(site.pageviews)} pageviews`,
                share: total ? `${(site.pageviews / total * 100).toFixed(1)}%` : '0.0%',
            }))
        },
        get pageRows() {
            const total = this.aggregatedStats.totalPageviews
            return this.combinedTopPages.map((page) => ({
                path: page.path,
                siteName: page.siteName,
                views: this.formatNumber(page.views),
                share: total ? `${(page.views / total * 100).toFixed(1)}%` : '0.0%',
            }))
        },
        get sourceRows() {
            const total = this.aggregatedStats.totalPageviews
            return this.combinedTrafficSources.map((source) => ({
                icon: this.getReferrerIcon(source.referrer),
                referrer: source.referrer,
                views: this.formatNumber(source.views),
                share: total
                    ? `(${(source.views / total * 100).toFixed(0)}%)`
                    : '(0%)',
            }))
        },
        get countryRows() {
            const total = this.aggregatedStats.totalPageviews
            return this.combinedCountries.map((country) => ({
                flag: this.getCountryFlag(country.country),
                country: country.country,
                share: total
                    ? `${(country.views / total * 100).toFixed(0)}%`
                    : '0%',
            }))
        },

        selectedWebsites: [],
        websites: {},
        allIds: [],
        loading: true,
        websiteStats: [],
        aggregatedStats: {
            totalPageviews: 0,
            uniqueVisitors: 0,
            avgViewsPerVisitor: 0
        },
        combinedTimeseries: [],
        combinedTopPages: [],
        combinedTrafficSources: [],
        combinedCountries: [],
        topPerformingSites: [],

        init() {
            const ids = document.getElementById('cross-domain-ids')
            const sites = document.getElementById('cross-domain-websites')
            this.allIds = ids ? JSON.parse(ids.textContent) : []
            this.selectedWebsites = [...this.allIds]
            this.websites = sites ? JSON.parse(sites.textContent) : {}
            this.loadAllData();
        },

        async loadAllData() {
            this.loading = true;
            try {
                const promises = this.selectedWebsites.map(id => this.fetchWebsiteStats(id));
                const results = await Promise.all(promises);

                this.websiteStats = results.filter(r => r !== null);
                this.aggregateStats();
                this.aggregateTimeseries();
                this.aggregateTopPages();
                this.aggregateTrafficSources();
                this.aggregateCountries();
                this.calculateTopPerformingSites();
                this.renderCombinedChart();
            } catch (error) {
                console.error('Error loading cross-domain data:', error);
            } finally {
                this.loading = false;
            }
        },

        async fetchWebsiteStats(websiteId) {
            try {
                // Calculate date range based on selected range
                const endDate = new Date();
                const startDate = new Date();

                if (this.range === '7d') {
                    startDate.setDate(endDate.getDate() - 7);
                } else if (this.range === '30d') {
                    startDate.setDate(endDate.getDate() - 30);
                } else if (this.range === '90d') {
                    startDate.setDate(endDate.getDate() - 90);
                }

                const startDateStr = startDate.toISOString();
                const endDateStr = endDate.toISOString();

                const response = await fetch(
                    `/api/v1/analytics/stats/${websiteId}?start_date=${startDateStr}&end_date=${endDateStr}`,
                    {
                        credentials: 'include'
                    }
                );

                if (!response.ok) {
                    console.error(`Failed to fetch stats for website ${websiteId}`);
                    return null;
                }

                const data = await response.json();
                return {
                    id: websiteId,
                    name: this.websites[websiteId].name,
                    domain: this.websites[websiteId].domain,
                    pageviews: data.total_pageviews || 0,
                    visitors: data.unique_visitors || 0,
                    topPages: data.top_pages || [],
                    referrers: data.top_referrers || [],
                    countries: data.top_countries || [],
                    timeseries: data.timeseries || []
                };
            } catch (error) {
                console.error(`Error fetching stats for website ${websiteId}:`, error);
                return null;
            }
        },

        aggregateStats() {
            this.aggregatedStats.totalPageviews = this.websiteStats.reduce((sum, site) => sum + site.pageviews, 0);
            this.aggregatedStats.uniqueVisitors = this.websiteStats.reduce((sum, site) => sum + site.visitors, 0);
            this.aggregatedStats.avgViewsPerVisitor = this.aggregatedStats.uniqueVisitors > 0
                ? this.aggregatedStats.totalPageviews / this.aggregatedStats.uniqueVisitors
                : 0;
        },

        aggregateTimeseries() {
            const timeseriesMap = new Map();

            this.websiteStats.forEach(site => {
                site.timeseries.forEach(point => {
                    const existing = timeseriesMap.get(point.date) || 0;
                    timeseriesMap.set(point.date, existing + point.views);
                });
            });

            this.combinedTimeseries = Array.from(timeseriesMap.entries())
                .map(([date, views]) => ({ date, views }))
                .sort((a, b) => new Date(a.date) - new Date(b.date));
        },

        aggregateTopPages() {
            const pagesMap = new Map();

            this.websiteStats.forEach(site => {
                site.topPages.forEach(page => {
                    const key = `${site.id}|${page.path}`;
                    pagesMap.set(key, {
                        id: site.id,
                        siteName: site.name,
                        path: page.path,
                        views: page.views
                    });
                });
            });

            this.combinedTopPages = Array.from(pagesMap.values())
                .sort((a, b) => b.views - a.views)
                .slice(0, 20);
        },

        aggregateTrafficSources() {
            const sourcesMap = new Map();

            this.websiteStats.forEach(site => {
                site.referrers.forEach(ref => {
                    const existing = sourcesMap.get(ref.referrer) || 0;
                    sourcesMap.set(ref.referrer, existing + ref.views);
                });
            });

            this.combinedTrafficSources = Array.from(sourcesMap.entries())
                .map(([referrer, views]) => ({ referrer, views }))
                .sort((a, b) => b.views - a.views)
                .slice(0, 10);
        },

        aggregateCountries() {
            const countriesMap = new Map();

            this.websiteStats.forEach(site => {
                site.countries.forEach(country => {
                    const existing = countriesMap.get(country.country) || 0;
                    countriesMap.set(country.country, existing + country.views);
                });
            });

            this.combinedCountries = Array.from(countriesMap.entries())
                .map(([country, views]) => ({ country, views }))
                .sort((a, b) => b.views - a.views)
                .slice(0, 10);
        },

        calculateTopPerformingSites() {
            this.topPerformingSites = [...this.websiteStats]
                .sort((a, b) => b.pageviews - a.pageviews)
                .slice(0, 5);
        },

        renderCombinedChart() {
            const ctx = document.getElementById('combined-traffic-chart');
            if (!ctx) return;

            const labels = this.combinedTimeseries.map(d => {
                const date = new Date(d.date);
                return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
            });
            const data = this.combinedTimeseries.map(d => d.views);

            if (window.combinedTrafficChart) {
                window.combinedTrafficChart.destroy();
            }

            window.combinedTrafficChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Combined Pageviews',
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
                            cornerRadius: 8,
                            callbacks: {
                                label: function(context) {
                                    return context.parsed.y.toLocaleString() + ' pageviews';
                                }
                            }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                callback: function(value) {
                                    return window.formatNumber(value);
                                }
                            },
                            grid: { color: 'rgba(0, 0, 0, 0.05)' }
                        },
                        x: { grid: { display: false } }
                    }
                }
            });
        },

        toggleAllWebsites() {
            if (this.selectedWebsites.length === Object.keys(this.websites).length) {
                this.selectedWebsites = [];
            } else {
                this.selectedWebsites = [...this.allIds];
            }
            this.loadAllData();
        },

        toggleWebsite(websiteId) {
            const index = this.selectedWebsites.indexOf(websiteId);
            if (index > -1) {
                this.selectedWebsites.splice(index, 1);
            } else {
                this.selectedWebsites.push(websiteId);
            }
            this.loadAllData();
        },

        changeRange(newRange) {
            this.range = newRange;
            this.loadAllData();
        },

        formatNumber(num) {
            if (num >= 1000000) {
                return (num / 1000000).toFixed(1) + 'M';
            }
            if (num >= 1000) {
                return (num / 1000).toFixed(1) + 'K';
            }
            return num.toString();
        },

        getReferrerIcon(referrer) {
            const lower = referrer.toLowerCase();
            if (lower.includes('google')) return '🔍';
            if (lower.includes('facebook') || lower.includes('fb.com')) return '📘';
            if (lower.includes('twitter') || lower.includes('t.co')) return '🐦';
            if (lower.includes('linkedin')) return '💼';
            if (lower.includes('github')) return '⚙️';
            if (referrer === '(Direct)' || referrer === 'Direct') return '➡️';
            return '🌐';
        },

        getCountryFlag(countryCode) {
            if (!countryCode || countryCode.length !== 2) return '🌍';
            const codePoints = countryCode.toUpperCase().split('').map(char => 127397 + char.charCodeAt(0));
            return String.fromCodePoint(...codePoints);
        }
    };
}

document.addEventListener('alpine:init', () => {
    Alpine.data('crossDomain', crossDomainDashboard)

    /** One row/tile, flattened: the CSP build cannot read row.name. */
    Alpine.data('crossRow', () => ({
        get id() { return this.row.id },
        get rank() { return this.row.rank },
        get name() { return this.row.name },
        get domain() { return this.row.domain },
        get path() { return this.row.path },
        get siteName() { return this.row.siteName },
        get referrer() { return this.row.referrer },
        get country() { return this.row.country },
        get icon() { return this.row.icon },
        get flag() { return this.row.flag },
        get pageviews() { return this.row.pageviews },
        get visitors() { return this.row.visitors },
        get views() { return this.row.views },
        get ratio() { return this.row.ratio },
        get share() { return this.row.share },
        get selected() { return this.row.selected },
        get siteHref() { return `/dashboard/website/${this.row.id}` },
        // An object, not a string. Alpine sets a string style with
        // setAttribute, which style-src 'self' blocks outright, so the bar
        // rendered with no width at all. The object form goes through
        // CSSOM .style.setProperty, which CSP does not gate.
        get barStyle() { return { width: `${this.row.width}%` } },
        get chipClass() {
            return this.row.selected
                ? 'bg-blue-600 text-white'
                : 'bg-gray-200 text-gray-700'
        },
        toggle() { this.toggleWebsite(this.row.id) },
    }))
})
