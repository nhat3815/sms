import os

with open("launcher.py", "r", encoding="utf-8") as f:
    content = f.read()

prefix = content[:content.find('@app.route("/")')]
tail_marker = 'if __name__ == "__main__":'
tail = content[content.find(tail_marker):]

new_home = """@app.route("/")
def home():
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "index.html")
    with open(html_path, "r", encoding="utf-8") as fp:
        html_code = fp.read()
    resp = Response(html_code, mimetype="text/html; charset=utf-8")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp
"""

full_content = prefix + new_home + "\n\n" + tail
with open("launcher.py", "w", encoding="utf-8") as f:
    f.write(full_content)

print("launcher.py successfully updated!")
