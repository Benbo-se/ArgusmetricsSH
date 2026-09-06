#!/usr/bin/env node
/**
 * Stamp the marketing site's stylesheets with a hash of their contents.
 *
 * The dashboard gets this from a Jinja helper at render time. The marketing
 * site is static HTML with nothing rendering it, so the stamping happens here,
 * as part of the build that produces the file being stamped. Doing it by hand
 * would mean remembering, and the number on the home page had already gone
 * stale by a hundred and thirty tests.
 *
 * Rewrites, in place:
 *
 *     href="/static/css/site.css"           → href="/static/css/site.css?v=3f9a1c02"
 *     href="/static/css/site.css?v=OLD"     → href="/static/css/site.css?v=3f9a1c02"
 *
 * tracker.min.js is never touched. It is embedded in other people's pages at
 * a URL we told them to paste, and it keeps the short cache that makes it
 * fixable. nginx has the same exception, so the two agree.
 *
 *     node scripts/version-site-assets.js
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const ROOT = path.resolve(__dirname, '..');
const SITE = path.join(ROOT, 'site');

/** Stylesheets and scripts the site serves and we rebuild. */
const VERSIONED = ['/static/css/site.css', '/static/css/tailwind.min.css'];

/** Never versioned: customers paste this URL verbatim. */
const NEVER = ['/static/tracker.min.js'];

function fingerprint(urlPath) {
    const file = path.join(SITE, urlPath.replace(/^\//, ''));
    if (!fs.existsSync(file)) return null;
    return crypto.createHash('sha256')
        .update(fs.readFileSync(file))
        .digest('hex')
        .slice(0, 8);
}

function htmlFiles(dir) {
    return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) return htmlFiles(full);
        return entry.name.endsWith('.html') ? [full] : [];
    });
}

function main() {
    const stamps = new Map();
    for (const asset of VERSIONED) {
        const hash = fingerprint(asset);
        if (hash) stamps.set(asset, hash);
        else console.warn(`skipping ${asset}: not built yet`);
    }

    if (stamps.size === 0) {
        console.error('No versionable assets found. Has the CSS been built?');
        process.exit(1);
    }

    let touched = 0;
    let replacements = 0;

    for (const file of htmlFiles(SITE)) {
        const before = fs.readFileSync(file, 'utf8');
        let after = before;

        for (const [asset, hash] of stamps) {
            // Matches the bare path and any version already on it, so running
            // this twice is the same as running it once.
            const pattern = new RegExp(
                asset.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(\\?v=[0-9a-f]+)?',
                'g'
            );
            after = after.replace(pattern, match => {
                replacements += 1;
                return `${asset}?v=${hash}`;
            });
        }

        if (after !== before) {
            fs.writeFileSync(file, after);
            touched += 1;
        }
    }

    for (const asset of NEVER) {
        const stamped = htmlFiles(SITE).filter(f =>
            new RegExp(asset.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\?v=')
                .test(fs.readFileSync(f, 'utf8')));
        if (stamped.length) {
            console.error(
                `${asset} was given a version in ${stamped.length} file(s). It `
                + 'must stay at the URL customers pasted.'
            );
            process.exit(1);
        }
    }

    console.log(
        `Stamped ${replacements} reference(s) across ${touched} file(s): `
        + [...stamps].map(([a, h]) => `${path.basename(a)}=${h}`).join(', ')
    );
}

main();
