r"""Fill this repo with Fine Print Frank's posts, then commit and push.

    python prepare.py 2026-10-12 5   # first posting date (US Eastern), first content day (skip 1-4)

Builds the 14-day calendar from FRANK\plan.py, copies the reels and carousel slides into
docs/media (served by GitHub Pages: Instagram fetches media from a public URL), and writes
manifest.json and the consent-code page used by connect.py.
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FRANK = os.path.dirname(HERE)
DOCS = os.path.join(HERE, "docs")
MEDIA = os.path.join(DOCS, "media")

CALLBACK = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Fine Print Frank connect</title>
<style>body{font:18px system-ui,sans-serif;background:#0b1220;color:#fff;display:grid;place-items:center;min-height:100vh;margin:0;padding:16px}
main{max-width:560px}code{display:block;word-break:break-all;background:#1e293b;padding:14px;border-radius:10px;margin:14px 0}
button{font:inherit;padding:10px 18px;border:0;border-radius:10px;background:#ffd23f;color:#0e1628;cursor:pointer}</style></head>
<body><main><h1>Copy this code</h1><p>Paste it into the window where connect.py is waiting.</p>
<code id="c">No code in this address.</code><button onclick="navigator.clipboard.writeText(document.getElementById('c').textContent)">Copy</button>
<p id="e"></p></main><script>
const q=new URLSearchParams(location.search);
if(q.get('code'))document.getElementById('c').textContent=q.get('code');
if(q.get('error'))document.getElementById('e').textContent='Error: '+q.get('error')+' '+(q.get('error_description')||'');
</script></body></html>
"""


def main(start, first_day=1):
    r = subprocess.run([sys.executable, "plan.py", "calendar", start, str(first_day)], cwd=FRANK,
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stderr[-800:])
    shutil.copy2(os.path.join(FRANK, "POSTING_CALENDAR_FRANK.csv"), os.path.join(HERE, "calendar.csv"))

    src_reels = os.path.join(FRANK, "out", "reels")
    os.makedirs(os.path.join(MEDIA, "reels"), exist_ok=True)
    for f in sorted(os.listdir(src_reels)):
        if f.endswith(".mp4"):
            shutil.copy2(os.path.join(src_reels, f), os.path.join(MEDIA, "reels", f))
    manifest = {}
    src_car = os.path.join(FRANK, "out", "carousels")
    for post in sorted(os.listdir(src_car)):
        folder = os.path.join(src_car, post)
        if not os.path.isdir(folder):
            continue
        slides = sorted(x for x in os.listdir(folder) if x.lower().endswith(".jpg"))
        os.makedirs(os.path.join(MEDIA, "instagram", post), exist_ok=True)
        for s in slides:
            shutil.copy2(os.path.join(folder, s), os.path.join(MEDIA, "instagram", post, s))
        manifest[post] = slides
    json.dump(manifest, open(os.path.join(HERE, "manifest.json"), "w", encoding="utf-8"), indent=1)
    open(os.path.join(DOCS, "callback.html"), "w", encoding="utf-8").write(CALLBACK)
    open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8").write(
        "<!doctype html><title>Fine Print Frank</title><p>Media for @fineprintfrank posts.</p>")
    open(os.path.join(DOCS, ".nojekyll"), "w").close()
    print("repo filled: %d carousels, %d reels" % (len(manifest), len(os.listdir(os.path.join(MEDIA, "reels")))))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1)
