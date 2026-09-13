# rsl-project-watch

GitHub Actions 每天抓 [ETH RSL 在招学生项目](https://rsl.ethz.ch/education-students/student-projects0/available-projects.html) 页面自带的 JSON feed，与快照 diff，把结果写进 `state/latest_run.json`，供每天 07:00 的 Cowork 定时任务免鉴权读取（Cowork 云端连不上 rsl.ethz.ch / sirop.org，Actions runner 可以）。

- 定时：`23 3 * * *`（UTC）= 瑞士 05:23 夏令时 / 04:23 冬令时；Actions 页也可手动 Run workflow。
- 本地只跑自检 `python3 check_rsl_projects.py --selftest`；直接运行会改 `state/`，和远端快照打架。
- `state/seen.json` 是快照 `{url: title}`；`state/history.jsonl` 是新增/下架流水（2026-09-13 之前的记录来自原 Mac 本地任务）。

## `state/latest_run.json`

    curl -fsS https://raw.githubusercontent.com/Yang251552/rsl-project-watch/main/state/latest_run.json

| 字段 | 含义 |
|---|---|
| `run_at` | 运行时间，瑞士时区，带偏移 |
| `push_date` | 该由哪天 07:00 的推送读取（`YYYY-MM-DD`） |
| `status` | `NEW` / `NONE` / `BASELINE` / `FETCH_FAILED` / `SUSPECT_EMPTY` |
| `listed` | 页面当前在挂项目数；抓取失败时为 `null` |
| `new` | 待推送的新增 `[{title, url, date, desc}]`，去重键是 `url` |
| `error` | `FETCH_FAILED` 的报错，否则 `null` |

同一 `push_date` 内的多次运行（手动触发、cron 延迟过 07:00）会累加 `new` 而不是覆盖：新增最多晚一天推，不会漏。唯一的缝：07:00 刚过、Cowork 还没读到的那几分钟里又跑了一次，当天待读的列表会被换成次日的——手动触发请避开 07:00–07:15。

## Cowork 定时任务提示词（每天 07:00，可直接粘贴）

每天早上 7 点检查 ETH RSL 有没有新增的在招学生项目。结果直接写在回复正文里，不要创建任何文件；用中文，项目英文标题原样保留（那是找项目的唯一标识，不要翻译）。

取数（唯一数据来源；不要自己抓 rsl.ethz.ch / sirop.org，云端会 403）：

    curl -fsS https://raw.githubusercontent.com/Yang251552/rsl-project-watch/main/state/latest_run.json

按顺序判断：

1. curl 失败或不是合法 JSON → 如实说明取数失败，附页面链接 https://rsl.ethz.ch/education-students/student-projects0/available-projects.html 。**绝不编造项目。**
2. `push_date` 早于今天（`TZ=Europe/Zurich date +%F`）→ 今天的检查没跑：写「ETH RSL：今天的自动检查没有运行（最近一次 <run_at>）」，附 https://github.com/Yang251552/rsl-project-watch/actions 和页面链接，不列项目。
3. `new` 非空 → 标题「🔔 ETH RSL 新增 N 个在招项目」，逐个两行：`title` 原样（英文不翻译）一行、`url` 一行。不筛选、不加描述。
4. 再按 `status` 补一句：
   - `NONE` → 「ETH RSL：当前没有最新的在招项目。」
   - `BASELINE` → 已开始追踪，共 `listed` 个项目，本次不算新增。
   - `FETCH_FAILED` / `SUSPECT_EMPTY` → 今天抓取失败 / feed 返回空，快照未改动（附 `error`），附页面链接让我手动查看。
