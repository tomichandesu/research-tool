"""Find the control character at JSON position 16110."""
import re
import sys

html_path = sys.argv[1] if len(sys.argv) > 1 else "/app/output/jobs/14/session_20260213_150415.html"
html = open(html_path, encoding="utf-8").read()

m = re.search(r"var DATA = JSON\.parse\('(.+?)'\);", html)
raw = m.group(1)

# In JS, \' becomes ' — simulate JS string interpretation
# But actually, JSON.parse sees the string AFTER JS processes it
# So we need to think about what JSON.parse receives

# The JS string literal is: '...'
# JS will process \' -> '  and \\ -> \
# Then JSON.parse receives the result

# Simulate JS single-quoted string processing
js_result = []
i = 0
while i < len(raw):
    if raw[i] == '\\' and i + 1 < len(raw):
        nxt = raw[i + 1]
        if nxt == "'":
            js_result.append("'")
        elif nxt == '\\':
            js_result.append('\\')
        elif nxt == 'n':
            js_result.append('\n')
        elif nxt == 't':
            js_result.append('\t')
        elif nxt == 'r':
            js_result.append('\r')
        elif nxt == '"':
            js_result.append('"')
        else:
            # JS passes through unknown escapes: \x -> x (in non-strict)
            # Actually in a JS string, \x followed by non-hex is an error in strict
            # But typically \/ -> / etc
            js_result.append(raw[i])
            js_result.append(nxt)
        i += 2
    else:
        js_result.append(raw[i])
        i += 1

json_str = ''.join(js_result)
print(f"JSON string length after JS unescape: {len(json_str)}")

# Check around position 16110
pos = 16110
start = max(0, pos - 50)
end = min(len(json_str), pos + 50)
context = json_str[start:end]
print(f"\nContext around position {pos}:")
print(repr(context))

# Find ALL control characters in the JSON string
print("\nAll control characters:")
for i, ch in enumerate(json_str):
    code = ord(ch)
    if code < 32 and ch not in ('\n', '\r', '\t'):
        ctx_start = max(0, i - 30)
        ctx_end = min(len(json_str), i + 30)
        print(f"  Position {i}: U+{code:04X} ({repr(ch)})")
        print(f"  Context: {repr(json_str[ctx_start:ctx_end])}")

# Also check the RAW string for chars that would be control chars after JS processing
print("\nControl chars in raw string (before JS unescape):")
for i, ch in enumerate(raw):
    code = ord(ch)
    if code < 32 and ch not in ('\n', '\r', '\t'):
        ctx_start = max(0, i - 30)
        ctx_end = min(len(raw), i + 30)
        print(f"  Position {i}: U+{code:04X} ({repr(ch)})")
        print(f"  Context: {repr(raw[ctx_start:ctx_end])}")
