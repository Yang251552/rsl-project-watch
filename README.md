# rsl-project-watch

GitHub Actions 每天抓 [ETH RSL 在招学生项目](https://rsl.ethz.ch/education-students/student-projects0/available-projects.html) 页面自带的 JSON feed，与快照 diff，把结果写进 `state/latest_run.json`，供每天 07:00 的 Cowork 定时任务免鉴权读取（Cowork 云端连不上 rsl.ethz.ch / sirop.org，Actions runner 可以）。

- 定时：`23 3,19 * * *`（UTC）= 瑞士 05:23 与 21:23（夏令时）/ 04:23 与 20:23（冬令时）；Actions 页也可随时手动 Run workflow。GitHub 的 `schedule` 只是尽力而为（无 SLA，高负载时延迟甚至丢弃）：2026-09-14/15 的 03:23 UTC 两次都晚了约 5.5 小时才创建运行，所以加一次前一晚的运行给 07:00 读取兜底；早上那次准点时数据更新鲜。
- 本地只跑自检 `python3 check_rsl_projects.py --selftest`；直接运行会改 `state/` 和 `summary/`，和远端快照打架。
- `state/seen.json` 是快照 `{url: title}`；`state/history.jsonl` 是新增/下架流水（2026-09-13 之前的记录来自原 Mac 本地任务）。
- [`summary/new-projects.md`](summary/new-projects.md) 是历次新增汇总：每次检查后从 `state/history.jsonl` 全量重新生成（原文件内更新，有新增时 diff 只多出新的几行），按检出日期（瑞士时间）分组、新的在上。

## `state/latest_run.json`

    curl -fsS https://raw.githubusercontent.com/Yang251552/rsl-project-watch/main/state/latest_run.json

| 字段 | 含义 |
|---|---|
| `run_at` | 最近一次运行的时间，瑞士时区，带偏移 |
| `status` | 最近一次运行的结果：`NEW`（检出新增）/ `NONE` / `BASELINE`（快照重建）/ `FETCH_FAILED` / `SUSPECT_EMPTY`（feed 为空） |
| `listed` | 页面当前在挂项目数；`FETCH_FAILED` / `SUSPECT_EMPTY` 时为 `null` |
| `new` | 最近 7 天检出的新增 `[{title, url, date, desc, push_date}]`，去重键是 `url`；超过 7 天的自动移除 |
| `error` | `FETCH_FAILED` 的报错，否则 `null` |

每条新增自带 `push_date`，即该由哪天 07:00 的推送列出：06:40 之前检出的算当天，之后的算次日（留 20 分钟给运行、push 和 raw 的 5 分钟缓存）。每条在 `new` 里保留 7 天，所以 cron 延迟、任意时间手动触发都不会让它在该推的那天之前被冲掉。推送只列当天的；Cowork 哪天没跑，那天的条目不补推，但一定在 `summary/new-projects.md` 里，读取规则第 4 条每天附上它的链接。前提：Cowork 不早于 06:50 读取。

## Cowork 定时任务提示词（每天 07:00，可直接粘贴）

每天早上 7 点检查 ETH RSL 有没有新增的在招学生项目。结果直接写在回复正文里，不要创建任何文件；用中文，项目英文标题原样保留（那是找项目的唯一标识，不要翻译）。

取数（唯一数据来源；不要自己抓 rsl.ethz.ch / sirop.org，云端会 403）：

    curl -fsS https://raw.githubusercontent.com/Yang251552/rsl-project-watch/main/state/latest_run.json

按顺序处理：

1. curl 失败或不是合法 JSON → 如实说明取数失败，附页面链接 https://rsl.ethz.ch/education-students/student-projects0/available-projects.html 。**绝不编造项目。**
2. 今天 = `TZ=Europe/Zurich date +%F`。挑 `new` 里 `push_date` 等于今天的条目。有 → 标题「🔔 ETH RSL 新增 N 个在招项目」，逐个两行：`title` 原样一行、`url` 一行，不筛选、不加描述。
3. 再补一句，取第一条命中的：
   - `run_at` 距现在超过 30 小时（07:00 读取时即早于昨天 01:00）→ 「ETH RSL：自动检查已超过 30 小时没有跑完（最近一次 <run_at>）」，附 https://github.com/Yang251552/rsl-project-watch/actions 和页面链接。
   - `status` 是 `FETCH_FAILED` 或 `SUSPECT_EMPTY` → 「ETH RSL：最近一次抓取失败 / feed 为空，快照未改动」（`error` 非空就附上），附页面链接。
   - `status` 是 `BASELINE` → 「ETH RSL：快照已重建，共 <listed> 个在挂项目，重建时已在挂的不算新增。」
   - 第 2 步一条都没有 → 「ETH RSL：当前没有最新的在招项目。」
4. 最后单独一行，原样照抄：「📄 历次新增汇总（按日期）：https://github.com/Yang251552/rsl-project-watch/blob/main/summary/new-projects.md」。不要再列 `push_date` 早于今天的条目，它们都在这个汇总里。
