#!/usr/bin/env node
/**
 * Fail the build if the tracker references a name that does not exist.
 *
 * This is here because of one line that shipped to every customer:
 *
 *     setTimeout(checkScrollMilestones, 100);
 *
 * recordScrollDepth used to be called that, back when it fired an event at
 * 25, 50, 75 and 100 per cent. The rename missed this caller. JavaScript
 * resolves a free variable only when it is reached, so nothing complained at
 * build time, nothing complained at parse time, and terser was right not to
 * touch a name it could not resolve. The first thing that noticed was a
 * customer's own end-to-end suite asserting zero console errors, months later.
 *
 * CI already checked that the minified file matches the source. That proves
 * the build is reproducible; it says nothing about whether either file runs.
 * A perfectly synced build of broken code passed.
 *
 * The check is deliberately coarse: every name declared anywhere in the file
 * against every name referenced anywhere in it. That cannot see a reference
 * that escapes its scope, which is a different bug, but it catches a name
 * that exists nowhere with no false positives from scoping. The tracker is
 * one IIFE, so there is nothing finer to be gained.
 *
 *     node check-globals.js dist/tracker.min.js
 */
const fs = require('fs');
const acorn = require('acorn');

/** What a browser gives you. Anything else must be declared in the file. */
const BROWSER_GLOBALS = new Set([
  'window', 'document', 'navigator', 'location', 'history', 'screen',
  'console', 'fetch', 'setTimeout', 'clearTimeout', 'setInterval',
  'clearInterval', 'requestAnimationFrame', 'cancelAnimationFrame',
  'URL', 'URLSearchParams', 'Blob', 'FormData', 'Headers', 'Request',
  'Response', 'MutationObserver', 'IntersectionObserver', 'AbortController',
  'Object', 'Array', 'String', 'Number', 'Boolean', 'Math', 'JSON', 'Date',
  'RegExp', 'Error', 'TypeError', 'Promise', 'Map', 'Set', 'WeakMap',
  'WeakSet', 'Symbol', 'BigInt', 'Infinity', 'NaN', 'undefined',
  'parseInt', 'parseFloat', 'isNaN', 'isFinite', 'encodeURIComponent',
  'decodeURIComponent', 'encodeURI', 'decodeURI', 'globalThis',
  'localStorage', 'sessionStorage', 'performance', 'CustomEvent', 'Event',
  // Not a global: an implicit binding the language puts in every
  // non-arrow function, which no declaration in the file will ever match.
  'arguments',
]);

/** Every node type that binds a name rather than reading one. */
function declaredNames(ast) {
  const names = new Set();

  const fromPattern = (node) => {
    if (!node || typeof node !== 'object') return;
    switch (node.type) {
      case 'Identifier':
        names.add(node.name);
        break;
      case 'ObjectPattern':
        node.properties.forEach((p) =>
          fromPattern(p.type === 'RestElement' ? p.argument : p.value));
        break;
      case 'ArrayPattern':
        node.elements.forEach(fromPattern);
        break;
      case 'AssignmentPattern':
        fromPattern(node.left);
        break;
      case 'RestElement':
        fromPattern(node.argument);
        break;
      default:
        break;
    }
  };

  walk(ast, (node) => {
    switch (node.type) {
      case 'FunctionDeclaration':
      case 'FunctionExpression':
      case 'ArrowFunctionExpression':
        if (node.id) names.add(node.id.name);
        node.params.forEach(fromPattern);
        break;
      case 'ClassDeclaration':
      case 'ClassExpression':
        if (node.id) names.add(node.id.name);
        break;
      case 'VariableDeclarator':
        fromPattern(node.id);
        break;
      case 'CatchClause':
        fromPattern(node.param);
        break;
      default:
        break;
    }
  });

  return names;
}

/** Every identifier read as a value, which is the set that must resolve. */
function referencedNames(ast) {
  const names = new Set();

  walk(ast, (node, parent, key) => {
    if (node.type !== 'Identifier') return;

    // A property name is not a reference: obj.foo, {foo: 1}, class { foo() {} }
    if (parent && !parent.computed) {
      if (parent.type === 'MemberExpression' && key === 'property') return;
      if (parent.type === 'Property' && key === 'key') return;
      if (parent.type === 'MethodDefinition' && key === 'key') return;
    }
    // Nor is a label, nor the name being bound by a declaration.
    if (parent && (parent.type === 'LabeledStatement'
                   || parent.type === 'BreakStatement'
                   || parent.type === 'ContinueStatement')) return;
    if (parent && key === 'id') return;
    if (parent && parent.type === 'VariableDeclarator' && key === 'id') return;

    names.add(node.name);
  });

  return names;
}

function walk(node, visit, parent = null, key = null) {
  if (!node || typeof node !== 'object') return;
  if (Array.isArray(node)) {
    node.forEach((child) => walk(child, visit, parent, key));
    return;
  }
  if (typeof node.type !== 'string') return;

  visit(node, parent, key);

  for (const [childKey, value] of Object.entries(node)) {
    if (childKey === 'type' || childKey === 'start' || childKey === 'end') continue;
    walk(value, visit, node, childKey);
  }
}

function main() {
  const file = process.argv[2];
  if (!file) {
    console.error('usage: node check-globals.js <file.js>');
    process.exit(2);
  }

  const source = fs.readFileSync(file, 'utf8');
  const ast = acorn.parse(source, { ecmaVersion: 2022, sourceType: 'script' });

  const declared = declaredNames(ast);
  const referenced = referencedNames(ast);

  const unresolved = [...referenced]
    .filter((name) => !declared.has(name) && !BROWSER_GLOBALS.has(name))
    .sort();

  // The check has to be able to see something, or it is a check that always
  // passes. A tracker with no references at all is a broken build too.
  if (referenced.size < 20) {
    console.error(
      `${file}: only ${referenced.size} identifiers found. The parse is `
      + 'probably wrong rather than the file being empty.'
    );
    process.exit(2);
  }

  if (unresolved.length) {
    console.error(`${file}: references ${unresolved.length} name(s) that are `
      + 'never defined and are not browser globals:\n  '
      + unresolved.join('\n  ')
      + '\n\nEach one throws a ReferenceError the moment that line runs, in '
      + "every visitor's browser. If one of these is a legitimate global, add "
      + 'it to BROWSER_GLOBALS in this file.');
    process.exit(1);
  }

  console.log(
    `${file}: ${referenced.size} identifiers, all resolved `
    + `(${declared.size} declared, ${BROWSER_GLOBALS.size} globals allowed)`
  );
}

main();
