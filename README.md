# newsdesk · 资讯解读站

一个给自己和朋友看的资讯站：自动抓官方文件、经济数据和媒体标题，每份官方文件生成一张事件卡，按影响范围分级，给事件配**每条结论都能点回原文**的 AI 解读。

- 线上站点：https://derek2035.github.io/newsdesk/
- 产品与技术方案：[CLAUDE.md](CLAUDE.md)
- 第 0 步手工事件卡底稿：[docs/step0/worksheet-fomc-2026-09-16.md](docs/step0/worksheet-fomc-2026-09-16.md)
- 当前计划：[.plan/v1.md](.plan/v1.md)

## 现在是第 1 版

| 做了 | 还没做 |
| --- | --- |
| 3 个官方源（美联储、国家统计局、中国政府网）+ 8 个媒体 RSS | 跨语言聚类（第 2 版） |
| 事件页：解读为主体，六段（事实三段 + 连锁反应 / 演化路径推演两段 + 各源差异），原文与信源作佐证 | 「被低估」栏与 GDELT 覆盖度（第 2 版） |
| 三道校验闸门：格式 / 逐字引文 / 数字回填；推演另加证伪信号与措辞检查 | 本地 cross-encoder 蕴含判定（用逐字引文代替） |
| 今日流、事件卡、归档搜索三页，静态站 | 访问控制（目前公开发布，页面 noindex + robots Disallow） |
| launchd 每日定时，失败不发布 | FOMC 会议纪要全文（新闻稿只是通知，第 1 版这类事件没有解读） |

## 跑起来

```bash
uv venv && uv pip install -e ".[dev]"
```

```bash
.venv/bin/python -m newsdesk run --no-publish
```

分步命令：

| 命令 | 作用 |
| --- | --- |
| `python -m newsdesk fetch` | 抓全部源（`--only fed,stats_cn` 只抓部分） |
| `python -m newsdesk events` | L1 文档 → 事件，范围打分、分级、挂媒体报道、判转载 |
| `python -m newsdesk interpret` | 给还没有解读的事件生成解读并过闸门（`--slug` 指定，`--force` 重做） |
| `python -m newsdesk regate` | 闸门规则改进后，用库里存的模型原始输出重新过闸门，不调模型 |
| `python -m newsdesk build` | 生成静态站到 `site/`（先写到 `site.tmp/`，成功才替换） |
| `python -m newsdesk publish` | 把 `site/` 推到 `gh-pages` 分支 |
| `python -m newsdesk stats` | 各表行数与闸门通过率 |

本地预览：

```bash
.venv/bin/python -m http.server 18321 --bind 127.0.0.1 -d site
```

测试（抓取器 golden file + 闸门）：

```bash
.venv/bin/python -m pytest -q
```

## 定时运行

```bash
cp launchd/com.derek.newsdesk.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.derek.newsdesk.plist
```

每天 07:30 跑 `scripts/run_daily.sh`：抓取 → 事件 → 解读 → 建站 → 发布 → 数据库快照提交。任何一步失败都不发布，站点停在上一个好版本，并弹 macOS 通知。日志在 `logs/`。

## 模型调用

| 等级 | 模型 | 实际情况 |
| --- | --- | --- |
| A+ / A | `claude-fable-5-1` | 本机 CLI 网关目前没有 Fable 通道，自动降级到 Opus 5，卡片署名写实际模型 |
| B | `claude-opus-5` | |
| C | `claude-sonnet-5` | |
| 标题翻译 | `claude-haiku-4-5-20251001` | |

- 设了 `ANTHROPIC_API_KEY`：走官方 SDK，temperature=0
- 没设：走本机 `claude -p`（订阅额度），关掉工具、替换系统提示词、在空目录里运行。CLI 不支持 temperature，靠固定 schema 和校验闸门兜底。用订阅额度跑定时批处理是否符合使用条款，请自行确认
- 不可用的模型会缓存 24 小时（`data/model_unavailable.json`），不会每次都白等超时

改模型档位：`newsdesk/config.py` 的 `GRADE_MODELS`。

## 信源与合规边界

- 只抓 robots.txt 允许的页面，同域名请求间隔 ≥ 2 秒。人民银行和 BLS API 的 robots.txt 全站禁止，所以没接
- 官方原文存全文段落（证据源）；媒体只存标题、时间、链接，不存正文
- 每条 AI 结论标注模型、生成时间、提示词版本；`generation_log` 表从第一天记录每次生成的输入哈希、原始输出、丢弃原因
- 手工补录的报道在 `config/manual_documents.yaml`，只有标题和链接

## 目录

```
config/sources.yaml          信源注册表
config/manual_documents.yaml 手工补录的媒体报道
newsdesk/fetch/              抓取适配器（fed / cn_gov / rss / manual）
newsdesk/resolvers.py        范围解析器与分级规则
newsdesk/events.py           事件生成、媒体挂接、转载判定
newsdesk/interpret.py        解读输入组装与落库
newsdesk/gates.py            三道校验闸门
newsdesk/llm.py              模型调用与降级
newsdesk/site/               静态站模板、样式、前端脚本
newsdesk/publish.py          原子发布到 gh-pages
data/newsdesk.db             SQLite（随 git 备份）
tests/golden/                抓取器页面快照与期望解析结果
```
