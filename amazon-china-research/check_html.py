"""Check if the session HTML report's embedded JSON is valid."""
import re
import json
import sys

html_path = sys.argv[1] if len(sys.argv) > 1 else "/app/output/jobs/14/session_20260213_150415.html"
html = open(html_path, encoding="utf-8").read()

m = re.search(r"var DATA = JSON\.parse\('(.+?)'\);", html)
if not m:
    print("DATA variable not found in HTML")
    sys.exit(1)

raw = m.group(1)
print(f"Raw JSON length: {len(raw)} chars")

# Check for unescaped single quotes
problems = []
i = 0
while i < len(raw):
    if raw[i] == "\\":
        i += 2
        continue
    if raw[i] == "'":
        problems.append(i)
    i += 1

if problems:
    print(f"Found {len(problems)} unescaped single quotes!")
    for pos in problems[:5]:
        start = max(0, pos - 40)
        end = min(len(raw), pos + 40)
        print(f"  Position {pos}: ...{raw[start:end]}...")
else:
    print("No unescaped single quotes")

# Try to unescape and parse
try:
    unescaped = raw.replace("\\'", "'")
    data = json.loads(unescaped)
    kws = data.get("keywords", [])
    print(f"JSON parsed OK: {len(kws)} keywords")
    for kw in kws:
        prods = kw.get("products", [])
        print(f"  {kw['keyword']}: {len(prods)} products")
except json.JSONDecodeError as e:
    print(f"JSON PARSE ERROR: {e}")
    # Show context around the error
    pos = e.pos if hasattr(e, 'pos') else 0
    start = max(0, pos - 60)
    end = min(len(unescaped), pos + 60)
    print(f"  Context: ...{unescaped[start:end]}...")
