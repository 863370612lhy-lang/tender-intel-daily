# Live Validation Notes

Validation date: 2026-03-23

## What was verified

- The live pipeline can run end-to-end and produce output files locally.
- Public-source access from this environment is mixed:
  - `search.ccgp.gov.cn` was reachable, but repeated keyword queries hit the site's "frequent access" protection.
  - `deal.ggzy.gov.cn` failed SSL handshake from Python in this environment.
- To keep the project usable, the script now writes a report even when zero live notices are collected and records source health in `latest.json`.

## Confirmed public examples from current web validation

These examples show that the target market is publicly discoverable outside paid aggregators.

1. Civil smoking environment
   - Title: 湖南省烟草公司怀化市公司关于2025年度文明吸烟环境建设项目招标公告
   - Date shown in search results: 2025-06-24 16:00
   - Public source: 怀化市公共资源交易中心
   - URL: https://ggzy.huaihua.gov.cn/ggzyjyzx/c116119/202506/269d87081b074ea8bfbaa58d97e6d6df.shtml

2. Civil smoking environment
   - Title: 湖南省烟草公司衡阳市公司文明吸烟环境建设项目（一标段）公开招标公告
   - Date shown in search results: 2025-07-14
   - Budget shown in search results: 929880元
   - Public source: 衡阳市公共资源交易网
   - URL: http://hyggzyjy.hengyang.gov.cn/jyxx/003002/003002001/20250714/d5fcf0a2-5f9a-4bdd-b976-6fddfdd2115a.html

3. Mobile toilet
   - Title: 2026年春节期间深圳湾口岸放置临时移动公厕租赁服务
   - Date shown in search results: 2026-01-19
   - Control price shown in search results: 60000元
   - Public source: 深圳市南山区人民政府
   - URL: https://www.szns.gov.cn/xxgk/qzfxxgkml/qt/tzgg/content/post_12017245.html

4. Tobacco system procurement
   - Title: 中国烟草总公司海南省公司容灾专线和互联网专线服务（2026-2029年）采购项目-公开招标公告
   - Date shown in search results: 2025-09-29 17:46
   - Amount shown in search results: 144.4320万元
   - Public source: 全国公共资源交易平台
   - URL: https://ggzy.gov.cn/information/html/b/460000/0201/202509/29/0046ea5f47833db74ab6aa2a9b4ab4f641ec.shtml

5. Tobacco system construction
   - Title: 同仁市烟草专卖局（营销部）经营业务用房项目标段一招标公告
   - Date shown in search results: 2025-12-25 15:39
   - Public source: 全国公共资源交易平台
   - URL: https://ggzy.gov.cn/information/html/b/630000/0101/202512/25/006359ef8603a6364385a9f7accda35cce5d.shtml

6. Adjacent category: garbage room
   - Title: 平房区2024年城市基础设施维修改造项目一期工程项目-生活垃圾房、阳光玻璃房...
   - Date shown in search results: 2025-08-14 15:12
   - Public source: 全国公共资源交易平台
   - URL: https://ggzy.gov.cn/information/html/b/230000/0101/202508/14/0023fab6964e867f44d592905328c9cca7a9.shtml

## Acceptance meaning

This proves the core business assumption is valid:

- public sources do contain tobacco-related, civil smoking environment, and adjacent-space opportunities
- a self-built AI pipeline can replace a large part of manual paid-aggregator monitoring
- the remaining challenge is source-specific access stability, not data availability
