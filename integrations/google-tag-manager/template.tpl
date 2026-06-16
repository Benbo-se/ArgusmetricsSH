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
    "help": "Your 8-character tracking code from Argusmetrics",
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
    "name": "apiEndpoint",
    "displayName": "API Endpoint (Optional)",
    "simpleValueType": true,
    "help": "Custom API endpoint. Leave empty to use default (https://app.argusmetrics.io/api/v1/analytics/track)",
    "defaultValue": "https://app.argusmetrics.io/api/v1/analytics/track",
    "valueValidators": []
  },
  {
    "type": "TEXT",
    "name": "excludeOutbound",
    "displayName": "Exclude Outbound Domains (Optional)",
    "simpleValueType": true,
    "help": "Comma-separated list of domains to exclude from outbound link tracking (e.g., example.com, another.com)",
    "valueValidators": []
  },
  {
    "type": "GROUP",
    "name": "advancedSettings",
    "displayName": "Advanced Settings",
    "groupStyle": "ZIPPY_CLOSED",
    "subParams": [
      {
        "type": "CHECKBOX",
        "name": "trackPageview",
        "checkboxText": "Track initial pageview",
        "simpleValueType": true,
        "defaultValue": true,
        "help": "Automatically track pageview when tag fires"
      },
      {
        "type": "CHECKBOX",
        "name": "enableOutboundTracking",
        "checkboxText": "Enable outbound link tracking",
        "simpleValueType": true,
        "defaultValue": true
      },
      {
        "type": "CHECKBOX",
        "name": "enableScrollTracking",
        "checkboxText": "Enable scroll depth tracking",
        "simpleValueType": true,
        "defaultValue": true
      }
    ]
  }
]


___SANDBOXED_JS_FOR_WEB_TEMPLATE___

const injectScript = require('injectScript');
const queryPermission = require('queryPermission');
const setInWindow = require('setInWindow');
const callInWindow = require('callInWindow');
const createArgumentsQueue = require('createArgumentsQueue');
const log = require('logToConsole');

// Script URL
const scriptUrl = 'https://argusmetrics.io/static/tracker.min.js';

// Get template parameters
const trackingCode = data.trackingCode;
const apiEndpoint = data.apiEndpoint || 'https://app.argusmetrics.io/api/v1/analytics/track';
const excludeOutbound = data.excludeOutbound || '';
const trackPageview = data.trackPageview !== false;
const enableOutbound = data.enableOutboundTracking !== false;
const enableScroll = data.enableScrollTracking !== false;

// Initialize Argus configuration
setInWindow('argusConfig', {
  trackingCode: trackingCode,
  apiEndpoint: apiEndpoint,
  excludeOutbound: excludeOutbound,
  autoTrack: trackPageview,
  enableOutbound: enableOutbound,
  enableScroll: enableScroll
}, false);

// Load the script
if (queryPermission('inject_script', scriptUrl)) {
  injectScript(scriptUrl, data.gtmOnSuccess, data.gtmOnFailure, scriptUrl);
} else {
  log('Script injection permission denied for: ' + scriptUrl);
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
                "string": "https://argusmetrics.io/static/tracker.min.js"
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
              },
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
                    "string": "argus"
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
                    "boolean": true
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

scenarios: []


___NOTES___

Created on 2025-10-31
