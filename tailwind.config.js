/**
 * One Tailwind build for both the dashboard and the marketing site.
 *
 * Before this there was no build at all: a 39KB file generated once in June
 * and copied to both static directories, byte for byte identical. Any class
 * not in that snapshot simply did nothing. No error, no warning, just the
 * wrong layout, which cost six separate debugging sessions.
 *
 * Both template trees are scanned together and the result is written to both
 * places, so a class used anywhere works everywhere. Two builds that could
 * drift apart is the bug this replaces, not a feature worth keeping.
 *
 * Tailwind cannot see a class it never reads as a literal string. Anything
 * assembled at runtime has to be listed in safelist below, with a note saying
 * where it comes from, or it will vanish from the build and take the styling
 * with it.
 */
module.exports = {
  content: [
    './backend/app/templates/**/*.html',
    './backend/app/static/js/**/*.js',
    './site/**/*.html',
    './site/static/js/**/*.js',
  ],

  safelist: [
    // Built from a status or metric name in dashboard.js and in the Alpine
    // expressions inside the templates, so they never appear as literals.
    { pattern: /^(bg|text|border)-(green|red|amber|yellow|blue|indigo|purple|violet|sky|rose|emerald|slate|gray)-(50|100|200|300|400|500|600|700|800|900)$/ },
    // Chart and table column counts chosen at render time.
    { pattern: /^(grid-cols|col-span)-(1|2|3|4|5|6|12)$/ },
    // Toast and badge variants, keyed on a type string.
    { pattern: /^(ring|from|to|via)-(green|red|amber|blue|indigo|purple)-(200|300|400|500|600)$/ },
  ],

  darkMode: 'class',

  theme: {
    extend: {},
  },

  plugins: [],
};
