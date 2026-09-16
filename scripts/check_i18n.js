// Simple approach: use regex to extract all key paths from i18n.js
const fs = require('fs');
const path = require('path');

const i18nPath = path.join(__dirname, '..', 'web', 'src', 'i18n.js');
const content = fs.readFileSync(i18nPath, 'utf-8');

// Strategy: Use a line-by-line approach to build key paths based on indentation
function extractKeysByIndentation(text) {
  const keys = new Set();
  const lines = text.split('\n');
  const stack = []; // {indent, key}
  
  for (const line of lines) {
    // Match patterns like "key: 'value'," or "key: {" or "key: number,"
    const m = line.match(/^(\s*)(\w+)\s*:\s*(.*)$/);
    if (!m) continue;
    
    const indent = m[1].length;
    const key = m[2];
    const value = m[3].trim();
    
    // Pop stack until we find the parent (indent < current indent)
    while (stack.length > 0 && stack[stack.length - 1].indent >= indent) {
      stack.pop();
    }
    
    const fullKey = stack.length > 0 
      ? stack.map(s => s.key).join('.') + '.' + key 
      : key;
    
    if (value.startsWith('{')) {
      // Nested object - push to stack
      stack.push({ indent, key });
    } else {
      // Leaf value (string, number, boolean, template literal)
      keys.add(fullKey);
    }
  }
  
  return keys;
}

const allKeys = extractKeysByIndentation(content);

// Now filter to get zh and en keys
const zhKeys = new Set([...allKeys].filter(k => k.startsWith('zh.')));
const enKeys = new Set([...allKeys].filter(k => k.startsWith('en.')));

// Strip the 'zh.' and 'en.' prefix
const zhKeysStripped = new Set([...zhKeys].map(k => k.replace(/^zh\./, '')));
const enKeysStripped = new Set([...enKeys].map(k => k.replace(/^en\./, '')));
const allDefinedKeys = new Set([...zhKeysStripped, ...enKeysStripped]);

// Extract all t('key') calls from Vue/JS files
const usedKeys = new Set();
const srcDir = path.join(__dirname, '..', 'web', 'src');
function walkDir(dir) {
  const files = fs.readdirSync(dir);
  for (const f of files) {
    const fullPath = path.join(dir, f);
    const stat = fs.statSync(fullPath);
    if (stat.isDirectory()) {
      walkDir(fullPath);
    } else if (f.endsWith('.vue') || f.endsWith('.js')) {
      if (f === 'i18n.js') continue;
      const c = fs.readFileSync(fullPath, 'utf-8');
      const matches = c.matchAll(/t\(\s*['"]([a-zA-Z][a-zA-Z0-9_]*\.[a-zA-Z][a-zA-Z0-9_.]*)['"]\s*[,)]/g);
      for (const m of matches) {
        usedKeys.add(m[1]);
      }
    }
  }
}
walkDir(srcDir);

// Find missing keys
const missing = [...usedKeys].filter(k => !allDefinedKeys.has(k)).sort();
if (missing.length > 0) {
  console.log(`=== ${missing.length} MISSING i18n keys (used but not defined) ===`);
  for (const k of missing) {
    const inZh = zhKeysStripped.has(k);
    const inEn = enKeysStripped.has(k);
    console.log(`  ${k}  [zh: ${inZh ? 'YES' : 'NO'}, en: ${inEn ? 'YES' : 'NO'}]`);
  }
} else {
  console.log('All used i18n keys are defined!');
}

// Check zh-en symmetry
const zhOnly = [...zhKeysStripped].filter(k => !enKeysStripped.has(k)).sort();
const enOnly = [...enKeysStripped].filter(k => !zhKeysStripped.has(k)).sort();

if (zhOnly.length > 0) {
  console.log(`\n=== ${zhOnly.length} keys in zh but MISSING in en ===`);
  for (const k of zhOnly) {
    console.log(`  ${k}`);
  }
}
if (enOnly.length > 0) {
  console.log(`\n=== ${enOnly.length} keys in en but MISSING in zh ===`);
  for (const k of enOnly) {
    console.log(`  ${k}`);
  }
}

console.log(`\n=== Summary ===`);
console.log(`Used keys: ${usedKeys.size}`);
console.log(`Defined zh keys: ${zhKeysStripped.size}`);
console.log(`Defined en keys: ${enKeysStripped.size}`);
console.log(`Missing (used but not defined): ${missing.length}`);
console.log(`zh-only (missing in en): ${zhOnly.length}`);
console.log(`en-only (missing in zh): ${enOnly.length}`);
