"""Check for missing i18n keys - only check dotted keys like 'devices.address' that look like real i18n keys."""
import re
import os
import sys

# Extract all t('key') calls from Vue/JS files
used_keys = set()
src_dir = os.path.join(os.path.dirname(__file__), '..', 'web', 'src')
for root, dirs, files in os.walk(src_dir):
    for f in files:
        if f.endswith(('.vue', '.js')) and f != 'i18n.js':
            filepath = os.path.join(root, f)
            with open(filepath, encoding='utf-8') as fh:
                content = fh.read()
            # Match t('some.key') patterns - only dotted keys with letters
            matches = re.findall(r"t\(\s*['\"]([a-zA-Z][a-zA-Z0-9_]*\.[a-zA-Z][a-zA-Z0-9_.]*)['\"]\s*[,)]", content)
            for m in matches:
                used_keys.add(m)

# Load i18n.js and parse the nested structure to get all valid key paths
i18n_path = os.path.join(src_dir, 'i18n.js')
with open(i18n_path, encoding='utf-8') as fh:
    i18n_content = fh.read()

def extract_keys_from_obj(content, prefix=''):
    """Extract all dotted key paths from a JS object literal."""
    keys = set()
    i = 0
    while i < len(content):
        m = re.search(r"^\s*(\w+)\s*:", content[i:], re.MULTILINE)
        if not m:
            break
        key_name = m.group(1)
        value_start = i + m.end()
        j = value_start
        while j < len(content) and content[j] in ' \t':
            j += 1
        if j >= len(content):
            break
        full_key = f"{prefix}.{key_name}" if prefix else key_name
        if content[j] == '{':
            depth = 1
            k = j + 1
            while k < len(content) and depth > 0:
                if content[k] == '{':
                    depth += 1
                elif content[k] == '}':
                    depth -= 1
                k += 1
            nested_content = content[j+1:k-1]
            nested_keys = extract_keys_from_obj(nested_content, full_key)
            keys.update(nested_keys)
            i = k
        elif content[j] in "'\"":
            quote = content[j]
            k = j + 1
            while k < len(content) and content[k] != quote:
                if content[k] == '\\':
                    k += 1
                k += 1
            keys.add(full_key)
            i = k + 1
        else:
            k = j
            while k < len(content) and content[k] not in ',\n}':
                k += 1
            keys.add(full_key)
            i = k
    return keys

defined_keys = extract_keys_from_obj(i18n_content)

# Find missing keys
missing = sorted(used_keys - defined_keys)
if missing:
    print(f"=== {len(missing)} MISSING i18n keys (used but not defined) ===")
    for k in missing:
        print(f"  {k}")
else:
    print("All used i18n keys are defined!")

print(f"\n=== Summary ===")
print(f"Used dotted keys: {len(used_keys)}")
print(f"Defined keys: {len(defined_keys)}")
print(f"Missing: {len(missing)}")
