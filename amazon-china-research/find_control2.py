"""Map JS error position back to raw HTML bytes."""
import re
import sys

html_path = sys.argv[1] if len(sys.argv) > 1 else "/app/output/jobs/14/session_20260213_150415.html"
html = open(html_path, encoding="utf-8").read()

m = re.search(r"var DATA = JSON\.parse\('(.+?)'\);", html)
raw = m.group(1)

# Simulate JS single-quoted string unescaping, tracking positions
js_chars = []  # (char, raw_position)
i = 0
while i < len(raw):
    if raw[i] == '\\' and i + 1 < len(raw):
        nxt = raw[i + 1]
        if nxt == 'n':
            js_chars.append(('\n', i))
        elif nxt == 't':
            js_chars.append(('\t', i))
        elif nxt == 'r':
            js_chars.append(('\r', i))
        elif nxt == '\\':
            js_chars.append(('\\', i))
        elif nxt == "'":
            js_chars.append(("'", i))
        elif nxt == '"':
            js_chars.append(('"', i))
        else:
            js_chars.append((raw[i], i))
            js_chars.append((nxt, i + 1))
        i += 2
    else:
        js_chars.append((raw[i], i))
        i += 1

# Find position 16110 in JS-processed string
target_pos = 16110
if target_pos < len(js_chars):
    ch, raw_pos = js_chars[target_pos]
    print(f"JS position {target_pos}: char={repr(ch)} (U+{ord(ch):04X}), raw position={raw_pos}")

    # Show raw bytes around that position
    start = max(0, raw_pos - 60)
    end = min(len(raw), raw_pos + 60)
    print(f"\nRaw HTML around position {raw_pos}:")
    print(repr(raw[start:end]))

    # Show the actual bytes
    print(f"\nBytes at raw position {raw_pos}-{raw_pos+5}:")
    for j in range(raw_pos, min(raw_pos + 6, len(raw))):
        print(f"  [{j}] {repr(raw[j])} U+{ord(raw[j]):04X}")

# Find ALL positions in JS string that become newlines
print(f"\nAll newline positions in JS-processed string:")
for idx, (ch, raw_pos) in enumerate(js_chars):
    if ch == '\n':
        start = max(0, raw_pos - 30)
        end = min(len(raw), raw_pos + 30)
        print(f"  JS pos {idx}, raw pos {raw_pos}: {repr(raw[start:end])}")
