#!/usr/bin/env python3
"""Capture App Store / Play Store screenshots from the live web app.

Why this exists: App Store Connect and Play Console both reject screenshots at
the wrong pixel size, and both require the shots to show the app *actually
running*. So this drives a real browser at the exact device geometry each store
asks for and saves what it sees. No mockups, no upscaling, no invented UI.

    python tools/store_shots.py --base-url https://musicconnectz.net \\
        --preset iphone-6.5 --out shots/

Logged-in screens need a session. Pass credentials for a real account and the
script logs in through the API and injects the tokens before navigating:

    python tools/store_shots.py --base-url https://musicconnectz.net \\
        --preset iphone-6.5 --out shots/ \\
        --login-identifier review@example.com --login-password '...' \\
        --token-key access --refresh-key refresh

``--token-key`` must match whatever key the frontend reads its JWT from in
localStorage. If the shots come out logged-out, that key is wrong — check the
frontend's auth store and pass the right one. Run ``--list-storage`` after a
manual login in the same browser profile to see what keys the app actually sets.

Requires: pip install playwright  (Chromium is already on the image; point at it
with --chromium if Playwright can't find its own build.)
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

# Each store rejects anything that isn't exactly one of its accepted sizes, so
# these are (css_width, css_height, scale) triples chosen to land on the pixel
# dimensions the console prints on the upload box — not approximations.
PRESETS = {
    # Apple. 6.5" accepts 1242x2688 or 1284x2778; we emit the first.
    "iphone-6.5": (414, 896, 3, "1242x2688"),
    "iphone-6.9": (430, 932, 3, "1290x2796"),
    "ipad-13": (1032, 1376, 2, "2064x2752"),
    # Google Play. Phone shots need 1080 on the short edge; 16:9 is safe.
    "play-phone": (360, 640, 3, "1080x1920"),
    "play-tablet-7": (600, 960, 2, "1200x1920"),
    "play-tablet-10": (800, 1280, 2, "1600x2560"),
}

# The screens worth showing a stranger, in the order they tell the story.
# Route -> output filename stem. Override with --routes routes.json.
DEFAULT_ROUTES = [
    {"path": "/", "name": "01-home"},
    {"path": "/tour", "name": "02-omviardz-tour"},
    {"path": "/feed", "name": "03-feed"},
    {"path": "/profile", "name": "04-profile-personas"},
    {"path": "/bodiez", "name": "05-bodiez"},
    {"path": "/merch", "name": "06-merch"},
    {"path": "/wallet", "name": "07-wallet"},
]


def log(msg):
    print(msg, flush=True)


def api_login(base_url, identifier, password, timeout=30):
    """Log in through the backend and return the token payload.

    Uses the same endpoint the app uses, so if this fails the credentials are
    genuinely wrong — it isn't a scripting artifact.
    """
    url = base_url.rstrip("/") + "/api/auth/login/"
    body = json.dumps({"identifier": identifier, "password": password}).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise SystemExit(f"login failed ({e.code}) at {url}: {detail}")
    except urllib.error.URLError as e:
        raise SystemExit(f"could not reach {url}: {e.reason}")


def build_parser():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", required=True, help="e.g. https://musicconnectz.net")
    p.add_argument("--preset", default="iphone-6.5", choices=sorted(PRESETS),
                   help="device geometry (default: iphone-6.5)")
    p.add_argument("--out", default="shots", help="output directory")
    p.add_argument("--routes", help="JSON file: [{\"path\": \"/feed\", \"name\": \"03-feed\"}]")
    p.add_argument("--login-identifier")
    p.add_argument("--login-password")
    p.add_argument("--token-key", default="access",
                   help="localStorage key the frontend reads the JWT from")
    p.add_argument("--refresh-key", default="refresh")
    p.add_argument("--wait", type=float, default=2.5,
                   help="seconds to settle after load, for fonts/animation")
    p.add_argument("--wait-for", help="CSS selector to wait for on every route")
    p.add_argument("--full-page", action="store_true",
                   help="capture the whole scroll height (NOT store-legal — "
                        "stores want exact device size; use for review only)")
    p.add_argument("--chromium", default=os.environ.get("CHROMIUM_PATH"),
                   help="explicit Chromium binary if Playwright's is missing")
    p.add_argument("--list-storage", action="store_true",
                   help="after loading, print localStorage keys and exit — use "
                        "this to discover the right --token-key")
    return p


def main():
    args = build_parser().parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("playwright is not installed — pip install playwright")

    width, height, scale, label = PRESETS[args.preset]
    expect_w, expect_h = (width * scale, height * scale)
    routes = DEFAULT_ROUTES
    if args.routes:
        with open(args.routes) as fh:
            routes = json.load(fh)

    tokens = None
    if args.login_identifier:
        if not args.login_password:
            raise SystemExit("--login-identifier needs --login-password")
        tokens = api_login(args.base_url, args.login_identifier, args.login_password)
        log(f"logged in as {(tokens.get('user') or {}).get('username', '?')}")

    os.makedirs(args.out, exist_ok=True)
    base = args.base_url.rstrip("/")
    written, failed, offsize = [], [], []

    with sync_playwright() as pw:
        launch = {}
        if args.chromium:
            launch["executable_path"] = args.chromium
        browser = pw.chromium.launch(**launch)
        ctx = browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=scale,
            is_mobile=True,
            has_touch=True,
        )
        if tokens:
            # Seed the tokens before any app JS runs, so the first paint is
            # already the logged-in view — no flash of the login screen, which
            # is exactly the frame a naive capture would catch.
            ctx.add_init_script(
                "(() => { try {"
                f"localStorage.setItem({json.dumps(args.token_key)}, {json.dumps(tokens.get('access', ''))});"
                f"localStorage.setItem({json.dumps(args.refresh_key)}, {json.dumps(tokens.get('refresh', ''))});"
                "} catch (e) {} })();"
            )
        page = ctx.new_page()

        if args.list_storage:
            page.goto(base, wait_until="networkidle", timeout=60000)
            time.sleep(args.wait)
            keys = page.evaluate("Object.keys(localStorage)")
            log(f"localStorage keys on {base}: {keys or '(none)'}")
            browser.close()
            return 0

        for route in routes:
            url = base + route["path"]
            dest = os.path.join(args.out, f"{route['name']}-{args.preset}.png")
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
                if args.wait_for:
                    page.wait_for_selector(args.wait_for, timeout=30000)
                time.sleep(args.wait)
                page.screenshot(path=dest, full_page=args.full_page)
            except Exception as e:  # one bad route shouldn't lose the rest
                log(f"  ✗ {route['name']:<24} {type(e).__name__}: {str(e)[:120]}")
                failed.append(route["name"])
                continue

            # Verify the pixels rather than trusting the viewport maths — a
            # page that forces its own zoom or a device pixel ratio override
            # will silently produce an off-size PNG the store then rejects.
            ok = True
            if not args.full_page:
                got = png_size(dest)
                ok = got == (expect_w, expect_h)
                if not ok:
                    log(f"  ⚠ {route['name']:<24} {got[0]}x{got[1]} — expected {label}")
                    offsize.append(route["name"])
            if ok:
                log(f"  ✓ {route['name']:<24} {label}")
            written.append(dest)

        browser.close()

    log(f"\n{len(written)} screenshot(s) in {args.out}/ at {label}")
    if failed:
        log(f"{len(failed)} route(s) failed: {', '.join(failed)}")
        log("A failed route usually means that path doesn't exist in the "
            "frontend — pass --routes with the real ones.")
    if offsize:
        log(f"\n{len(offsize)} shot(s) came out the wrong size. The store will "
            "reject these.")
        log("Almost always the cause is a missing viewport meta tag — the page "
            "needs\n  <meta name=\"viewport\" content=\"width=device-width, "
            "initial-scale=1\">\nin its <head>. Without it Chromium lays the "
            "page out at a desktop width and\nscales it down, which rounds the "
            "capture off by a pixel. Fix the tag on the\nsite rather than "
            "resizing the PNGs — the same tag is what makes the app look\n"
            "right on a real phone.")
    return 1 if (failed and not written) or offsize else 0


def png_size(path):
    """Read width/height straight from the PNG IHDR chunk."""
    with open(path, "rb") as fh:
        head = fh.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return (0, 0)
    return (int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big"))


if __name__ == "__main__":
    sys.exit(main())
