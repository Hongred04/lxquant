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
   `lxquant/server.py` 是 **CRLF**，其余文件是 **LF**。用 `open(p,'w')` 整体写回会把整个
   文件的行尾换掉，`git diff` 从 80 行变成 900 行，review 时真改动被淹没。
   稳妥写法：`open(p,'rb').read()` → 替换 → `open(p,'wb').write()`。

6. **推送 GitHub 要先开代理。**
   `git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 push origin main`
   代理没开时 `git push` 会卡住或报 443 连不上，不是仓库的问题。

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
| `backtest.py` | 回测 + `robust_score` 分折稳健分 | 交易排序必须完全确定，见下 |
| `verdict.py` | 策略准入判定（四级结论） | 门槛常量集中在文件顶部 |
| `memory.py` | 选股记忆：记账、回看涨跌、总账 | 有写入保护，改动前先读 §一.4 |
| `auto.py` | 自动调度线程（首扫/尾盘扫/补扫） | `_final_reason()` 是纯函数，好测 |
| `market_state.py` | 大盘状态开关（指数 vs MA20） | 有锁，别去掉 |
| `runlog.py` | 一行式运行日志 | `data/logs/run-YYYY-MM-DD.log` |
| `limitup.py` | 涨停/连板识别（按板块分 10%/20%/30%，ST 5%） | 别在别处写死 9.9% |
| `overnight.py` | 隔夜低吸（首阴套利）：出名单、记开盘价、结算 | 独立账本 `data/overnight/` |
| `emotion.py` | 东财涨停池：官方连板数、板块、炸板次数 | 失败返回空，不许当必需品 |
| `server.py` | HTTP 服务 + 32 个 `/api/*` 路由 | 路由是 if-elif 长链，加接口见 §三 |
| `watchlist.py` / `portfolio.py` | 自选股提醒 / 模拟账户 | |

前端 `web/`：`index.html`（单页，7 个 view）+ `app.js`（**3500+ 行，131 个函数**）+ `style.css`。
`app.js` 内部有 12 个 `/* ==== 分区 ==== */` 注释，改之前先 `grep -n "====" web/app.js` 定位，
不要整文件通读。

`web_m/`（手机版界面）和 `android/`（APK 打包工程）**已于 2026-10-30 删除**：
打包成 APK 在手机上跑太慢，那条线不再维护。现在只有 `web/` 一套界面。
需要找回旧代码：`git checkout 7649dd5 -- android web_m`（提交号见 git log）。

---

## 二·五、隔夜低吸（首阴套利）—— 与主策略完全独立的第二条线

**两套策略的区别，混了就全错：**

| | 主策略（选股页） | 隔夜低吸（隔夜低吸页） |
| --- | --- | --- |
| 决策时点 | 14:45 尾盘 | 前一交易日收盘后 |
| 买入价 | 14:45 分时价 / 收盘价 | **次日开盘价（9:25 集合竞价）** |
| 持有期 | 几天，跌破均价线才走 | **当天收盘必须卖** |
| 账本 | `data/memory/` | `data/overnight/` |

**规则（`overnight.py` 顶部常量，不给设置页开开关）：**
连板 ≥3 的票，出现第一根实体阴线（收盘 ≤ 开盘×0.99）→ 次日开盘买、当日收盘卖。

**为什么必须 9:25 挂单：** 实测（22 个交易日、5548 个低开样本）首 5 分钟 VWAP
比开盘价高 0.45~0.95%（低开越大越高），且首 5 分钟最高价中位比开盘价高 3%。
9:35 之后再买，这笔交易的期望基本被吃掉。

**三条实现约束：**
1. 日期锚点用 `overnight.ref_day()`（最近一个**已收盘**的交易日），不要用 `datetime.now()`——
   周日打开软件要把名单挂到上周五，否则整份名单的日期都是错的。
2. 收盘一字跌停卖不掉 → 状态机里 `deferred + 1` 顺延，最多扛 3 天，**不许假装当天平仓**。
3. 没执行的信号记一笔 `status="missed"`，只用来算执行率，不进收益统计——
   否则"没做的那天"等于凭空消失，看起来会比实际更好。

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
