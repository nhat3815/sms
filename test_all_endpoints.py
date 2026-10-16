import re
import launcher

with open("templates/index.html", "r", encoding="utf-8") as f:
    html = f.read()

fetches = re.findall(r"fetch\((['\"])(.*?)\1", html)
endpoint_paths = sorted(set([f[1] for f in fetches]))

print("Frontend Fetch Endpoints:")
for ep in endpoint_paths:
    print("  ->", ep)

client = launcher.app.test_client()

print("\nTesting Endpoints:")
for ep in endpoint_paths:
    if ep in ["/shutdown"]:
        continue
    res_get = client.get(ep)
    res_post = client.post(ep, json={})
    print(f"  {ep:<30} GET: {res_get.status_code:<5} POST: {res_post.status_code}")
