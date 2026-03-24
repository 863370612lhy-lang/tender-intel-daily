from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import openpyxl
from openpyxl.utils.datetime import from_excel


ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT / "docs"
DATA_FILE = DOCS_DIR / "tenders.json"
INDEX_FILE = DOCS_DIR / "index.html"
NOJEKYLL_FILE = DOCS_DIR / ".nojekyll"

TAG_RULES = {
    "烟草": ["烟草", "中烟"],
    "文明吸烟环境": ["文明吸烟环境", "文明吸烟"],
    "吸烟室": ["吸烟室", "室内吸烟室"],
    "吸烟亭": ["吸烟亭"],
    "移动公厕": ["移动公厕", "移动厕所", "厕所", "公厕"],
    "垃圾房": ["垃圾房"],
    "集装箱厢房": ["集装箱", "厢房", "箱房", "岗亭", "模块化"],
}

PRIMARY_COLORS = {
    "文明吸烟环境": "#7af0d8",
    "吸烟室": "#ffd38a",
    "吸烟亭": "#8ec5ff",
    "移动公厕": "#ffa98f",
}


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ")
    return re.sub(r"\s+", " ", text).strip()


def excel_date_to_text(value: Any) -> str:
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
        return clean_text(converted)
    return clean_text(value)


def normalize_url(value: str) -> str:
    compact = value.replace(" ", "")
    return compact


def first_url(values: list[str]) -> tuple[str, list[str]]:
    urls: list[str] = []
    for value in values:
        if value.startswith("http://") or value.startswith("https://"):
            urls.append(normalize_url(value))
    if not urls:
        return "", []
    return urls[0], urls[1:]


def match_tags(title: str, sheet_name: str) -> list[str]:
    text = f"{sheet_name} {title}"
    tags = [label for label, keywords in TAG_RULES.items() if any(keyword in text for keyword in keywords)]
    if sheet_name not in tags:
        tags.insert(0, sheet_name)
    return list(dict.fromkeys(tag for tag in tags if tag))


def infer_relevance(title: str, tags: list[str]) -> int:
    score = 0
    joined = f"{title} {' '.join(tags)}"
    if "烟草" in joined or "中烟" in joined:
        score += 4
    if "文明吸烟环境" in joined:
        score += 3
    if "吸烟室" in joined or "吸烟亭" in joined:
        score += 2
    if "集装箱厢房" in tags or "垃圾房" in tags or "移动公厕" in tags:
        score += 1
    return score


def parse_sheet_rows(workbook: openpyxl.Workbook, workbook_name: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    index = 1

    for sheet in workbook.worksheets:
        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 3:
            continue

        for row in rows[2:]:
            if not any(cell not in (None, "") for cell in row):
                continue

            province = clean_text(row[1] if len(row) > 1 else "")
            city = clean_text(row[2] if len(row) > 2 else "")
            title = clean_text(row[3] if len(row) > 3 else "")
            budget = clean_text(row[4] if len(row) > 4 else "")
            buy_window = excel_date_to_text(row[5] if len(row) > 5 else "")
            open_time = excel_date_to_text(row[6] if len(row) > 6 else "")

            raw_values = [clean_text(cell) for cell in row]
            url, alt_urls = first_url(raw_values)
            host = urlparse(url).netloc if url else ""
            tags = match_tags(title, sheet.title)
            relevance = infer_relevance(title, tags)

            if not title:
                continue

            items.append(
                {
                    "id": index,
                    "sheet": sheet.title,
                    "workbook": workbook_name,
                    "province": province,
                    "city": city,
                    "title": title,
                    "budget": budget,
                    "buy_window": buy_window,
                    "open_time": open_time,
                    "url": url,
                    "alt_urls": alt_urls,
                    "host": host or "未标注来源域名",
                    "tags": tags,
                    "relevance": relevance,
                    "primary_tag": tags[0] if tags else sheet.title,
                }
            )
            index += 1

    items.sort(
        key=lambda item: (
            item["relevance"],
            item["open_time"],
            item["buy_window"],
            item["title"],
        ),
        reverse=True,
    )
    return items


def build_payload(items: list[dict[str, Any]], workbook_name: str) -> dict[str, Any]:
    provinces = Counter(item["province"] for item in items if item["province"])
    sheets = Counter(item["sheet"] for item in items if item["sheet"])
    hosts = Counter(item["host"] for item in items if item["host"])
    tobacco_related = sum(
        1 for item in items if any(tag in {"烟草", "文明吸烟环境", "吸烟室", "吸烟亭"} for tag in item["tags"])
    )

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "workbook_name": workbook_name,
        "summary": {
            "total_items": len(items),
            "tobacco_related_items": tobacco_related,
            "province_count": len(provinces),
            "source_host_count": len(hosts),
            "top_provinces": [{"name": name, "count": count} for name, count in provinces.most_common(8)],
            "top_sheets": [{"name": name, "count": count} for name, count in sheets.most_common()],
            "top_hosts": [{"name": name, "count": count} for name, count in hosts.most_common(6)],
        },
        "items": items,
    }


def render_html(payload: dict[str, Any]) -> str:
    data_json = json.dumps(payload, ensure_ascii=False)
    default_color = "#7af0d8"
    color_map_json = json.dumps(PRIMARY_COLORS, ensure_ascii=False)
    title = "Tender Signal Atlas"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
    <meta
      name="description"
      content="面向文明吸烟环境、吸烟室、吸烟亭、移动公厕等业务方向的招标情报看板。"
    />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600;700&family=Manrope:wght@400;500;600;700;800&family=Noto+Sans+SC:wght@400;500;700;900&display=swap"
      rel="stylesheet"
    />
    <style>
      :root {{
        --bg: #09111a;
        --bg-2: #101b29;
        --panel: rgba(12, 22, 34, 0.78);
        --panel-strong: rgba(9, 17, 26, 0.92);
        --line: rgba(145, 207, 255, 0.12);
        --text: #f6fbff;
        --muted: #9db0be;
        --mint: #7af0d8;
        --teal: #0fb7a2;
        --sand: #ffd38a;
        --coral: #ffa98f;
        --blue: #8ec5ff;
        --shadow: 0 30px 90px rgba(0, 0, 0, 0.32);
      }}

      * {{
        box-sizing: border-box;
      }}

      body {{
        margin: 0;
        color: var(--text);
        background:
          radial-gradient(circle at 15% 12%, rgba(15, 183, 162, 0.18), transparent 28%),
          radial-gradient(circle at 82% 18%, rgba(255, 211, 138, 0.14), transparent 24%),
          radial-gradient(circle at 50% 100%, rgba(142, 197, 255, 0.12), transparent 22%),
          linear-gradient(180deg, #09111a 0%, #0b1622 52%, #060c12 100%);
        font-family: "Noto Sans SC", "Manrope", sans-serif;
      }}

      .shell {{
        width: min(1320px, calc(100% - 28px));
        margin: 0 auto;
        padding: 22px 0 52px;
      }}

      .nav {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 16px;
        padding: 16px 18px;
        border: 1px solid var(--line);
        border-radius: 22px;
        background: rgba(9, 17, 26, 0.68);
        box-shadow: var(--shadow);
        backdrop-filter: blur(16px);
      }}

      .brand {{
        display: flex;
        align-items: center;
        gap: 12px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        font-family: "Manrope", sans-serif;
        font-size: 12px;
        font-weight: 800;
      }}

      .brand-dot {{
        width: 12px;
        height: 12px;
        border-radius: 999px;
        background: linear-gradient(135deg, var(--sand), var(--mint));
        box-shadow: 0 0 18px rgba(122, 240, 216, 0.65);
      }}

      .nav-meta {{
        color: var(--muted);
        font-size: 13px;
      }}

      .hero {{
        display: grid;
        grid-template-columns: 1.12fr 0.88fr;
        gap: 20px;
        margin-top: 24px;
      }}

      .hero-main,
      .hero-side {{
        border: 1px solid var(--line);
        border-radius: 32px;
        background: var(--panel);
        box-shadow: var(--shadow);
        backdrop-filter: blur(18px);
      }}

      .hero-main {{
        padding: 30px;
        position: relative;
        overflow: hidden;
      }}

      .hero-main::after {{
        content: "";
        position: absolute;
        inset: auto -10% -24% auto;
        width: 300px;
        height: 300px;
        border-radius: 999px;
        background: radial-gradient(circle, rgba(122, 240, 216, 0.24), transparent 65%);
      }}

      .eyebrow {{
        margin: 0;
        color: var(--mint);
        font-family: "Manrope", sans-serif;
        font-size: 12px;
        font-weight: 800;
        letter-spacing: 0.18em;
        text-transform: uppercase;
      }}

      h1 {{
        margin: 14px 0 12px;
        font-family: "Cormorant Garamond", serif;
        font-size: clamp(46px, 6vw, 78px);
        line-height: 0.92;
        font-weight: 600;
      }}

      .hero-subtitle {{
        margin: 0;
        max-width: 760px;
        color: #e7f7f4;
        font-size: clamp(17px, 2vw, 23px);
        line-height: 1.8;
      }}

      .hero-body {{
        margin-top: 16px;
        max-width: 760px;
        color: var(--muted);
        font-size: 14px;
        line-height: 1.9;
      }}

      .stat-grid {{
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
        margin-top: 24px;
      }}

      .stat {{
        padding: 16px;
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 18px;
        background: rgba(255, 255, 255, 0.03);
      }}

      .stat span {{
        display: block;
        color: var(--muted);
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }}

      .stat strong {{
        display: block;
        margin-top: 8px;
        font-family: "Manrope", sans-serif;
        font-size: 28px;
        font-weight: 800;
      }}

      .hero-side {{
        padding: 24px;
      }}

      .panel-title {{
        margin: 0 0 14px;
        color: var(--muted);
        font-size: 12px;
        font-weight: 800;
        letter-spacing: 0.14em;
        text-transform: uppercase;
      }}

      .rank-list {{
        display: grid;
        gap: 12px;
      }}

      .rank-item {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 14px 16px;
        border-radius: 18px;
        border: 1px solid rgba(255, 255, 255, 0.06);
        background: rgba(255, 255, 255, 0.03);
      }}

      .rank-name {{
        font-size: 15px;
      }}

      .rank-count {{
        color: var(--sand);
        font-family: "Manrope", sans-serif;
        font-weight: 800;
      }}

      .filters {{
        display: grid;
        grid-template-columns: 1.3fr 0.7fr 0.7fr;
        gap: 12px;
        margin-top: 26px;
      }}

      .filter-box {{
        padding: 14px 16px;
        border: 1px solid var(--line);
        border-radius: 18px;
        background: rgba(8, 16, 25, 0.72);
      }}

      .filter-box label {{
        display: block;
        margin-bottom: 8px;
        color: var(--muted);
        font-size: 12px;
      }}

      .filter-box input,
      .filter-box select {{
        width: 100%;
        border: none;
        outline: none;
        color: var(--text);
        background: transparent;
        font-size: 15px;
      }}

      .filter-box option {{
        color: #0f1720;
      }}

      .chip-row {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 18px;
      }}

      .chip {{
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 999px;
        padding: 10px 14px;
        color: var(--text);
        background: rgba(255, 255, 255, 0.04);
        font-size: 13px;
        cursor: pointer;
        transition: 160ms ease;
      }}

      .chip.active,
      .chip:hover {{
        border-color: rgba(122, 240, 216, 0.35);
        background: rgba(122, 240, 216, 0.12);
      }}

      .section-head {{
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 12px;
        margin: 32px 0 16px;
      }}

      .section-head h2 {{
        margin: 0;
        font-family: "Manrope", sans-serif;
        font-size: 18px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }}

      .section-head span {{
        color: var(--muted);
        font-size: 13px;
      }}

      .grid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 18px;
      }}

      .card {{
        border: 1px solid var(--line);
        border-radius: 28px;
        overflow: hidden;
        background: var(--panel-strong);
        box-shadow: var(--shadow);
      }}

      .card-top {{
        position: relative;
        padding: 20px 20px 18px;
        background:
          radial-gradient(circle at 80% 20%, rgba(255, 255, 255, 0.08), transparent 18%),
          linear-gradient(135deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0.08));
      }}

      .accent-line {{
        position: absolute;
        inset: 0 auto auto 0;
        width: 100%;
        height: 4px;
        background: var(--accent, {default_color});
      }}

      .badge-row {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }}

      .badge {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 7px 10px;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.05);
        font-size: 12px;
      }}

      .badge strong {{
        font-weight: 800;
      }}

      .card h3 {{
        margin: 16px 0 0;
        font-size: 22px;
        line-height: 1.45;
      }}

      .card-body {{
        padding: 20px;
      }}

      .meta {{
        display: grid;
        gap: 10px;
      }}

      .meta-item {{
        display: flex;
        justify-content: space-between;
        gap: 12px;
        padding-bottom: 10px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.06);
      }}

      .meta-item:last-child {{
        padding-bottom: 0;
        border-bottom: none;
      }}

      .meta-item span {{
        color: var(--muted);
        font-size: 12px;
      }}

      .meta-item strong {{
        flex: 1;
        text-align: right;
        font-size: 13px;
        line-height: 1.6;
      }}

      .tag-list {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 16px;
      }}

      .tag {{
        padding: 7px 10px;
        border-radius: 999px;
        background: rgba(122, 240, 216, 0.08);
        color: #dffcf7;
        font-size: 12px;
      }}

      .actions {{
        display: flex;
        gap: 10px;
        margin-top: 18px;
      }}

      .link-btn {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 999px;
        padding: 12px 15px;
        text-decoration: none;
        font-size: 13px;
        font-weight: 700;
      }}

      .link-primary {{
        color: #0a151e;
        background: linear-gradient(135deg, var(--sand), #fff1cb);
      }}

      .link-secondary {{
        color: var(--text);
        border: 1px solid rgba(255, 255, 255, 0.1);
        background: rgba(255, 255, 255, 0.03);
      }}

      .empty {{
        padding: 28px;
        border: 1px dashed rgba(255, 255, 255, 0.14);
        border-radius: 24px;
        color: var(--muted);
        text-align: center;
      }}

      .footer {{
        margin-top: 28px;
        color: var(--muted);
        font-size: 13px;
        line-height: 1.9;
        text-align: center;
      }}

      @media (max-width: 1120px) {{
        .hero,
        .filters {{
          grid-template-columns: 1fr;
        }}

        .grid {{
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }}

        .stat-grid {{
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }}
      }}

      @media (max-width: 760px) {{
        .shell {{
          width: min(100% - 18px, 1320px);
          padding-top: 16px;
        }}

        .nav {{
          flex-direction: column;
          align-items: flex-start;
        }}

        .hero-main,
        .hero-side,
        .card {{
          border-radius: 24px;
        }}

        .hero-main {{
          padding: 22px;
        }}

        .grid,
        .stat-grid {{
          grid-template-columns: 1fr;
        }}

        .card h3 {{
          font-size: 20px;
        }}

        .actions {{
          flex-direction: column;
        }}
      }}
    </style>
  </head>
  <body>
    <div class="shell">
      <nav class="nav">
        <div class="brand">
          <span class="brand-dot"></span>
          <span>Tender Signal Atlas</span>
        </div>
        <div class="nav-meta">历史样本来自 {payload["workbook_name"]}，生成时间 {payload["generated_at"]}</div>
      </nav>

      <section class="hero">
        <div class="hero-main">
          <p class="eyebrow">Business Intelligence Surface</p>
          <h1>文明吸烟环境招标情报中枢</h1>
          <p class="hero-subtitle">
            把去年的人工整理表，转成可以筛选、搜索、回溯原始链接的高级看板。
          </p>
          <p class="hero-body">
            这份原型先基于你提供的历史 Excel 建站，用来沉淀你们的项目定义、关键词模型和销售跟进线索。
            下一阶段只要把“历史表输入”替换成“官方公开渠道每日采集”，就能升级成自动跑数、自动发邮箱的正式系统。
          </p>

          <div class="stat-grid">
            <div class="stat">
              <span>历史项目</span>
              <strong>{payload["summary"]["total_items"]}</strong>
            </div>
            <div class="stat">
              <span>烟草相关</span>
              <strong>{payload["summary"]["tobacco_related_items"]}</strong>
            </div>
            <div class="stat">
              <span>覆盖省份</span>
              <strong>{payload["summary"]["province_count"]}</strong>
            </div>
            <div class="stat">
              <span>来源域名</span>
              <strong>{payload["summary"]["source_host_count"]}</strong>
            </div>
          </div>
        </div>

        <aside class="hero-side">
          <p class="panel-title">重点地区</p>
          <div class="rank-list" id="province-ranks"></div>
          <p class="panel-title" style="margin-top: 20px;">主要来源</p>
          <div class="rank-list" id="host-ranks"></div>
        </aside>
      </section>

      <section class="filters">
        <div class="filter-box">
          <label for="search-input">搜索项目名称 / 标签 / 地区</label>
          <input id="search-input" type="text" placeholder="例如：烟草、吸烟室、移动厕所、江苏" />
        </div>
        <div class="filter-box">
          <label for="province-filter">按省份筛选</label>
          <select id="province-filter">
            <option value="">全部省份</option>
          </select>
        </div>
        <div class="filter-box">
          <label for="sheet-filter">按业务类别筛选</label>
          <select id="sheet-filter">
            <option value="">全部类别</option>
          </select>
        </div>
      </section>

      <div class="chip-row" id="tag-chips"></div>

      <section>
        <div class="section-head">
          <h2>Project Stream</h2>
          <span id="result-count"></span>
        </div>
        <div class="grid" id="card-grid"></div>
        <div class="empty" id="empty-state" hidden>当前筛选条件下没有匹配项目。</div>
      </section>

      <div class="footer">
        页面仅用于历史样本沉淀和后续自动化设计。正式生产版建议只抓取公开来源，并始终保留公告原址链接，不绕过登录、反爬或会员限制。
      </div>
    </div>

    <script>
      const DATA = {data_json};
      const COLOR_MAP = {color_map_json};
      const provinceSelect = document.getElementById("province-filter");
      const sheetSelect = document.getElementById("sheet-filter");
      const searchInput = document.getElementById("search-input");
      const resultCount = document.getElementById("result-count");
      const cardGrid = document.getElementById("card-grid");
      const emptyState = document.getElementById("empty-state");
      const chipRow = document.getElementById("tag-chips");

      let activeTag = "";

      function buildRankList(targetId, items) {{
        const target = document.getElementById(targetId);
        target.innerHTML = items
          .map(
            item => `
              <div class="rank-item">
                <span class="rank-name">${{item.name}}</span>
                <span class="rank-count">${{item.count}}</span>
              </div>
            `
          )
          .join("");
      }}

      function buildSelectOptions() {{
        const provinces = [...new Set(DATA.items.map(item => item.province).filter(Boolean))].sort();
        const sheets = [...new Set(DATA.items.map(item => item.sheet).filter(Boolean))];

        provinceSelect.innerHTML += provinces
          .map(name => `<option value="${{name}}">${{name}}</option>`)
          .join("");
        sheetSelect.innerHTML += sheets
          .map(name => `<option value="${{name}}">${{name}}</option>`)
          .join("");
      }}

      function buildChips() {{
        const tags = [...new Set(DATA.items.flatMap(item => item.tags))];
        chipRow.innerHTML = ['全部', ...tags]
          .map(tag => {{
            const value = tag === '全部' ? '' : tag;
            const activeClass = value === activeTag ? 'chip active' : 'chip';
            return `<button class="${{activeClass}}" data-tag="${{value}}">${{tag}}</button>`;
          }})
          .join("");

        chipRow.querySelectorAll(".chip").forEach(button => {{
          button.addEventListener("click", () => {{
            activeTag = button.dataset.tag || "";
            buildChips();
            renderCards();
          }});
        }});
      }}

      function cardTemplate(item) {{
        const accent = COLOR_MAP[item.sheet] || "{default_color}";
        const altLink = item.alt_urls && item.alt_urls.length
          ? `<a class="link-btn link-secondary" href="${{item.alt_urls[0]}}" target="_blank" rel="noreferrer">备用网址</a>`
          : "";

        return `
          <article class="card">
            <div class="card-top" style="--accent: ${{accent}}">
              <div class="accent-line"></div>
              <div class="badge-row">
                <span class="badge"><strong>${{item.sheet}}</strong></span>
                <span class="badge">${{item.province || '未标注省份'}}${{item.city ? ' / ' + item.city : ''}}</span>
                <span class="badge">${{item.host || '未标注来源'}}</span>
              </div>
              <h3>${{item.title}}</h3>
            </div>
            <div class="card-body">
              <div class="meta">
                <div class="meta-item">
                  <span>预算金额</span>
                  <strong>${{item.budget || '未披露'}}</strong>
                </div>
                <div class="meta-item">
                  <span>购买标书</span>
                  <strong>${{item.buy_window || '未披露'}}</strong>
                </div>
                <div class="meta-item">
                  <span>开标时间</span>
                  <strong>${{item.open_time || '未披露'}}</strong>
                </div>
              </div>
              <div class="tag-list">
                ${{item.tags.map(tag => `<span class="tag">${{tag}}</span>`).join("")}}
              </div>
              <div class="actions">
                <a class="link-btn link-primary" href="${{item.url || '#'}}" target="_blank" rel="noreferrer">查看原公告</a>
                ${{altLink}}
              </div>
            </div>
          </article>
        `;
      }}

      function renderCards() {{
        const searchValue = searchInput.value.trim().toLowerCase();
        const provinceValue = provinceSelect.value;
        const sheetValue = sheetSelect.value;

        const filtered = DATA.items.filter(item => {{
          const blob = [
            item.title,
            item.province,
            item.city,
            item.sheet,
            ...(item.tags || []),
          ].join(" ").toLowerCase();

          const matchSearch = !searchValue || blob.includes(searchValue);
          const matchProvince = !provinceValue || item.province === provinceValue;
          const matchSheet = !sheetValue || item.sheet === sheetValue;
          const matchTag = !activeTag || (item.tags || []).includes(activeTag);

          return matchSearch && matchProvince && matchSheet && matchTag;
        }});

        resultCount.textContent = `当前展示 ${{filtered.length}} / ${{DATA.items.length}} 个项目`;
        cardGrid.innerHTML = filtered.map(cardTemplate).join("");
        emptyState.hidden = filtered.length !== 0;
      }}

      buildRankList("province-ranks", DATA.summary.top_provinces);
      buildRankList("host-ranks", DATA.summary.top_hosts);
      buildSelectOptions();
      buildChips();
      renderCards();

      searchInput.addEventListener("input", renderCards);
      provinceSelect.addEventListener("change", renderCards);
      sheetSelect.addEventListener("change", renderCards);
    </script>
  </body>
</html>
"""


def write_outputs(payload: dict[str, Any]) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    INDEX_FILE.write_text(render_html(payload), encoding="utf-8")
    NOJEKYLL_FILE.write_text("", encoding="utf-8")


def build_dashboard(workbook_path: Path) -> dict[str, Any]:
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    items = parse_sheet_rows(workbook, workbook_path.name)
    payload = build_payload(items, workbook_path.name)
    write_outputs(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a premium tender dashboard from a workbook.")
    parser.add_argument("workbook", type=Path, help="Path to the source .xlsx workbook.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workbook_path = args.workbook.expanduser().resolve()
    if not workbook_path.exists():
        raise FileNotFoundError(f"Workbook not found: {workbook_path}")

    payload = build_dashboard(workbook_path)
    print(
        f"Generated dashboard with {payload['summary']['total_items']} items into {INDEX_FILE}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
