#!/usr/bin/env python3
"""Finalize GitHub Pages custom domain for woodwardwelldrilling.com.

Idempotent. Only runs once DNS actually resolves, so the github.io preview
never gets redirected to a dead domain.

Usage:  python finalize_domain.py [--force]
"""
import json
import subprocess
import sys
import time
import urllib.request

DOMAIN = "woodwardwelldrilling.com"
REPO = "copernicusjones/woodwardwelldrilling"
DEPLOY = r"C:/Users/brook/AppData/Local/hermes/profiles/saint/projects/woodwardwelldrilling-deploy"
GITHUB_IPS = ["185.199.108.153", "185.199.109.153", "185.199.110.153", "185.199.111.153"]


def sh(*args, cwd=None, check=False):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, shell=False)
    if check and r.returncode != 0:
        raise RuntimeError(f"{args} failed: {r.stderr or r.stdout}")
    return r


def dns_ready():
    """True when at least two GitHub apex IPs answer for the domain."""
    try:
        out = sh("nslookup", DOMAIN, "8.8.8.8").stdout
    except Exception:
        return False, []
    found = [ip for ip in GITHUB_IPS if ip in out]
    return len(found) >= 2, found


def http_status(url, tries=1):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "saint-finalize/1.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.status, len(r.read())
        except Exception as e:
            code = getattr(e, "code", None)
            if code:
                return code, 0
            if i + 1 < tries:
                time.sleep(10)
    return None, 0


def main():
    force = "--force" in sys.argv
    ok, ips = dns_ready()
    print(f"DNS A records matching GitHub: {ips or 'none'}")

    if not ok and not force:
        print("BLOCKED: DNS not pointing at GitHub yet. Add the records at Porkbun first.")
        print("Refusing to set the custom domain while it would not resolve.")
        return 2

    # 1. CNAME file in the repo
    cname_path = f"{DEPLOY}/CNAME"
    with open(cname_path, "w", encoding="utf-8") as f:
        f.write(DOMAIN + "\n")
    sh("git", "add", "CNAME", cwd=DEPLOY, check=True)
    commit = sh("git", "commit", "-m", f"Point custom domain at {DOMAIN}", cwd=DEPLOY)
    if commit.returncode == 0:
        sh("git", "push", cwd=DEPLOY, check=True)
        print("CNAME committed and pushed")
    else:
        print("CNAME unchanged, nothing to commit")

    # 2. Set Pages custom domain
    r = sh("gh", "api", "-X", "PUT", f"repos/{REPO}/pages",
           "-f", f"cname={DOMAIN}")
    print("pages cname set:", (r.stdout or r.stderr).strip()[:200])

    # 3. Wait for cert, then enforce HTTPS
    for attempt in range(18):  # ~6 min
        time.sleep(20)
        info = sh("gh", "api", f"repos/{REPO}/pages")
        try:
            d = json.loads(info.stdout)
        except Exception:
            print("could not read pages status"); continue
        state = d.get("https_certificate", {}).get("state")
        print(f"[{attempt+1}] cert={state} cname={d.get('cname')} status={d.get('status')}")
        if state == "approved":
            sh("gh", "api", "-X", "PUT", f"repos/{REPO}/pages", "-F", "https_enforced=true")
            print("HTTPS enforced")
            break
    else:
        print("WARNING: cert not approved in time; HTTPS not enforced yet")

    # 4. Verify both hostnames
    for url in (f"https://{DOMAIN}/", f"https://www.{DOMAIN}/"):
        code, size = http_status(url, tries=6)
        print(f"{url} -> {code} ({size} bytes)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
