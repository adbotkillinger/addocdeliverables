#!/usr/bin/env python3
"""Lint Adamic Theory evidence strips against the live Theme Explorer.

The live Theme Explorer is the source of truth for mapped-work IDs and work-level
status. Every evidence strip must point to the canonical Work-level tiers anchor.
Mapped works must also point back to their exact Theme Explorer node; unmapped
works must not pretend to have one.

No third-party packages are required so the check can run from GitHub Actions or
any stock Python 3.11+ installation.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

USER_AGENT = "AdamicEvidenceLint/1.0 (+https://github.com/adbotkillinger/addocdeliverables)"
PROTOCOL_PATH = "/adamic-theory/the-evidence-protocol/"
PROTOCOL_FRAGMENT = "work-level-tiers"
EXPLORER_PATH = "/adamic-theory/theme-explorer/"
TIER_NAMES = {
    "A": "Tested",
    "B": "Falsifiable",
    "C": "Graded",
    "D": "Hypothesis",
    "E": "Interpretive",
    "F": "Fiction",
    "O": "Operational",
}


@dataclass(frozen=True)
class Link:
    href: str
    text: str


@dataclass
class Result:
    errors: list[str]
    strips: int = 0
    mapped: int = 0

    def fail(self, message: str) -> None:
        self.errors.append(message)


def request_text(url: str, timeout: int) -> tuple[str, object]:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json"})
    try:
        with urlopen(req, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace"), response.headers
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"request failed for {url}: {exc}") from exc


def plain_text(markup: str) -> str:
    text = re.sub(r"<[^>]+>", " ", markup)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def normalize_path(url_or_path: str, site: str) -> str:
    parsed = urlparse(urljoin(site + "/", html.unescape(url_or_path)))
    path = re.sub(r"/+", "/", parsed.path)
    if not path.endswith("/"):
        path += "/"
    return path


def anchors(markup: str) -> list[Link]:
    links: list[Link] = []
    for match in re.finditer(
        r"<a\b[^>]*\bhref\s*=\s*([\"'])(.*?)\1[^>]*>(.*?)</a>",
        markup,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        links.append(Link(html.unescape(match.group(2)), plain_text(match.group(3))))
    return links


def evidence_strips(markup: str) -> list[str]:
    strips: list[str] = []
    for paragraph in re.findall(r"<p\b[^>]*>.*?</p>", markup, flags=re.IGNORECASE | re.DOTALL):
        text = plain_text(paragraph)
        if re.match(r"^Evidence\s+(?:tier|mode)\s*:", text, flags=re.IGNORECASE):
            strips.append(paragraph)
    return strips


def parse_tier(strip: str) -> str | None:
    text = plain_text(strip)
    match = re.match(r"^Evidence\s+(?:tier|mode)\s*:\s*([A-Za-z-]+)", text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def parse_explorer(html_text: str) -> dict:
    match = re.search(
        r"<script\b[^>]*\bid\s*=\s*([\"'])ate-data\1[^>]*>(.*?)</script>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        # Attribute order is not guaranteed.
        match = re.search(
            r"<script\b[^>]*id=[\"']ate-data[\"'][^>]*>(.*?)</script>",
            html_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            raise RuntimeError("Theme Explorer does not expose <script id=\"ate-data\">")
        payload = match.group(1)
    else:
        payload = match.group(2)
    try:
        return json.loads(html.unescape(payload).strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ate-data is not valid JSON: {exc}") from exc


def fetch_pages(site: str, timeout: int) -> list[dict]:
    pages: list[dict] = []
    page = 1
    while True:
        params = urlencode(
            {
                "per_page": 100,
                "page": page,
                "status": "publish",
                "_fields": "id,link,slug,title,content,status",
            }
        )
        url = f"{site}/wp-json/wp/v2/pages?{params}"
        try:
            body, headers = request_text(url, timeout)
        except RuntimeError as exc:
            # WordPress returns 400 when pagination advances past the final page.
            if page > 1 and "HTTP Error 400" in str(exc):
                break
            raise
        batch = json.loads(body)
        if not batch:
            break
        pages.extend(batch)
        total_pages = int(headers.get("X-WP-TotalPages", page))
        if page >= total_pages or len(batch) < 100:
            break
        page += 1
    return pages


def link_parts(href: str, site: str) -> tuple[str, str, dict[str, list[str]]]:
    parsed = urlparse(urljoin(site + "/", href))
    path = normalize_path(parsed.path, site)
    return path, parsed.fragment, parse_qs(parsed.query)


def lint(site: str, timeout: int) -> Result:
    result = Result(errors=[])
    explorer_url = site + EXPLORER_PATH
    explorer_html, _ = request_text(explorer_url, timeout)
    data = parse_explorer(explorer_html)
    works = data.get("works")
    if not isinstance(works, list) or not works:
        raise RuntimeError("ate-data contains no works array")

    result.mapped = len(works)
    work_by_path: dict[str, dict] = {}
    work_ids: set[str] = set()

    for work in works:
        wid = str(work.get("id", "")).strip()
        tier = str(work.get("tier", "")).strip()
        url = str(work.get("url", "")).strip()
        title = str(work.get("title", wid)).strip()
        if not wid:
            result.fail(f"Explorer work {title!r} has no id")
            continue
        if wid in work_ids:
            result.fail(f"Explorer contains duplicate work id {wid!r}")
        work_ids.add(wid)
        if tier not in TIER_NAMES:
            result.fail(f"Explorer work {wid!r} has unknown tier {tier!r}")
        if not url:
            result.fail(f"Explorer work {wid!r} has no URL")
            continue
        path = normalize_path(url, site)
        if path in work_by_path:
            result.fail(f"Explorer maps more than one work to {path}")
        work_by_path[path] = work

    pages = fetch_pages(site, timeout)
    page_by_path = {normalize_path(p.get("link", ""), site): p for p in pages if p.get("link")}
    strips_by_path: dict[str, list[str]] = {}

    for path, page in page_by_path.items():
        rendered = ((page.get("content") or {}).get("rendered") or "")
        strips = evidence_strips(rendered)
        if not strips:
            continue
        strips_by_path[path] = strips
        result.strips += len(strips)
        title = plain_text(((page.get("title") or {}).get("rendered") or page.get("slug") or path))

        if len(strips) != 1:
            result.fail(f"{title}: expected one evidence strip, found {len(strips)}")

        for strip in strips:
            strip_links = anchors(strip)
            protocol_links = []
            explorer_links = []
            for link in strip_links:
                lpath, fragment, query = link_parts(link.href, site)
                if lpath == PROTOCOL_PATH:
                    protocol_links.append((link, fragment))
                if lpath == EXPLORER_PATH:
                    explorer_links.append((link, query))

            if len(protocol_links) != 1:
                result.fail(f"{title}: evidence strip must contain exactly one Evidence Protocol link")
            elif protocol_links[0][1] != PROTOCOL_FRAGMENT:
                result.fail(
                    f"{title}: Evidence Protocol link must end in #{PROTOCOL_FRAGMENT}; "
                    f"found {protocol_links[0][0].href!r}"
                )

            mapped = work_by_path.get(path)
            if mapped:
                expected_id = str(mapped["id"])
                if len(explorer_links) != 1:
                    result.fail(f"{title}: mapped work must contain exactly one Theme Explorer link")
                else:
                    values = explorer_links[0][1].get("work", [])
                    if values != [expected_id]:
                        result.fail(
                            f"{title}: Theme Explorer link must use ?work={expected_id}; "
                            f"found {explorer_links[0][0].href!r}"
                        )
                found_tier = parse_tier(strip)
                expected_tier = TIER_NAMES.get(str(mapped.get("tier", "")))
                if not found_tier:
                    result.fail(f"{title}: could not parse evidence tier from strip")
                elif expected_tier and found_tier.casefold() != expected_tier.casefold():
                    result.fail(
                        f"{title}: strip says {found_tier!r} but explorer says {expected_tier!r}"
                    )
            elif explorer_links:
                result.fail(f"{title}: unmapped work must not use a work-specific Theme Explorer link")

    for path, work in work_by_path.items():
        title = str(work.get("title", work.get("id", path)))
        if path not in page_by_path:
            result.fail(f"{title}: explorer URL does not match a published WordPress page ({path})")
        elif path not in strips_by_path:
            result.fail(f"{title}: mapped work has no evidence strip")

    return result


def write_summary(result: Result) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("## Adamic evidence-link lint\n\n")
        handle.write(f"- Mapped works: **{result.mapped}**\n")
        handle.write(f"- Evidence strips: **{result.strips}**\n")
        handle.write(f"- Errors: **{len(result.errors)}**\n")
        if result.errors:
            handle.write("\n### Drift\n\n")
            for error in result.errors:
                handle.write(f"- {error}\n")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", default="https://addocdeliverables.ca", help="WordPress site root")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds")
    args = parser.parse_args(argv)
    site = args.site.rstrip("/")

    try:
        result = lint(site, args.timeout)
    except Exception as exc:  # network/schema failures should fail CI loudly
        print(f"ERROR: lint could not run: {exc}", file=sys.stderr)
        return 2

    for error in result.errors:
        print(f"ERROR: {error}")
    print(
        f"lint: {len(result.errors)} errors across {result.strips} evidence strips "
        f"and {result.mapped} mapped works"
    )
    write_summary(result)
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
