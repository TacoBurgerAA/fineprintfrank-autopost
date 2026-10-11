r"""Post whatever is due from calendar.csv. Runs on GitHub Actions every 30 minutes.

Free replacement for a paid scheduler: Instagram (Instagram API with Instagram Login) and
the owner's LinkedIn profile (Share on LinkedIn, w_member_social). Slot C rows (TikTok and
YouTube only) are skipped: those are scheduled by hand in TikTok Studio and YouTube Studio
until those platforms approve an app for public posting.

    python post_due.py                 # post what is due now (what the workflow runs)
    python post_due.py --dry 2026-10-01 2026-10-07   # list what would post in a date range

Environment (set as GitHub secrets / variables by connect.py):
    IG_TOKEN, IG_USER_ID, LI_TOKEN, LI_PERSON, MEDIA_BASE, IG_EXPIRES, LI_EXPIRES
A platform whose token is missing is skipped, so it works with Instagram alone.

API calls as documented on 28 Sep 2026:
  Instagram: developers.facebook.com/docs/instagram-platform/content-publishing
    POST graph.instagram.com/<ver>/<IG_ID>/media, GET <container>?fields=status_code,
    POST <IG_ID>/media_publish. Media must be at a public URL. 100 API posts per 24 h.
  LinkedIn: learn.microsoft.com/linkedin/consumer/integrations/self-serve/share-on-linkedin
    POST /v2/assets?action=registerUpload, upload to uploadUrl, POST /v2/ugcPosts.
"""
import csv
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CAL = os.path.join(HERE, "calendar.csv")
LOG = os.path.join(HERE, "posted.csv")
MANIFEST = os.path.join(HERE, "manifest.json")
PTIN_OPEN = os.path.join(HERE, "ptin_open.txt")    # create after irs.gov shows renewal is open
IG_VER = os.environ.get("IG_API_VERSION", "v23.0")
GRACE = dt.timedelta(hours=3)                      # GitHub cron can run late; older rows are skipped
HELD = ("06_ptin_renewal_open", "04_ptin_renewal_open")
def targets(row):
    """Platforms this script posts to, read from the row's "where" column. TikTok, YouTube and
    Pinterest rows are left for their own schedulers until those APIs allow public posts."""
    where = row.get("where", "").lower()
    return tuple(p for p in ("instagram", "linkedin") if p in where)


# ---------------------------------------------------------------- time (US Eastern)

def _nth_sunday(year, month, n):
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(6 - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def et_to_utc(date_str, time_str):
    day = dt.date.fromisoformat(date_str)
    hh, mm = map(int, time_str.replace("ET", "").strip().split(":"))
    local = dt.datetime.combine(day, dt.time(hh, mm))
    start = dt.datetime.combine(_nth_sunday(day.year, 3, 2), dt.time(2))
    end = dt.datetime.combine(_nth_sunday(day.year, 11, 1), dt.time(2))
    return (local + dt.timedelta(hours=4 if start <= local < end else 5)).replace(tzinfo=dt.timezone.utc)


# ---------------------------------------------------------------- http

def http(method, url, params=None, body=None, headers=None, data=None, tries=4):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    hdrs = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                raw = r.read()
                return (json.loads(raw) if raw.strip() else {}), dict(r.headers)
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace")[:800]
            if e.code >= 500 or e.code == 429:
                time.sleep(20 * (attempt + 1))
                continue
            raise RuntimeError("HTTP %d %s %s: %s" % (e.code, method, url.split("?")[0], text))
        except urllib.error.URLError as e:
            time.sleep(20)
    raise RuntimeError("gave up on %s %s" % (method, url.split("?")[0]))


def media_urls(row):
    base = os.environ["MEDIA_BASE"].rstrip("/")
    if row["type"] == "carousel":
        slides = json.load(open(MANIFEST, encoding="utf-8"))[row["post"]]
        return ["%s/instagram/%s/%s" % (base, row["post"], s) for s in slides[:10]]
    return ["%s/reels/%s.mp4" % (base, row["post"])]


# ---------------------------------------------------------------- Instagram

def ig(method, path, **params):
    params["access_token"] = os.environ["IG_TOKEN"]
    url = "https://graph.instagram.com/%s/%s" % (IG_VER, path)
    if method == "GET":
        return http("GET", url, params=params)[0]
    return http("POST", url, data=urllib.parse.urlencode(params).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"})[0]


def ig_wait(cid, limit=600):
    t0 = time.time()
    while time.time() - t0 < limit:
        st = ig("GET", cid, fields="status_code").get("status_code")
        if st == "FINISHED":
            return
        if st in ("ERROR", "EXPIRED"):
            raise RuntimeError("Instagram container %s: %s" % (cid, st))
        time.sleep(8)
    raise RuntimeError("Instagram container %s not ready after %ds" % (cid, limit))


def post_instagram(row, caption):
    uid = os.environ["IG_USER_ID"]
    urls = media_urls(row)
    if row["type"] == "carousel":
        # alt_text: image and carousel items only, up to 1,000 characters (Meta, added 24 Mar 2025)
        alt = (row.get("alt_text") or "").strip()
        extra = lambda k: {"alt_text": ("Slide %d of %d. %s" % (k + 1, len(urls), alt))[:1000]} if alt else {}  # noqa: E731
        kids = [ig("POST", uid + "/media", image_url=u, is_carousel_item="true", **extra(k))["id"]
                for k, u in enumerate(urls)]
        for k in kids:
            ig_wait(k, 120)
        cid = ig("POST", uid + "/media", media_type="CAROUSEL", children=",".join(kids), caption=caption)["id"]
    else:
        # Reels carry the synthetic voice: Meta requires the AI disclosure, which the API sets with
        # is_ai_generated on the container (IG User Media reference; not allowed on carousel children).
        # If Instagram rejects it, the run fails rather than posting without the label.
        cid = ig("POST", uid + "/media", media_type="REELS", video_url=urls[0], caption=caption,
                 share_to_feed="true", is_ai_generated="true")["id"]
    ig_wait(cid)
    return ig("POST", uid + "/media_publish", creation_id=cid)["id"]


# ---------------------------------------------------------------- LinkedIn

LI_HDR = {"X-Restli-Protocol-Version": "2.0.0"}


def li_headers():
    return dict(LI_HDR, Authorization="Bearer " + os.environ["LI_TOKEN"])


def li_upload(url, kind):
    owner = "urn:li:person:" + os.environ["LI_PERSON"]
    reg = http("POST", "https://api.linkedin.com/v2/assets?action=registerUpload", headers=li_headers(), body={
        "registerUploadRequest": {"recipes": ["urn:li:digitalmediaRecipe:feedshare-" + kind], "owner": owner,
                                  "serviceRelationships": [{"relationshipType": "OWNER",
                                                            "identifier": "urn:li:userGeneratedContent"}]}})[0]
    v = reg["value"]
    up = v["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]
    with urllib.request.urlopen(url, timeout=300) as r:
        blob = r.read()
    http("PUT", up["uploadUrl"], data=blob,
         headers=dict(up.get("headers") or {}, Authorization="Bearer " + os.environ["LI_TOKEN"]))
    asset = v["asset"]
    if kind == "video":                                   # wait until LinkedIn has processed it
        aid = urllib.parse.quote(asset.split(":")[-1])
        t0 = time.time()
        while time.time() - t0 < 600:
            st = http("GET", "https://api.linkedin.com/v2/assets/" + aid, headers=li_headers())[0]
            states = [r.get("status") for r in st.get("recipes", [])]
            if states and all(s == "AVAILABLE" for s in states):
                break
            time.sleep(10)
    return asset


def post_linkedin(row, caption):
    kind = "image" if row["type"] == "carousel" else "video"
    assets = [li_upload(u, kind) for u in media_urls(row)]
    body = {"author": "urn:li:person:" + os.environ["LI_PERSON"], "lifecycleState": "PUBLISHED",
            "specificContent": {"com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": caption},
                "shareMediaCategory": "IMAGE" if kind == "image" else "VIDEO",
                "media": [{"status": "READY", "media": a} for a in assets]}},
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}}
    _, hdrs = http("POST", "https://api.linkedin.com/v2/ugcPosts", headers=li_headers(), body=body)
    return hdrs.get("X-RestLi-Id") or hdrs.get("x-restli-id") or "?"


POSTERS = {"instagram": ("IG_TOKEN", post_instagram), "linkedin": ("LI_TOKEN", post_linkedin)}


# ---------------------------------------------------------------- bookkeeping

def load_rows():
    with open(CAL, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["utc"] = et_to_utc(r["date_ET"], r["time_ET"])
        r["key"] = "%s_%s_%s" % (r["date_ET"], r["slot"], r["post"])
    return rows


def done():
    if not os.path.exists(LOG):
        return set()
    with open(LOG, encoding="utf-8", newline="") as f:
        return {(r["key"], r["platform"]) for r in csv.DictReader(f)}


def log(row, platform, post_id):
    new = not os.path.exists(LOG)
    with open(LOG, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["key", "platform", "scheduled_utc", "post_id", "posted_utc"])
        w.writerow([row["key"], platform, row["utc"].isoformat(), post_id,
                    dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")])


def remind():
    """Open a GitHub issue (GitHub emails the owner) a week before a token expires."""
    today = dt.date.today()
    for var, name, how in (("IG_EXPIRES", "Instagram", "python connect.py instagram --refresh"),
                           ("LI_EXPIRES", "LinkedIn", "python connect.py linkedin")):
        exp = os.environ.get(var)
        if not exp or not os.environ.get("GH_TOKEN"):
            continue
        left = (dt.date.fromisoformat(exp) - today).days
        if left <= 7:
            title = "Reconnect %s: token expires %s" % (name, exp)
            open_ = subprocess.run(["gh", "issue", "list", "--state", "open", "--search", title, "--json", "title"],
                                   capture_output=True, text=True).stdout
            if title not in open_:
                subprocess.run(["gh", "issue", "create", "--title", title, "--body",
                                "Posting to %s stops when the token expires. On the PC, in the autopost folder, run:\n\n"
                                "    %s\n" % (name, how)])


def main():
    rows = load_rows()
    if "--dry" in sys.argv:
        a, b = sys.argv[sys.argv.index("--dry") + 1:][:2]
        for r in rows:
            if a <= r["date_ET"] <= b:
                print(r["date_ET"], r["time_ET"], r["utc"].strftime("%H:%M UTC"), r["type"], r["post"],
                      "->", ", ".join(targets(r)) or "manual (TikTok/YouTube)")
        return 0
    remind()
    now = dt.datetime.now(dt.timezone.utc)
    have = done()
    ptin_ok = os.path.exists(PTIN_OPEN)
    failed = 0
    for r in rows:
        if not (now - GRACE <= r["utc"] <= now):
            continue
        if r["post"] in HELD and not ptin_ok:
            print("held until ptin_open.txt exists:", r["key"])
            continue
        for platform in targets(r):
            env, fn = POSTERS[platform]
            if not os.environ.get(env) or (r["key"], platform) in have:
                continue
            try:
                pid = fn(r, r["caption_and_hashtags"])
                log(r, platform, pid)
                print("posted", r["key"], platform, pid)
            except Exception as e:          # one platform failing must not stop the other
                failed += 1
                print("FAILED", r["key"], platform, e)
    return 1 if failed else 0             # a failed run turns red and GitHub emails the owner


if __name__ == "__main__":
    sys.exit(main())
