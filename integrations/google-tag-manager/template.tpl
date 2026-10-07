___TERMS_OF_SERVICE___

By creating or modifying this file you agree to Google Tag Manager's Community
Template Gallery Developer Terms of Service available at
https://developers.google.com/tag-manager/gallery-tos (or such other URL as
Google may provide), as modified from time to time.


___INFO___

{
  "type": "TAG",
  "id": "argus_metrics",
  "version": 1,
  "securityGroups": [],
  "displayName": "Argusmetrics",
  "brand": {
    "id": "argus_metrics",
    "displayName": "Argusmetrics",
    "thumbnail": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
  },
  "description": "Privacy-first, GDPR-compliant analytics. Lightweight tracking script with no cookies.",
  "containerContexts": [
    "WEB"
  ]
}


___TEMPLATE_PARAMETERS___

[
  {
    "type": "TEXT",
    "name": "trackingCode",
    "displayName": "Tracking Code",
    "simpleValueType": true,
    "help": "The 8-character tracking code from your website's settings in Argusmetrics.",
    "valueValidators": [
      {
        "type": "NON_EMPTY"
      },
      {
        "type": "STRING_LENGTH",
        "args": [8, 8]
      }
    ]
  },
  {
    "type": "TEXT",
    "name": "instanceUrl",
    "displayName": "Instance URL",
    "simpleValueType": true,
    "help": "The address of your own Argusmetrics server, e.g. https://analytics.your-domain.com. The tracking script and the endpoint both come from there. There is no hosted service. Also allow this address under Permissions, Injects scripts.",
    "valueValidators": [
      {
        "type": "NON_EMPTY"
      },
      {
        "type": "REGEX",
        "args": ["^https://[^/\\s]+/?$"],
        "errorMessage": "An https:// address with no path, e.g. https://analytics.your-domain.com"
      }
    ]
  },
  {
    "type": "TEXT",
    "name": "excludeOutbound",
    "displayName": "Exclude Outbound Domains (Optional)",
    "simpleValueType": true,
    "help": "Comma-separated domains whose links are not counted as outbound, e.g. shop.your-domain.com, blog.your-domain.com",
    "valueValidators": []
  }
]


___SANDBOXED_JS_FOR_WEB_TEMPLATE___

const injectScript = require('injectScript');
const queryPermission = require('queryPermission');
const setInWindow = require('setInWindow');
const log = require('logToConsole');

// One setting gives both, as in the WordPress plugin: the tracking script and
// the endpoint live on the operator's own instance. No default host, because
// a default pointing at a domain nobody owns sends visitor data into the void,
// or to whoever registers it next.
let base = data.instanceUrl || '';
while (base.length > 0 && base.charAt(base.length - 1) === '/') {
  base = base.substring(0, base.length - 1);
}
const scriptUrl = base + '/static/tracker.min.js';

// The tracker reads its settings from data attributes on its own script tag.
// A script injected from this sandbox cannot carry any, so the settings go in
// window.argusConfig, which the tracker reads when its tag has none (#109).
// Overwritten on every fire, so a changed setting takes effect.
setInWindow('argusConfig', {
  trackingCode: data.trackingCode,
  apiEndpoint: base + '/api/v1/analytics/track',
  excludeOutbound: data.excludeOutbound || ''
}, true);

if (queryPermission('inject_script', scriptUrl)) {
  injectScript(scriptUrl, data.gtmOnSuccess, data.gtmOnFailure, scriptUrl);
} else {
  log('Argusmetrics: not allowed to load ' + scriptUrl + '. Add it under Permissions, Injects scripts.');
  data.gtmOnFailure();
}


___WEB_PERMISSIONS___

[
  {
    "instance": {
      "key": {
        "publicId": "inject_script",
        "versionId": "1"
      },
      "param": [
        {
          "key": "urls",
          "value": {
            "type": 2,
            "listItem": [
              {
                "type": 1,
                "string": "https://analytics.example.com/static/tracker.min.js"
              }
            ]
          }
        }
      ]
    },
    "clientAnnotations": {
      "isEditedByUser": true
    },
    "isRequired": true
  },
  {
    "instance": {
      "key": {
        "publicId": "access_globals",
        "versionId": "1"
      },
      "param": [
        {
          "key": "keys",
          "value": {
            "type": 2,
            "listItem": [
              {
                "type": 3,
                "mapKey": [
                  {
                    "type": 1,
                    "string": "key"
                  },
                  {
                    "type": 1,
                    "string": "read"
                  },
                  {
                    "type": 1,
                    "string": "write"
                  },
                  {
                    "type": 1,
                    "string": "execute"
                  }
                ],
                "mapValue": [
                  {
                    "type": 1,
                    "string": "argusConfig"
                  },
                  {
                    "type": 8,
                    "boolean": true
                  },
                  {
                    "type": 8,
                    "boolean": true
                  },
                  {
                    "type": 8,
                    "boolean": false
                  }
                ]
              }
            ]
          }
        }
      ]
    },
    "clientAnnotations": {
      "isEditedByUser": true
    },
    "isRequired": true
  },
  {
    "instance": {
      "key": {
        "publicId": "logging",
        "versionId": "1"
      },
      "param": [
        {
          "key": "environments",
          "value": {
            "type": 1,
            "string": "debug"
          }
        }
      ]
    },
    "isRequired": true
  }
]


___TESTS___

scenarios:
- name: Loads the tracker from the instance and passes its settings
  code: |-
    const mockData = {
      trackingCode: 'k3x9q2ab',
      instanceUrl: 'https://analytics.example.com/',
      excludeOutbound: 'shop.example.com'
    };
    let injected;
    let config;
    mock('injectScript', (url, onSuccess) => { injected = url; onSuccess(); });
    mock('setInWindow', (key, value) => { if (key === 'argusConfig') config = value; });
    runCode(mockData);
    assertThat(injected).isEqualTo('https://analytics.example.com/static/tracker.min.js');
    assertThat(config.trackingCode).isEqualTo('k3x9q2ab');
    assertThat(config.apiEndpoint).isEqualTo('https://analytics.example.com/api/v1/analytics/track');
    assertThat(config.excludeOutbound).isEqualTo('shop.example.com');
    assertApi('gtmOnSuccess').wasCalled();


___NOTES___

Created on 2025-10-31. Rewritten 2026-10-07 (#109): instance URL, window.argusConfig.
