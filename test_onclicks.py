import re

with open("templates/index.html", "r", encoding="utf-8") as f:
    html = f.read()

# Find all onclick attributes in HTML
onclicks = re.findall(r'onclick=([\'"])(.*?)\1', html)
print(f"Found {len(onclicks)} onclick handlers in HTML:")
onclick_funcs = []
for _, handler in onclicks:
    clean = handler.split('(')[0].strip()
    if clean and clean not in onclick_funcs:
        onclick_funcs.append(clean)
    print(f"  - {handler}")

# Check that every single onclick function is defined in JS
script_text = re.search(r'<script[\s\S]*?>([\s\S]*?)</script>', html, re.IGNORECASE).group(1)

missing = []
for fn in onclick_funcs:
    pattern = rf"(function\s+{fn}\b|{fn}\s*=\s*function|\bconst\s+{fn}\s*=|\blet\s+{fn}\s*=|\bvar\s+{fn}\s*=|\basync\s+function\s+{fn}\b)"
    if not re.search(pattern, script_text):
        missing.append(fn)

if missing:
    print(f"\n[ERROR] Missing JS functions for onclick: {missing}")
else:
    print(f"\n[SUCCESS] ALL {len(onclick_funcs)} onclick functions are DEFINED and VALID in JavaScript!")
