#!/usr/bin/env python3
"""
Claims-register generator — addocdeliverables.ca / Adamic Theory System.

Reads claim blocks straight off the published pages and emits
claims-register.json and claims-register.md, plus lint findings for
both the claims graph and the evidence strips.

The live site is the source of truth. Nothing here is hand-maintained:
inbound dependents are derived, never typed.

Usage:
    python3 adamic_claims-register-generator_2026-09-14.py [--out DIR]

A claim is recognized on a page as:
    <strong>UR-XXX-000</strong> <em>(Grade)</em> — claim text
    <strong>UR-XXX-000.</strong> claim text            (grade taken from context)

Status is derived:
    withdrawn  the claim sits inside a <s> strike, or a correction block names it as replaced
    revised    the grade string starts with "Revised"
    active     everything else
"""
import argparse, json, os, re, sys, urllib.request, html
from datetime import date

API = "https://addocdeliverables.ca/wp-json/wp/v2/pages"
FIELDS = "id,slug,link,title,content"
CLAIM_ID = r"UR-[A-Z]{2,5}-\d{3}"
GRADES = ("Measured", "Modelled", "Inferred", "Asserted", "Heuristic")


def fetch_pages():
    out, page = [], 1
    while True:
        url = f"{API}?per_page=100&page={page}&_fields={FIELDS}&_cb={int(__import__('time').time())}"
        try:
            data = json.load(urllib.request.urlopen(url))
        except Exception:
            break
        if not isinstance(data, list) or not data:
            break
        out += data
        if len(data) < 100:
            break
        page += 1
    return out


def strip_tags(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def extract(pages):
    claims, by_page = {}, {}
    for p in pages:
        raw = p["content"]["rendered"]
        if "/adamic-theory/" not in p["link"]:
            continue
        tier = re.search(r"Evidence tier:\s*([A-Za-z]+)", raw)
        work = re.search(r"theme-explorer/\?work=([a-z]+)", raw)
        struck = set(re.findall(CLAIM_ID, " ".join(re.findall(r"<s>.*?</s>", raw, re.S))))
        pat = re.compile(
            r"<strong>(" + CLAIM_ID + r")\.?</strong>\s*(?:<em>\(([^)]+)\)</em>)?\s*[—–-]?\s*(.{0,600}?)</p>",
            re.S)
        found = []
        for m in pat.finditer(raw):
            cid, grade, text = m.group(1), (m.group(2) or "").strip(), strip_tags(m.group(3))
            if cid in claims and len(claims[cid]["text"]) >= len(text):
                continue
            if not grade:
                near = strip_tags(raw[max(0, m.start() - 600):m.start()])
                g = [x for x in GRADES if x in near]
                if not g:
                    after = strip_tags(raw[m.end():m.end() + 400])
                    g = [x for x in GRADES if x in after]
                grade = g[-1] if g else ""
            if not grade:
                continue  # house style always prints a grade; an ungraded hit is a passing mention
            status = "withdrawn" if cid in struck else ("revised" if grade.lower().startswith("revised") else "active")
            claims[cid] = dict(id=cid, layer=cid.split("-")[1], page=strip_tags(p["title"]["rendered"]),
                               page_id=p["id"], url=p["link"], tier=tier.group(1) if tier else "",
                               work=work.group(1) if work else "", grade=grade, status=status, text=text,
                               refs=sorted(set(re.findall(CLAIM_ID, text)) - {cid}))
            found.append(cid)
        # printed MOC-nnn identifiers register as UR-COOP-nnn (The Machinery of Cooperation)
        moc = re.compile(r"<strong>\s*(Measured[^<]*?|Modelled|Inferred|Asserted|Heuristic)[^<]*?[\u2014\u2013-]\s*(MOC-\d{3})\.?\s*</strong>\s*(.{0,600}?)</p>", re.S)
        for m in moc.finditer(raw):
            grade, printed, text = m.group(1).strip(), m.group(2), strip_tags(m.group(3))
            cid = "UR-COOP-" + printed.split("-")[1]
            if cid in claims and len(claims[cid]["text"]) >= len(text):
                continue
            claims[cid] = dict(id=cid, printed_id=printed, layer="COOP", page=strip_tags(p["title"]["rendered"]),
                               page_id=p["id"], url=p["link"], tier=tier.group(1) if tier else "",
                               work=work.group(1) if work else "", grade=grade, status="active", text=text,
                               refs=sorted(set(re.findall(CLAIM_ID, text)) - {cid}))
            found.append(cid)

        # a replacement named in a correction block: "UR-X is replaced by UR-Y"
        for a, b in re.findall(r"(" + CLAIM_ID + r")\s+is replaced by\s+(" + CLAIM_ID + r")", strip_tags(raw)):
            if a not in claims:
                # withdrawn in place: the struck passage is the claim, and it carries no marker of its own
                st = re.search(r"<s>(.*?)</s>", raw, re.S)
                claims[a] = dict(id=a, layer=a.split("-")[1], page=strip_tags(p["title"]["rendered"]),
                                 page_id=p["id"], url=p["link"], tier=tier.group(1) if tier else "",
                                 work=work.group(1) if work else "", grade="withdrawn on publication",
                                 status="withdrawn", text=strip_tags(st.group(1))[:600] if st else "",
                                 refs=[], dependents=[])
                found.append(a)
            claims[a]["status"] = "withdrawn"
            claims[a]["replacement"] = b
        if found:
            by_page.setdefault(p["link"], []).extend(found)
    # derive inbound dependents
    for c in claims.values():
        c["dependents"] = sorted(k for k, v in claims.items() if c["id"] in v["refs"])
    return claims, by_page


def lint(claims):
    out = []
    for c in claims.values():
        for r in c["refs"]:
            if r not in claims:
                out.append(f"dangling reference: {c['id']} cites {r}, which is not published")
        if c["status"] == "withdrawn" and not c.get("replacement"):
            out.append(f"withdrawn without replacement: {c['id']}")
        if c["status"] == "active":
            for r in c["refs"]:
                if r in claims and claims[r]["status"] == "withdrawn":
                    out.append(f"active claim depends on withdrawn claim: {c['id']} -> {r}")
        if not c["grade"]:
            out.append(f"no status grade found: {c['id']} on {c['page']}")
    return out



# --- Strip lint -------------------------------------------------------------
# House rule for the evidence strip, derived from the site rather than hard-coded:
#   * the tier named must be one the Evidence Protocol defines in VII. Work-level tiers
#   * every strip links to the tier definitions anchor
#   * a work that is a node in the Theme Explorer's ate-data.works also links to
#     exactly its own ?work=<id>, and to no other node
#   * a work that is not a node carries no node-specific explorer link
PROTOCOL_PATH = "/adamic-theory/the-evidence-protocol/"
TIERS_ANCHOR = PROTOCOL_PATH + "#work-level-tiers"
STRIP_RE = re.compile(r"<p[^>]*>((?:(?!</p>).)*?Evidence tier:.*?)</p>", re.S)


def explorer_works(pages):
    """Ids of every mapped work, read from the Theme Explorer's ate-data block."""
    for p in pages:
        m = re.search(r'id="ate-data"[^>]*>(.*?)</script>', p["content"]["rendered"], re.S)
        if m:
            try:
                return {w["id"] for w in json.loads(html.unescape(m.group(1)))["works"]}
            except Exception:
                return set()
    return set()


def protocol_tiers(pages):
    """Tier names defined in VII. Work-level tiers, and whether the anchor exists."""
    for p in pages:
        raw = p["content"]["rendered"]
        if PROTOCOL_PATH not in p["link"]:
            continue
        anchor = 'id="work-level-tiers"' in raw
        sec = raw.split('id="work-level-tiers"', 1)[-1]
        sec = sec.split("VIII.", 1)[0]
        names = set()
        for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", sec, re.S):
            t = strip_tags(cell)
            m = re.fullmatch(r"([A-Z][a-z]+)(?:\s*—\s*off-bar)?", t)
            if m:
                names.add(m.group(1))
        return names - {"Tier", "Meaning"}, anchor
    return set(), False


def lint_strips(pages):
    works = explorer_works(pages)
    tiers, anchor_exists = protocol_tiers(pages)
    out = []
    if not anchor_exists:
        out.append("strip: the Evidence Protocol has no id=\"work-level-tiers\" anchor to link to")
    for p in pages:
        if "/adamic-theory/" not in p["link"]:
            continue
        raw = p["content"]["rendered"]
        title = strip_tags(p["title"]["rendered"])
        for seg in (m.group(1) for m in STRIP_RE.finditer(raw)):
            text = strip_tags(seg)
            hrefs = re.findall(r'href="([^"]+)"', seg)
            slugs = sorted(set(re.findall(r"theme-explorer/\?work=([a-z0-9-]+)", " ".join(hrefs))))
            m = re.search(r"Evidence tier:\s*([A-Za-z]+)", text)
            tier = m.group(1) if m else None

            if tier is None:
                out.append(f"strip: {title} names no tier")
            elif tiers and tier not in tiers:
                out.append(f"strip: {title} names tier '{tier}', which VII. Work-level tiers does not define")

            if not any(h.startswith(TIERS_ANCHOR) for h in hrefs):
                out.append(f"strip: {title} does not link to the tier definitions ({TIERS_ANCHOR})")

            mapped = [s for s in slugs if s in works]
            unknown = [s for s in slugs if s not in works]
            if unknown:
                out.append(f"strip: {title} links to ?work={','.join(unknown)}, not a node in ate-data.works")
            if len(mapped) > 1:
                out.append(f"strip: {title} links to more than one node: {', '.join(mapped)}")
    return out


def render_md(claims, findings):
    rows = sorted(claims.values(), key=lambda c: c["id"])
    L = [f"# Claims register — Adamic Theory System", "",
         f"Generated {date.today().isoformat()} from the published pages. Do not edit by hand.", "",
         f"{len(rows)} claims across {len({c['url'] for c in rows})} pages.", "",
         "| Claim | Grade | Status | Page | Depends on | Depended on by |",
         "|---|---|---|---|---|---|"]
    for c in rows:
        L.append(f"| [{c['id']}]({c['url']}) | {c['grade'] or '—'} | {c['status']} | {c['page']} | "
                 f"{', '.join(c['refs']) or '—'} | {', '.join(c['dependents']) or '—'} |")
    L += ["", "## Claim text", ""]
    for c in rows:
        L.append(f"**{c['id']}** — *{c['grade'] or 'ungraded'}*, {c['status']}. {c['text']}")
        if c.get("replacement"):
            L.append(f"  Replaced by {c['replacement']}.")
        L.append("")
    L += ["## Lint", ""]
    L += [f"- {f}" for f in findings] or ["- No findings."]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=".")
    a = ap.parse_args()
    pages = fetch_pages()
    claims, _ = extract(pages)
    findings = lint(claims) + lint_strips(pages)
    os.makedirs(a.out, exist_ok=True)
    json.dump({"generated": date.today().isoformat(), "claims": claims, "lint": findings},
              open(os.path.join(a.out, "claims-register.json"), "w"), indent=1, ensure_ascii=False)
    open(os.path.join(a.out, "claims-register.md"), "w", encoding="utf-8").write(render_md(claims, findings))
    print(f"{len(claims)} claims, {len(findings)} lint findings")
    for f in findings:
        print("  -", f)
    return 1 if any(f.startswith("strip:") or "dangling" in f or "depends on withdrawn" in f
                    for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
