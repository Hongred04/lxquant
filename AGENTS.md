# AGENTS.md · 给 AI / 新接手的人

自用的 A 股选股工具。**纯 Python 标准库 + 原生 JS，没有框架、没有 npm 依赖**。
读这一页能省掉半天摸索；下面的「硬规则」每一条都是踩过坑才写下来的。

跑起来：`./runtime/python.exe run.py`（默认 8777，`启动选股.bat` 同效）。
改完自检：`./runtime/python.exe tools/check.py` ← **改任何东西之后都先跑这个**。

---

## 一、硬规则（违反会白干或毁数据）

1. **改了 `web/app.js` / `web/style.css` 必须构建。**
   服务端优先返回 `.min` 产物（`server.py::_static`），只改源文件刷新页面看不到任何变化，
   会误判成"改了没用"。构建：`node tools/build.js`（或 `tools/check.py --fix`）。
   调试时想临时看源码版：访问 `http://127.0.0.1:8777/app.js?raw=1`。
   ⚠️ 仓库里没有 node 依赖，构建脚本 `tools/minify.js` 是自己写的，只用 node 内置模块。

2. **不许加第三方依赖。** 整个项目跑在 `runtime/` 里那个裸 Python 上。
   需要的能力用标准库实现（HTTP 用 `urllib`，不要 requests；数据用 `pandas` 除外——
   pandas/numpy 是 runtime 里唯一带的第三方库，可以用）。

3. **日线缓存有两条，口径不同，绝对不能混：**

   | 缓存 | 口径 | 谁在用 |
   | --- | --- | --- |
   | `data/cache/d_<code>.pkl` | **不复权** | 实时选股、盘中判定 |
   | `data/cache/dl_<code>.pkl` | **前复权**（长历史） | 回测、选股记忆、模拟账户 |

   混用会让涨跌幅在除权日凭空跳 10%，而且不报错。

4. **`data/memory/*.json` 是账本，不许程序化改写。**
   盘中定型的名单被 `save_result()` 保护着（盘后重扫连 `force=True` 也覆盖不了）。
   真要纠错只能手工编辑文件 —— 这是刻意的，防止顺手点一下就把账冲了。
   测试写记忆文件时用 `1999-xx-xx` 这种假日期，跑完删掉。

5. **改源码用二进制模式读写，别顺手改行尾。**
   这个仓库里两种行尾并存：`web/style.css`、`web/index.html`、`lxquant/server.py`、
   `screener.py`、`memory.py` 是 **CRLF**；`web/app.js`、`equity.py`、`portfolio.py`、
   `tests/` 全部、所有 `.md` 是 **LF**。新文件一律用 **LF**。
   用 `open(p,'w')` 整体写回会把整个文件的行尾换掉，`git diff` 从 80 行变成 900 行，
   review 时真改动被淹没。稳妥写法：`open(p,'rb').read()` → 替换 → `open(p,'wb').write()`。
   改完可以自查：
   ```
   ./runtime/python.exe -c "b=open('文件','rb').read();print(b.count(b'\r\n'), b.count(b'\n')-b.count(b'\r\n'))"
   ```
   两个数都不为 0 = 混行尾，必须修回纯的。

6. **推送 GitHub 要先开代理。**
   `git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 push origin main`
   代理没开时 `git push` 会卡住或报 443 连不上，不是仓库的问题。

7. **避雷打分（`avoid.py`）只标雷，不许悄悄删票。**
   它的输出是给名单贴一个「避」标记，`screener` 该出几只还出几只。
   一旦接进筛选流程直接过滤，界面上写的「命中 50 只」就和实际不符了 ——
   用户会以为那是选股条件，而它其实只是个参考。
   同理，它在 `/api/last` 里是**贴在响应上**的，不写回 `_last_screen`。

---

## 二、文件地图

后端 `lxquant/`（每个文件只干一件事）：

| 文件 | 管什么 | 注意 |
| --- | --- | --- |
| `datasource.py` | 所有外部数据源（腾讯/新浪/东财） | 有腾讯三入口轮换，见「已知的坑」 |
| `store.py` | 缓存读写、周期合成、选股池维护 | `get_kline` 三级降级：腾讯→合成→旧缓存 |
| `indicators.py` | 指标与筹码分布（MA/量比/获利盘） | |
| `strategies/` | 策略与关卡（`oversold_bounce` 是唯一在用的） | 新策略继承 `base.py` 的 Strategy |
| `screener.py` | 全市场筛选主流程 | `basis` 口径判定在 `basis_label()` |
| `backtest.py` | 回测 + `robust_score` 分折稳健分 | **只服务详情抽屉的「历史同类信号」**，页面上没有独立入口了；交易排序必须完全确定，见下 |
| `equity.py` | 收益曲线：`portfolio.run()` 的结果落盘 `data/equity.json` | 改撮合口径要同步 `CACHE_VERSION`，否则旧曲线冒充新口径 |
| `avoid.py` | 避雷打分：全市场排「谁最不该买」，落在 `data/avoid.json` | **只标雷不改名单**；池子按最新交易日卡死，见下 |
| `verdict.py` | 策略准入判定（四级结论） | 门槛常量集中在文件顶部 |
| `memory.py` | 选股记忆：记账、回看涨跌、总账 | 有写入保护，改动前先读 §一.4 |
| `auto.py` | 自动调度线程（首扫/尾盘扫/补扫） | `_final_reason()` 是纯函数，好测 |
| `market_state.py` | 大盘状态开关（指数 vs MA20） | 有锁，别去掉 |
| `runlog.py` | 一行式运行日志 | `data/logs/run-YYYY-MM-DD.log` |
| `limitup.py` | 涨停/连板识别（按板块分 10%/20%/30%，ST 5%） | 别在别处写死 9.9% |
| `emotion.py` | 东财涨停池：官方连板数、板块、炸板次数 | 失败返回空，不许当必需品 |
| `finance.py` | **唯一在用的策略**：大金融 2 只、弱市买、持有 40 天 | 参数写死；池子见 `POOL`；`CACHE_VERSION` 跟着字段走 |
| `fin_pos.py` | 持仓跟踪：第几天 / 还剩几天 / 浮盈亏 | 到期日按**工作日**推算，不含节假日表 |
| `server.py` | HTTP 服务 + `/api/fin*` 六个接口（其余是历史遗留） | 路由是 if-elif 长链，加接口见 §三 |
| `watchlist.py` / `portfolio.py` | 自选股提醒 / 资金撮合（收益曲线的计算内核） | |

前端 `web/`：`index.html`（154 行，两栏 6 块）+ `app.js`（503 行，含 3 个手写 canvas 图表）
+ `style.css`（368 行，深浅双主题）。**零依赖**，没有构建期框架，`tools/build.js` 只做压缩。

**2026-11-04 起这个软件只做一个策略：大金融中长线。** 旧的选股 / 盯盘 / 记忆 /
收益曲线 / 避雷全部从界面上移除了（后端模块还在，但没有任何页面调用；
`server.py` 里那些 `/api/*` 路由也还留着，删它们有风险、留着无害）。

改界面前先记住五件事：
1. **1440×900 必须一屏**。验收看到的是 `document.documentElement.scrollHeight <= 900`
   （左栏和右栏谁高谁决定页高，所以两边都得盯）。更矮的窗口允许滚动，
   但顶部必须可见 —— 见第 3 条。加内容前先想清楚要不要为此牺牲一屏；
   2026-11-04 加「规则」卡时就是因为左栏比右栏高出 4px，整页从一屏变成要滚一点。
2. **不允许用 `justify-content:center` 做垂直居中**（2026-11-04 踩过）。
   内容比视口高时，flex 居中会把溢出量对半分到上下两端 —— 顶部那半截被推到
   滚动区之外，滚动条拉到 0 也依然看不见（实测默认窗口下大数字上半截消失、
   footer 整个不见，用户第一眼就是「UI 被挡住了」）。
   正确写法是 `justify-content:flex-start; justify-content:safe center;`：
   有富余就居中，装不下自动退回顶部对齐，由浏览器判断，不要用媒体查询猜阈值
   —— 窄屏 + 矮屏组合下猜错一次就是整块内容被切掉。
3. **矮屏靠媒体查询压缩尺寸，不删内容**。`max-height:820px` / `640px` 两档，
   内容从约 720px 收到 590 / 470px。验收标准不是「零滚动」，是
   **在 1440×900 / 1366×650 / 1080×490 / 390×844 / 375×667 / 320×480 六档下，
   `#hero` 的 `getBoundingClientRect().top` 都 ≥ 0**。改完 CSS 用无头 Edge
   逐档截图量一遍（CDP `Emulation.setDeviceMetricsOverride`），别只在自己那块屏上看 ——
   这次就是只测了 900 和 844 两档，漏掉了默认窗口。
4. **没有导航**。只有一个页面，所以不存在 view 切换、TITLE/LEVEL 表、
   `switchView()` 这些东西，别再往回调。
5. **参数不给用户调**。`GATE / HOLD_DAYS / QUOTA` 写死在 `finance.py` 顶部。
6. **重数据必须离线算好再进界面**。`/api/fin/history`（10 年曲线）和
   `/api/fin/trades`（39 次机会）都是脚本产出后落盘的，接口只读文件 ——
   算一次要读 1 GB 的 `data/long_all.pkl`，放进请求路径必然把页面拖死。
   脚本：`factor_lab/71_dump_history.py`、`factor_lab/70_dump_trades.py`。
7. **指数要读 `data/idx_long.pkl`，不要用 `datasource.index_daily`。**
   后者走新浪，`datalen` 上限 1023 根 = 4.2 年。个股有 10.8 年、指数只有 4.2 年，
   拼在一起的结果是 2022 年之前 `vs20` 全是 NaN → 那段被当成空仓，
   所谓「10 年回测」实际只有 4 年（实测只剩 3 次调仓，年化被报到 6.5%，
   真实全样本是 3.8%）。长表用 `factor_lab/72_fetch_index.py` 抓，东财 8756 根。
   给的旋钮越多，越容易用调出来的参数骗自己 —— 这是这个项目最重要的教训。

`web_m/`（手机版界面）和 `android/`（APK 打包工程）**已于 2026-10-30 删除**：
打包成 APK 在手机上跑太慢，那条线不再维护。现在只有 `web/` 一套界面。
需要找回旧代码：`git checkout 7649dd5 -- android web_m`（提交号见 git log）。

---

## 三、要加东西放哪

- **新 API**：`server.py` 的路由链里加 `if p == "/api/xxx":`，返回 `self._json({...})`。
  前端统一用 `api('/api/xxx')` 调用。
- **新页面**：`index.html` 加 `<section id="view-xxx" class="view">`，
  `app.js` 里加 `renderXxx()` 并在 `switchView` 分发；导航按钮在 `index.html` 顶部。
- **新策略**：`strategies/` 下建模块，继承 `base.py`，实现 `facts()` 与 `gates`；
  在 `strategies/__init__.py` 注册。参数默认值别用 `p.get(k, d) or d`（0 会被吃掉，
  用 `_pnum()`）。
- **新指标**：`indicators.py`，纯函数、输入 DataFrame、输出 float/Series。
- **新门槛**：`verdict.py` 顶部常量 + `_checks()` 里加一条。

---

## 四、已知的坑（都真实发生过）

- **腾讯 `fqkline` 会整片 501**，那不是接口下线，是单入口限流，第二天自己好。
  三个入口数据一致、可用性独立波动，现在按「上次成功的优先」轮换：
  `ifzq.gtimg.cn` / `web.ifzq.gtimg.cn` / `proxy.finance.qq.com/ifzqgtimg`。
- **腾讯的 `qfq` 是等差口径**（逐次减每股分红），长历史高分红老股早期价格会被减成负数
  （实测茅台月线 300 根里 178 根为负）。检测到非正价格会自动改走
  「不复权长历史 + 新浪比例因子」，不要把这个分支删掉。
- **不复权端点**是 `/appstock/app/kline/kline?param=sym,kind,,,N`，
  末位不能留空（留空直接 501）；复权端点是 `fqkline/get?...qfq`。两者不能混用。
- **回测的交易排序必须完全确定**：`robust_score` 的排序键是
  `(buy_date, code, signal_date)`。只按 `buy_date` 排会让同一天多只票的顺序
  取决于线程完成顺序，同一批交易三次跑出三个分数。
- **参数 0 是合法值**：`turn_min=0` 表示不看收盘位置。老写法 `p.get(k, 0.5) or 0.5`
  会把 0 换成 0.5，面板上拧到 0 根本不生效且看不出来。用 `_pnum()`。
- **涨停不能一刀切 9.9%**：主板 10%、创业板/科创板 20%、北交所 30%、ST 5%。
  用统一阈值会把 20cm 的板全漏掉，连板数直接算错。走 `limitup.py`。
- **`<details>` 放进 flex 列容器会被压扁**（展开后高度 2px，像点了没反应），
  要显式 `flex:0 0 auto`。
- **Windows 上端口可能双绑**：重启服务前先确认旧进程真的退了，
  否则新代码没生效而你以为生效了（`netstat -ano | grep :8777` 看 PID）。
- **日线缓存是按需更新的，不是全市场同步**。实测 5234 只里只有 2300 只
  更新到最新交易日，其余停在十天前。任何要"全市场截面"的计算（避雷打分、
  因子排序）都必须先按最新交易日过滤池子，拿陈数据算出来的分位是假的。
  `avoid.py` 的 `_read_pool()` 就是干这个的，别绕过它。
- **盘中拿到的「今天」是实时价，不是收盘价**（2026-11-04 踩过）。
  行情接口在 9:30 之后就会返回一根日期是今天的日线，值是现价。拿它算 vs20，
  信号会随盘中价格漂移：上午显示「可以买」，下午变「再等等」，而用户看到的
  都是「今天的信号」—— 同一句话两小时后自我否定。
  这套规则的决策基准是收盘价，所以 `finance._drop_unclosed()` 在 15:10 之前
  一律丢掉今天那根。**离线脚本（70/71）也必须调用它**，否则机会表和界面
  会停在两个不同的日期。
- **上证指数不能用 `datasource.index_daily`**：它走新浪，上限 1023 根 = 4.2 年。
  个股 10.8 年、指数 4.2 年，拼起来就是「10 年回测实际只跑了 4 年」，
  年化被报成 6.5%（真实 3.8%）。用 `finance._index_close()`（长表打底 +
  新浪补最新），或 `data/idx_long.pkl`（东财 8756 根）。
- **`vs20` 不是「当日涨跌」**。它是「相对 20 日均线的偏离」，数值接近、
  语义完全不同。顶栏的指数点位旁边必须放当日涨跌（`market.chg`），
  放 vs20 会被读成「今天跌了 2.89%」。历史机会表的列名同理，写「偏离」不写「大盘」。
- **「还差多少到进场线」= `vs20 + gate` 截 0**。写成 `gate - |vs20|` 在均线上方
  会把 3.2 算成 0.8；写成 `-vs20 - gate` 在已跌破时算出 0.89 这种正数。
  `finance._gap()` 有单测钉着，别在界面上重算。
- **不要在 `build()` 里复用 `chg` 这个变量名**：个股当日涨跌幅是个 dict，
  指数当日涨跌是 float，同名会直接 AttributeError（已经踩过一次）。
- **`_factors()` 要求 60 根**，不是 40 根：`ma60 = c.tail(60).mean()` 在只有
  40 行时会静默算成 40 日均线，把「上市两个月的新股」判成「跌破 60 日线」。
- **`d_` 是不复权**：除权日会凭空造出「暴跌」。避雷打分用的是 d_ 口径
  （dl_ 只覆盖 10.6%），所以必须把最近 20 个交易日内有过 |涨跌|>21% 的票剔掉 ——
  否则那几只的 std20 会被除权顶到天上，白白标红。

---

## 五、验证

```bash
./runtime/python.exe tools/check.py        # 语法 + 单测 + 前端语法 + 构建新鲜度
./runtime/python.exe -m tests.run verdict  # 只跑某组测试
```

测试只用标准库、不联网、不碰真实数据（写记忆用 1999 年假日期）。
写新测试：`tests/test_*.py` 里定义 `test_*` 函数，直接 assert，
失败信息写清「期望 vs 实际」。

界面改动要眼见为实 —— 起服务后用浏览器看，别只相信代码。
最省事的自检顺序：`check.py` → 起服务 → 打开对应页面 → 看控制台有没有报错。
