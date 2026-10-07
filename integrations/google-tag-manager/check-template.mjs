// Runs the GTM template's sandboxed code with GTM's APIs stubbed, and checks
// the contract with the tracker (#109):
//
//   - the script is injected from <instance>/static/tracker.min.js
//   - window.argusConfig carries the tracking code and the endpoint, because
//     a script injected from the sandbox cannot carry data attributes
//   - a refused injection fails the tag rather than passing silently
//
// The template's own ___TESTS___ scenario says the same inside GTM's editor;
// this is the half CI can run. Usage: node check-template.mjs
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';

const tpl = readFileSync(new URL('./template.tpl', import.meta.url), 'utf8');
const start = tpl.indexOf('___SANDBOXED_JS_FOR_WEB_TEMPLATE___') + '___SANDBOXED_JS_FOR_WEB_TEMPLATE___'.length;
const code = tpl.slice(start, tpl.indexOf('___WEB_PERMISSIONS___'));

function run(data, { allowed = true } = {}) {
  const calls = { injected: null, globals: {}, success: 0, failure: 0, logs: [] };
  const apis = {
    injectScript: (url, onSuccess) => { calls.injected = url; onSuccess(); },
    queryPermission: () => allowed,
    setInWindow: (key, value) => { calls.globals[key] = value; },
    logToConsole: (msg) => calls.logs.push(msg),
  };
  const fullData = {
    ...data,
    gtmOnSuccess: () => { calls.success++; },
    gtmOnFailure: () => { calls.failure++; },
  };
  new Function('require', 'data', code)((name) => {
    assert.ok(name in apis, `the template requires ${name}, which this check does not stub`);
    return apis[name];
  }, fullData);
  return calls;
}

// The normal case, with the trailing slash people paste.
let r = run({ trackingCode: 'k3x9q2ab', instanceUrl: 'https://analytics.example.com/', excludeOutbound: 'shop.example.com' });
assert.equal(r.injected, 'https://analytics.example.com/static/tracker.min.js');
assert.deepEqual(r.globals.argusConfig, {
  trackingCode: 'k3x9q2ab',
  apiEndpoint: 'https://analytics.example.com/api/v1/analytics/track',
  excludeOutbound: 'shop.example.com',
});
assert.equal(r.success, 1);
assert.equal(r.failure, 0);

// Without a slash, and without the optional setting.
r = run({ trackingCode: 'k3x9q2ab', instanceUrl: 'https://analytics.example.com' });
assert.equal(r.injected, 'https://analytics.example.com/static/tracker.min.js');
assert.equal(r.globals.argusConfig.excludeOutbound, '');

// The instance not allowed under Permissions: the tag fails, and says why.
r = run({ trackingCode: 'k3x9q2ab', instanceUrl: 'https://analytics.example.com' }, { allowed: false });
assert.equal(r.injected, null);
assert.equal(r.failure, 1);
assert.match(r.logs[0], /Permissions/);

// The keys the tracker reads from window.argusConfig (CONFIG_KEYS in
// tracker.js) are the keys this template writes.
const tracker = readFileSync(new URL('../../frontend/tracking-script/src/tracker.js', import.meta.url), 'utf8');
for (const key of ['trackingCode', 'apiEndpoint', 'excludeOutbound']) {
  assert.ok(tracker.includes(`'${key}'`), `tracker.js does not read argusConfig.${key}`);
}

console.log('GTM template: injects from the instance, configures the tracker, fails when not allowed.');
