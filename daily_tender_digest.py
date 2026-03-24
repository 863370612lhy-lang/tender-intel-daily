from __future__ import annotations

import json
import os
import re
import smtplib
import sys
import csv
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse
from zoneinfo import ZoneInfo

import openpyxl
import requests
from bs4 import BeautifulSoup
from openpyxl.utils.datetime import from_excel

try:
    from google import genai
    from google.genai import types
except Exception:  # noqa: BLE001
    genai = None
    types = None


ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT / "docs"
SOURCE_CATALOG_FILE = ROOT / "source-catalog.json"
DATA_FILE = DOCS_DIR / "latest.json"
SALES_DATA_FILE = DOCS_DIR / "sales-top.json"
SALES_CSV_FILE = DOCS_DIR / "sales-leads.csv"
INDEX_FILE = DOCS_DIR / "index.html"
EXECUTIVE_FILE = DOCS_DIR / "executive.html"
SALES_VIEW_FILE = DOCS_DIR / "sales.html"
ARCHIVE_DIR = DOCS_DIR / "archive"
ARCHIVE_INDEX_FILE = ARCHIVE_DIR / "index.html"
NOJEKYLL_FILE = DOCS_DIR / ".nojekyll"

DEFAULT_MODEL = "gemini-2.5-flash-lite"
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_TIMEOUT = 20
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_PAGE_LIMIT = 3
DEFAULT_MAX_ITEMS = 120
DEFAULT_SEARCH_RECENCY = "m"
DEFAULT_EMAIL_ITEM_LIMIT = 20
DEFAULT_EMAIL_TO = "863370612lhy@gmail.com"
DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 465

NOTICE_TERMS = [
    "招标",
    "采购",
    "公告",
    "磋商",
    "询价",
    "比选",
    "竞价",
    "竞争性",
    "公开招标",
]

KEYWORD_GROUPS = {
    "Direct Tobacco": [
        "烟草",
        "烟草公司",
        "中烟",
        "文明吸烟环境",
        "吸烟室",
        "吸烟亭",
        "吸烟筒",
    ],
    "Adjacent Space": [
        "移动公厕",
        "移动厕所",
        "公厕",
        "厕所",
        "垃圾房",
        "集装箱",
        "厢房",
        "箱房",
        "岗亭",
        "模块化房",
    ],
}

SEARCH_KEYWORDS = [
    "文明吸烟环境",
    "文明吸烟环境建设",
    "吸烟室",
    "吸烟亭",
    "烟草公司",
    "烟草专卖局",
    "烟草机械",
    "移动公厕",
    "移动厕所",
    "垃圾房",
    "集装箱厢房",
    "箱房",
    "岗亭",
]

OFFICIAL_SOURCES = [
    {
        "name": "China Government Procurement",
        "kind": "official",
        "homepage": "https://www.ccgp.gov.cn/",
        "search_url": "https://search.ccgp.gov.cn/bxsearch",
        "parser": "ccgp",
    },
    {
        "name": "National Public Resource Trading Platform",
        "kind": "official",
        "homepage": "https://deal.ggzy.gov.cn/ds/deal/dealList.jsp",
        "search_url": "https://deal.ggzy.gov.cn/ds/deal/dealList.jsp",
        "parser": "ggzy",
    },
]

SOURCE_HEALTH: dict[str, dict[str, Any]] = {}
SEARCH_FALLBACK_SOURCE = {
    "name": "Yahoo Search Fallback",
    "kind": "search-fallback",
    "homepage": "https://search.yahoo.com/",
}
YAHOO_SITE_QUERIES = [
    ("site:ggzy.gov.cn", "烟草公司 招标公告", ["烟草", "中烟"]),
    ("site:gov.cn", "烟草公司 招标公告", ["烟草", "中烟"]),
    ("site:ggzy.gov.cn", "中国烟草 招标公告", ["烟草", "中烟"]),
    ("site:ggzy.gov.cn", "文明吸烟环境 招标", ["文明吸烟环境", "吸烟"]),
    ("site:gov.cn", "文明吸烟环境 招标", ["文明吸烟环境", "吸烟"]),
    ("site:ggzy.gov.cn", "吸烟室 招标", ["吸烟室"]),
    ("site:ggzy.gov.cn", "吸烟亭 招标", ["吸烟亭"]),
    ("site:gov.cn", "移动公厕 招标 公告", ["移动公厕", "移动厕所", "公厕", "厕所"]),
    ("site:gov.cn", "垃圾房 招标 公告", ["垃圾房"]),
    ("site:gov.cn", "集装箱厢房 招标 公告", ["集装箱", "厢房", "箱房"]),
]
OFFICIAL_DOMAIN_HINTS = [
    "ggzy.gov.cn",
    "ccgp.gov.cn",
    "gov.cn",
    "tobacco.gov.cn",
]
DEFAULT_SEARCH_SITE_SEEDS = [
    {
        "name": "National Public Resource Trading Platform",
        "domain": "ggzy.gov.cn",
        "queries": [
            ("烟草公司 招标公告", ["烟草", "中烟"]),
            ("文明吸烟环境 招标", ["文明吸烟环境", "吸烟"]),
            ("吸烟室 招标", ["吸烟室"]),
            ("吸烟亭 招标", ["吸烟亭"]),
        ],
    },
    {
        "name": "Government Portals",
        "domain": "gov.cn",
        "queries": [
            ("烟草公司 招标公告", ["烟草", "中烟"]),
            ("文明吸烟环境 招标", ["文明吸烟环境", "吸烟"]),
            ("移动公厕 招标 公告", ["移动公厕", "移动厕所", "公厕", "厕所"]),
            ("垃圾房 招标 公告", ["垃圾房"]),
            ("集装箱厢房 招标 公告", ["集装箱", "厢房", "箱房"]),
        ],
    },
]


@dataclass
class TenderItem:
    id: int
    title: str
    source_name: str
    source_kind: str
    source_url: str
    search_url: str
    query_keyword: str
    published: str = ""
    region: str = ""
    amount: str = ""
    snippet: str = ""
    tags: list[str] = field(default_factory=list)
    score: int = 0
    priority: str = "Watch"
    opportunity_type: str = "Monitor"
    summary: str = ""
    sales_angle: str = ""
    next_action: str = ""


def load_source_catalog() -> dict[str, Any]:
    if not SOURCE_CATALOG_FILE.exists():
        return {}
    try:
        return json.loads(SOURCE_CATALOG_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def extract_domain_from_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower()


def get_official_domain_hints() -> list[str]:
    hints = set(OFFICIAL_DOMAIN_HINTS)
    catalog = load_source_catalog()

    for group_name in ("active_sources", "next_sources_to_add", "seed_sources"):
        for source in catalog.get(group_name, []):
            homepage = source.get("homepage", "")
            domain = source.get("domain", "")
            if homepage:
                hints.add(extract_domain_from_url(homepage))
            if domain:
                hints.add(domain.lower())

    return sorted(hint for hint in hints if hint)


def build_seed_site_queries() -> list[tuple[str, str, list[str]]]:
    catalog = load_source_catalog()
    seeds = [*DEFAULT_SEARCH_SITE_SEEDS]
    seeds.extend(catalog.get("seed_sources", []))

    queries: list[tuple[str, str, list[str]]] = []
    seen: set[str] = set()
    for seed in seeds:
        domain = clean_text(seed.get("domain", "")).lower()
        if not domain:
            continue
        for query in seed.get("queries", []):
            if isinstance(query, tuple):
                terms = clean_text(query[0] if len(query) > 0 else "")
                required_terms = [clean_text(term) for term in (query[1] if len(query) > 1 else []) if clean_text(term)]
            else:
                terms = clean_text(query.get("terms", ""))
                required_terms = [clean_text(term) for term in query.get("required_terms", []) if clean_text(term)]
            if not terms or not required_terms:
                continue
            dedupe_key = f"{domain}|{terms}|{'/'.join(required_terms)}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            queries.append((f"site:{domain}", terms, required_terms))
    return queries


def getenv_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def init_source_health() -> None:
    SOURCE_HEALTH.clear()
    for source in OFFICIAL_SOURCES:
        SOURCE_HEALTH[source["name"]] = {
            "name": source["name"],
            "kind": source["kind"],
            "homepage": source["homepage"],
            "status": "unknown",
            "success_count": 0,
            "failure_count": 0,
            "last_error": "",
        }
    SOURCE_HEALTH[SEARCH_FALLBACK_SOURCE["name"]] = {
        "name": SEARCH_FALLBACK_SOURCE["name"],
        "kind": SEARCH_FALLBACK_SOURCE["kind"],
        "homepage": SEARCH_FALLBACK_SOURCE["homepage"],
        "status": "unknown",
        "success_count": 0,
        "failure_count": 0,
        "last_error": "",
    }


def record_source_success(source_name: str, increment: int = 1) -> None:
    item = SOURCE_HEALTH[source_name]
    item["status"] = "ok"
    item["success_count"] += increment


def record_source_failure(source_name: str, error: str) -> None:
    item = SOURCE_HEALTH[source_name]
    item["failure_count"] += 1
    if item["status"] != "ok":
        item["status"] = "error"
    item["last_error"] = error[:280]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def looks_like_notice(text: str) -> bool:
    normalized = clean_text(text)
    if len(normalized) < 8:
        return False
    if normalized in {"首页", "上一页", "下一页"}:
        return False
    return any(term in normalized for term in NOTICE_TERMS)


def extract_amount(text: str) -> str:
    match = re.search(r"(\d[\d,\.]*\s*(?:万元|万|元|人民币))", text)
    return match.group(1) if match else ""


def extract_date(text: str) -> str:
    for pattern in [r"(\d{4}-\d{2}-\d{2})", r"(\d{4}/\d{2}/\d{2})", r"(\d{4}年\d{1,2}月\d{1,2}日)"]:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""


def extract_region(text: str) -> str:
    match = re.search(
        r"((?:内蒙古|广西|宁夏|新疆|西藏)?[\u4e00-\u9fff]{1,10}(?:省|市|自治区|区|县|州))",
        text,
    )
    return match.group(1) if match else ""


def contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def classify_item(item: TenderItem) -> TenderItem:
    blob = " ".join([item.title, item.snippet])
    tags: list[str] = []
    score = 0

    if contains_any(blob, KEYWORD_GROUPS["Direct Tobacco"]):
        tags.append("tobacco")
        score += 4
    if "文明吸烟环境" in blob:
        tags.append("smoking-environment")
        score += 3
    if "吸烟室" in blob or "吸烟亭" in blob:
        tags.append("smoking-space")
        score += 2
    if contains_any(blob, KEYWORD_GROUPS["Adjacent Space"]):
        tags.append("adjacent-space")
        score += 1
    if item.source_kind == "official":
        tags.append("official-source")
        score += 1

    item.score = score
    item.tags = list(dict.fromkeys(tags))

    if score >= 7:
        item.priority = "High"
        item.opportunity_type = "Direct"
    elif score >= 4:
        item.priority = "Medium"
        item.opportunity_type = "Direct"
    elif "adjacent-space" in item.tags:
        item.priority = "Watch"
        item.opportunity_type = "Adjacent"
    else:
        item.priority = "Watch"
        item.opportunity_type = "Monitor"

    buyer_hint = "tobacco system" if "tobacco" in item.tags else "public procurement"
    item.summary = (
        f"{buyer_hint} notice matched keyword '{item.query_keyword}' on {item.source_name}. "
        "Review the source page for scope, deadline, and bid-book purchase instructions."
    )
    item.sales_angle = (
        "Prioritize direct contact when the notice is tobacco-related or explicitly mentions smoking spaces."
    )
    item.next_action = (
        "Open the source notice, verify the buyer, purchase window, and required qualification documents."
    )
    return item


def build_ccgp_query(keyword: str, page: int, start_date: str, end_date: str) -> tuple[str, dict[str, str]]:
    params = {
        "searchtype": "1",
        "page_index": str(page),
        "bidType": "7",
        "dbselect": "bidx",
        "kw": keyword,
        "start_time": start_date,
        "end_time": end_date,
        "timeType": "6",
    }
    return OFFICIAL_SOURCES[0]["search_url"], params


def build_ggzy_query(keyword: str, page: int, start_date: str, end_date: str) -> tuple[str, dict[str, str]]:
    params = {
        "TIMEBEGIN_SHOW": start_date,
        "TIMEEND_SHOW": end_date,
        "TIMEBEGIN": start_date,
        "TIMEEND": end_date,
        "DEAL_TIME": "02",
        "FINDTXT": keyword,
        "currentPage": str(page),
        "pageNo": str(page),
    }
    return OFFICIAL_SOURCES[1]["search_url"], params


def fetch_html(url: str, params: dict[str, str]) -> str:
    headers = {
        "User-Agent": "tender-intel-daily/1.0 (+public-source-monitoring)",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    response = requests.get(
        url,
        params=params,
        headers=headers,
        timeout=getenv_int("REQUEST_TIMEOUT_SECONDS", DEFAULT_TIMEOUT),
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def parse_ccgp_results(html: str, keyword: str, search_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    nodes = soup.select("ul.vT-srch-result-list li")
    if not nodes:
        nodes = [node for node in soup.select("li") if keyword in node.get_text(" ", strip=True)]

    parsed: list[dict[str, str]] = []
    for node in nodes:
        anchor = node.find("a", href=True)
        if not anchor:
            continue
        title = clean_text(anchor.get_text(" ", strip=True))
        href = urljoin(search_url, anchor["href"])
        blob = clean_text(node.get_text(" ", strip=True))
        if not looks_like_notice(title):
            continue
        parsed.append(
            {
                "title": title,
                "url": href,
                "published": extract_date(blob),
                "region": extract_region(blob),
                "amount": extract_amount(blob),
                "snippet": blob[:360],
            }
        )
    return parsed


def parse_ggzy_results(html: str, keyword: str, search_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.select("a[href]")
    parsed: list[dict[str, str]] = []

    for anchor in anchors:
        title = clean_text(anchor.get_text(" ", strip=True))
        href = urljoin(search_url, anchor.get("href", ""))
        blob = clean_text(anchor.parent.get_text(" ", strip=True) if anchor.parent else title)
        if not href.startswith("http"):
            continue
        if keyword not in f"{title} {blob}" and not looks_like_notice(title):
            continue
        if not looks_like_notice(title):
            continue
        parsed.append(
            {
                "title": title,
                "url": href,
                "published": extract_date(blob),
                "region": extract_region(blob or title),
                "amount": extract_amount(blob),
                "snippet": blob[:360],
            }
        )
    return parsed


def decode_yahoo_redirect(href: str) -> str:
    parsed = urlparse(href)
    if "r.search.yahoo.com" not in parsed.netloc:
        return href
    query = parse_qs(parsed.query)
    ru_values = query.get("RU")
    if ru_values:
        return unquote(ru_values[0])
    parts = href.split("/RU=")
    if len(parts) < 2:
        return href
    ru_part = parts[1].split("/RK=")[0]
    return unquote(ru_part)


def is_official_notice_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(hint in host for hint in get_official_domain_hints())


def build_yahoo_queries() -> list[str]:
    all_queries = [*YAHOO_SITE_QUERIES, *build_seed_site_queries()]
    deduped: list[str] = []
    seen: set[str] = set()
    for site_scope, terms, _ in all_queries:
        query = f"{site_scope} {terms}"
        if query in seen:
            continue
        seen.add(query)
        deduped.append(query)
    return deduped


def has_required_terms(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def collect_yahoo_fallback_items() -> list[TenderItem]:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    items: list[TenderItem] = []
    counter = 100000
    recency = os.getenv("SEARCH_RECENCY", DEFAULT_SEARCH_RECENCY)

    all_queries = [*YAHOO_SITE_QUERIES, *build_seed_site_queries()]
    seen_queries: set[str] = set()

    for site_scope, terms, required_terms in all_queries:
        query = f"{site_scope} {terms}"
        if query in seen_queries:
            continue
        seen_queries.add(query)
        try:
            response = requests.get(
                "https://search.yahoo.com/search",
                params={"p": query, "btf": recency, "nojs": "1"},
                headers=headers,
                timeout=getenv_int("REQUEST_TIMEOUT_SECONDS", DEFAULT_TIMEOUT),
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            record_source_failure(SEARCH_FALLBACK_SOURCE["name"], str(exc))
            print(f"[warn] Failed Yahoo fallback query={query}: {exc}", file=sys.stderr)
            continue

        response.encoding = response.apparent_encoding or response.encoding
        soup = BeautifulSoup(response.text, "html.parser")
        found = 0

        for anchor in soup.find_all("a", href=True):
            title = clean_text(anchor.get_text(" ", strip=True))
            if not looks_like_notice(title):
                continue

            source_url = decode_yahoo_redirect(anchor["href"])
            if not source_url.startswith("http") or not is_official_notice_url(source_url):
                continue

            context = clean_text(anchor.parent.get_text(" ", strip=True) if anchor.parent else title)
            evidence = f"{title} {context}"
            if not has_required_terms(evidence, required_terms):
                continue
            item = TenderItem(
                id=counter,
                title=title,
                source_name=SEARCH_FALLBACK_SOURCE["name"],
                source_kind=SEARCH_FALLBACK_SOURCE["kind"],
                source_url=source_url,
                search_url=response.url,
                query_keyword=query,
                published=extract_date(context),
                region=extract_region(context or title),
                amount=extract_amount(context),
                snippet=context[:360],
            )
            items.append(classify_item(item))
            counter += 1
            found += 1

        if found:
            record_source_success(SEARCH_FALLBACK_SOURCE["name"], found)
        else:
            record_source_failure(SEARCH_FALLBACK_SOURCE["name"], f"No result extracted for query: {query}")

    deduped = dedupe_items(items)
    deduped.sort(key=lambda item: (item.score, item.published, item.title), reverse=True)
    return deduped[: getenv_int("MAX_ITEMS", DEFAULT_MAX_ITEMS)]


def enrich_source_page(item: TenderItem) -> TenderItem:
    if os.getenv("ENRICH_SOURCE_PAGES", "1") not in {"1", "true", "TRUE"}:
        return item

    try:
        response = requests.get(
            item.source_url,
            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
            timeout=getenv_int("REQUEST_TIMEOUT_SECONDS", DEFAULT_TIMEOUT),
        )
        response.raise_for_status()
    except Exception:
        return item

    response.encoding = response.apparent_encoding or response.encoding
    soup = BeautifulSoup(response.text, "html.parser")
    page_title = clean_text((soup.title.get_text(" ", strip=True) if soup.title else ""))
    h1 = clean_text((soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else ""))
    body_text = clean_text(soup.get_text(" ", strip=True))

    preferred_title = h1 or page_title
    if preferred_title and len(preferred_title) >= 8 and looks_like_notice(preferred_title):
        item.title = preferred_title

    if not item.published:
        item.published = extract_date(body_text)
    if not item.amount:
        item.amount = extract_amount(body_text)
    if not item.region:
        item.region = extract_region(body_text)
    if body_text:
        item.snippet = body_text[:360]

    return classify_item(item)


def dedupe_items(items: list[TenderItem]) -> list[TenderItem]:
    seen: set[str] = set()
    deduped: list[TenderItem] = []
    for item in items:
        normalized_title = re.sub(r"\s+", "", item.title.lower())
        key = f"{item.source_url.lower()}::{normalized_title}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def collect_live_items() -> list[TenderItem]:
    init_source_health()
    now = datetime.now(UTC).astimezone(ZoneInfo(DEFAULT_TIMEZONE))
    end_date = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=getenv_int("LOOKBACK_DAYS", DEFAULT_LOOKBACK_DAYS))).strftime(
        "%Y-%m-%d"
    )
    page_limit = getenv_int("SOURCE_PAGE_LIMIT", DEFAULT_PAGE_LIMIT)

    collected: list[TenderItem] = []
    counter = 1

    for source in OFFICIAL_SOURCES:
        for keyword in SEARCH_KEYWORDS:
            for page in range(1, page_limit + 1):
                if source["parser"] == "ccgp":
                    request_url, params = build_ccgp_query(keyword, page, start_date, end_date)
                else:
                    request_url, params = build_ggzy_query(keyword, page, start_date, end_date)

                search_url = f"{request_url}?{urlencode(params)}"
                try:
                    html = fetch_html(request_url, params)
                except Exception as exc:  # noqa: BLE001
                    record_source_failure(source["name"], str(exc))
                    print(
                        f"[warn] Failed {source['name']} keyword={keyword} page={page}: {exc}",
                        file=sys.stderr,
                    )
                    continue

                if source["parser"] == "ccgp":
                    parsed = parse_ccgp_results(html, keyword, request_url)
                else:
                    parsed = parse_ggzy_results(html, keyword, request_url)

                if parsed:
                    record_source_success(source["name"], len(parsed))

                for raw in parsed:
                    item = TenderItem(
                        id=counter,
                        title=raw["title"],
                        source_name=source["name"],
                        source_kind=source["kind"],
                        source_url=raw["url"],
                        search_url=search_url,
                        query_keyword=keyword,
                        published=raw["published"],
                        region=raw["region"],
                        amount=raw["amount"],
                        snippet=raw["snippet"],
                    )
                    collected.append(classify_item(item))
                    counter += 1

    deduped = dedupe_items(collected)
    deduped.sort(key=lambda item: (item.score, item.published, item.title), reverse=True)
    return deduped[: getenv_int("MAX_ITEMS", DEFAULT_MAX_ITEMS)]


def workbook_date_to_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (int, float)):
        try:
            converted = from_excel(value)
        except Exception:
            return clean_text(value)
        if isinstance(converted, datetime):
            return converted.strftime("%Y-%m-%d")
    return clean_text(value)


def first_url_from_row(row: tuple[Any, ...]) -> str:
    for cell in row:
        text = clean_text(cell)
        if text.startswith("http://") or text.startswith("https://"):
            return text.replace(" ", "")
    return ""


def load_items_from_workbook(path: Path) -> list[TenderItem]:
    init_source_health()
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    items: list[TenderItem] = []
    counter = 1

    for sheet in workbook.worksheets:
        rows = list(sheet.iter_rows(values_only=True))
        for row in rows[2:]:
            if not any(cell not in (None, "") for cell in row):
                continue
            title = clean_text(row[3] if len(row) > 3 else "")
            if not title:
                continue
            url = first_url_from_row(row)
            item = TenderItem(
                id=counter,
                title=title,
                source_name="Workbook Demo",
                source_kind="sample",
                source_url=url or "https://example.com/source-missing",
                search_url=str(path),
                query_keyword=sheet.title,
                published=workbook_date_to_text(row[6] if len(row) > 6 else ""),
                region=" / ".join(
                    part
                    for part in [
                        clean_text(row[1] if len(row) > 1 else ""),
                        clean_text(row[2] if len(row) > 2 else ""),
                    ]
                    if part
                ),
                amount=clean_text(row[4] if len(row) > 4 else ""),
                snippet=clean_text(row[5] if len(row) > 5 else ""),
            )
            items.append(classify_item(item))
            counter += 1

    items.sort(key=lambda item: (item.score, item.published, item.title), reverse=True)
    return items[: getenv_int("MAX_ITEMS", DEFAULT_MAX_ITEMS)]


def enrich_with_gemini(items: list[TenderItem]) -> tuple[dict[str, str], list[TenderItem]]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or genai is None or types is None or not items:
        summary = {
            "page_title": "招标雷达 Tender Radar",
            "page_subtitle": "烟草吸烟空间与相邻模块化空间公开项目监测 / Public-source feed for smoking-space and adjacent-space projects.",
            "overview": (
                f"本次共采集 {len(items)} 条公开项目，优先跟进烟草系统与吸烟空间直接机会。 "
                f"/ {len(items)} public notices collected; prioritize tobacco-system and smoking-space direct-fit opportunities first."
            ),
        }
        return summary, items

    payload = []
    for item in items[:12]:
        payload.append(
            {
                "id": item.id,
                "title": item.title,
                "source": item.source_name,
                "published": item.published,
                "region": item.region,
                "keyword": item.query_keyword,
                "priority": item.priority,
                "snippet": item.snippet,
            }
        )

    schema = {
        "type": "object",
        "properties": {
            "page_title": {"type": "string"},
            "page_subtitle": {"type": "string"},
            "overview": {"type": "string"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "summary": {"type": "string"},
                        "sales_angle": {"type": "string"},
                        "next_action": {"type": "string"},
                    },
                    "required": ["id", "summary", "sales_angle", "next_action"],
                },
            },
        },
        "required": ["page_title", "page_subtitle", "overview", "items"],
    }

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=os.getenv("GEMINI_MODEL", DEFAULT_MODEL),
        contents=(
            "Create a concise Chinese tender briefing for a company that sells smoking rooms, smoking booths, "
            "and adjacent modular space products. Use only supplied notice metadata.\n\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        ),
        config=types.GenerateContentConfig(
            system_instruction=(
                "You are a careful B2B tender analyst. Do not invent facts. "
                "Write sharp, practical Chinese summaries for sales teams."
            ),
            temperature=0.2,
            response_mime_type="application/json",
            response_json_schema=schema,
        ),
    )
    if not response.text:
        raise RuntimeError("Gemini returned an empty response.")

    parsed = json.loads(response.text)
    by_id = {item.id: item for item in items}
    for enriched in parsed.get("items", []):
        item = by_id.get(enriched["id"])
        if not item:
            continue
        item.summary = enriched["summary"]
        item.sales_angle = enriched["sales_angle"]
        item.next_action = enriched["next_action"]

    return {
        "page_title": parsed["page_title"],
        "page_subtitle": parsed["page_subtitle"],
        "overview": parsed["overview"],
    }, items


def build_payload(items: list[TenderItem], ai_summary: dict[str, str]) -> dict[str, Any]:
    priority_counts: dict[str, int] = {"High": 0, "Medium": 0, "Watch": 0}
    source_counts: dict[str, int] = {}
    source_health = list(SOURCE_HEALTH.values())
    catalog = load_source_catalog()

    for item in items:
        priority_counts[item.priority] = priority_counts.get(item.priority, 0) + 1
        source_counts[item.source_name] = source_counts.get(item.source_name, 0) + 1

    direct_items = [item for item in items if item.opportunity_type == "Direct"]
    direct_items.sort(key=lambda item: (item.score, item.published, item.title), reverse=True)
    adjacent_items = [item for item in items if item.opportunity_type == "Adjacent"]
    adjacent_items.sort(key=lambda item: (item.score, item.published, item.title), reverse=True)
    source_page_limit = getenv_int("SOURCE_PAGE_LIMIT", DEFAULT_PAGE_LIMIT)
    official_query_count = len(OFFICIAL_SOURCES) * len(SEARCH_KEYWORDS) * source_page_limit

    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "generated_at_local": datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).strftime("%Y-%m-%d %H:%M"),
        "report_date": datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).strftime("%Y-%m-%d"),
        "lookback_days": getenv_int("LOOKBACK_DAYS", DEFAULT_LOOKBACK_DAYS),
        "summary": ai_summary,
        "stats": {
            "total_items": len(items),
            "high_priority": priority_counts.get("High", 0),
            "medium_priority": priority_counts.get("Medium", 0),
            "direct_opportunities": sum(1 for item in items if item.opportunity_type == "Direct"),
            "source_count": len(source_counts),
        },
        "coverage": {
            "active_source_count": len(OFFICIAL_SOURCES),
            "seed_source_count": len(catalog.get("seed_sources", [])),
            "healthy_source_count": sum(1 for item in source_health if item.get("status") == "ok"),
            "error_source_count": sum(1 for item in source_health if item.get("status") == "error"),
            "official_query_count": official_query_count,
            "fallback_query_count": len(build_yahoo_queries()),
        },
        "source_counts": source_counts,
        "source_health": source_health,
        "top_direct_items": [asdict(item) for item in direct_items[:6]],
        "watch_items": [asdict(item) for item in adjacent_items[:8]],
        "items": [asdict(item) for item in items],
    }


def build_sales_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sales_items = [
        item
        for item in payload["items"]
        if item["opportunity_type"] == "Direct" and item["priority"] in {"High", "Medium"}
    ]
    sales_items.sort(
        key=lambda item: (
            1 if item["priority"] == "High" else 0,
            item.get("published", ""),
            item.get("title", ""),
        ),
        reverse=True,
    )
    return {
        "generated_at": payload["generated_at"],
        "report_date": payload["report_date"],
        "summary": {
            "title": "销售优先线索 Sales Priority Leads",
            "subtitle": "适合销售立即跟进的直接匹配公开项目 / Direct-fit public tender leads for immediate follow-up.",
            "lead_count": len(sales_items),
        },
        "items": sales_items,
    }


def render_html(payload: dict[str, Any]) -> str:
    data_json = json.dumps(payload, ensure_ascii=False)
    template = """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
    <meta name="description" content="{subtitle}" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600;700&family=Manrope:wght@400;500;600;700;800&family=Noto+Sans+SC:wght@400;500;700;900&display=swap"
      rel="stylesheet"
    />
    <style>
      :root { --bg:#09111a; --panel:rgba(11,20,30,.8); --panel-strong:rgba(9,16,24,.94); --line:rgba(131,181,221,.14); --text:#f7fbff; --muted:#95aabd; --mint:#83f3d7; --gold:#f6cd87; --blue:#89bfff; --shadow:0 28px 85px rgba(0,0,0,.34); }
      * { box-sizing:border-box; }
      body { margin:0; color:var(--text); background:radial-gradient(circle at 12% 18%, rgba(131,243,215,.16), transparent 26%), radial-gradient(circle at 86% 16%, rgba(246,205,135,.14), transparent 22%), radial-gradient(circle at 55% 100%, rgba(137,191,255,.12), transparent 24%), linear-gradient(180deg, #09111a 0%, #0b1622 54%, #050b12 100%); font-family:"Noto Sans SC","Manrope",sans-serif; }
      .shell { width:min(1340px, calc(100% - 28px)); margin:0 auto; padding:22px 0 48px; }
      .nav { display:flex; justify-content:space-between; align-items:center; gap:16px; padding:16px 18px; border:1px solid var(--line); border-radius:22px; background:rgba(8,14,22,.68); box-shadow:var(--shadow); backdrop-filter:blur(16px); }
      .brand { display:flex; align-items:center; gap:12px; font-family:"Manrope",sans-serif; font-size:12px; font-weight:800; letter-spacing:.14em; text-transform:uppercase; }
      .brand-dot { width:12px; height:12px; border-radius:999px; background:linear-gradient(135deg, var(--gold), var(--mint)); box-shadow:0 0 18px rgba(131,243,215,.66); }
      .nav-meta { color:var(--muted); font-size:13px; }
      .hero { margin-top:24px; display:grid; grid-template-columns:1.12fr .88fr; gap:20px; }
      .hero-main,.hero-side { border:1px solid var(--line); border-radius:32px; background:var(--panel); box-shadow:var(--shadow); backdrop-filter:blur(18px); }
      .hero-main { padding:30px; position:relative; overflow:hidden; }
      .hero-main::after { content:""; position:absolute; inset:auto -12% -26% auto; width:310px; height:310px; border-radius:999px; background:radial-gradient(circle, rgba(131,243,215,.24), transparent 65%); }
      .eyebrow { margin:0; color:var(--mint); font-size:12px; font-family:"Manrope",sans-serif; font-weight:800; letter-spacing:.18em; text-transform:uppercase; }
      h1 { margin:14px 0 12px; font-family:"Cormorant Garamond",serif; font-size:clamp(44px, 6vw, 78px); line-height:.92; font-weight:600; }
      .hero-subtitle { margin:0; max-width:760px; font-size:clamp(17px, 2vw, 23px); line-height:1.8; }
      .hero-overview { margin-top:16px; max-width:760px; color:var(--muted); font-size:14px; line-height:1.9; }
      .stat-grid { margin-top:24px; display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:12px; }
      .stat { padding:16px; border-radius:18px; border:1px solid rgba(255,255,255,.06); background:rgba(255,255,255,.03); }
      .stat span { display:block; color:var(--muted); font-size:11px; font-weight:700; letter-spacing:.12em; text-transform:uppercase; }
      .stat strong { display:block; margin-top:8px; font-size:28px; font-family:"Manrope",sans-serif; font-weight:800; }
      .hero-side { padding:24px; }
      .panel-title { margin:0 0 14px; color:var(--muted); font-size:12px; font-weight:800; letter-spacing:.14em; text-transform:uppercase; }
      .rank-list { display:grid; gap:12px; }
      .rank-item { display:flex; justify-content:space-between; gap:12px; padding:14px 16px; border-radius:18px; border:1px solid rgba(255,255,255,.06); background:rgba(255,255,255,.03); }
      .rank-count { color:var(--gold); font-family:"Manrope",sans-serif; font-weight:800; }
      .filters { display:grid; grid-template-columns:1.2fr .8fr .8fr; gap:12px; margin-top:26px; }
      .filter-box { padding:14px 16px; border:1px solid var(--line); border-radius:18px; background:rgba(8,15,24,.72); }
      .filter-box label { display:block; margin-bottom:8px; color:var(--muted); font-size:12px; }
      .filter-box input,.filter-box select { width:100%; border:none; outline:none; color:var(--text); background:transparent; font-size:15px; }
      .filter-box option { color:#08111a; }
      .section-head { display:flex; justify-content:space-between; align-items:baseline; gap:12px; margin:32px 0 16px; }
      .section-head h2 { margin:0; font-size:18px; font-family:"Manrope",sans-serif; letter-spacing:.14em; text-transform:uppercase; }
      .section-head span { color:var(--muted); font-size:13px; }
      .grid { display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:18px; }
      .card { border:1px solid var(--line); border-radius:28px; overflow:hidden; background:var(--panel-strong); box-shadow:var(--shadow); }
      .card-top { position:relative; padding:20px; background:radial-gradient(circle at 80% 20%, rgba(255,255,255,.08), transparent 18%), linear-gradient(135deg, rgba(255,255,255,.02), rgba(255,255,255,.08)); }
      .accent { position:absolute; inset:0 auto auto 0; width:100%; height:4px; background:var(--accent, var(--mint)); }
      .badge-row { display:flex; flex-wrap:wrap; gap:8px; }
      .badge { padding:7px 10px; border-radius:999px; background:rgba(255,255,255,.05); font-size:12px; }
      .card h3 { margin:14px 0 0; font-size:22px; line-height:1.45; }
      .card-body { padding:20px; }
      .meta { display:grid; gap:10px; }
      .meta-item { display:flex; justify-content:space-between; gap:12px; padding-bottom:10px; border-bottom:1px solid rgba(255,255,255,.06); }
      .meta-item:last-child { border-bottom:none; padding-bottom:0; }
      .meta-item span { color:var(--muted); font-size:12px; }
      .meta-item strong { flex:1; text-align:right; font-size:13px; line-height:1.6; }
      .summary,.sales-angle { margin-top:16px; color:var(--muted); font-size:14px; line-height:1.85; }
      .sales-angle strong { color:var(--text); }
      .tag-list { display:flex; flex-wrap:wrap; gap:8px; margin-top:16px; }
      .tag { padding:7px 10px; border-radius:999px; background:rgba(131,243,215,.1); font-size:12px; }
      .actions { display:flex; gap:10px; margin-top:18px; }
      .link-btn { display:inline-flex; align-items:center; justify-content:center; border-radius:999px; padding:12px 15px; text-decoration:none; font-size:13px; font-weight:700; }
      .link-primary { color:#09111a; background:linear-gradient(135deg, var(--gold), #fff0cb); }
      .link-secondary { color:var(--text); border:1px solid rgba(255,255,255,.1); background:rgba(255,255,255,.03); }
      .empty { padding:28px; border:1px dashed rgba(255,255,255,.14); border-radius:24px; color:var(--muted); text-align:center; }
      .footer { margin-top:28px; color:var(--muted); font-size:13px; line-height:1.9; text-align:center; }
      @media (max-width:1120px) { .hero,.filters { grid-template-columns:1fr; } .grid { grid-template-columns:repeat(2, minmax(0,1fr)); } .stat-grid { grid-template-columns:repeat(2, minmax(0,1fr)); } }
      @media (max-width:760px) { .shell { width:min(100% - 18px, 1340px); padding-top:16px; } .nav { flex-direction:column; align-items:flex-start; } .hero-main,.hero-side,.card { border-radius:24px; } .hero-main { padding:22px; } .grid,.stat-grid { grid-template-columns:1fr; } .actions { flex-direction:column; } }
    </style>
  </head>
  <body>
    <div class="shell">
      <nav class="nav">
        <div class="brand"><span class="brand-dot"></span><span>Tender Signal Atlas</span></div>
        <div class="nav-meta">Generated {generated_at} | Lookback {lookback_days} days</div>
      </nav>
      <section class="hero">
        <div class="hero-main">
          <p class="eyebrow">Daily Opportunity Feed</p>
          <h1>{title}</h1>
          <p class="hero-subtitle">{subtitle}</p>
          <p class="hero-overview">{overview}</p>
          <div class="stat-grid">
            <div class="stat"><span>Total notices</span><strong>{total_items}</strong></div>
            <div class="stat"><span>High priority</span><strong>{high_priority}</strong></div>
            <div class="stat"><span>Direct fits</span><strong>{direct_opportunities}</strong></div>
            <div class="stat"><span>Sources</span><strong>{source_count}</strong></div>
          </div>
        </div>
        <aside class="hero-side">
          <p class="panel-title">Source mix</p>
          <div class="rank-list" id="source-ranks"></div>
        </aside>
      </section>
      <section class="filters">
        <div class="filter-box">
          <label for="search-input">Search title, region, keyword</label>
          <input id="search-input" type="text" placeholder="smoking room / tobacco / mobile toilet / Jiangsu" />
        </div>
        <div class="filter-box">
          <label for="priority-filter">Priority</label>
          <select id="priority-filter">
            <option value="">All priorities</option>
            <option value="High">High</option>
            <option value="Medium">Medium</option>
            <option value="Watch">Watch</option>
          </select>
        </div>
        <div class="filter-box">
          <label for="type-filter">Opportunity type</label>
          <select id="type-filter">
            <option value="">All types</option>
            <option value="Direct">Direct</option>
            <option value="Adjacent">Adjacent</option>
            <option value="Monitor">Monitor</option>
          </select>
        </div>
      </section>
      <section>
        <div class="section-head">
          <h2>Opportunity stream</h2>
          <span id="result-count"></span>
        </div>
        <div class="grid" id="card-grid"></div>
        <div class="empty" id="empty-state" hidden>No notices matched the current filters.</div>
      </section>
      <div class="footer">
        This site is built for public-source monitoring. Keep the original notice URL and do not bypass login walls,
        anti-bot controls, or paid memberships.
      </div>
    </div>
    <script>
      const DATA = {data_json};
      const cardGrid = document.getElementById("card-grid");
      const resultCount = document.getElementById("result-count");
      const searchInput = document.getElementById("search-input");
      const priorityFilter = document.getElementById("priority-filter");
      const typeFilter = document.getElementById("type-filter");
      const emptyState = document.getElementById("empty-state");
      function buildSourceRanks() {
        const container = document.getElementById("source-ranks");
        const entries = Object.entries(DATA.source_counts).sort((a, b) => b[1] - a[1]);
        if (entries.length) {
          container.innerHTML = entries.map(([name, count]) => `<div class="rank-item"><span>${name}</span><span class="rank-count">${count}</span></div>`).join("");
          return;
        }
        const health = DATA.source_health || [];
        container.innerHTML = health.map(item => {
          const right = item.status === "ok" ? `ok / ${item.success_count}` : "error";
          const title = item.last_error ? item.last_error.replace(/"/g, "&quot;") : "";
          return `<div class="rank-item" title="${title}"><span>${item.name}</span><span class="rank-count">${right}</span></div>`;
        }).join("");
      }
      function accentFor(priority) {
        if (priority === "High") return "var(--mint)";
        if (priority === "Medium") return "var(--gold)";
        return "var(--blue)";
      }
      function cardTemplate(item) {
        return `
          <article class="card">
            <div class="card-top" style="--accent: ${accentFor(item.priority)};">
              <div class="accent"></div>
              <div class="badge-row">
                <span class="badge">${item.priority}</span>
                <span class="badge">${item.opportunity_type}</span>
                <span class="badge">${item.source_name}</span>
              </div>
              <h3>${item.title}</h3>
            </div>
            <div class="card-body">
              <div class="meta">
                <div class="meta-item"><span>Keyword</span><strong>${item.query_keyword}</strong></div>
                <div class="meta-item"><span>Published</span><strong>${item.published || "Unknown"}</strong></div>
                <div class="meta-item"><span>Region</span><strong>${item.region || "Unknown"}</strong></div>
                <div class="meta-item"><span>Amount</span><strong>${item.amount || "Not listed"}</strong></div>
              </div>
              <div class="summary">${item.summary}</div>
              <div class="sales-angle"><strong>Sales angle:</strong> ${item.sales_angle}</div>
              <div class="tag-list">${(item.tags || []).map(tag => `<span class="tag">${tag}</span>`).join("")}</div>
              <div class="actions">
                <a class="link-btn link-primary" href="${item.source_url}" target="_blank" rel="noreferrer">Open notice</a>
                <a class="link-btn link-secondary" href="${item.search_url}" target="_blank" rel="noreferrer">Open search</a>
              </div>
            </div>
          </article>`;
      }
      function renderCards() {
        const query = searchInput.value.trim().toLowerCase();
        const priority = priorityFilter.value;
        const type = typeFilter.value;
        const filtered = DATA.items.filter(item => {
          const blob = [item.title, item.region, item.query_keyword, item.source_name, ...(item.tags || [])].join(" ").toLowerCase();
          const matchQuery = !query || blob.includes(query);
          const matchPriority = !priority || item.priority === priority;
          const matchType = !type || item.opportunity_type === type;
          return matchQuery && matchPriority && matchType;
        });
        resultCount.textContent = `Showing ${filtered.length} / ${DATA.items.length} notices`;
        cardGrid.innerHTML = filtered.map(cardTemplate).join("");
        emptyState.hidden = filtered.length !== 0;
      }
      buildSourceRanks();
      renderCards();
      searchInput.addEventListener("input", renderCards);
      priorityFilter.addEventListener("change", renderCards);
      typeFilter.addEventListener("change", renderCards);
    </script>
  </body>
</html>
"""
    return (
        template.replace("{title}", escape(payload["summary"]["page_title"]))
        .replace("{subtitle}", escape(payload["summary"]["page_subtitle"]))
        .replace("{generated_at}", escape(payload["generated_at"]))
        .replace("{lookback_days}", str(payload["lookback_days"]))
        .replace("{overview}", escape(payload["summary"]["overview"]))
        .replace("{total_items}", str(payload["stats"]["total_items"]))
        .replace("{high_priority}", str(payload["stats"]["high_priority"]))
        .replace("{direct_opportunities}", str(payload["stats"]["direct_opportunities"]))
        .replace("{source_count}", str(payload["stats"]["source_count"]))
        .replace("{data_json}", data_json)
    )


def render_html_v2(payload: dict[str, Any]) -> str:
    data_json = json.dumps(payload, ensure_ascii=False)
    template = """<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
    <meta name="description" content="{subtitle}" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600;700&family=Manrope:wght@400;500;600;700;800&family=Noto+Sans+SC:wght@400;500;700;900&display=swap"
      rel="stylesheet"
    />
    <style>
      :root { --bg:#071019; --panel:rgba(9,19,29,.82); --panel-strong:rgba(8,15,23,.94); --line:rgba(170,206,235,.12); --text:#f6fbff; --muted:#97abbe; --mint:#7ff1d1; --gold:#f6cd87; --blue:#8ec2ff; --shadow:0 30px 80px rgba(0,0,0,.34); }
      * { box-sizing:border-box; }
      body { margin:0; color:var(--text); background:radial-gradient(circle at 10% 12%, rgba(127,241,209,.15), transparent 24%), radial-gradient(circle at 88% 14%, rgba(246,205,135,.14), transparent 22%), radial-gradient(circle at 40% 100%, rgba(142,194,255,.12), transparent 22%), linear-gradient(180deg, #08111a 0%, #0b1722 48%, #060c13 100%); font-family:"Noto Sans SC","Manrope",sans-serif; }
      .shell { width:min(1440px, calc(100% - 28px)); margin:0 auto; padding:22px 0 54px; }
      .nav { display:flex; justify-content:space-between; align-items:center; gap:16px; padding:16px 18px; border:1px solid var(--line); border-radius:24px; background:rgba(9,16,24,.66); box-shadow:var(--shadow); backdrop-filter:blur(18px); }
      .brand { display:flex; align-items:center; gap:12px; font-size:12px; font-weight:800; letter-spacing:.16em; text-transform:uppercase; }
      .brand-dot { width:12px; height:12px; border-radius:999px; background:linear-gradient(135deg, var(--gold), var(--mint)); box-shadow:0 0 18px rgba(127,241,209,.52); }
      .nav-right { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
      .nav-meta { color:var(--muted); font-size:13px; }
      .lang-switch { display:flex; gap:8px; padding:4px; border:1px solid rgba(255,255,255,.08); border-radius:999px; background:rgba(255,255,255,.03); }
      .lang-btn { border:none; border-radius:999px; background:transparent; color:var(--muted); padding:8px 14px; cursor:pointer; font-size:12px; font-weight:800; letter-spacing:.08em; }
      .lang-btn.active { color:#08111a; background:linear-gradient(135deg, var(--gold), #fff0ca); }
      .quick-nav { margin-top:18px; display:flex; flex-wrap:wrap; gap:10px; }
      .quick-link { display:inline-flex; align-items:center; justify-content:center; padding:10px 14px; border-radius:999px; text-decoration:none; font-size:13px; font-weight:800; background:rgba(255,255,255,.06); color:var(--text); border:1px solid rgba(255,255,255,.08); }
      .hero { margin-top:24px; display:grid; grid-template-columns:1.08fr .92fr; gap:20px; }
      .hero-main,.hero-side,.section-panel,.filter-box,.card,.focus-card,.health-card { border:1px solid var(--line); border-radius:32px; box-shadow:var(--shadow); backdrop-filter:blur(18px); }
      .hero-main { padding:32px; position:relative; overflow:hidden; background:linear-gradient(160deg, rgba(12,24,36,.92), rgba(8,16,24,.88)); }
      .hero-main::before { content:""; position:absolute; inset:auto -8% -26% auto; width:360px; height:360px; border-radius:999px; background:radial-gradient(circle, rgba(127,241,209,.22), transparent 64%); }
      .eyebrow { margin:0; color:var(--mint); font-size:12px; font-weight:800; letter-spacing:.2em; text-transform:uppercase; }
      h1 { margin:16px 0 12px; max-width:820px; font-family:"Cormorant Garamond",serif; font-size:clamp(46px, 5.6vw, 82px); line-height:.94; font-weight:600; }
      .hero-subtitle { margin:0; max-width:780px; font-size:clamp(17px, 2vw, 24px); line-height:1.8; }
      .hero-overview { margin-top:16px; max-width:780px; color:var(--muted); font-size:14px; line-height:1.95; }
      .metric-grid { margin-top:24px; display:grid; grid-template-columns:repeat(6, minmax(0,1fr)); gap:12px; }
      .metric-card { padding:16px; border-radius:22px; border:1px solid rgba(255,255,255,.06); background:rgba(255,255,255,.03); }
      .metric-label { display:block; color:var(--muted); font-size:11px; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }
      .metric-value { display:block; margin-top:10px; font-size:28px; font-family:"Manrope",sans-serif; font-weight:800; }
      .hero-side { padding:24px; background:linear-gradient(180deg, rgba(9,19,29,.88), rgba(8,14,22,.92)); }
      .panel-title { margin:0 0 14px; color:var(--muted); font-size:12px; font-weight:800; letter-spacing:.14em; text-transform:uppercase; }
      .coverage-grid { display:grid; grid-template-columns:repeat(2, minmax(0,1fr)); gap:12px; margin-top:14px; }
      .coverage-card { padding:14px 16px; border-radius:20px; background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.05); }
      .coverage-card strong { display:block; margin-top:6px; font-size:22px; }
      .health-list,.focus-grid,.grid { display:grid; gap:14px; }
      .health-card { padding:16px; background:rgba(255,255,255,.03); border-radius:22px; }
      .health-top { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }
      .health-name { font-size:14px; font-weight:800; }
      .health-status { font-size:12px; color:var(--gold); font-weight:800; text-transform:uppercase; }
      .health-error { margin-top:8px; color:var(--muted); font-size:12px; line-height:1.7; }
      .section-panel { margin-top:22px; padding:24px; background:rgba(8,15,23,.72); }
      .section-head { display:flex; justify-content:space-between; align-items:baseline; gap:16px; margin-bottom:16px; }
      .section-head h2 { margin:0; font-size:18px; letter-spacing:.12em; text-transform:uppercase; }
      .section-head span { color:var(--muted); font-size:13px; }
      .focus-grid { grid-template-columns:repeat(3, minmax(0,1fr)); }
      .focus-card { padding:20px; background:linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,.02)); border-radius:26px; }
      .focus-badges,.badge-row,.tag-list,.control-row { display:flex; flex-wrap:wrap; gap:8px; }
      .mini-badge,.badge,.tag { display:inline-flex; align-items:center; justify-content:center; padding:7px 10px; border-radius:999px; font-size:12px; }
      .mini-badge,.badge { background:rgba(255,255,255,.06); }
      .focus-card h3,.card h3 { margin:14px 0 0; font-size:22px; line-height:1.5; }
      .focus-card p { margin:12px 0 0; color:var(--muted); font-size:13px; line-height:1.85; }
      .focus-link,.link-btn { display:inline-flex; align-items:center; justify-content:center; border-radius:999px; padding:12px 16px; text-decoration:none; font-size:13px; font-weight:800; }
      .focus-link { margin-top:16px; color:#08111a; background:linear-gradient(135deg, var(--gold), #fff2cb); }
      .filters { margin-top:22px; display:grid; grid-template-columns:1.3fr .85fr .85fr .95fr; gap:12px; }
      .filter-box { padding:14px 16px; background:rgba(8,15,23,.74); }
      .filter-box label { display:block; margin-bottom:8px; color:var(--muted); font-size:12px; }
      .filter-box input,.filter-box select { width:100%; border:none; outline:none; background:transparent; color:var(--text); font-size:15px; }
      .filter-box option { color:#08111a; }
      .grid { margin-top:18px; grid-template-columns:repeat(3, minmax(0,1fr)); }
      .card { overflow:hidden; background:linear-gradient(180deg, rgba(10,18,28,.94), rgba(8,14,22,.96)); }
      .card-top { position:relative; padding:20px; background:radial-gradient(circle at 85% 18%, rgba(255,255,255,.08), transparent 18%), linear-gradient(135deg, rgba(255,255,255,.02), rgba(255,255,255,.08)); }
      .accent { position:absolute; inset:0 auto auto 0; width:100%; height:4px; background:var(--accent, var(--mint)); }
      .card-body { padding:20px; }
      .meta { display:grid; gap:10px; }
      .meta-item { display:flex; justify-content:space-between; gap:12px; padding-bottom:10px; border-bottom:1px solid rgba(255,255,255,.06); }
      .meta-item:last-child { border-bottom:none; padding-bottom:0; }
      .meta-item span { color:var(--muted); font-size:12px; }
      .meta-item strong { flex:1; text-align:right; font-size:13px; line-height:1.6; }
      .summary,.sales-angle { margin-top:16px; color:var(--muted); font-size:14px; line-height:1.85; }
      .sales-angle strong { color:var(--text); }
      .tag { background:rgba(127,241,209,.12); }
      .actions { display:flex; gap:10px; margin-top:18px; }
      .link-primary { color:#08111a; background:linear-gradient(135deg, var(--gold), #fff0cb); }
      .link-secondary { color:var(--text); border:1px solid rgba(255,255,255,.08); background:rgba(255,255,255,.03); }
      .empty { margin-top:18px; padding:28px; border:1px dashed rgba(255,255,255,.14); border-radius:24px; color:var(--muted); text-align:center; }
      .footer { margin-top:30px; color:var(--muted); font-size:13px; line-height:1.9; text-align:center; }
      @media (max-width:1220px) { .hero,.filters,.focus-grid,.grid { grid-template-columns:1fr 1fr; } .metric-grid { grid-template-columns:repeat(3, minmax(0,1fr)); } }
      @media (max-width:860px) { .hero,.filters,.focus-grid,.grid,.coverage-grid,.metric-grid { grid-template-columns:1fr; } .nav { flex-direction:column; align-items:flex-start; } .hero-main,.hero-side,.section-panel,.card,.focus-card,.health-card,.filter-box { border-radius:24px; } .actions { flex-direction:column; } }
    </style>
  </head>
  <body>
    <div class="shell">
      <nav class="nav">
        <div class="brand"><span class="brand-dot"></span><span>Tender Signal Atlas</span></div>
        <div class="nav-right">
          <div class="nav-meta" id="nav-meta">{generated_at_local} | Lookback {lookback_days} days</div>
          <div class="lang-switch">
            <button class="lang-btn active" id="lang-zh" type="button">中文</button>
            <button class="lang-btn" id="lang-en" type="button">EN</button>
          </div>
        </div>
      </nav>
      <div class="quick-nav">
        <a class="quick-link" href="./index.html">总站 Main</a>
        <a class="quick-link" href="./executive.html">老板页 Executive</a>
        <a class="quick-link" href="./sales.html">销售页 Sales</a>
        <a class="quick-link" href="./archive/index.html">历史归档 Archive</a>
      </div>
      <section class="hero">
        <div class="hero-main">
          <p class="eyebrow" id="eyebrow">Daily Opportunity Feed</p>
          <h1>{title}</h1>
          <p class="hero-subtitle">{subtitle}</p>
          <p class="hero-overview">{overview}</p>
          <div class="metric-grid">
            <div class="metric-card"><span class="metric-label" id="metric-total-label">Total notices</span><strong class="metric-value">{total_items}</strong></div>
            <div class="metric-card"><span class="metric-label" id="metric-high-label">High priority</span><strong class="metric-value">{high_priority}</strong></div>
            <div class="metric-card"><span class="metric-label" id="metric-direct-label">Direct fits</span><strong class="metric-value">{direct_opportunities}</strong></div>
            <div class="metric-card"><span class="metric-label" id="metric-sources-label">Live sources</span><strong class="metric-value">{source_count}</strong></div>
            <div class="metric-card"><span class="metric-label" id="metric-seeds-label">Seed sources</span><strong class="metric-value">{seed_source_count}</strong></div>
            <div class="metric-card"><span class="metric-label" id="metric-fallback-label">Fallback queries</span><strong class="metric-value">{fallback_query_count}</strong></div>
          </div>
        </div>
        <aside class="hero-side">
          <p class="panel-title" id="coverage-title">Coverage health</p>
          <div class="coverage-grid">
            <div class="coverage-card"><span id="coverage-active-label">Official source set</span><strong>{active_source_count}</strong></div>
            <div class="coverage-card"><span id="coverage-healthy-label">Healthy sources</span><strong>{healthy_source_count}</strong></div>
            <div class="coverage-card"><span id="coverage-error-label">Error sources</span><strong>{error_source_count}</strong></div>
            <div class="coverage-card"><span id="coverage-query-label">Official query count</span><strong>{official_query_count}</strong></div>
          </div>
          <div class="section-head" style="margin-top:22px;margin-bottom:12px;">
            <h2 id="source-health-title">Source health</h2>
          </div>
          <div class="health-list" id="health-list"></div>
        </aside>
      </section>
      <section class="section-panel">
        <div class="section-head">
          <h2 id="focus-title">Sales focus</h2>
          <span id="focus-subtitle"></span>
        </div>
        <div class="focus-grid" id="focus-grid"></div>
      </section>
      <section class="filters">
        <div class="filter-box">
          <label for="search-input" id="search-label">Search title, region, keyword</label>
          <input id="search-input" type="text" placeholder="请输入项目名称、区域、关键词 / Search by title, region, keyword" />
        </div>
        <div class="filter-box">
          <label for="priority-filter" id="priority-label">Priority</label>
          <select id="priority-filter">
            <option value="" id="priority-all">All priorities</option>
            <option value="High">High</option>
            <option value="Medium">Medium</option>
            <option value="Watch">Watch</option>
          </select>
        </div>
        <div class="filter-box">
          <label for="type-filter" id="type-label">Opportunity type</label>
          <select id="type-filter">
            <option value="" id="type-all">All types</option>
            <option value="Direct">Direct</option>
            <option value="Adjacent">Adjacent</option>
            <option value="Monitor">Monitor</option>
          </select>
        </div>
        <div class="filter-box">
          <label for="source-filter" id="source-filter-label">Source</label>
          <select id="source-filter">
            <option value="" id="source-all">All sources</option>
          </select>
        </div>
      </section>
      <section class="section-panel">
        <div class="section-head">
          <h2 id="stream-title">Opportunity stream</h2>
          <span id="result-count"></span>
        </div>
        <div class="grid" id="card-grid"></div>
        <div class="empty" id="empty-state" hidden>当前筛选条件下没有匹配项目。</div>
      </section>
      <div class="footer" id="footer-note">本站仅监测公开来源并保留原始链接，不绕过登录、会员墙、验证码或反爬限制。</div>
    </div>
    <script>
      const DATA = {data_json};
      const I18N = { zh: { navMeta: "本地生成时间 {time} | 回溯 {days} 天", eyebrow: "每日商机监测", totalNotices: "项目总数", highPriority: "高优先项目", directFits: "直接匹配", liveSources: "命中来源", seedSources: "种子站点", fallbackQueries: "补充检索词", coverageHealth: "覆盖健康度", officialSet: "官方源集合", healthySources: "健康源", errorSources: "异常源", officialQueries: "官方查询次数", sourceHealth: "来源健康状态", salesFocus: "销售重点线索", focusSubtitle: "老板和销售建议先看这里", searchLabel: "搜索项目名称、区域、关键词", searchPlaceholder: "请输入项目名称、区域、关键词", priorityLabel: "优先级", priorityAll: "全部优先级", typeLabel: "项目类型", typeAll: "全部类型", sourceLabel: "来源站点", sourceAll: "全部来源", streamTitle: "全量项目流", resultCount: "显示 {shown} / {total} 条项目", emptyState: "当前筛选条件下没有匹配项目。", footer: "本站仅监测公开来源并保留原始链接，不绕过登录、会员墙、验证码或反爬限制。", keyword: "关键词", published: "发布日期", region: "区域", amount: "金额", salesAngle: "销售建议", nextAction: "下一步动作", openNotice: "查看原文", openSearch: "查看搜索页", focusOpen: "打开项目", noDate: "未标注", noRegion: "未标注", noAmount: "未标注", noFocus: "本轮没有高优先或中优先的直接匹配项目。", priorityMap: { High: "高优先 / High", Medium: "中优先 / Medium", Watch: "观察 / Watch" }, typeMap: { Direct: "直接匹配 / Direct", Adjacent: "邻近机会 / Adjacent", Monitor: "持续观察 / Monitor" }, statusMap: { ok: "正常", error: "异常", unknown: "未知" } }, en: { navMeta: "Generated {time} | Lookback {days} days", eyebrow: "Daily Opportunity Feed", totalNotices: "Total notices", highPriority: "High priority", directFits: "Direct fits", liveSources: "Hit sources", seedSources: "Seed sources", fallbackQueries: "Fallback queries", coverageHealth: "Coverage health", officialSet: "Official source set", healthySources: "Healthy sources", errorSources: "Error sources", officialQueries: "Official query count", sourceHealth: "Source health", salesFocus: "Sales focus", focusSubtitle: "Suggested first-read section for leadership and sales", searchLabel: "Search title, region, keyword", searchPlaceholder: "Search by title, region, keyword", priorityLabel: "Priority", priorityAll: "All priorities", typeLabel: "Opportunity type", typeAll: "All types", sourceLabel: "Source", sourceAll: "All sources", streamTitle: "Opportunity stream", resultCount: "Showing {shown} / {total} notices", emptyState: "No notices matched the current filters.", footer: "This site monitors public sources only and keeps original links without bypassing paywalls, logins, CAPTCHA, or anti-bot controls.", keyword: "Keyword", published: "Published", region: "Region", amount: "Amount", salesAngle: "Sales angle", nextAction: "Next action", openNotice: "Open notice", openSearch: "Open search", focusOpen: "Open lead", noDate: "Unknown", noRegion: "Unknown", noAmount: "Not listed", noFocus: "No direct High or Medium opportunities in this run.", priorityMap: { High: "High / 高优先", Medium: "Medium / 中优先", Watch: "Watch / 观察" }, typeMap: { Direct: "Direct / 直接匹配", Adjacent: "Adjacent / 邻近机会", Monitor: "Monitor / 持续观察" }, statusMap: { ok: "OK", error: "Error", unknown: "Unknown" } } };
      const cardGrid = document.getElementById("card-grid");
      const resultCount = document.getElementById("result-count");
      const searchInput = document.getElementById("search-input");
      const priorityFilter = document.getElementById("priority-filter");
      const typeFilter = document.getElementById("type-filter");
      const sourceFilter = document.getElementById("source-filter");
      const emptyState = document.getElementById("empty-state");
      const focusGrid = document.getElementById("focus-grid");
      const healthList = document.getElementById("health-list");
      let currentLang = "zh";
      function t(key) { return I18N[currentLang][key]; }
      function formatText(template, values) { let output = template; Object.entries(values).forEach(([key, value]) => { output = output.replace(`{${key}}`, String(value)); }); return output; }
      function priorityLabel(priority) { return I18N[currentLang].priorityMap[priority] || priority; }
      function typeLabel(type) { return I18N[currentLang].typeMap[type] || type; }
      function statusLabel(status) { return I18N[currentLang].statusMap[status] || status; }
      function accentFor(priority) { if (priority === "High") return "var(--mint)"; if (priority === "Medium") return "var(--gold)"; return "var(--blue)"; }
      function applyStaticText() {
        document.getElementById("nav-meta").textContent = formatText(t("navMeta"), { time: DATA.generated_at_local || DATA.generated_at, days: DATA.lookback_days });
        document.getElementById("eyebrow").textContent = t("eyebrow");
        document.getElementById("metric-total-label").textContent = t("totalNotices");
        document.getElementById("metric-high-label").textContent = t("highPriority");
        document.getElementById("metric-direct-label").textContent = t("directFits");
        document.getElementById("metric-sources-label").textContent = t("liveSources");
        document.getElementById("metric-seeds-label").textContent = t("seedSources");
        document.getElementById("metric-fallback-label").textContent = t("fallbackQueries");
        document.getElementById("coverage-title").textContent = t("coverageHealth");
        document.getElementById("coverage-active-label").textContent = t("officialSet");
        document.getElementById("coverage-healthy-label").textContent = t("healthySources");
        document.getElementById("coverage-error-label").textContent = t("errorSources");
        document.getElementById("coverage-query-label").textContent = t("officialQueries");
        document.getElementById("source-health-title").textContent = t("sourceHealth");
        document.getElementById("focus-title").textContent = t("salesFocus");
        document.getElementById("focus-subtitle").textContent = t("focusSubtitle");
        document.getElementById("search-label").textContent = t("searchLabel");
        document.getElementById("search-input").placeholder = t("searchPlaceholder");
        document.getElementById("priority-label").textContent = t("priorityLabel");
        document.getElementById("priority-all").textContent = t("priorityAll");
        document.getElementById("type-label").textContent = t("typeLabel");
        document.getElementById("type-all").textContent = t("typeAll");
        document.getElementById("source-filter-label").textContent = t("sourceLabel");
        document.getElementById("source-all").textContent = t("sourceAll");
        document.getElementById("stream-title").textContent = t("streamTitle");
        document.getElementById("empty-state").textContent = t("emptyState");
        document.getElementById("footer-note").textContent = t("footer");
      }
      function buildSourceFilter() {
        const currentValue = sourceFilter.value;
        const entries = Object.entries(DATA.source_counts || {}).sort((a, b) => b[1] - a[1]);
        sourceFilter.innerHTML = `<option value="">${t("sourceAll")}</option>` + entries.map(([name, count]) => `<option value="${name}">${name} (${count})</option>`).join("");
        sourceFilter.value = currentValue;
      }
      function renderHealthList() {
        const items = DATA.source_health || [];
        healthList.innerHTML = items.map(item => `<article class="health-card"><div class="health-top"><div class="health-name">${item.name}</div><div class="health-status">${statusLabel(item.status)} · ${item.success_count || 0}/${item.failure_count || 0}</div></div><div class="health-error">${item.last_error || "&nbsp;"}</div></article>`).join("");
      }
      function renderFocusCards() {
        const items = DATA.top_direct_items || [];
        if (!items.length) { focusGrid.innerHTML = `<div class="empty">${t("noFocus")}</div>`; return; }
        focusGrid.innerHTML = items.map(item => `<article class="focus-card"><div class="focus-badges"><span class="mini-badge">${priorityLabel(item.priority)}</span><span class="mini-badge">${typeLabel(item.opportunity_type)}</span></div><h3>${item.title}</h3><p>${item.summary}</p><div class="control-row" style="margin-top:14px;"><span class="mini-badge">${t("published")} · ${item.published || t("noDate")}</span><span class="mini-badge">${t("region")} · ${item.region || t("noRegion")}</span></div><a class="focus-link" href="${item.source_url}" target="_blank" rel="noreferrer">${t("focusOpen")}</a></article>`).join("");
      }
      function cardTemplate(item) {
        return `<article class="card"><div class="card-top" style="--accent:${accentFor(item.priority)};"><div class="accent"></div><div class="badge-row"><span class="badge">${priorityLabel(item.priority)}</span><span class="badge">${typeLabel(item.opportunity_type)}</span><span class="badge">${item.source_name}</span></div><h3>${item.title}</h3></div><div class="card-body"><div class="meta"><div class="meta-item"><span>${t("keyword")}</span><strong>${item.query_keyword}</strong></div><div class="meta-item"><span>${t("published")}</span><strong>${item.published || t("noDate")}</strong></div><div class="meta-item"><span>${t("region")}</span><strong>${item.region || t("noRegion")}</strong></div><div class="meta-item"><span>${t("amount")}</span><strong>${item.amount || t("noAmount")}</strong></div></div><div class="summary">${item.summary}</div><div class="sales-angle"><strong>${t("salesAngle")}:</strong> ${item.sales_angle}</div><div class="sales-angle"><strong>${t("nextAction")}:</strong> ${item.next_action}</div><div class="tag-list">${(item.tags || []).map(tag => `<span class="tag">${tag}</span>`).join("")}</div><div class="actions"><a class="link-btn link-primary" href="${item.source_url}" target="_blank" rel="noreferrer">${t("openNotice")}</a><a class="link-btn link-secondary" href="${item.search_url}" target="_blank" rel="noreferrer">${t("openSearch")}</a></div></div></article>`;
      }
      function renderCards() {
        const query = searchInput.value.trim().toLowerCase();
        const priority = priorityFilter.value;
        const type = typeFilter.value;
        const source = sourceFilter.value;
        const filtered = DATA.items.filter(item => {
          const blob = [item.title, item.region, item.query_keyword, item.source_name, item.summary, ...(item.tags || [])].join(" ").toLowerCase();
          return (!query || blob.includes(query)) && (!priority || item.priority === priority) && (!type || item.opportunity_type === type) && (!source || item.source_name === source);
        });
        resultCount.textContent = formatText(t("resultCount"), { shown: filtered.length, total: DATA.items.length });
        cardGrid.innerHTML = filtered.map(cardTemplate).join("");
        emptyState.hidden = filtered.length !== 0;
      }
      function setLanguage(lang) {
        currentLang = lang;
        document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
        document.getElementById("lang-zh").classList.toggle("active", lang === "zh");
        document.getElementById("lang-en").classList.toggle("active", lang === "en");
        applyStaticText();
        buildSourceFilter();
        renderHealthList();
        renderFocusCards();
        renderCards();
      }
      document.getElementById("lang-zh").addEventListener("click", () => setLanguage("zh"));
      document.getElementById("lang-en").addEventListener("click", () => setLanguage("en"));
      searchInput.addEventListener("input", renderCards);
      priorityFilter.addEventListener("change", renderCards);
      typeFilter.addEventListener("change", renderCards);
      sourceFilter.addEventListener("change", renderCards);
      setLanguage("zh");
    </script>
  </body>
</html>
"""
    return (
        template.replace("{title}", escape(payload["summary"]["page_title"]))
        .replace("{subtitle}", escape(payload["summary"]["page_subtitle"]))
        .replace("{generated_at_local}", escape(payload.get("generated_at_local", payload["generated_at"])))
        .replace("{lookback_days}", str(payload["lookback_days"]))
        .replace("{overview}", escape(payload["summary"]["overview"]))
        .replace("{total_items}", str(payload["stats"]["total_items"]))
        .replace("{high_priority}", str(payload["stats"]["high_priority"]))
        .replace("{direct_opportunities}", str(payload["stats"]["direct_opportunities"]))
        .replace("{source_count}", str(payload["stats"]["source_count"]))
        .replace("{seed_source_count}", str(payload["coverage"]["seed_source_count"]))
        .replace("{fallback_query_count}", str(payload["coverage"]["fallback_query_count"]))
        .replace("{active_source_count}", str(payload["coverage"]["active_source_count"]))
        .replace("{healthy_source_count}", str(payload["coverage"]["healthy_source_count"]))
        .replace("{error_source_count}", str(payload["coverage"]["error_source_count"]))
        .replace("{official_query_count}", str(payload["coverage"]["official_query_count"]))
        .replace("{data_json}", data_json)
    )


def render_executive_html(payload: dict[str, Any]) -> str:
    top_items = payload.get("top_direct_items", [])[:5]
    watch_items = payload.get("watch_items", [])[:6]
    source_health = payload.get("source_health", [])

    top_markup = "".join(
        f"""
        <article class="lead-card">
          <div class="lead-top">
            <span class="pill">{escape(item.get("priority", ""))}</span>
            <span class="pill soft">{escape(item.get("opportunity_type", ""))}</span>
          </div>
          <h3>{escape(item.get("title", ""))}</h3>
          <p>{escape(item.get("summary", ""))}</p>
          <div class="meta-row">
            <span>发布时间 Published: {escape(item.get("published") or "Unknown")}</span>
            <span>地区 Region: {escape(item.get("region") or "Unknown")}</span>
          </div>
          <a class="cta" href="{escape(item.get("source_url", ""))}" target="_blank" rel="noreferrer">查看原公告 Open notice</a>
        </article>
        """.strip()
        for item in top_items
    ) or '<div class="empty">本轮没有直接优先机会。No direct priority opportunities in this run.</div>'

    watch_markup = "".join(
        f"""
        <tr>
          <td>{escape(item.get("title", ""))}</td>
          <td>{escape(item.get("published") or "Unknown")}</td>
          <td>{escape(item.get("opportunity_type") or "")}</td>
        </tr>
        """.strip()
        for item in watch_items
    ) or '<tr><td colspan="3">本轮没有关注池项目。No adjacent watch items in this run.</td></tr>'

    source_markup = "".join(
        f"""
        <div class="health-card">
          <strong>{escape(item.get("name", ""))}</strong>
          <span>状态 Status: {escape(source_health_label(item))}</span>
          <p>{escape(item.get("last_error", "") or "No error recorded / 本轮无异常。")}</p>
        </div>
        """.strip()
        for item in source_health
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>老板简报 Executive Brief | {escape(payload["summary"]["page_title"])}</title>
    <style>
      :root {{ --bg:#08111a; --panel:#0f1924; --panel-soft:#121f2d; --line:rgba(255,255,255,.08); --text:#f6fbff; --muted:#9db0c1; --gold:#f6cd87; --mint:#7ff1d1; }}
      * {{ box-sizing:border-box; }}
      body {{ margin:0; background:linear-gradient(180deg,#08111a 0%,#0d1823 100%); color:var(--text); font-family:"Segoe UI","Noto Sans SC",sans-serif; }}
      .shell {{ width:min(1280px,calc(100% - 28px)); margin:0 auto; padding:22px 0 42px; }}
      .quick-nav {{ margin-bottom:16px; display:flex; flex-wrap:wrap; gap:10px; }}
      .quick-link {{ display:inline-flex; align-items:center; gap:8px; padding:10px 14px; border-radius:999px; border:1px solid var(--line); background:rgba(255,255,255,.04); color:var(--text); text-decoration:none; font-size:13px; }}
      .hero {{ padding:28px; border:1px solid var(--line); border-radius:30px; background:radial-gradient(circle at top right, rgba(127,241,209,.16), transparent 24%), var(--panel); }}
      .hero h1 {{ margin:8px 0 12px; font-size:44px; line-height:1.06; }}
      .hero p {{ margin:0; color:var(--muted); line-height:1.9; }}
      .kpis {{ display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:12px; margin-top:18px; }}
      .kpi {{ padding:16px; border-radius:20px; background:var(--panel-soft); border:1px solid var(--line); }}
      .kpi span {{ display:block; color:var(--muted); font-size:12px; }}
      .kpi strong {{ display:block; margin-top:8px; font-size:28px; }}
      .layout {{ display:grid; grid-template-columns:1.15fr .85fr; gap:18px; margin-top:20px; }}
      .panel {{ padding:24px; border-radius:28px; border:1px solid var(--line); background:var(--panel); }}
      .panel h2 {{ margin:0 0 14px; font-size:18px; letter-spacing:.08em; text-transform:uppercase; }}
      .lead-list, .health-list {{ display:grid; gap:14px; }}
      .lead-card, .health-card {{ padding:18px; border-radius:22px; background:var(--panel-soft); border:1px solid var(--line); }}
      .lead-top {{ display:flex; gap:8px; }}
      .pill {{ display:inline-flex; padding:6px 10px; border-radius:999px; background:#f6cd87; color:#08111a; font-size:12px; font-weight:700; }}
      .pill.soft {{ background:rgba(255,255,255,.08); color:var(--text); }}
      .lead-card h3 {{ margin:12px 0 8px; font-size:20px; line-height:1.45; }}
      .lead-card p, .health-card p {{ margin:0; color:var(--muted); line-height:1.8; }}
      .meta-row {{ display:flex; justify-content:space-between; gap:12px; margin-top:12px; color:var(--muted); font-size:12px; }}
      .cta {{ display:inline-flex; margin-top:14px; padding:10px 14px; border-radius:999px; background:linear-gradient(135deg,var(--gold),#fff0ca); color:#08111a; text-decoration:none; font-weight:700; }}
      table {{ width:100%; border-collapse:collapse; }}
      th,td {{ padding:12px 10px; border-bottom:1px solid var(--line); text-align:left; font-size:13px; }}
      th {{ color:var(--muted); }}
      .empty {{ padding:20px; border:1px dashed var(--line); border-radius:20px; color:var(--muted); text-align:center; }}
      @media (max-width:1000px) {{ .layout,.kpis {{ grid-template-columns:1fr; }} }}
    </style>
  </head>
  <body>
    <div class="shell">
      <div class="quick-nav">
        <a class="quick-link" href="./index.html">总览首页 Main</a>
        <a class="quick-link" href="./sales.html">销售页 Sales</a>
        <a class="quick-link" href="./archive/index.html">历史归档 Archive</a>
      </div>
      <section class="hero">
        <div style="font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:var(--mint);font-weight:800;">老板简报 Executive Brief</div>
        <h1>管理层快照 Management Snapshot</h1>
        <p>{escape(payload["summary"]["overview"])}</p>
        <p style="margin-top:10px;">生成时间 Generated {escape(payload.get("generated_at_local", payload["generated_at"]))} | 报告日期 Report date {escape(payload["report_date"])}</p>
        <div class="kpis">
          <div class="kpi"><span>项目总数 Total notices</span><strong>{payload["stats"]["total_items"]}</strong></div>
          <div class="kpi"><span>直接匹配 Direct fits</span><strong>{payload["stats"]["direct_opportunities"]}</strong></div>
          <div class="kpi"><span>高优先级 High priority</span><strong>{payload["stats"]["high_priority"]}</strong></div>
          <div class="kpi"><span>健康来源 Healthy sources</span><strong>{payload["coverage"]["healthy_source_count"]}</strong></div>
          <div class="kpi"><span>种子来源 Seed sources</span><strong>{payload["coverage"]["seed_source_count"]}</strong></div>
          <div class="kpi"><span>回退检索 Fallback queries</span><strong>{payload["coverage"]["fallback_query_count"]}</strong></div>
        </div>
      </section>
      <section class="layout">
        <div class="panel">
          <h2>重点机会 Priority Leads</h2>
          <div class="lead-list">{top_markup}</div>
        </div>
        <div class="panel">
          <h2>来源健康 Source Health</h2>
          <div class="health-list">{source_markup}</div>
        </div>
      </section>
      <section class="panel" style="margin-top:18px;">
        <h2>关注池 Watchlist</h2>
        <table>
          <thead><tr><th>项目 Notice</th><th>发布时间 Published</th><th>类型 Type</th></tr></thead>
          <tbody>{watch_markup}</tbody>
        </table>
      </section>
    </div>
  </body>
</html>"""


def render_sales_html(payload: dict[str, Any]) -> str:
    sales_items = build_sales_payload(payload)["items"]
    sales_markup = "".join(
        f"""
        <article class="sales-card">
          <div class="sales-top">
            <span class="badge">{escape(item.get("priority", ""))}</span>
            <span class="badge soft">{escape(item.get("opportunity_type", ""))}</span>
            <span class="source">{escape(item.get("source_name", ""))}</span>
          </div>
          <h3>{escape(item.get("title", ""))}</h3>
          <div class="info-grid">
            <div><span>关键词 Keyword</span><strong>{escape(item.get("query_keyword", ""))}</strong></div>
            <div><span>发布时间 Published</span><strong>{escape(item.get("published") or "Unknown")}</strong></div>
            <div><span>地区 Region</span><strong>{escape(item.get("region") or "Unknown")}</strong></div>
            <div><span>金额 Amount</span><strong>{escape(item.get("amount") or "Not listed")}</strong></div>
          </div>
          <p>{escape(item.get("summary", ""))}</p>
          <p><strong>销售切入点 Sales angle:</strong> {escape(item.get("sales_angle", ""))}</p>
          <p><strong>下一步动作 Next action:</strong> {escape(item.get("next_action", ""))}</p>
          <div class="actions">
            <a class="cta" href="{escape(item.get("source_url", ""))}" target="_blank" rel="noreferrer">查看原公告 Open notice</a>
          </div>
        </article>
        """.strip()
        for item in sales_items
    ) or '<div class="empty">本轮暂无可直接跟进的销售线索。No direct sales-ready leads in this run.</div>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>销售视图 Sales View | {escape(payload["summary"]["page_title"])}</title>
    <style>
      :root {{ --bg:#f5f7fb; --panel:#ffffff; --line:#e4ebf3; --text:#112031; --muted:#637488; --gold:#f6cd87; --mint:#cffff0; }}
      * {{ box-sizing:border-box; }}
      body {{ margin:0; background:linear-gradient(180deg,#eef3f8 0%,#f8fbff 100%); color:var(--text); font-family:"Segoe UI","Noto Sans SC",sans-serif; }}
      .shell {{ width:min(1180px,calc(100% - 28px)); margin:0 auto; padding:22px 0 42px; }}
      .quick-nav {{ margin-bottom:16px; display:flex; flex-wrap:wrap; gap:10px; }}
      .quick-link {{ display:inline-flex; align-items:center; gap:8px; padding:10px 14px; border-radius:999px; border:1px solid var(--line); background:#fff; color:var(--text); text-decoration:none; font-size:13px; box-shadow:0 10px 24px rgba(15,24,36,.05); }}
      .hero {{ padding:28px; border-radius:28px; background:linear-gradient(140deg,#0c1520 0%,#132030 100%); color:#f7fbff; }}
      .hero h1 {{ margin:10px 0 10px; font-size:42px; }}
      .hero p {{ margin:0; color:#c8d3df; line-height:1.9; }}
      .grid {{ display:grid; gap:16px; margin-top:18px; }}
      .sales-card {{ padding:22px; border-radius:26px; background:var(--panel); border:1px solid var(--line); box-shadow:0 20px 50px rgba(15,24,36,.08); }}
      .sales-top {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; }}
      .badge {{ display:inline-flex; padding:7px 10px; border-radius:999px; background:var(--gold); color:#08111a; font-size:12px; font-weight:700; }}
      .badge.soft {{ background:#eef3f8; color:var(--text); }}
      .source {{ color:var(--muted); font-size:12px; }}
      .sales-card h3 {{ margin:12px 0 10px; font-size:24px; line-height:1.45; }}
      .info-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-top:12px; }}
      .info-grid div {{ padding:12px 14px; border-radius:16px; background:#f5f8fc; }}
      .info-grid span {{ display:block; color:var(--muted); font-size:12px; }}
      .info-grid strong {{ display:block; margin-top:6px; }}
      .sales-card p {{ color:var(--muted); line-height:1.85; }}
      .actions {{ margin-top:14px; }}
      .cta {{ display:inline-flex; padding:12px 16px; border-radius:999px; background:linear-gradient(135deg,#f6cd87,#fff0ca); color:#08111a; text-decoration:none; font-weight:700; }}
      .empty {{ padding:24px; border-radius:22px; border:1px dashed var(--line); color:var(--muted); text-align:center; background:#fff; }}
      @media (max-width:900px) {{ .info-grid {{ grid-template-columns:1fr 1fr; }} }}
      @media (max-width:640px) {{ .info-grid {{ grid-template-columns:1fr; }} }}
    </style>
  </head>
  <body>
    <div class="shell">
      <div class="quick-nav">
        <a class="quick-link" href="./index.html">总览首页 Main</a>
        <a class="quick-link" href="./executive.html">老板页 Executive</a>
        <a class="quick-link" href="./archive/index.html">历史归档 Archive</a>
      </div>
      <section class="hero">
        <div style="font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:#7ff1d1;font-weight:800;">销售视图 Sales View</div>
        <h1>销售直跟线索板 Direct-Fit Lead Board</h1>
        <p>{escape(payload["summary"]["overview"])}</p>
        <p style="margin-top:10px;">生成时间 Generated {escape(payload.get("generated_at_local", payload["generated_at"]))} | 报告日期 Report date {escape(payload["report_date"])}</p>
      </section>
      <section class="grid">{sales_markup}</section>
    </div>
  </body>
</html>"""


def split_email_sections(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    items = payload["items"]
    direct_items = [
        item for item in items if item["opportunity_type"] == "Direct" and item["priority"] in {"High", "Medium"}
    ]
    watch_items = [item for item in items if item["opportunity_type"] != "Direct"]
    health_items = payload.get("source_health", [])
    return (
        direct_items[: getenv_int("EMAIL_ITEM_LIMIT", DEFAULT_EMAIL_ITEM_LIMIT)],
        watch_items[:5],
        health_items,
    )


def source_health_label(item: dict[str, Any]) -> str:
    if item.get("status") == "ok":
        return f"ok / {item.get('success_count', 0)}"
    if item.get("status") == "error":
        return f"error / {item.get('failure_count', 0)}"
    return "unknown"


def build_text_email(payload: dict[str, Any]) -> str:
    direct_items, watch_items, health_items = split_email_sections(payload)
    lines = [
        "招标情报日报 Tender Intel Daily",
        f"生成时间 Generated: {payload.get('generated_at_local', payload['generated_at'])}",
        f"报告日期 Report date: {payload['report_date']}",
        "",
        payload["summary"]["overview"],
        "",
        "核心指标 Core metrics",
        f"- 项目总数 Total notices: {payload['stats']['total_items']}",
        f"- 高优先 High priority: {payload['stats']['high_priority']}",
        f"- 中优先 Medium priority: {payload['stats']['medium_priority']}",
        f"- 直接匹配 Direct opportunities: {payload['stats']['direct_opportunities']}",
        "",
    ]

    if direct_items:
        lines.append("销售重点 Sales priority")
    else:
        lines.append("销售重点 Sales priority")
        lines.append("- 本轮没有直接高/中优先项目 No direct High/Medium opportunities in this run.")

    for index, item in enumerate(direct_items, start=1):
        lines.extend(
            [
                f"{index}. {item['title']}",
                f"优先级 Priority: {item['priority']} | 类型 Type: {item['opportunity_type']}",
                f"关键词 Keyword: {item['query_keyword']}",
                f"发布日期 Published: {item['published'] or 'Unknown'}",
                f"区域 Region: {item['region'] or 'Unknown'}",
                f"金额 Amount: {item['amount'] or 'Not listed'}",
                f"摘要 Summary: {item['summary']}",
                f"销售建议 Sales angle: {item['sales_angle']}",
                f"下一步动作 Next action: {item['next_action']}",
                f"原文链接 Notice: {item['source_url']}",
                "",
            ]
        )

    if watch_items:
        lines.append("观察池 Watchlist")
        for index, item in enumerate(watch_items, start=1):
            lines.extend(
                [
                    f"{index}. {item['title']}",
                    f"类型 Type: {item['opportunity_type']} | 发布 Published: {item['published'] or 'Unknown'} | 来源 Source: {item['source_name']}",
                    f"原文链接 Notice: {item['source_url']}",
                    "",
                ]
            )

    if health_items:
        lines.append("来源健康 Source health")
        for item in health_items:
            lines.append(f"- {item['name']}: {source_health_label(item)}")

    return "\n".join(lines).strip()


def build_html_email(payload: dict[str, Any]) -> str:
    direct_items, watch_items, health_items = split_email_sections(payload)

    def metric_card(label: str, value: Any, accent: str) -> str:
        return (
            f'<div style="padding:18px 16px;border-radius:22px;background:{accent};color:#08111a;">'
            f'<div style="font-size:12px;letter-spacing:.12em;text-transform:uppercase;opacity:.76;">{escape(label)}</div>'
            f'<div style="margin-top:10px;font-size:34px;font-weight:800;line-height:1;">{escape(str(value))}</div>'
            f"</div>"
        )

    def lead_card(item: dict[str, Any]) -> str:
        badge_bg = "#dbfff4" if item["priority"] == "High" else "#fff1cf"
        return f"""
        <div style="margin:0 0 18px;padding:22px;border:1px solid rgba(10,25,41,.08);border-radius:24px;background:#ffffff;box-shadow:0 18px 48px rgba(9,17,26,.08);">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;">
            <span style="display:inline-block;padding:8px 12px;border-radius:999px;background:{badge_bg};font-size:12px;font-weight:800;">{escape(item["priority"])} / {escape(item["opportunity_type"])}</span>
            <span style="color:#607086;font-size:12px;">{escape(item["source_name"])}</span>
          </div>
          <h3 style="margin:14px 0 10px;font-size:22px;line-height:1.5;color:#0a1522;">{escape(item["title"])}</h3>
          <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-bottom:14px;">
            <div style="padding:12px 14px;border-radius:16px;background:#f5f8fc;color:#516173;font-size:13px;">Keyword<br><strong style="color:#0a1522;">{escape(item["query_keyword"])}</strong></div>
            <div style="padding:12px 14px;border-radius:16px;background:#f5f8fc;color:#516173;font-size:13px;">Published<br><strong style="color:#0a1522;">{escape(item["published"] or "Unknown")}</strong></div>
            <div style="padding:12px 14px;border-radius:16px;background:#f5f8fc;color:#516173;font-size:13px;">Region<br><strong style="color:#0a1522;">{escape(item["region"] or "Unknown")}</strong></div>
            <div style="padding:12px 14px;border-radius:16px;background:#f5f8fc;color:#516173;font-size:13px;">Amount<br><strong style="color:#0a1522;">{escape(item["amount"] or "Not listed")}</strong></div>
          </div>
          <p style="margin:0 0 10px;color:#46576a;font-size:14px;line-height:1.85;">{escape(item["summary"])}</p>
          <p style="margin:0 0 10px;color:#46576a;font-size:14px;line-height:1.85;"><strong style="color:#0a1522;">Sales angle:</strong> {escape(item["sales_angle"])}</p>
          <p style="margin:0 0 16px;color:#46576a;font-size:14px;line-height:1.85;"><strong style="color:#0a1522;">Next action:</strong> {escape(item["next_action"])}</p>
          <a href="{escape(item["source_url"])}" style="display:inline-block;padding:12px 18px;border-radius:999px;background:linear-gradient(135deg,#f7d391,#fff1cd);color:#08111a;text-decoration:none;font-weight:800;">Open notice</a>
        </div>
        """.strip()

    def watch_row(item: dict[str, Any]) -> str:
        return (
            "<tr>"
            f'<td style="padding:12px 10px;border-bottom:1px solid #eef2f7;color:#0a1522;font-size:13px;line-height:1.6;">{escape(item["title"])}</td>'
            f'<td style="padding:12px 10px;border-bottom:1px solid #eef2f7;color:#607086;font-size:12px;">{escape(item["published"] or "Unknown")}</td>'
            f'<td style="padding:12px 10px;border-bottom:1px solid #eef2f7;color:#607086;font-size:12px;">{escape(item["opportunity_type"])}</td>'
            f'<td style="padding:12px 10px;border-bottom:1px solid #eef2f7;"><a href="{escape(item["source_url"])}" style="color:#0a5bd7;text-decoration:none;">Open</a></td>'
            "</tr>"
        )

    direct_markup = "".join(lead_card(item) for item in direct_items) or """
        <div style="padding:22px;border:1px dashed rgba(10,25,41,.14);border-radius:24px;background:rgba(255,255,255,.72);color:#5d6c7d;">
          No direct High or Medium opportunities were detected in this run.
        </div>
    """.strip()

    watch_markup = "".join(watch_row(item) for item in watch_items)
    health_markup = "".join(
        f'<div style="padding:14px 16px;border-radius:18px;background:#ffffff;border:1px solid rgba(10,25,41,.08);">'
        f'<div style="font-size:13px;font-weight:800;color:#0a1522;">{escape(item["name"])}</div>'
        f'<div style="margin-top:6px;color:#607086;font-size:13px;">{escape(source_health_label(item))}</div>'
        f'<div style="margin-top:6px;color:#8a97a7;font-size:12px;line-height:1.6;">{escape(item.get("last_error", "")[:180] or "No error recorded.")}</div>'
        "</div>"
        for item in health_items
    )

    return f"""
    <html>
      <body style="margin:0;padding:28px;background:#eef3f8;color:#15202b;font-family:'Segoe UI',Arial,sans-serif;">
        <div style="max-width:980px;margin:0 auto;">
          <div style="padding:28px 28px 26px;border-radius:32px;background:radial-gradient(circle at top right, rgba(131,243,215,.3), transparent 22%),linear-gradient(180deg,#09111a 0%,#0d1722 100%);color:#f7fbff;box-shadow:0 28px 80px rgba(5,11,18,.24);">
            <div style="font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:#83f3d7;font-weight:800;">Daily Tender Brief</div>
            <h1 style="margin:14px 0 12px;font-size:46px;line-height:1.02;">{escape(payload["summary"]["page_title"])}</h1>
            <p style="margin:0 0 10px;font-size:18px;line-height:1.8;color:#dfe9f3;">{escape(payload["summary"]["page_subtitle"])}</p>
            <p style="margin:0;color:#9fb2c5;font-size:14px;line-height:1.9;">{escape(payload["summary"]["overview"])}</p>
            <p style="margin:16px 0 0;color:#9fb2c5;font-size:13px;">Generated {escape(payload["generated_at"])} | Report date {escape(payload["report_date"])}</p>
          </div>

          <div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-top:18px;">
            {metric_card("Total notices", payload["stats"]["total_items"], "#dff8ef")}
            {metric_card("High priority", payload["stats"]["high_priority"], "#fff1cf")}
            {metric_card("Medium priority", payload["stats"]["medium_priority"], "#dcecff")}
            {metric_card("Direct fits", payload["stats"]["direct_opportunities"], "#f5e7ff")}
          </div>

          <div style="margin-top:22px;padding:24px;border-radius:28px;background:#f8fbfe;border:1px solid rgba(10,25,41,.08);">
            <div style="font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#607086;font-weight:800;">Sales priority</div>
            <div style="margin-top:16px;">{direct_markup}</div>
          </div>

          <div style="margin-top:18px;display:grid;grid-template-columns:1.15fr .85fr;gap:18px;">
            <div style="padding:24px;border-radius:28px;background:#ffffff;border:1px solid rgba(10,25,41,.08);">
              <div style="font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#607086;font-weight:800;">Watchlist</div>
              <table style="width:100%;margin-top:14px;border-collapse:collapse;">
                <thead>
                  <tr>
                    <th align="left" style="padding:0 10px 12px;color:#7d8b99;font-size:12px;">Notice</th>
                    <th align="left" style="padding:0 10px 12px;color:#7d8b99;font-size:12px;">Published</th>
                    <th align="left" style="padding:0 10px 12px;color:#7d8b99;font-size:12px;">Type</th>
                    <th align="left" style="padding:0 10px 12px;color:#7d8b99;font-size:12px;">Link</th>
                  </tr>
                </thead>
                <tbody>
                  {watch_markup or '<tr><td colspan="4" style="padding:12px 10px;color:#7d8b99;">No adjacent watch items in this run.</td></tr>'}
                </tbody>
              </table>
            </div>

            <div style="padding:24px;border-radius:28px;background:#ffffff;border:1px solid rgba(10,25,41,.08);">
              <div style="font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#607086;font-weight:800;">Source health</div>
              <div style="display:grid;gap:12px;margin-top:14px;">
                {health_markup}
              </div>
            </div>
          </div>
        </div>
      </body>
    </html>
    """.strip()


def send_email(payload: dict[str, Any]) -> None:
    if os.getenv("SEND_EMAIL", "0") not in {"1", "true", "TRUE"}:
        print("[info] Email skipped because SEND_EMAIL is not enabled.")
        return

    smtp_username = require_env("SMTP_USERNAME")
    smtp_password = require_env("SMTP_PASSWORD")
    smtp_host = os.getenv("SMTP_HOST") or DEFAULT_SMTP_HOST
    smtp_port = getenv_int("SMTP_PORT", DEFAULT_SMTP_PORT)
    email_to = os.getenv("EMAIL_TO") or DEFAULT_EMAIL_TO
    email_from = os.getenv("EMAIL_FROM") or smtp_username

    message = EmailMessage()
    message["Subject"] = f"Tender Intel Daily | {payload['report_date']}"
    message["From"] = email_from
    message["To"] = email_to
    message.set_content(build_text_email(payload))
    message.add_alternative(build_html_email(payload), subtype="html")

    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(smtp_username, smtp_password)
            server.send_message(message)
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(message)

    print(f"[info] Email sent to {email_to}")


def write_outputs(payload: dict[str, Any]) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    sales_payload = build_sales_payload(payload)
    DATA_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    SALES_DATA_FILE.write_text(json.dumps(sales_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    INDEX_FILE.write_text(render_html_v2(payload), encoding="utf-8")
    EXECUTIVE_FILE.write_text(render_executive_html(payload), encoding="utf-8")
    SALES_VIEW_FILE.write_text(render_sales_html(payload), encoding="utf-8")
    NOJEKYLL_FILE.write_text("", encoding="utf-8")
    write_sales_csv(sales_payload["items"])
    write_archive_snapshot(payload, sales_payload)
    write_archive_index()


def write_sales_csv(items: list[dict[str, Any]]) -> None:
    with SALES_CSV_FILE.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "priority",
                "opportunity_type",
                "title",
                "query_keyword",
                "published",
                "region",
                "amount",
                "source_name",
                "source_url",
                "summary",
                "sales_angle",
                "next_action",
            ],
        )
        writer.writeheader()
        for item in items:
            writer.writerow(
                {
                    "priority": item.get("priority", ""),
                    "opportunity_type": item.get("opportunity_type", ""),
                    "title": item.get("title", ""),
                    "query_keyword": item.get("query_keyword", ""),
                    "published": item.get("published", ""),
                    "region": item.get("region", ""),
                    "amount": item.get("amount", ""),
                    "source_name": item.get("source_name", ""),
                    "source_url": item.get("source_url", ""),
                    "summary": item.get("summary", ""),
                    "sales_angle": item.get("sales_angle", ""),
                    "next_action": item.get("next_action", ""),
                }
            )


def write_archive_snapshot(payload: dict[str, Any], sales_payload: dict[str, Any]) -> None:
    report_date = payload["report_date"]
    snapshot_dir = ARCHIVE_DIR / report_date
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    (snapshot_dir / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (snapshot_dir / "sales-top.json").write_text(
        json.dumps(sales_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (snapshot_dir / "index.html").write_text(render_html_v2(payload), encoding="utf-8")
    (snapshot_dir / "executive.html").write_text(render_executive_html(payload), encoding="utf-8")
    (snapshot_dir / "sales.html").write_text(render_sales_html(payload), encoding="utf-8")

    with (snapshot_dir / "sales-leads.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "priority",
                "opportunity_type",
                "title",
                "query_keyword",
                "published",
                "region",
                "amount",
                "source_name",
                "source_url",
                "summary",
                "sales_angle",
                "next_action",
            ],
        )
        writer.writeheader()
        for item in sales_payload["items"]:
            writer.writerow(
                {
                    "priority": item.get("priority", ""),
                    "opportunity_type": item.get("opportunity_type", ""),
                    "title": item.get("title", ""),
                    "query_keyword": item.get("query_keyword", ""),
                    "published": item.get("published", ""),
                    "region": item.get("region", ""),
                    "amount": item.get("amount", ""),
                    "source_name": item.get("source_name", ""),
                    "source_url": item.get("source_url", ""),
                    "summary": item.get("summary", ""),
                    "sales_angle": item.get("sales_angle", ""),
                    "next_action": item.get("next_action", ""),
                }
            )


def write_archive_index() -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_dirs = sorted([item for item in ARCHIVE_DIR.iterdir() if item.is_dir()], reverse=True)
    cards = []
    for snapshot_dir in snapshot_dirs:
        label = snapshot_dir.name
        cards.append(
            f"""
            <article class="card">
              <h2>{escape(label)}</h2>
              <div class="links">
                <a href="./{escape(label)}/index.html">Main</a>
                <a href="./{escape(label)}/executive.html">Executive</a>
                <a href="./{escape(label)}/sales.html">Sales</a>
                <a href="./{escape(label)}/latest.json">JSON</a>
              </div>
            </article>
            """.strip()
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Tender Archive</title>
    <style>
      :root {{ --bg:#08111a; --panel:#101b27; --line:rgba(255,255,255,.08); --text:#f6fbff; --muted:#9fb2c5; --gold:#f6cd87; }}
      * {{ box-sizing:border-box; }}
      body {{ margin:0; background:linear-gradient(180deg,#08111a 0%,#0d1722 100%); color:var(--text); font-family:"Segoe UI","Noto Sans SC",sans-serif; }}
      .shell {{ width:min(1100px,calc(100% - 28px)); margin:0 auto; padding:22px 0 40px; }}
      .hero {{ padding:28px; border-radius:28px; background:var(--panel); border:1px solid var(--line); }}
      .hero h1 {{ margin:0 0 10px; font-size:40px; }}
      .hero p {{ margin:0; color:var(--muted); line-height:1.9; }}
      .grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:16px; margin-top:18px; }}
      .card {{ padding:22px; border-radius:24px; background:var(--panel); border:1px solid var(--line); }}
      .card h2 {{ margin:0 0 12px; font-size:22px; }}
      .links {{ display:grid; gap:10px; }}
      .links a {{ display:inline-flex; padding:10px 14px; border-radius:999px; background:linear-gradient(135deg,var(--gold),#fff0ca); color:#08111a; text-decoration:none; font-weight:700; width:max-content; }}
      .empty {{ margin-top:18px; padding:22px; border-radius:22px; border:1px dashed var(--line); color:var(--muted); text-align:center; }}
      @media (max-width:900px) {{ .grid {{ grid-template-columns:1fr; }} }}
    </style>
  </head>
  <body>
    <div class="shell">
      <section class="hero">
        <h1>Archive Center</h1>
        <p>Daily tender snapshots for leadership review, sales follow-up, and historical traceability.</p>
      </section>
      {f'<section class="grid">{"".join(cards)}</section>' if cards else '<div class="empty">No archived snapshots yet.</div>'}
    </div>
  </body>
</html>"""
    ARCHIVE_INDEX_FILE.write_text(html, encoding="utf-8")


def collect_items() -> list[TenderItem]:
    demo_workbook = os.getenv("DEMO_WORKBOOK")
    if demo_workbook:
        return load_items_from_workbook(Path(demo_workbook))
    live_items = collect_live_items()
    if live_items:
        return live_items
    fallback_items = collect_yahoo_fallback_items()
    return [enrich_source_page(item) for item in fallback_items]


def main() -> int:
    items = collect_items()
    if not items:
        ai_summary = {
            "page_title": "Daily Tender Radar",
            "page_subtitle": "Public-source tender monitor completed with no collected notices.",
            "overview": (
                "No notices were collected in this run. Review source_health in latest.json to see "
                "whether the sources returned no matches or temporarily blocked automated access."
            ),
        }
        enriched_items: list[TenderItem] = []
    else:
        ai_summary, enriched_items = enrich_with_gemini(items)
    payload = build_payload(enriched_items, ai_summary)
    write_outputs(payload)
    send_email(payload)
    print(f"Generated {len(enriched_items)} notices into {INDEX_FILE}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"[error] {exc}", file=sys.stderr)
        raise SystemExit(1)
