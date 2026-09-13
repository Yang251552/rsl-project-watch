# rsl-project-watch

GitHub Actions 每天抓 [ETH RSL 在招学生项目](https://rsl.ethz.ch/education-students/student-projects0/available-projects.html) 页面自带的 JSON feed，与快照 diff，把结果写进 `state/latest_run.json`，供每天 07:00 的 Cowork 定时任务免鉴权读取（Cowork 云端连不上 rsl.ethz.ch / sirop.org，Actions runner 可以）。

- 定时：`23 3 * * *`（UTC）= 瑞士 05:23 夏令时 / 04:23 冬令时；Actions 页也可随时手动 Run workflow。
- 本地只跑自检 `python3 check_rsl_projects.py --selftest`；直接运行会改 `state/`，和远端快照打架。
- `state/seen.json` 是快照 `{url: title}`；`state/history.jsonl` 是新增/下架流水（2026-09-13 之前的记录来自原 Mac 本地任务）。

## `state/latest_run.json`

    curl -fsS https://raw.githubusercontent.com/Yang251552/rsl-project-watch/main/state/latest_run.json

| 字段 | 含义 |
|---|---|
| `run_at` | 最近一次运行的时间，瑞士时区，带偏移 |
| `status` | 最近一次运行的结果：`NEW`（检出新增）/ `NONE` / `BASELINE`（快照重建）/ `FETCH_FAILED` / `SUSPECT_EMPTY`（feed 为空） |
| `listed` | 页面当前在挂项目数；`FETCH_FAILED` / `SUSPECT_EMPTY` 时为 `null` |
| `new` | 待推送的新增 `[{title, url, date, desc, push_date}]`，去重键是 `url` |
| `error` | `FETCH_FAILED` 的报错，否则 `null` |

每条新增自带 `push_date`，即该由哪天 07:00 的推送列出：06:40 之前检出的算当天，之后的算次日（留 20 分钟给运行、push 和 raw 的 5 分钟缓存）。每次运行都带上 `push_date` 还没过去的条目，所以 cron 延迟、任意时间手动触发、当天晚读，都不会漏推或重复推。前提：Cowork 不早于 06:50 读取。

## Cowork 定时任务提示词（每天 07:00，可直接粘贴）

每天早上 7 点检查 ETH RSL 有没有新增的在招学生项目。结果直接写在回复正文里，不要创建任何文件；用中文，项目英文标题原样保留（那是找项目的唯一标识，不要翻译）。

取数（唯一数据来源；不要自己抓 rsl.ethz.ch / sirop.org，云端会 403）：

    curl -fsS https://raw.githubusercontent.com/Yang251552/rsl-project-watch/main/state/latest_run.json

按顺序处理：

1. curl 失败或不是合法 JSON → 如实说明取数失败，附页面链接 https://rsl.ethz.ch/education-students/student-projects0/available-projects.html 。**绝不编造项目。**
2. 今天 = `TZ=Europe/Zurich date +%F`。只挑 `new` 里 `push_date` 等于今天的条目（其他日期的要么推过、要么明天推，一律不列）。有 → 标题「🔔 ETH RSL 新增 N 个在招项目」，逐个两行：`title` 原样一行、`url` 一行，不筛选、不加描述。
3. 再补一句，取第一条命中的：
   - `run_at` 的日期早于今天 → 「ETH RSL：今天的自动检查还没完成（最近一次 <run_at>）」，附 https://github.com/Yang251552/rsl-project-watch/actions 和页面链接。
   - `status` 是 `FETCH_FAILED` 或 `SUSPECT_EMPTY` → 「ETH RSL：最近一次抓取失败 / feed 为空，快照未改动」（`error` 非空就附上），附页面链接。
   - `status` 是 `BASELINE` → 「ETH RSL：快照已重建，共 <listed> 个在挂项目，重建时已在挂的不算新增。」
   - 第 2 步一条都没有 → 「ETH RSL：当前没有最新的在招项目。」
