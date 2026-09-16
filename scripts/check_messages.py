"""Check messages.py for zh-en key symmetry."""
import re

with open('protoforge/observability/messages.py', encoding='utf-8') as f:
    content = f.read()

# Extract MESSAGES_ZH and MESSAGES_EN blocks
zh_match = re.search(r'MESSAGES_ZH\s*=\s*\{(.*?)\}', content, re.DOTALL)
en_match = re.search(r'MESSAGES_EN\s*=\s*\{(.*?)\}', content, re.DOTALL)

if not zh_match or not en_match:
    print("Could not find MESSAGES_ZH or MESSAGES_EN")
    exit(1)

# Extract keys
zh_keys = set(re.findall(r"^\s*'([^']+)'\s*:", zh_match.group(1), re.MULTILINE))
en_keys = set(re.findall(r"^\s*'([^']+)'\s*:", en_match.group(1), re.MULTILINE))

zh_only = sorted(zh_keys - en_keys)
en_only = sorted(en_keys - zh_keys)

print(f"zh keys: {len(zh_keys)}")
print(f"en keys: {len(en_keys)}")
print(f"zh-only (missing in en): {len(zh_only)}")
print(f"en-only (missing in zh): {len(en_only)}")

if zh_only:
    print("\n=== Keys in zh but MISSING in en ===")
    for k in zh_only:
        print(f"  {k}")

if en_only:
    print("\n=== Keys in en but MISSING in zh ===")
    for k in en_only:
        print(f"  {k}")
