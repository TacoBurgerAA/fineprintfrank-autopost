r"""One-time connection of Instagram and LinkedIn to the free autoposter. Run on the PC:

    python connect.py instagram            # opens the Instagram consent screen
    python connect.py instagram --refresh  # extend the Instagram token another 60 days, no browser
    python connect.py linkedin             # opens the LinkedIn consent screen (repeat every ~60 days)

It reads the app IDs and secrets from ..\_autopost_secrets\app.json (the owner creates it,
outside this public repo), exchanges the code for a token, keeps a copy in
..\_autopost_secrets\tokens.json and stores it as a GitHub Actions secret with `gh`.
Tokens and secrets are never printed.

Token rules (developer docs, 28 Sep 2026): Instagram long-lived tokens last 60 days and can
be refreshed once they are 24 h old; LinkedIn member tokens last 60 days and self-serve apps
get no refresh token, so LinkedIn needs this consent click about every two months.
"""
import datetime as dt
import json
import os
import re
import secrets
import subprocess
import sys
import urllib.parse
import webbrowser

from post_due import http, IG_VER

HERE = os.path.dirname(os.path.abspath(__file__))
SECRETS = os.path.join(os.path.dirname(HERE), "_autopost_secrets")
APP = os.path.join(SECRETS, "app.json")
TOKENS = os.path.join(SECRETS, "tokens.json")


def repo():
    url = subprocess.run(["git", "-C", HERE, "remote", "get-url", "origin"], capture_output=True, text=True).stdout
    m = re.search(r"github\.com[:/](.+?)/(.+?)(\.git)?\s*$", url)
    if not m:
        raise SystemExit("This folder is not pushed to GitHub yet.")
    return m.group(1), m.group(2)


def redirect_uri():
    owner, name = repo()
    return "https://%s.github.io/%s/callback.html" % (owner.lower(), name)


def gh_set(kind, name, value):
    owner, rp = repo()
    r = subprocess.run(["gh", kind, "set", name, "-R", "%s/%s" % (owner, rp)], input=value, text=True,
                       capture_output=True)
    if r.returncode:
        raise SystemExit("gh %s set %s failed: %s" % (kind, name, r.stderr.strip()))


def load(path):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}


def save_token(key, data):
    os.makedirs(SECRETS, exist_ok=True)
    t = load(TOKENS)
    t[key] = data
    json.dump(t, open(TOKENS, "w", encoding="utf-8"), indent=1)


def ask_code(url):
    print("\nA browser tab opens. Approve, then copy the code shown on the Fine Print Frank page.")
    print("If no tab opens, paste this address into your browser:\n  " + url.split("?")[0] + "?...")
    webbrowser.open(url)
    code = input("\nPaste the code here and press Enter: ").strip()
    return code.split("#")[0]


def instagram(refresh=False):
    app = load(APP)
    if refresh:
        tok = load(TOKENS).get("instagram", {}).get("access_token")
        if not tok:
            raise SystemExit("No saved Instagram token; run: python connect.py instagram")
        res = http("GET", "https://graph.instagram.com/refresh_access_token",
                   params={"grant_type": "ig_refresh_token", "access_token": tok})[0]
        long_tok, secs = res["access_token"], int(res.get("expires_in", 5184000))
        uid = load(TOKENS)["instagram"]["user_id"]
    else:
        state = secrets.token_urlsafe(12)
        url = "https://www.instagram.com/oauth/authorize?" + urllib.parse.urlencode({
            "client_id": app["ig_app_id"], "redirect_uri": redirect_uri(), "response_type": "code",
            "scope": "instagram_business_basic,instagram_business_content_publish", "state": state})
        code = ask_code(url)
        res = http("POST", "https://api.instagram.com/oauth/access_token", data=urllib.parse.urlencode({
            "client_id": app["ig_app_id"], "client_secret": app["ig_app_secret"],
            "grant_type": "authorization_code", "redirect_uri": redirect_uri(), "code": code}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"})[0]
        short = (res.get("data") or [res])[0]["access_token"]
        res = http("GET", "https://graph.instagram.com/access_token", params={
            "grant_type": "ig_exchange_token", "client_secret": app["ig_app_secret"], "access_token": short})[0]
        long_tok, secs = res["access_token"], int(res.get("expires_in", 5184000))
        me = http("GET", "https://graph.instagram.com/%s/me" % IG_VER,
                  params={"fields": "user_id,username", "access_token": long_tok})[0]
        uid = str(me["user_id"])
        print("Connected Instagram account: @%s" % me.get("username"))
    expires = (dt.date.today() + dt.timedelta(seconds=secs)).isoformat()
    save_token("instagram", {"access_token": long_tok, "user_id": uid, "expires": expires})
    gh_set("secret", "IG_TOKEN", long_tok)
    gh_set("variable", "IG_USER_ID", uid)
    gh_set("variable", "IG_EXPIRES", expires)
    print("Instagram ready. Token valid until %s." % expires)


def linkedin():
    app = load(APP)
    state = secrets.token_urlsafe(12)
    url = "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": app["li_client_id"], "redirect_uri": redirect_uri(),
        "state": state, "scope": "openid profile w_member_social"})
    code = ask_code(url)
    res = http("POST", "https://www.linkedin.com/oauth/v2/accessToken", data=urllib.parse.urlencode({
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(),
        "client_id": app["li_client_id"], "client_secret": app["li_client_secret"]}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"})[0]
    tok, secs = res["access_token"], int(res.get("expires_in", 5184000))
    me = http("GET", "https://api.linkedin.com/v2/userinfo", headers={"Authorization": "Bearer " + tok})[0]
    expires = (dt.date.today() + dt.timedelta(seconds=secs)).isoformat()
    save_token("linkedin", {"access_token": tok, "person": me["sub"], "expires": expires})
    gh_set("secret", "LI_TOKEN", tok)
    gh_set("variable", "LI_PERSON", me["sub"])
    gh_set("variable", "LI_EXPIRES", expires)
    print("LinkedIn ready (%s). Token valid until %s." % (me.get("name", "profile"), expires))


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else ""
    if which == "instagram":
        instagram("--refresh" in sys.argv)
    elif which == "linkedin":
        linkedin()
    else:
        raise SystemExit(__doc__)
