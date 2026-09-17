# 第 0 步工作底稿：美联储 2026-09-16 加息 25bp

> 手工走一遍流水线，不写代码。产物：[event-card.html](event-card.html)。
> 整理时间 2026-09-17（北京时间晚间）。整理者：人工 + Claude Opus 5 辅助。

## 0. 为什么选这个事件

- 属于第 1–2 版三个范围解析器之一（央行利率调整），走完能直接指导解析器设计
- 有 L1 官方原文 + 上一版文件（7 月声明），能做「变了什么」条文 diff
- 中英文媒体都有大量报道，能试同源检测与各源差异

## 1. 信源（L1 官方 = 证据源，全文可用）

| ID | 文件 | URL | 用到的段落 |
| --- | --- | --- | --- |
| S | FOMC 声明 2026-09-16 | https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm | S0 投票行、S1–S3 三段 |
| P | FOMC 声明 2026-07-29（上一版） | https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm | P0 投票行、P1–P4 |
| I | 执行说明 2026-09-16 | https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a1.htm | I1 IORB、I2 指令、I3 贴现率 |
| J | 执行说明 2026-07-29 | https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a1.htm | J1–J3 |
| T | 经济预测（SEP）表 1 / 图 2 | https://www.federalreserve.gov/monetarypolicy/fomcprojtabl20260916.htm | T1 表 1、T2 点阵分布 |
| H | FOMC 声明 2023-07-26（上次加息） | https://www.federalreserve.gov/newsevents/pressreleases/monetary20230726a.htm | H1 |
| B | BLS CPI 2026 年 8 月（9-11 发布） | https://www.bls.gov/news.release/cpi.nr0.htm | B1–B4 |
| F | FRED：GDP（2026Q2）、POPTHM（2026-07） | https://fred.stlouisfed.org/series/GDP 、/POPTHM | F1、F2 |

关键原文段落（逐字，供数字回填核对）：

- **S0** `The Federal Open Market Committee approved the following statement for release by a 12 – 0 vote:`
- **S1** `The Committee decided to raise the target range for the federal funds rate by 1/4 percentage point to 3-3/4 to 4 percent, in support of the Federal Reserve's dual mandate. The Committee is continuing its policy of maintaining ample reserves in the banking system.`
- **S2** `Economic activity is expanding at a solid pace. While uncertainty remains elevated owing, in part, to geopolitical developments, domestic spending has been resilient. Productivity growth is strong, and capital investment is robust. Job gains have kept pace with the workforce, and the unemployment rate has changed little.`
- **S3** `Inflation remains elevated. Today's policy action will support a timelier return to the Committee's 2 percent goal. The Committee will deliver price stability.`
- **P0** `... approved the following statement for release by a 9 – 3 vote:`
- **P1** `The Committee decided to maintain the target range for the federal funds rate at 3-1/2 to 3-3/4 percent, ...`
- **P2** `Economic activity is expanding at a solid pace despite elevated uncertainty that owes, in part, to the conflict in the Middle East. Productivity growth and capital investment are strong. Job gains have kept pace with the workforce, and the unemployment rate has changed little.`
- **P3** `Inflation remains elevated relative to the Committee's 2 percent goal, in part reflecting supply shocks that have driven price increases in certain sectors, including energy. The Committee will deliver price stability.`
- **P4** `Voting against the monetary policy action were Beth M. Hammack, Neel Kashkari, and Lorie K. Logan, who preferred to raise the target range for the federal funds rate by 1/4 percentage point at this meeting.`
- **I1** `... voted unanimously to raise the interest rate paid on reserve balances to 3.90 percent, effective September 17, 2026.`
- **I2** `Conduct standing overnight repurchase agreement operations at a rate of 4.0 percent.` / `... reverse repurchase agreement operations at an offering rate of 3.75 percent ...`
- **I3** `... approve a 1/4 percentage point increase in the primary credit rate to 4.0 percent ... submitted by the Board of Directors of the Federal Reserve Banks of Cleveland, Richmond, Atlanta, Chicago, Minneapolis, Kansas City, and Dallas.`
- **J1** `... maintain the interest rate paid on reserve balances at 3.65 percent ...`；**J2** SRF `3.75 percent`、ON RRP `3.5 percent`；**J3** primary credit `3.75 percent`
- **T1** 表 1 中值（9 月 / 6 月）：联邦基金利率 2026 `4.1`/`3.8`、2027 `4.1`/`3.6`、2028 `3.9`/`3.4`、长期 `3.2`/`3.1`；PCE 2026 `3.7`/`3.6`；核心 PCE 2026 `3.4`/`3.3`；失业率 2026 `4.1`/`4.3`；GDP 2026 `2.3`/`2.2`；PCE 2029 `2.0`
- **T2** 图 2，2026 年末：`4.375` 4 人、`4.125` 12 人、`3.875` 2 人
- **H1** `... decided to raise the target range for the federal funds rate to 5-1/4 to 5-1/2 percent.`
- **B1** `Over the last 12 months, the all items index increased 3.4 percent before seasonal adjustment.`
- **B2** `The all items less food and energy index rose 2.4 percent over the year ...`
- **B3** `The energy index increased 16.3 percent for the 12 months ending August.`
- **F1** GDP 2026Q2 `32,486.066` 十亿美元（SAAR）；**F2** 人口 2026-07 `342,909` 千人

## 2. 媒体报道（二、三类：只记标题 / 时间 / URL，不存正文）

| 媒体 | 语 | 标题 | 是否独立 | 核验方式 |
| --- | --- | --- | --- | --- |
| CNBC | 英 | Fed rate decision September 2026: Rates rise to 3.75%-4% | 独立 | 仅标题（页面 403） |
| CNN Business | 英 | What Kevin Warsh said about the Fed's first rate hike since 2023 | 独立 | 仅标题（451） |
| Fox Business | 英 | Federal Reserve hikes interest rates for first time since 2023 | 独立 | 仅标题 |
| Yahoo Finance（Jennifer Schonberger） | 英 | Fed raises interest rates by a quarter point in unanimous decision, marking first hike in 3 years | 独立 | 已读 |
| NBC News | 英 | Fed raises interest rates for first time since 2023, defying Trump as inflation mounts | 独立 | 仅标题 |
| CBS News | 英 | The Federal Reserve just raised interest rates for the first time since 2023. Here's how mortgage rates may respond. | 独立 | 仅标题 |
| NerdWallet / Kiplinger / Advisor Perspectives / investingLive | 英 | （略） | 独立 | 仅标题 |
| KVIA | 英 | Federal Reserve raises interest rates for the 1st time since 2023 | **疑似转载**（地方台常用 CNN 通稿） | 未核 |
| 澎湃新闻 | 中 | 美联储全票通过加息25个基点，点阵图预测今年或再加息一次（附声明全文） | 独立 | 经 21 经济网转载页读到，署名「澎湃新闻」 |
| 21 经济网 | 中 | 同上 | **转载**（署名澎湃） | 署名规则 |
| 21 经济网 | 中 | 时隔三年多 美联储宣布加息25个基点 | 待定 | 未读 |
| 证券时报 | 中 | 重磅！美联储，加息25个基点！ | 独立 | 经新浪转载页读到 |
| 新浪财经 | 中 | 同上 | **转载**（署名证券时报） | 署名规则 |
| VOA 中文 | 中 | 美联储三年来首次加息，上调25个基点 | 独立 | 已读 |
| 禁闻网 ×2 | 中 | 与 VOA 标题逐字相同等 | **转载** | 标题完全一致 |
| 凤凰网 | 中 | 美联储加息25个基点 年内或再加息一次 | 待定 | 未读 |

**独立报道数（去转载）≈ 14，转载 ≥ 4。** 发现 18 小时内，头部中英文财经媒体全覆盖。

## 3. 可信度

L1 官方源（美联储声明 + 执行说明）直接确认 → **已确认**。无「知情人士」链条，无否认。

## 4. 影响范围四维度

| 维度 | 取值 | 依据 | log10 |
| --- | --- | --- | --- |
| 人口 | 3.43 亿 | F2 美国人口（直接受影响范围只算美国，保守；外溢到全球美元融资不计） | 8.54 |
| 持续时间 | 12 个月（**估计**） | 点阵中值路径：2026 末 4.1 → 2027 末 4.1 → 2028 末 3.9（T1），即这一利率水平约维持到 2027 年底；取保守值 12 个月 | 1.08 |
| 行业数 | 11 | 利率是全行业融资成本，按 GICS 11 个一级行业全计 | 1.04 |
| 经济规模 | 3.25 万亿美元 ×10 = 32.5 万亿美元 | F1 美国名义 GDP（年化） | 13.51 |
| **score** |  |  | **24.17** |

## 5. 覆盖度落差

- GDELT DOC 2.0 本次 **三次请求均被限流**（"Please limit requests to one every 5 seconds"），未拿到数
- 退化为人工计数：独立报道 ≈ 14，头部媒体全覆盖 → 覆盖度「高」
- 范围分高 + 覆盖度高 → **不低估**，不打低估标

## 6. 等级

阈值尚未用历史事件标定，这里按「稀有程度」列人工判断：

- 方向反转（2023-07 以来首次加息）、12–0 全票、点阵图同步上移 → 一年数次到十余次这个量级 → **A**
- 如果是普通「维持不变」的议息会议 → 应为 B

⚠ **发现问题：score 公式区分不了「维持」和「加息」**。四个维度对任何一次 FOMC 会议都一样（同样的人口、行业、GDP），加息和按兵不动得分相同。见第 8 节。

## 7. 解读（四段，逐条标证据）

完整版见卡片。每条 claim 的引用与数字回填结果：

| # | 结论 | 证据 | 引用 | 数字回填 |
| --- | --- | --- | --- | --- |
| 1 | 12–0 上调 1/4 个百分点至 3-3/4 到 4 厘 | E1 | S0 S1 | ✅（需分数格式归一化） |
| 2 | 上次 9–3，Hammack/Kashkari/Logan 主张加息 | E1 | P0 P4 | ✅ |
| 3 | 「中东冲突」→「地缘政治发展」；新增「国内支出有韧性」 | E1 | P2 S2 | ✅ 文本 diff |
| 4 | 通胀段删除「部分反映能源等供给冲击」，新增「更及时地回到 2% 目标」 | E1 | P3 S3 | ✅ 文本 diff |
| 5 | IORB 3.65→3.90；隔夜回购 3.75→4.0；逆回购 3.5→3.75；贴现率 3.75→4.0 | E1 | I1 I2 I3 J1 J2 J3 | ✅ |
| 6 | 点阵 2026 末中值 3.8→4.1，2027 3.6→4.1 | E1 | T1 | ✅ |
| 7 | 18 人中 16 人预期年内至少再加一次 | E2：12 + 4 = 16 | T2 | ✅ |
| 8 | 距上次加息 1148 天 ≈ 37.7 个月 | E2：2026-09-16 − 2023-07-26 | S1 H1 | ✅ |
| 9 | 利率上限比 2023 峰值低 150bp | E2：5.50 − 4.00 | S1 H1 | ✅ |
| 10 | 上限减 8 月 CPI 同比 = +0.6pp；减核心 CPI = +1.6pp | E2：4.00 − 3.4；4.00 − 2.4 | S1 B1 B2 | ✅ |
| 11 | 能源 CPI 同比 16.3%，是总体 3.4% 的约 4.8 倍 | E1 + E2：16.3 / 3.4 | B1 B3 | ✅ |
| 12 | 2026 PCE 预测 3.7%，高出目标 1.7pp；中值到 2029 才回到 2.0 | E1 + E2 | T1 S3 | ✅ |
| ✗ | 「10 年期美债一度超 5%、油价超 100 美元」 | — | 只有 VOA 单一媒体，无 L1 出处 | **丢弃**，不上卡 |
| ✗ | 「美股盘中道指 +0.01%……」 | — | 证券时报决议后 14 分钟的盘中快照，非收盘，无 L1 | **丢弃** |

## 8. 走完一遍的发现（给第 1 版的输入）

1. **最有价值的是 diff。** 两份声明逐句对比，看出通胀段**删掉了「供给冲击 / 能源」归因**——这是本次措辞最有信息量的改动，而且完全客观可溯源。读到的中文报道提到了新增的「更及时回到 2%」一句，没提删掉的那半句。印证了文档「变了什么是最硬的功能」。
2. **score 公式对同一 event_type 几乎是常数。** 每次 FOMC 的人口 / 行业 / GDP 都一样。需要在解析器里加「变化量」因子（如：利率变动 bp、是否方向反转、投票分歧变化），否则分级只能靠 event_type 区分，同类事件全落同一级。
3. **持续时间可以不是纯估计。** 央行利率事件可以用点阵中值路径推出「这一利率水平预计维持多久」，算 E2，比默认值好。
4. **数字回填需要格式归一化。** 原文是 `3-3/4 to 4 percent`、`1/4 percentage point`，媒体和解读里写 `3.75%-4%`、`25 个基点`。逐字匹配会误杀，要先做分数 / bp / 百分号归一化再比。
5. **LLM 摘要会编造。** 本次调研中，一个搜索工具的中文摘要声称声明里有「当前政策仍显不足」——原文没有；另一个网页转述把 2026 年点阵分布说成了 2027 年。**校验必须对原文逐字做，不能对任何中间摘要做。**第三道闸门不能省。
6. **署名规则很好用。** 21 经济网（署名澎湃）、新浪（署名证券时报）两条转载，只看署名就能抓到；禁闻网靠标题完全一致抓到。SimHash 可以放第 2 版。
7. **抓取可达性比预想差：**
   - GDELT DOC API：连续三次限流 → 需要全局节流（≥ 6s/次）+ 指数退避 + 结果缓存；覆盖度是第 2 版的主信号，得先解决
   - BLS 页面拒绝 curl、FRED 的 fredgraph.csv 无返回 → 走 BLS API v2 与 FRED 官方 API（需要免费 key）
   - CNBC 403、CNN 451 → 只能走 RSS 拿标题摘要，本来也只需要这些
   - 美联储官网 curl 直接可用，段落结构干净，L1 解析很省事
8. **单源 + 无 L1 出处的数字一律丢弃**，卡片短了两条，但没有损失——那两条本来就不该出现在「有据可依」的站上。
