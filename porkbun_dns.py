#!/usr/bin/env python3
"""Point woodwardwelldrilling.com at GitHub Pages via the Porkbun API.

Reads credentials from porkbun_creds.json (never from argv, never logged).

    {"apikey": "...", "secretapikey": "..."}

Default is DRY RUN (prints the plan, changes nothing).
    python porkbun_dns.py            # dry run
    python porkbun_dns.py --apply    # actually change records

What it does:
  1. Delete the apex A records pointing at Porkbun parking (207.207.210.x)
  2. Create the four GitHub Pages apex A records
  3. Repoint the www CNAME at copernicusjones.github.io
  4. Leave MX / SPF / everything else untouched
  5. Re-read the zone and print the resulting state
"""
import json
import os
import sys
import urllib.request

API = "https://api.porkbun.com/api/json/v3"
DOMAIN = "woodwardwelldrilling.com"
HERE = os.path.dirname(os.path.abspath(__file__))
CREDS = os.path.join(HERE, "porkbun_creds.json")

GITHUB_A = ["185.199.108.153", "185.199.109.153", "185.199.110.153", "185.199.111.153"]
PARKING_PREFIX = "207.207.210."
WWW_TARGET = "copernicusjones.github.io"


def load_creds():
    if not os.path.isfile(CREDS):
        sys.exit(f"missing {CREDS}")
    with open(CREDS, encoding="utf-8") as f:
        c = json.load(f)
    if not c.get("apikey") or not c.get("secretapikey"):
        sys.exit("creds file needs apikey and secretapikey")
    return c


def call(path, extra=None, creds=None):
    body = {"apikey": creds["apikey"], "secretapikey": creds["secretapikey"]}
    if extra:
        body.update(extra)
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "saint-porkbun/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode())
    if d.get("status") != "SUCCESS":
        # never echo the request body; it holds the keys
        raise RuntimeError(f"{path} -> {d.get('status')} / {d.get('message')}")
    return d


def main():
    apply = "--apply" in sys.argv
    creds = load_creds()

    print(f"Porkbun DNS sync for {DOMAIN}  ({'APPLY' if apply else 'DRY RUN'})")

    recs = call(f"/dns/retrieve/{DOMAIN}", creds=creds).get("records", [])
    print(f"\ncurrent records: {len(recs)}")
    for r in recs:
        print(f"  [{r['id']:>9}] {r['type']:<6} {r['name']:<34} {r['content']}")

    # --- apex parking records to remove -------------------------------------
    # Porkbun parks with ALIAS (not A) at the apex plus a wildcard CNAME,
    # both aimed at uixie.porkbun.com. Either form must go.
    def is_parking(r):
        c = (r.get("content") or "").lower()
        return "porkbun.com" in c and r["type"] == "ALIAS" and r["name"] == DOMAIN

    kill = [r for r in recs if is_parking(r)]

    wildcard = [
        r for r in recs
        if r["type"] == "CNAME"
        and r["name"].startswith("*.")
        and "porkbun.com" in (r.get("content") or "").lower()
    ]

    # --- apex records already correct? --------------------------------------
    have = {r["content"] for r in recs if r["type"] == "A" and r["name"] == DOMAIN}
    need = [ip for ip in GITHUB_A if ip not in have]

    # --- www cname ----------------------------------------------------------
    www = [r for r in recs if r["type"] == "CNAME" and r["name"] == f"www.{DOMAIN}"]
    www_bad = [r for r in www if not r["content"].startswith(WWW_TARGET)]
    create_www = not www

    print("\nplan:")
    for r in kill:
        print(f"  DELETE {r['type']:<6} {r['name']} -> {r['content']}  (parking, id {r['id']})")
    for r in wildcard:
        print(f"  DELETE {r['type']:<6} {r['name']} -> {r['content']}  (parking wildcard, id {r['id']})")
    for ip in need:
        print(f"  CREATE A      {DOMAIN} -> {ip}")
    for r in www_bad:
        print(f"  EDIT   CNAME  {r['name']} -> {WWW_TARGET}  (was {r['content']}, id {r['id']})")
    if create_www:
        print(f"  CREATE CNAME  www.{DOMAIN} -> {WWW_TARGET}")
    if not (kill or wildcard or need or www_bad or create_www):
        print("  nothing to change")
    untouched = len(recs) - len(kill) - len(wildcard) - len(www_bad)
    print(f"  untouched: {untouched} records (NS, MX, TXT/SPF, ACME)")

    if not apply:
        print("\ndry run only. re-run with --apply")
        return 0

    for r in kill:
        call(f"/dns/delete/{DOMAIN}/{r['id']}", creds=creds)
        print(f"deleted {r['type']} {r['content']}")
    for r in wildcard:
        call(f"/dns/delete/{DOMAIN}/{r['id']}", creds=creds)
        print(f"deleted wildcard {r['content']}")
    for ip in need:
        call(f"/dns/create/{DOMAIN}",
             {"name": "", "type": "A", "content": ip, "ttl": "600"}, creds=creds)
        print(f"created A {ip}")
    for r in www_bad:
        call(f"/dns/edit/{DOMAIN}/{r['id']}",
             {"name": "www", "type": "CNAME", "content": WWW_TARGET, "ttl": "600"},
             creds=creds)
        print(f"edited www CNAME -> {WWW_TARGET}")
    if create_www:
        call(f"/dns/create/{DOMAIN}",
             {"name": "www", "type": "CNAME", "content": WWW_TARGET, "ttl": "600"},
             creds=creds)
        print(f"created www CNAME -> {WWW_TARGET}")

    print("\n--- resulting zone ---")
    for r in call(f"/dns/retrieve/{DOMAIN}", creds=creds).get("records", []):
        print(f"  {r['type']:<6} {r['name']:<34} {r['content']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
