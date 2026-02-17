"""Check for characters that would break JavaScript JSON.parse in a single-quoted string."""
import re
import sys

html_path = sys.argv[1] if len(sys.argv) > 1 else "/app/output/jobs/14/session_20260213_150415.html"
html = open(html_path, encoding="utf-8").read()

m = re.search(r"var DATA = JSON\.parse\('(.+?)'\);", html)
if not m:
    print("DATA not found")
    sys.exit(1)

raw = m.group(1)
print(f"JSON string length: {len(raw)}")

issues = []

for i, ch in enumerate(raw):
    code = ord(ch)
    # Newlines break JS single-line strings
    if ch in ("\n", "\r"):
        issues.append(f"NEWLINE at pos {i}: U+{code:04X}")
    # Control characters
    elif code < 32 and ch != "\t":
        issues.append(f"CONTROL at pos {i}: U+{code:04X}")
    # Unescaped backslash followed by invalid escape
    elif ch == "\\" and i + 1 < len(raw):
        nxt = raw[i + 1]
        if nxt not in "ntrfbu/\\'\"":
            context = raw[max(0, i-20):i+30]
            issues.append(f"BAD_ESCAPE at pos {i}: \\{nxt} context: {repr(context)}")

if issues:
    print(f"Found {len(issues)} issues:")
    for issue in issues[:20]:
        print(f"  {issue}")
else:
    print("No JS-breaking characters found")

# Also verify by trying to simulate what JS JSON.parse would see
# After JS interprets the single-quoted string, the backslash escapes are processed
# \\' -> '  (in JS string literal)
# \\" -> "  (in JS string literal)
# \\\\ -> \\  (in JS string literal)
# \\n -> newline (in JS string literal)
# etc.
# Then JSON.parse sees the result

# Simulate: process JS string escapes first
js_str = raw.replace("\\'", "'")
# Check if this is valid JSON
import json
try:
    data = json.loads(js_str)
    print(f"Simulated JS parse OK: {len(data.get('keywords', []))} keywords")
except json.JSONDecodeError as e:
    print(f"Simulated JS parse FAILED: {e}")
    pos = e.pos if hasattr(e, 'pos') else 0
    start = max(0, pos - 80)
    end = min(len(js_str), pos + 80)
    print(f"  Context around error: {repr(js_str[start:end])}")
