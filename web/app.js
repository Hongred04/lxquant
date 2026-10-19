/* =========================================================
   lxquant 前端 —— 无框架原生 JS，Canvas 手绘图表
   ========================================================= */
'use strict';

/* ------------------------------------------------ 工具 */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const fmt = (v, d = 2) => (v === null || v === undefined || Number.isNaN(+v)) ? '—' : (+v).toFixed(d);
const pct = (v, d = 2) => (v === null || v === undefined || Number.isNaN(+v)) ? '—' : (+v).toFixed(d) + '%';
const cls = v => (+v > 0 ? 'up' : +v < 0 ? 'down' : '');
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function toast(msg, isErr) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast show' + (isErr ? ' err' : '');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.className = 'toast'; }, 2600);
}

async function api(url, opt) {
  const r = await fetch(url, opt);
  const j = await r.json().catch(() => ({ ok: false, error: 'HTTP ' + r.status }));
  if (!j.ok) throw new Error(j.error || '请求失败');
  return j;
}

/* ------------------------------------------------ 图标 */
const ICONS = {
  target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.5"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  chart: '<path d="M3 3v18h18"/><path d="M7 15l4-5 3 3 5-7"/>',
  sliders: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h10M18 18h2"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="16" cy="18" r="2"/>',
  // 书页图标太细，16px 下看着像一个空方框 —— 换成"说明书"样式的文档图标，一眼能认出
  book: '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4"/><path d="M9 12h7M9 16h5"/>',
  memory: '<path d="M12 3a4 4 0 0 0-4 4v1a3.5 3.5 0 0 0-2 6.3A3.5 3.5 0 0 0 9 21h3a3 3 0 0 0 3-3V7a4 4 0 0 0-3-4z"/><path d="M12 3v18"/><path d="M15 8h3a2 2 0 0 1 2 2v1"/>',
  wallet: '<rect x="3" y="6" width="18" height="13" rx="2.5"/><path d="M3 10h18M16 14.5h2"/><path d="M6.5 6l9-3 1.5 3"/>',
  play: '<path d="M7 4l12 8-12 8z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
  download: '<path d="M12 3v12M7 11l5 5 5-5M4 21h16"/>',
  save: '<path d="M5 3h11l3 3v15H5z"/><path d="M8 3v6h7V3M8 21v-7h8v7"/>',
  reset: '<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  moon: '<path d="M21 13.2A9 9 0 1 1 10.8 3a7 7 0 0 0 10.2 10.2z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.5 1.5M17.6 17.6l1.5 1.5M19.1 4.9l-1.5 1.5M6.4 17.6l-1.5 1.5"/>',
  back: '<path d="M15 5l-7 7 7 7"/>',
  chevron: '<path d="M9 5l7 7-7 7"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
};
function paintIcons(root = document) {
  $$('[data-ic]', root).forEach(el => {
    const n = el.dataset.ic;
    if (ICONS[n]) el.innerHTML = `<svg viewBox="0 0 24 24" fill="${n === 'play' || n === 'stop' ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${ICONS[n]}</svg>`;
  });
}

/* ------------------------------------------------ 主题（亮 / 暗） */
const THEME_KEY = 'lxquant-theme';
let _PAL = null;

function themeNow() {
  return document.documentElement.getAttribute('data-theme') || 'dark';
}
/** 读取 CSS 变量作为画布调色板（主题切换时缓存失效） */
function T() {
  if (_PAL) return _PAL;
  const cs = getComputedStyle(document.documentElement);
  const v = n => cs.getPropertyValue(n).trim();
  _PAL = {
    txt: v('--txt'), txt2: v('--txt-2'), txt3: v('--txt-3'),
    line: v('--line'), line2: v('--line-2'),
    up: v('--up'), down: v('--down'),
    ok: v('--ok'), okSoft: v('--ok-soft'),
    gold: v('--gold'), accent: v('--accent'), accentSoft: v('--accent-soft'),
    chartBg: v('--chart-bg'), panel: v('--panel'),
    dark: themeNow() === 'dark',
  };
  return _PAL;
}
/** 把颜色按透明度转换成 rgba（用于画布渐变） */
function alpha(hex, a) {
  let h = (hex || '').trim().replace('#', '');
  if (h.length === 3) h = h.split('').map(c => c + c).join('');
  if (h.length !== 6) return hex;
  const n = parseInt(h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

function applyTheme(t, repaint = true) {
  document.documentElement.setAttribute('data-theme', t);
  try { localStorage.setItem(THEME_KEY, t); } catch (e) { }
  _PAL = null;
  const btn = document.getElementById('theme-btn');
  if (btn) {
    // 暗色时显示太阳（点击转亮），亮色时显示月亮
    btn.dataset.ic = t === 'dark' ? 'sun' : 'moon';
    btn.title = t === 'dark' ? '当前：暗色 · 点击切换亮色' : '当前：亮色 · 点击切换暗色';
    paintIcons(btn);
  }
  if (repaint) repaintCharts();
}

/** 主题切换后重绘所有画布（canvas 颜色不会跟随 CSS 变量自动更新） */
function repaintCharts() {
  if (S.detail && $('#drawer').classList.contains('show')) {
    const tab = document.querySelector('#dw-body .tab.active');
    drawChip($('#chip-cv'), S.detail);
    drawKline($('#k-cv'), S.detail, tab ? tab.dataset.tab : 'day');
  }
  paintBtCharts();
  paintPfCharts();
  try { paintMemChart(); } catch (_) { }
}

/** 图表还没数据时，别留一块黑 —— 画一句提示（否则二级页看着像"没数据"） */
function drawHint(cv, title, sub) {
  if (!cv || !cv.clientWidth) return;
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = 220;
  cv.width = W * dpr; cv.height = H * dpr; cv.style.height = H + 'px';
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  g.textAlign = 'center';
  g.fillStyle = T().txt2; g.font = '13px sans-serif';
  g.fillText(title, W / 2, H / 2 - 6);
  g.fillStyle = T().txt3; g.font = '12px sans-serif';
  g.fillText(sub, W / 2, H / 2 + 16);
}

function paintBtCharts() {
  const cv = $('#eq-chart'); if (!cv) return;
  if (S.bt && S.bt.curve && S.bt.curve.length) drawEquity(cv, S.bt.curve);
  else drawHint(cv, '还没检验过', '点上面的「开始检验」，用历史数据跑一遍');
}

function paintPfCharts() {
  const cv = $('#pf-chart'); if (!cv) return;
  if (S.pf && S.pf.curve && S.pf.curve.length) drawPtf(cv, S.pf.curve);
  else drawHint(cv, '还没模拟过', '点上面的「模拟一遍」，看看钱一年能变成多少');
}

function initTheme() {
  let t = null;
  const q = new URLSearchParams(location.search).get('theme');
  if (q === 'light' || q === 'dark') t = q;
  if (!t) { try { t = localStorage.getItem(THEME_KEY); } catch (e) { } }
  if (!t) t = 'dark';
  applyTheme(t, false);
}

/* ------------------------------------------------ 全局状态 */
const S = {
  cfg: null,
  view: 'screen',
  mode: 'balanced',
  items: [],
  watch: [],
  sort: { key: 'score', dir: -1 },
  filter: '',
  scanItems: [],
  bt: null,
  btResult: null,
  pf: null,
  detail: null,
  busy: {},
  /* 「值得盯着」弹窗（S.watchModalOpen）和它的筛选（S.watchFilter：all / near） */
  watchModalOpen: false,
  watchFilter: 'all',
  modalTab: 'gates',
  /* 自选股（盯盘页那一块）和它上面已经弹出来的提醒 */
  watchList: [],
  watchHits: {},
  watchAt: '',
  alerts: [],
};

/* ------------------------------------------------ 视图切换 */
const TITLES = { screen: '选股', watch: '盯盘 / 自选', memory: '记忆', backtest: '策略检验', portfolio: '模拟账户', method: '使用说明', settings: '参数设置' };
/* 二级页层数：0 = 主页面（侧栏常驻、整块内容一起滚）；
   1 = 从主页面钻进去的工具页（策略检验 / 模拟账户 / 使用说明 / 参数设置），
       顶部只留一条面包屑 + 吸顶的工具条，别让人迷失在长表格里 */
const LEVEL = { screen: 0, watch: 0, memory: 1, backtest: 1, portfolio: 1, method: 1, settings: 1 };
const REHOME = Object.keys(LEVEL).filter(v => LEVEL[v] === 0);   // 操作台：用 app-main 把二级页的头部还回去
const HINTS = {
  screen: '软件自己会选，你回来直接看名单就行',
  watch: '自选股在这里盯着，买点卖点会自己弹出来；下面这份是全市场谁有资金在托价',
  memory: '每天选完自动记一笔。隔几天回来看：那天选的票，后来涨了还是跌了',
  backtest: '拿过去的数据把买卖规则跑一遍，看这套打法历史上是什么成绩',
  portfolio: '像真实账户一样算：钱只有一份，买满了就买不进，还要扣手续费和滑点',
  method: '五个条件、怎么买卖、数据从哪来',
  settings: '所有门槛都能改，保存后下一次自动选股就按新的来',
};

/* 页面头 = 顶栏（标题 / 面包屑 / 本页工具条）这一整块 .hd。每个页面在自己的 .view 里都留了个空的
   <header class="topbar"> 占着"家"的位置；这里把真正的 #topbar 放进当前页面的那个坑里，
   别的页面留下空占位。切页 = 把一块 DOM 换个坑，不复制元素，按 id 取元素的代码一行都不用改。 */

/** 把真正的顶栏搬进这一页预留的空位，顺手把标题 / 提示语 / 面包屑更新成这一页的 */
function mountTopbar(v) {
  const bar = $('#topbar'), sec = document.getElementById('view-' + v);
  const slot = sec && sec.querySelector(':scope > .hd > header.topbar, :scope > .hd > #topbar');
  if (bar && slot && slot !== bar) slot.replaceWith(bar);
  if (!bar) return;
  const t = $('#view-title'), h = $('#view-hint');
  if (t) t.textContent = TITLES[v] || '';
  if (h) h.textContent = HINTS[v] || '';
  renderCrumb(v);
}

/** 顶栏之外的东西各归各位：本页工具条收进 .hd；不是当前页的 .hd 收起来 */
function rehomeViews(v) {
  const main = $('main.main');
  const sub = !!LEVEL[v];
  if (!main) return;
  main.classList.toggle('is-sub', sub);
  $$('.view[id^="view-"]').forEach(sec => {
    const hd = sec.querySelector(':scope > .hd'), top = sec.querySelector(':scope > .toolbar');
    if (hd && top && top.parentElement !== hd) hd.insertBefore(top, hd.firstElementChild);
    // 二级页时主页面（选股 / 盯盘）让位。
    // 别的页面的显隐只走 .active 一个开关：switchView 里已经按 id 切过了，
    // 这里再按 hidden 动一次会跟 CSS 的 .view.active{display:flex} 打架（.view 的 display:none 输给它），
    // 二级页就是这样被顶成空白页过 —— 只收页面头，别碰 .view 本身。
    if (hd) hd.hidden = sec.id !== 'view-' + v;                // 别的页面的页面头收起来
  });
}

/** 切页 = 把顶栏搬进这一页 + 本页工具条收进 .hd + 其余页面的页面头收起来 */
function moveViews(v) {
  rehomeViews(v);
  mountTopbar(v);
}

/** 面包屑："← 操作台 / 参数设置" —— 二级页上点一下退回主页面 */
function renderCrumb(v) {
  const lv = LEVEL[v] || 0;
  const app = $('#app'), el = $('#crumb');
  if (app) app.dataset.level = lv ? 'sub' : 'main';
  if (!el) return;
  el.hidden = lv < 1;
  if (lv < 1) return;
  const nm = $('#crumb-name');
  if (nm) nm.textContent = TITLES[v] || '';
}

function switchView(v) {
  S.view = v;
  $$('.ni').forEach(b => b.classList.toggle('active', b.dataset.view === v));
  $$('.view').forEach(s => s.classList.toggle('active', s.id === 'view-' + v));
  moveViews(v);                                  // 顶栏搬进这一页，标题 / 面包屑都在里面更新
  // 记住当前页签，刷新后还停在同一页；隐藏详情抽屉，免得切页后它挂在别的页面上
  if (location.search.indexOf('v=' + v) < 0) {
    try { history.replaceState(null, '', '?v=' + v); } catch (_) { }
  }
  if (typeof closeDrawer === 'function') { try { closeDrawer(); } catch (_) { } }
  if (v === 'settings') { try { renderSettings(); } catch (_) { } }
  if (v === 'watch') {                                  // 自选股：切过来就刷一遍名单
    try { loadWatchlist(); } catch (_) { }
  }
  // 图表页切过来时画布刚有宽度，得重画一次（藏着的 canvas 宽度是 0，画了也是空）
  if (v === 'backtest') { try { paintBtCharts(); renderBtEmpty(); } catch (_) { } }
  if (v === 'portfolio') { try { paintPfCharts(); renderPfEmpty(); } catch (_) { } }
  if (v === 'memory') { try { loadMemory(); } catch (_) { } }
}

/* ================================================================ 选股 */
/* 侧栏那 5 条条件说明已经撤掉，五关的进度改在「全部数据 → 五关各筛掉多少」里看 */

function renderKpis(stats, items) {
  const el = $('#kpis');
  if (!el) return;                                 // 这块在「全部数据」弹窗里，页面被裁过也不该炸
  if (!stats) { el.innerHTML = ''; return; }
  const avgScore = items.length ? items.reduce((a, b) => a + (b.score || 0), 0) / items.length : 0;
  const avgProfit = items.length ? items.reduce((a, b) => a + ((b.chip && b.chip.profit_ratio) || 0), 0) / items.length * 100 : 0;
  // 按收盘价（对照口径）跑的那次要说清楚，别和尾盘名单混为一谈
  const was = stats.basis === 'close' ? '（按收盘价算）' : '';
  // 能买 / 值得盯着 这两张是今天要看的重点，做得比后面几张统计卡显眼；
  // 「值得盯着」点一下弹出全名单
  const watchN = (S.watch || []).length;
  el.innerHTML = [
    { k: '现在能买' + was, v: stats.hit, s: `一共看了 ${stats.scanned} 只`, c: 'ok', hero: items.length ? 'hot' : '', kpi: 'hit' },
    { k: '值得盯着', v: watchN, s: watchN ? '还差一点，接近了 · 点开看全部' : '还差一点，接近了', c: '', hero: watchN ? 'hot' : '', kpi: 'watch' },
    { k: '平均把握度', v: fmt(avgScore, 1), s: '满分 100，越高越该关注', c: 'up', kpi: 'score' },
    { k: '平均套牢盘', v: pct(avgProfit, 1), s: '上方等着解套的筹码，越低越好', c: 'down', kpi: 'chip' },
    { k: '用了多久', v: stats.elapsed + 's', s: stats.failed ? `有 ${stats.failed} 只没取到数据` : '全部取到数据', c: 'warn', kpi: 'time' },
  ].map(x => `<div class="kpi ${x.c} ${x.hero || ''}" data-kpi="${x.kpi}"${x.kpi === 'watch' ? ' role="button" tabindex="0" title="点开看全部值得盯着的股票"' : ''}><div class="k">${x.k}</div><div class="v">${x.v}</div><div class="s">${x.s}</div></div>`).join('');
}

function boardBadge(code) {
  if (code.startsWith('688')) return '<span class="badge b688">科创</span>';
  if (code.startsWith('300') || code.startsWith('301')) return '<span class="badge b300">创业</span>';
  if (/^(8|4|9)/.test(code)) return '<span class="badge b8">北交</span>';
  return '';
}

/* 这一次名单是按哪个价算的：preview / tail 看平均成本线，close 看收盘价。
   判定用哪个口径，表格就得显示哪个口径，否则会出现"判成能买、却显示✗ 0天"的自相矛盾 */
function basisMode() {
  const r = S.lastResult || {};
  const st = r.stats || {};
  if (st.basis === 'tail' || st.basis === 'preview') return 'tail';
  if (st.basis === 'close') return 'close';
  const fm = (r.funnel || {}).entry_mode;
  if (fm) return fm === 'close' ? 'close' : 'tail';
  return 'tail';
}

/* 按当次口径取一只股票的"连上几天 / 高出多少 / 逐日明细" */
function pickAvg(a) {
  const tail = basisMode() === 'tail';
  const d = a.avg || {};
  const det = tail
    ? ((d.tail_detail && d.tail_detail.length) ? d.tail_detail : d.detail)
    : d.detail;
  return {
    tail,
    streak: tail ? (d.tail_streak ?? d.streak) : d.streak,
    surplus: tail ? (d.tail_surplus ?? d.avg_surplus) : d.avg_surplus,
    detail: det || [],
    lab: tail ? (d.tail_from || '14:30') : '收盘',
  };
}

function streakCells(a) {
  const need = (a.avg && a.avg.need) || 3;
  const p = pickAvg(a);
  const det = p.detail;
  const cells = [];
  for (let i = 0; i < need; i++) {
    const d = det[i];
    if (!d) { cells.push('<span class="sq n">·</span>'); continue; }
    const sur = Number(d.surplus) || 0;
    cells.push(`<span class="sq ${d.ok ? 'y' : 'n'}" title="${d.date} ${p.lab}：价格 ${d.close}，当天平均成本 ${d.avg}（${sur >= 0 ? '高出' : '低了'} ${Math.abs(sur).toFixed(2)}%）">${d.ok ? '✓' : '✗'}</span>`);
  }
  cells.push(`<em title="已经连续 ${p.streak} 天价格站在当天平均成本上方（按 ${p.lab} 算）">${p.streak}天</em>`);
  return `<div class="streak">${cells.join('')}</div>`;
}

function scoreCell(v, plan) {
  const c = v >= 75 ? 'm-high' : v >= 50 ? 'm-mid' : 'm-low';
  // plan.ok 为假说明赚赔比不够或止损太远：分数高也只是"看着顺眼"，不是能下手
  const bad = plan && plan.ok === false ? `<i class="scorebad" title="${esc(plan.note || '这单不划算')}">别急着买</i>` : '';
  return `<div class="score"><b>${fmt(v, 1)}</b><div class="meter ${c}"><i style="width:${Math.min(100, v)}%"></i></div></div>${bad}`;
}

function chipCell(profitRatio, pos) {
  if (profitRatio === null || profitRatio === undefined) return '—';
  const cap = +((S.cfg && S.cfg.params && S.cfg.params.profit_cap) ?? 0.25);
  const w = Math.min(100, profitRatio * 100);
  return `<div style="display:flex;align-items:center;gap:6px;justify-content:flex-end">
      <span class="${profitRatio <= cap ? 'down' : profitRatio >= 0.6 ? 'up' : ''}">${pct(profitRatio * 100, 1)}</span>
      <div class="chipbar"><i style="width:${w}%"></i><u style="left:${Math.min(100, cap * 100)}%"></u></div>
    </div>`;
}

function renderFunnel(stats, funnel) {
  // 漏斗现在只住在「全部数据」弹窗里，页面上没有这个容器了
  const el = $('#funnel');
  if (!el) return;
  if (!funnel || !stats) { el.hidden = true; return; }
  el.hidden = false;
  const tot = stats.scanned || 1;
  const tf = funnel.tail_from || '14:30';
  const tailMode = (funnel.entry_mode || 'tail') === 'tail';
  const basisTxt = tailMode ? tf : '收盘';
  // 卡片上只放短名（长了会折成两行），完整意思放 title
  const items = [
    ['扫过多少只', stats.scanned, 1, false, `一共看了 ${tot} 只`],
    ['① 三天都强于平均成本', funnel.ma, funnel.ma / tot, true, `看过的 ${tot} 只里，有 ${funnel.ma} 只连续 3 天都站在当天平均成本上方（按 ${basisTxt} 算）`],
    ['② 上方套牢盘少', funnel.chip, funnel.chip / tot, false, `有 ${funnel.chip} 只上方等着解套的筹码够少`],
    ['③ 价格在低位', funnel.pos, funnel.pos / tot, false, `有 ${funnel.pos} 只价格还在最近 120 天的低位`],
    ['④ 底部横着走', funnel.bottom, funnel.bottom / tot, false, `有 ${funnel.bottom} 只跌不动了、在底部横着`],
    ['⑤ 还在 20 日均线上', funnel.trend, funnel.trend / tot, false, `有 ${funnel.trend} 只没跌破 20 日均线，大方向没坏`],
  ];
  if (tailMode && funnel.ma_close != null) {
    items.push(['参考：按收盘价算能过几只', funnel.ma_close, funnel.ma_close / tot, false,
      `如果改用收盘价判断，第一关能过 ${funnel.ma_close} 只 —— 只作对照，实际下单看尾盘`]);
  }
  // 只有真的试算出东西来才占一张卡；0 只的时候这行纯属噪音
  if (funnel.tail_watch > 0) {
    items.push([`盯：${funnel.preview_at || '14:00'} 试算选中`, funnel.tail_watch, funnel.tail_watch / tot, false,
      `${funnel.preview_at || '14:00'} 按当时的价试算已经够格的有 ${funnel.tail_watch} 只，等 ${tf} 再确认一次才算数`]);
  }
  el.innerHTML = items.map(([k, v, r, gate, tip], i) => `
    <div class="fn ${gate ? 'gate' : ''} ${i && (v / tot) < 0.02 ? 'bad' : ''}" title="${esc(tip || '')}">
      <span class="fk">${k}${gate ? '<em class="fk-gate">最难过</em>' : ''}</span>
      <span class="fv">${v == null ? '—' : v}${i ? `<span class="fp">${pct((r || 0) * 100, 1)}</span>` : ''}</span>
    </div>`).join('') || '<div class="fempty">这一次没有筛过的记录</div>';
}

/* 「值得盯着」一行的渲染：窄栏里一行放下，弹窗里加一档全尺寸。
   原来这里是一张 13 列的表格，塞在选股页最下面只有半屏高，数字全挤成小字 —— 现在改成行卡片 */
const WATCH_KEYS = [
  ['ma', '价格站在成本上', '连续 3 天价格都在当天平均成本上方'],
  ['chip', '套牢盘少', '头上压着等着解套的筹码不多'],
  ['pos', '价格低', '在近 120 天区间的下边'],
  ['bottom', '底部横着走', '最近 20 天没在一路往下掉'],
  ['trend', '趋势向上', '短期均线方向向上'],
];
/* 还差几项没过：五关里有几关没打勾（尾盘确认那一下只算提示，不进这组） */
function watchGap(a) {
  const c = a.checks || {};
  const known = WATCH_KEYS.filter(([k]) => k in c);
  if (known.length) return known.filter(([k]) => !c[k]).length;
  return a.watch ? 2 : 0;
}
function watchRow(a, full) {
  const p = pickAvg(a);
  const sur = p.surplus;
  const pr = a.chip && a.chip.profit_ratio;
  const pos = a.pos && a.pos.pos;
  const gap = watchGap(a);
  const gapTxt = gap === 0 ? '全过' : gap === 1 ? '只差 1 项' : '差 2 项以上';
  const why = (a.watch || '').replace(/^（[^）]*）\s*/, '');
  return `<div class="wrow${full ? ' full' : ''}${gap === 1 ? ' near' : ''}" data-code="${a.code}" tabindex="0" title="${esc(why || '点开看它差在哪')}">
    <span class="wr-rank">${a.rank ?? ''}</span>
    <span class="wr-main">
      <span class="wr-name">${esc(a.name)}${boardBadge(a.code)}</span>
      <span class="wr-code">${a.code}</span>
      <span class="wr-price ${cls(a.chg_pct)}">${fmt(a.price)} <em>${a.chg_pct == null ? '' : (a.chg_pct > 0 ? '+' : '') + fmt(a.chg_pct) + '%'}</em></span>
    </span>
    <span class="wr-score">${scoreCell(a.score, a.plan)}</span>
    <span class="wr-streak">${streakCells(a)}</span>
    <span class="wr-nums">
      <span class="${(sur ?? 0) >= 0 ? 'up' : 'down'}">高出成本 <b>${sur == null ? '—' : (sur > 0 ? '+' : '') + fmt(sur, 2) + '%'}</b></span>
      <span>套牢盘 <b>${pr == null ? '—' : pct(pr * 100, 1)}</b></span>
      <span>位置 <b>${pos == null ? '—' : fmt(pos * 100, 0) + '%'}</b></span>
    </span>
    <span class="checks warn">${WATCH_KEYS.map(([k, n]) => `<span class="ck ${a.checks && a.checks[k] ? 'y' : 'n'}" title="${n}${a.checks && a.checks[k] ? '：符合' : '：不符合'}">${a.checks && a.checks[k] ? '✓' : '·'}</span>`).join('')}</span>
    <span class="wr-why">${esc(why || '—')}${a.checks && a.checks.tail_watch ? ' <span class="ck y" title="今天就差最后这一下">尾盘</span>' : ''}</span>
    <span class="wr-gap ${gap === 1 ? 'warn' : ''}">${gapTxt}</span>
    ${full ? `<span class="wr-act"><button class="btn sm ghost" data-detail="${a.code}">详情</button></span>` : ''}
  </div>`;
}
function paintWatchList(el, items, full) {
  if (!el) return;
  el.innerHTML = items.map(a => watchRow(a, full)).join('') ||
    `<div class="wempty">这一次没有"差一点"的股票</div>`;
}

function renderWatch() {
  // 主页不再挂「值得盯着」那张表，统一收进「全部数据 → 值得盯着」弹窗里看
  if (S.watchModalOpen) renderDetailModal();
}

/* ---------------- 细节弹窗：五关 / 汇总数字 / 值得盯着 ---------------- */
const MODAL_TABS = { gates: '五关各筛掉多少', stats: '汇总数字', watch: '值得盯着' };
function setModalTab(t) {
  S.modalTab = t;
  $$('#wm-tabs button').forEach(b => b.classList.toggle('on', b.dataset.wt === t));
  $('#wm-filter').hidden = t !== 'watch';
  ['gates', 'stats', 'watch'].forEach(k => {
    const p = $('#wt-' + k);
    if (p) p.hidden = k !== t;
  });
}
function renderDetailModal() {
  const r = S.lastResult;
  const items = S.watch || [];
  const n = (S.items || []).length;
  const st = (r && r.stats) || {};
  $('#wm-title').textContent = '这次选股的细节';
  $('#wm-sub').textContent = `看了 ${st.scanned ?? '—'} 只 · 能买 ${n} 只 · 值得盯着 ${items.length} 只`;
  // 五关：一关一关筛，卡片上写"过了这关还剩几只"
  if (!r || !r.stats) {
    // 还没跑过（或者结果被清掉了）：别拿模板里那串"准备中…"当结果摆在弹窗里
    $$('#wt-gates .fc, #wt-stats .kpi').forEach(x => { x.textContent = '还没跑过'; });
    $('#wm-sub').textContent = '还没跑过 —— 点「立即选股」跑一次就有了';
    $('#wm-foot').textContent = '';
    setModalTab(S.modalTab || 'gates');
    return;
  }
  const { funnel, stats } = r;
  renderFunnel(stats, funnel);
  // 汇总数字（原来铺在主页的那五张卡）
  renderKpis(stats, S.items || []);
  renderPickLine(r);
  // 值得盯着
  const f = S.watchFilter || 'all';
  const list = f === 'near' ? items.filter(a => watchGap(a) <= 1) : items;
  paintWatchList($('#wm-list'), list, true);
  const nearN = items.filter(a => watchGap(a) === 1).length;
  $('#wm-foot').textContent = (S.modalTab || 'gates') === 'watch'
    ? (f === 'near' ? `这里 ${list.length} 只只差最后一项 · 明天再确认一次就可能进「能买」`
      : `共 ${items.length} 只，其中 ${nearN} 只只差一项`)
    : '这些数只解释"为什么选出这几只"，不影响买卖';
  $$('#wm-filter button').forEach(b => b.classList.toggle('on', b.dataset.wf === f));
  setModalTab(S.modalTab || 'gates');
}
/** 打开细节弹窗；tab = gates / stats / watch */
function openDetailModal(tab) {
  S.modalTab = tab || S.modalTab || 'gates';
  S.watchModalOpen = true;
  renderDetailModal();
  paintIcons($('#watch-modal'));
  $('#watch-modal').hidden = false;
  $('#wm-mask').classList.add('show');
  // 弹窗和详情抽屉会叠加：抽屉层级比弹窗高（见 style.css 的 .drawer z-index），
  // 点行看详情时抽屉盖上来，关掉抽屉后弹窗还在原处
  setTimeout(() => $('#wm-close') && $('#wm-close').focus(), 30);
}
function closeWatchModal() {
  S.watchModalOpen = false;
  $('#watch-modal').hidden = true;
  $('#wm-mask').classList.remove('show');
}

function renderScreen() {
  const tb = $('#tb-screen');
  let items = S.items.slice();
  const q = S.filter.trim().toLowerCase();
  if (q) items = items.filter(a => a.code.includes(q) || (a.name || '').toLowerCase().includes(q));
  const k = S.sort.key, d = S.sort.dir;
  // 取排序值：这几处是深层的嵌套字段，缺一层就会抛错把整张表打空，所以逐层兜 null
  const get = a => ({
    code: a.code, name: a.name, price: a.price, chg_pct: a.chg_pct, score: a.score,
    streak: pickAvg(a).streak,
    avg_surplus: pickAvg(a).surplus,
    profit_ratio: a.chip ? a.chip.profit_ratio : null,
    pos: a.pos ? a.pos.pos : null,
    amp: a.bottom ? a.bottom.amp : null,
  })[k];
  items.sort((x, y) => {
    const a = get(x), b = get(y);
    // 空值不管升序降序都沉底，免得点一下"价格位置 ▲"就把没数据的排到最前面
    const an = a === null || a === undefined || a === '', bn = b === null || b === undefined || b === '';
    if (an || bn) return an && bn ? 0 : an ? 1 : -1;
    return (a > b ? 1 : a < b ? -1 : 0) * d;
  });
  $$('#tbl-screen thead th.sortable').forEach(th => {
    th.classList.toggle('sorted', th.dataset.s === k);
    th.textContent = th.textContent.replace(/ [▲▼]$/, '') + (th.dataset.s === k ? (d > 0 ? ' ▲' : ' ▼') : '');
  });

  if (!items.length) {
    tb.innerHTML = `<tr class="empty"><td colspan="13">${S.items.length ? '没有匹配的股票（换个关键词试试）' : '这一次没有全部达标的股票 —— 点「看看细节 → 值得盯着」看差一点的，或者到「参数设置」把条件放宽一点'}</td></tr>`;
    if (S.lastResult) { try { renderPickLine(S.lastResult); } catch (_) { } }
    return;
  }
  tb.innerHTML = items.map(a => {
    const plan = a.plan || {};
    return `<tr data-code="${a.code}">
      <td class="c-rank">${a.rank}</td>
      <td class="code">${a.code}</td>
      <td class="name">${esc(a.name)}${boardBadge(a.code)}</td>
      <td class="num">${fmt(a.price)}</td>
      <td class="num ${cls(a.chg_pct)}">${a.chg_pct == null ? '—' : (a.chg_pct > 0 ? '+' : '') + fmt(a.chg_pct)}%</td>
      <td>${scoreCell(a.score, a.plan)}</td>
      <td>${streakCells(a)}</td>
      <td class="num ${(pickAvg(a).surplus ?? 0) >= 0 ? 'up' : 'down'}">${(() => { const v = pickAvg(a).surplus; return v == null ? '—' : (v > 0 ? '+' : '') + fmt(v, 2) + '%'; })()}</td>
      <td>${chipCell(a.chip ? a.chip.profit_ratio : null, a.pos ? a.pos.pos : null)}</td>
      <td class="num ${!a.pos || a.pos.pos == null ? '' : a.pos.pos <= +((S.cfg && S.cfg.params && S.cfg.params.pos_cap) ?? 0.30) ? 'down' : ''}">${!a.pos || a.pos.pos == null ? '—' : fmt(a.pos.pos * 100, 0) + '%'}</td>
      <td class="num ref">${fmt(plan.stop)}</td>
      <td class="num ref">${fmt(plan.target)}<em class="sub">+${fmt(plan.target_pct, 1)}%</em></td>
      <td class="c-act"><button class="btn sm ghost" data-detail="${a.code}">详情</button><button class="btn sm ghost star" data-star="${a.code}" data-name="${esc(a.name)}" title="加进自选股，之后软件帮你盯买点卖点">${(S.watchList || []).some(w => w.code === a.code) ? '★' : '☆'}</button></td>
    </tr>`;
  }).join('');
  // 手动改过排序后，序号就不再是原来的名次了，跟着排序重排一遍，免得「1 号」排在最后
  if (k !== 'score' || d > 0) {
    $$('#tbl-screen tbody td.c-rank').forEach((td, i) => { td.textContent = i + 1; });
  }
  // 表格下面那条也带上"现在按哪个价"的当前状态，切排序时会重新渲染
  if (S.lastResult) { try { renderPickLine(S.lastResult); } catch (_) { } }
}

function applyResult(r, tag) {
  if (!r || !r.stats) { toast('这次没拿到结果', true); return; }
  S.items = r.items || [];
  S.watch = r.watch || [];
  S.lastResult = r;
  // 主页只画结论条和名单；五关 / 汇总数字 / 值得盯着 都在细节弹窗里按需渲染
  renderScreen();
  renderWatch();
  renderHl(r);
  const a = r.auto || null;
  const when = a ? (a.at || r.generated_at) : r.generated_at;
  const old = tag === '（上次的结果）' ? ' · 上次跑的' : '';
  const src = a ? `（自动 · ${a.reason || '定时扫'}${old}）` : (tag || '');
  const pv = r.funnel && r.funnel.preview_at;
  const pvt = pv ? ` · 今天按 ${pv} 试算，${(r.funnel.tail_from || '14:30')} 再确认` : '';
  // 扫过 0 只、耗时 0 秒时不要硬写"看过 0 只 · 用时 0s"，那是没信息的东西
  const seen = r.stats.scanned ? `看过 ${r.stats.scanned} 只` : '';
  const t = r.stats.elapsed ? `用时 ${r.stats.elapsed}s` : '';
  const nums = [when, seen, `能买 ${r.stats.hit ?? S.items.length} 只`,
    `值得盯着 ${S.watch.length} 只`, t].filter(Boolean).join(' · ');
  $('#res-meta').textContent = nums + src + pvt;
}

async function runScreen() {
  if (S.busy.screen) return;
  S.busy.screen = true;
  const manual = true;
  const btn = $('#btn-run');
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span>正在看';
  $('#btn-stop').hidden = false;
  $('#prog').hidden = false;
  if (manual) { try { await api('/api/auto/hold', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ on: true }) }); } catch { } }
  let nm = '';
  try {
    // 0 = 用参数里设好的自动扫描只数
    nm = +($('#limit-sel').value || 0);
    const j = await api('/api/screen', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(nm > 0 ? { limit: nm } : {}),
    });
    S.job = j.job.id;
    await pollJob(j.job.id, $('#pg-msg'), $('#pg-pct'), $('#bar'));
    const r = await api('/api/job/result?id=' + encodeURIComponent(j.job.id));
    if (r.state !== 'done') throw new Error(r.error || '没跑完');
    applyResult(r.result, '（你手动点的）');
    toast(`看完了：能买 ${S.items.length} 只，值得盯着 ${S.watch.length} 只`);
  } catch (e) {
    toast('选股失败：' + e.message, true);
  } finally {
    S.busy.screen = false;
    btn.disabled = false; btn.innerHTML = '<i data-ic="play"></i>立即选股'; paintIcons(btn);
    $('#btn-stop').hidden = true;
    setTimeout(() => { $('#prog').hidden = true; }, 800);
    if (manual) {
      try { await api('/api/auto/hold', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ on: false }) }); } catch { }
      try { await pollAuto(); } catch { }
    }
    // 手动那次用了自定义只数，参数没变，放回"自动"
    try { $('#limit-sel').value = '0'; } catch { }
  }
}

/* ---------------------------------------------------------------- 自动选股 */
const AUTO = { st: null, timer: null, sig: '' };

function fmtHm(s) {
  const t = String(s || '').trim();
  return /^\d{1,2}:\d{2}/.test(t) ? t.slice(0, 5).padStart(5, '0') : '—';
}

function autoText(st) {
  if (!st) return '连接中…';
  if (st.hold) return '我在等你（你正在手动选股）';
  if (st.enabled === false) return '已关闭（到参数设置里开）';
  const p = S.cfg && S.cfg.params ? S.cfg.params : {};
  if (st.busy) return '正在看…';
  if (!st.trade_day) return '今天休市，歇着';
  if (!st.in_hours) {
    const h0 = String(st.hours || p.auto_hours || '09:35-15:00').split('-')[0] || '09:35';
    return st.last_run ? `收盘了 · 最后一次 ${fmtHm(st.last_run)}`
      : `休息中 · ${h0} 开盘后自动开始`;
  }
  // 上次是今天的才叫"上次"，隔夜的那个名单不算今天的状态
  const today = st.now ? String(st.now).slice(0, 10) : '';
  const ranToday = st.last_run && (!today || String(st.last_run).slice(0, 10) === today);
  let s;
  if (ranToday) {
    const rs = String(st.last_reason || '').replace(/（.*?）/g, '').trim();
    s = `上次 ${fmtHm(st.last_run)}${rs ? ' ' + rs.slice(0, 24) : ''}`;
  } else {
    s = '今天还没扫过，马上开始';
  }
  if (st.next_run) s += ` · 下次 ${fmtHm(st.next_run)}`;
  // 上次自动跑挂了，把原因直接说给用户听，别让人以为名单是新的
  if (st.last_error) s += ` · 上次没跑通：${String(st.last_error).slice(0, 40)}`;
  return s;
}

function renderAuto() {
  const pill = $('#auto-pill');
  if (!pill) return;
  const st = AUTO.st;
  pill.classList.remove('on', 'busy', 'off');
  $('#auto-txt').textContent = autoText(st);
  pill.title = '自动选股：开盘自动扫、盘中定时扫、14:50 给出最终名单' +
    (st && st.limit ? `；每次扫 ${st.limit} 只` : '') +
    (st && st.now ? `；服务器时间 ${st.now}` : '');
  const live = st && !st.hold && st.enabled;
  if (!live) pill.classList.add('off');
  else if (st.busy) pill.classList.add('busy');
  else pill.classList.add('on');
}

async function pollAuto() {
  try {
    const st = await api('/api/auto');
    const prev = AUTO.st;
    const sig = [st.busy, st.last_run, st.hold, st.next_run, st.last_error || ''].join('|');
    AUTO.st = st;
    renderAuto();
    // 后台自动跑完了一轮（或首次进页面时已经有上次结果），把结果取回来
    const finished = prev && prev.busy && !st.busy && st.last_run;
    if (finished) await loadLast();
    else if (sig !== AUTO.sig && st.last_run) await loadLast();
    AUTO.sig = sig;
  } catch { }
}

async function loadLast() {
  if (S.busy.screen) return;
  try {
    const r = await api('/api/last');
    if (!r.result) return;
    if (S.items.length && S.lastResult && r.result.generated_at === S.lastResult.generated_at) return;
    applyResult(r.result, '（自动）');
  } catch { }
}

/* =========================================================
   买点卖点提醒 —— 软件跑完一轮就往这里塞一条，右上角弹卡片 + 响一声
   ========================================================= */
const ALERTS = {
  list: [],                 // 正在页面上显示的那几条
  sigs: new Set(),          // 已经展示过的（同一条不重复弹；页面上叉掉之后才会再来）
  soundOn: true,
  MAX: 3,
};
const ALERT_SOUND_KEY = 'lxquant-alert-sound';

/** 响一声：没有音频文件，用 WebAudio 现场合成两个音。浏览器要求先有用户手势，
    被自动播放策略挡下来的时候只是不响，不报错，卡片照样弹 */
function beep(kind) {
  if (!ALERTS.soundOn) return;
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    const ctx = beep._ctx || (beep._ctx = new AC());
    if (ctx.state === 'suspended') ctx.resume().catch(() => { });
    const t0 = ctx.currentTime + 0.01;
    // 买点往上走两个音，卖点往下走；音色用正弦，音量压小，不吵
    const notes = kind === 'buy' ? [784, 1047] : [660, 494];
    notes.forEach((f, i) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = 'sine';
      o.frequency.value = f;
      const t = t0 + i * 0.14;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.12, t + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.26);
      o.connect(g); g.connect(ctx.destination);
      o.start(t); o.stop(t + 0.3);
    });
  } catch (e) { /* 没有声音也能用 */ }
}

/** 一条提醒长什么样 */
function alertCard(al) {
  const buy = al.kind === 'buy';
  const d = document.createElement('div');
  d.className = 'alert ' + (buy ? 'buy' : 'sell');
  d.dataset.sig = al.sig;
  const rise = (al.vs_cost != null && al.vs_cost >= 0);
  const vsCost = al.vs_cost == null ? '—'
    : `<b class="${rise ? 'rise' : 'fall'}">${rise ? '+' : ''}${fmt(al.vs_cost, 2)}%</b>`;
  d.innerHTML =
    `<div class="al-hd"><span class="al-tag">${buy ? '买点' : '卖点'}</span>
       <span class="al-code">${esc(al.code)}</span>
       <span class="al-time">${esc(al.at || '')}</span></div>
     <div class="al-name">${esc(al.name || '')}</div>
     <div class="al-msg">${esc(al.msg || '')}</div>
     <div class="al-nums"><span>现价<b>${fmt(al.price, 2)}</b></span>
       <span>比成本${vsCost}</span>
       <span>今天<b class="${cls(al.chg_pct)}">${al.chg_pct > 0 ? '+' : ''}${fmt(al.chg_pct, 2)}%</b></span></div>
     <button class="al-x" title="关掉这条（记成已读，不再弹）">✕</button>`;
  // 点卡片 = 打开详情抽屉（K 线、五关、成本线），叉号只关卡片
  d.addEventListener('click', ev => {
    if (ev.target.closest('.al-x')) { ev.stopPropagation(); dropAlert(al.sig, true); return; }
    if (al.code) openDetail(al.code);
  });
  return d;
}

/** 往右上角塞一条；同一条（sig 一样）只弹一次。返回是否真的弹了 */
function pushAlert(al, sound = true) {
  if (!al || !al.sig) return false;
  if (ALERTS.sigs.has(al.sig)) return false;
  if (ALERTS.dropped && ALERTS.dropped.has(al.sig)) return false;
  ALERTS.sigs.add(al.sig);
  const box = $('#alerts');
  if (!box) return false;
  const d = alertCard(al);
  box.prepend(d);
  ALERTS.list.unshift(al);
  // 攒着同一页里的几条，下一帧一起滑出来，别一条一条闪
  if (!ALERTS.flush) {
    ALERTS.flush = setTimeout(() => {
      [...box.children].forEach(x => x.classList.add('in'));
      ALERTS.flush = null;
    }, 16);
  }
  while (box.children.length > ALERTS.MAX) {
    const last = box.lastElementChild;
    if (last) { last.remove(); ALERTS.list.pop(); }
  }
  if (sound) beep(al.kind);
  return true;
}

/** 关掉一条卡片；readed=true 表示用户看见了，这条就不再弹 */
function dropAlert(sig, readed) {
  const box = $('#alerts');
  const d = box && [...box.children].find(x => x.dataset.sig === sig);
  if (d) {
    d.classList.add('out');
    setTimeout(() => d.remove(), 220);
  }
  ALERTS.list = ALERTS.list.filter(a => a.sig !== sig);
  if (readed) {
    // 看见了：记成"别再捡回来"，但允许以后新的相同提醒重新弹
    ALERTS.sigs.delete(sig);
    ALERTS.dropped = ALERTS.dropped || new Set();
    ALERTS.dropped.add(sig);
  } else {
    ALERTS.sigs.delete(sig);
  }
}

/** 拉服务器上的提醒队列：新出现的弹卡片，页面上已经没有了的老卡片自己收起来 */
async function syncAlerts() {
  let j;
  try { j = await api('/api/alerts'); } catch (e) { return; }
  const list = (j.alerts || []);
  const box = $('#alerts');
  if (!box) return;
  // 服务端说"已读"了的（比如在自选股页点过标记已读），这里的卡片跟着消失
  $$('.alert', box).forEach(d => {
    if (!list.some(a => a.sig === d.dataset.sig)) {
      d.classList.add('out');
      setTimeout(() => d.remove(), 220);
    }
  });
  // 关掉的、已经淡出的卡片就别再捡回来了（否则清不干净）
  ALERTS.dropped = ALERTS.dropped || new Set();
  // 新提醒：从旧到新依次补上，最后一条响
  const fresh = list.filter(a => !ALERTS.sigs.has(a.sig) && !ALERTS.dropped.has(a.sig))
    .slice().reverse();
  fresh.forEach((a, i) => pushAlert(a, i === fresh.length - 1));
  initSoundPref();
}

/** 记一下"要不要声音"，跨刷新保留 */
function initSoundPref() {
  try {
    const v = localStorage.getItem(ALERT_SOUND_KEY);
    if (v === '0') ALERTS.soundOn = false;
  } catch (e) { }
}

function setAlertSound(on) {
  ALERTS.soundOn = !!on;
  try { localStorage.setItem(ALERT_SOUND_KEY, on ? '1' : '0'); } catch (e) { }
}

/** 打开页面时先解锁一次音频（浏览器要求用户点过才有声音） */
function primeAudio() {
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (AC && (!beep._ctx || beep._ctx.state === 'suspended')) {
      const ctx = beep._ctx || (beep._ctx = new AC());
      if (ctx.state === 'suspended') ctx.resume().catch(() => { });
    }
  } catch (e) { }
  document.removeEventListener('pointerdown', primeAudio, true);
  document.removeEventListener('keydown', primeAudio, true);
}

function renderHl(r) {
  const el = $('#hl');
  if (!el) return;
  if (!r || !r.stats) { el.hidden = true; renderPickLine(null); return; }
  renderPickLine(r);
  const n = (r.items || []).length, w = (r.watch || []).length;
  const st = r.stats || {};
  const fu = r.funnel || {};
  const auto = r.auto || {};
  renderPickLine(r);
  const isClose = st.basis === 'close';      // 按收盘价算的对照口径
  const isPv = st.basis === 'preview';       // 尾盘前试算，今天还没定型
  const tail = fu.tail_from || '14:30';
  /* 主页只留这一句结论：几个数字 + 一句"现在该干什么"。
     五关各筛掉多少、平均把握度这些都在「全部数据」弹窗里，别在主页铺开 */
  let cls = '', tag = '', nums = '', say = '';
  const N = (v, unit) => `<b class="hl-num">${v}</b><em>${unit}</em>`;
  if (isClose) {
    cls = 'warn'; tag = '收盘口径';
    nums = n ? `能买 ${N(n, '只')}` : '没有能买的';
    say = w ? `另有 ${w} 只值得盯着` : '实际下单看尾盘那次';
  } else if (n) {
    tag = isPv ? '试算能买' : '可以买';
    nums = `能买 ${N(n, '只')}`;
    say = isPv ? `按 ${fu.preview_at || '14:00'} 的价试算的，${tail} 再确认一次才算数`
      : tail !== 'close' ? `${tail} 之后买进去` : '这些是全部条件都过了的';
  } else if (w) {
    cls = 'warn'; tag = '还差一点';
    nums = `能买 0 只 · 接近 ${N(w, '只')}`;
    say = fu.preview_at ? `现在是 ${fu.preview_at} 的试算，${tail} 再定` : '点「全部数据」看它们差在哪';
  } else if (fu.preview_at) {
    cls = 'warn'; tag = '等尾盘';
    nums = `现在能买 0 只`;
    say = `现在是 ${fu.preview_at} 的试算，到 ${tail} 再算一次`;
  } else {
    cls = 'warn'; tag = '空仓等';
    nums = '这次没有能买的';
    const off = !!(S.cfg && S.cfg.params && S.cfg.params.auto_scan === false);
    say = off ? '自动选股现在是关着的，只有点「立即选股」才会再算'
      : auto.reason ? auto.reason : '条件是严的，空着是常态 —— 等下一个信号';
  }
  const tail2 = w && !isClose && !nums.includes('接近') && n ? ` · ${w} 只值得盯着` : '';
  el.className = 'hl' + (cls ? ' ' + cls : '');
  el.hidden = false;
  el.innerHTML = `<span class="hl-tag">${tag}</span><span class="hl-nums">${nums}${tail2}</span><span class="hl-say">${esc(say)}</span>
    <span class="spacer"></span>
    <button class="btn sm ghost" id="hl-more">看看细节</button>`;
}

/** 表格下面那条：这次到底是怎么选出来的（比顶部结论更具体） */
function renderPickLine(r) {
  const el = $('#pick-line');
  if (!el) return;
  if (!r || !r.stats) { el.hidden = true; return; }
  const st = r.stats || {}, fu = r.funnel || {};
  const n = (r.items || []).length, w = (r.watch || []).length;
  let basis = '收盘价';
  if (st.basis === 'tail') basis = fu.tail_from && fu.tail_from !== 'close' ? `${fu.tail_from} 之后` : '收盘那会儿';
  else if (st.basis === 'preview') basis = `${fu.preview_at || '14:00'} 试算`;
  const ma = fu.ma;
  const parts = [
    `<span>比的是 <b>${esc(basis)}</b> 的价和平均成本</span>`,
    `<i class="pl-sep"></i>`,
    `<span>全程看了 <b>${st.scanned ?? 0}</b> 只</span>`,
    `<i class="pl-sep"></i>`,
    `<span>能买 <b class="pl-ok">${n}</b> 只</span>`,
    `<i class="pl-sep"></i>`,
    `<span>值得盯着 <b>${w}</b> 只</span>`,
  ];
  if (st.elapsed) parts.push(`<i class="pl-sep"></i><span>用了 <b>${st.elapsed}</b> 秒</span>`);
  if (st.failed) parts.push(`<i class="pl-sep"></i><span class="pl-msg">有 ${st.failed} 只没取到行情，跳过了</span>`);
  // ma 和 n 是同一件事（能买的就是站上平均成本的），两个都写会让人以为是两组数
  if (ma != null && !n) parts.push(`<i class="pl-sep"></i><span class="pl-msg">其中 ${ma} 只连着站上了平均成本</span>`);
  // 说明这份名单的覆盖范围，免得看到"0 只"就以为全市场真的一只都没有
  if (st.mode === 'all') parts.push(`<i class="pl-sep"></i><span class="pl-msg">范围：全部沪深A股</span>`);
  else if (st.limit) parts.push(`<i class="pl-sep"></i><span class="pl-msg">范围：成交额最大的 ${st.limit} 只</span>`);
  el.innerHTML = parts.join('');
  el.hidden = false;
}

async function pollJob(id, msgEl, pctEl, barEl) {
  while (true) {
    const j = await api('/api/job?id=' + encodeURIComponent(id));
    if (msgEl) msgEl.textContent = j.msg;
    if (pctEl) pctEl.textContent = j.pct + '%';
    if (barEl) barEl.style.width = j.pct + '%';
    if (j.state === 'done' || j.state === 'error' || j.state === 'cancelled') return j;
    await new Promise(r => setTimeout(r, 600));
  }
}

/* ================================================================ 盯盘扫描 */
async function runScan() {
  if (S.busy.scan) return;
  S.busy.scan = true;
  const btn = $('#btn-scan');
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span>正在看';
  $('#scan-prog').hidden = false;
  try {
    const j = await api('/api/scan', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit: +$('#scan-limit').value }),
    });
    await pollJob(j.job.id, $('#scan-msg'), $('#scan-pct'), $('#scan-bar'));
    const r = await api('/api/job/result?id=' + encodeURIComponent(j.job.id));
    if (r.state !== 'done') throw new Error(r.error || '没跑完');
    S.scanItems = r.result.items || [];
    renderScan();
    toast('看完了');
  } catch (e) { toast('没能看一眼：' + e.message, true); }
  finally {
    S.busy.scan = false;
    btn.disabled = false; btn.innerHTML = '<i data-ic="play"></i>马上看一眼'; paintIcons(btn);
    setTimeout(() => { $('#scan-prog').hidden = true; }, 700);
  }
}

/* ================================================================ 自选股（买点卖点） */
const W_KEYS = [['ma', '站上平均成本'], ['chip', '套牢盘不多'], ['pos', '价格在低位'],
  ['bottom', '底部横着走'], ['trend', '在均线上']];
const W_KIND_CN = {
  'buy.near': '差一点就够格', 'buy.ma': '五关全过', 'buy.pull': '回到均线附近',
  'sell.stop': '跌破止损', 'sell.target': '到目标价', 'sell.ma': '掉破平均成本', 'sell.trail': '高点回落',
};

/** 自选股页：一只一行，左边是谁、中间五关、右边该买该卖的结论 */
function renderWatchlist() {
  const box = $('#w-list');
  if (!box) return;
  const items = S.watchList || [];
  const meta = $('#w-meta');
  if (meta) {
    meta.textContent = items.length
      ? `${items.length} 只 · 上一次看是 ${S.watchAt || '还没看过'} · 每 3 分钟自动看一次`
      : '加进来之后，软件每 3 分钟看一次买点卖点';
  }
  if (!items.length) {
    box.innerHTML = `<div class="wl-empty">还没有自选股。在上面填 6 位代码加进来，或者到「选股」表格里点每行最后的 ☆。</div>`;
    return;
  }
  const lastHit = (code) => (S.alerts || []).find(a => a.code === code);
  box.innerHTML = items.map(it => {
    const l = it.last || {}, ck = l.checks || {}, plan = l.plan || {};
    const al = lastHit(it.code);
    const buy = (S.watchHits || {})[it.code] || [];
    const verdict = al
      ? `<span class="wv ${al.kind}">${W_KIND_CN[al.why] || al.tag}</span>`
      : buy.length
        ? `<span class="wv ${String(buy[0]).startsWith('sell') ? 'sell' : 'buy'}">${W_KIND_CN[buy[0]] || '看着'}</span>`
        : `<span class="wv none">先看着</span>`;
    // 这只票今天命中的提醒（后端 /api/watch/check 返回的 rows[].hits），有就整行拉色条
    const hitCls = buy.length ? (String(buy[0]).startsWith('sell') ? ' hit-sell' : ' hit-buy') : '';
    return `<div class="wrow${hitCls}" style="--wcols:minmax(120px,1.2fr) 88px 110px 86px minmax(140px,1fr) 128px auto" data-code="${it.code}">
      <div class="wr-id"><b>${esc(it.name || '—')}</b><span class="code">${it.code}</span></div>
      <div class="wr-px"><b>${fmt(l.price)}</b><span class="${cls(l.chg_pct)}">${l.chg_pct == null ? '—' : (l.chg_pct > 0 ? '+' : '') + fmt(l.chg_pct) + '%'}</span></div>
      <div class="wr-chk" title="五关：${W_KEYS.map(([k, n]) => n + (ck[k] ? '✓' : '✗')).join(' · ')}">${W_KEYS.map(([k, n]) => `<i class="ck ${ck[k] ? 'yes' : 'no'}" title="${n}${ck[k] ? '：符合' : '：不符合'}">${ck[k] ? '✓' : '✗'}</i>`).join('')}</div>
      <div class="wr-score">把握 <b>${!l.price ? '—' : (l.score == null ? '—' : fmt(l.score, 0))}</b></div>
      <div class="wr-verdict">${verdict}<em class="wv-at">${esc((al || {}).at || '')}</em></div>
      <div class="wr-plan"><span>止损 ${fmt(it.stop || plan.stop)}</span><span>目标 ${fmt(it.target || plan.target)}</span></div>
      <div class="wr-act">
        <button class="btn sm ghost" data-detail="${it.code}">详情</button>
        <button class="btn sm ghost" data-wdel="${it.code}" title="从自选股里删掉">删</button>
      </div>
    </div>`;
  }).join('');
  // 有提醒的行，左边拉一条色条（红=买点，绿=卖点），扫一眼就知道哪只要动手
  [...box.children].forEach(row => {
    const al = lastHit(row.dataset.code);
    if (al) row.classList.add('hit-' + al.kind);
  });
  paintIcons(box);
}

/** 拉一次自选股名单（顺带把每只票上次的判断结果带上） */
async function loadWatchlist() {
  try {
    const j = await api('/api/watch');
    S.watchList = j.items || [];
    S.watchAt = j.check_at || '';
    // 服务器上已经算过的提醒，当作这只票的"最近结论"
    (j.alerts || []).forEach(a => { if (!(S.alerts || []).some(x => x.sig === a.sig)) (S.alerts || []).push(a); });
    renderWatchlist();
  } catch (e) { toast('自选股没读出来：' + e.message, true); }
}

/** 立刻检查一遍（不用等自动的 3 分钟） */
async function checkWatchlist(force = true) {
  const btn = $('#w-check');
  if (btn) { btn.disabled = true; btn.textContent = '正在看…'; }
  try {
    const j = await api('/api/watch/check', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force }),
    });
    S.watchHits = {};
    (j.rows || []).forEach(r => { S.watchHits[r.code] = r.hits || []; });
    S.watchList = (S.watchList || []).map(it => {
      const row = (j.rows || []).find(r => r.code === it.code);
      return row ? { ...it, last: row.last } : it;
    });
    S.watchAt = j.checked_at || S.watchAt;
    if ((j.new || []).length) (j.alerts || []).forEach(a => { if (!(S.alerts || []).some(x => x.sig === a.sig)) (S.alerts || []).unshift(a); });
    renderWatchlist();
    await syncAlerts();
    toast((j.new || []).length ? `有 ${j.new.length} 条新提醒` : '看完了，暂时没有新的买点卖点');
  } catch (e) { toast('没能检查：' + e.message, true); }
  finally { if (btn) { btn.disabled = false; btn.textContent = '马上检查'; } }
}

async function addWatch(code, name) {
  code = String(code || '').trim();
  // 名字也行（后端会去找）；代码就照旧要 6 位
  if (!code) { toast('填个股票名字或代码', true); return; }
  if (/^\d+$/.test(code) && code.length !== 6) { toast('代码要 6 位，或者直接填名字', true); return; }
  try {
    const j = await api('/api/watch/add', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, name: name || '' }),
    });
    // 服务器可能刚把名字补全（或者本来就带名字），先把这只塞进列表，
    // 别等 checkWatchlist 那一轮才出现，不然期间点开详情会找不到代码
    if (j && j.item) {
      S.watchList = (S.watchList || []).filter(x => x.code !== j.item.code).concat([j.item]);
      renderWatchlist();
    }
    toast('加进来了，马上帮你看看');
    await loadWatchlist();
    checkWatchlist(true);
  } catch (e) { toast('没加上：' + e.message, true); }
}

async function removeWatch(code) {
  try {
    await api('/api/watch/remove', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
    });
    toast('删掉了');
    loadWatchlist();
  } catch (e) { toast('没删掉：' + e.message, true); }
}

/** 自选股那一块上的按钮和行内操作（内容每次重画，用事件委托） */
function bindWatchlistPanel() {
  const box = $('#wpanel');
  if (!box) return;
  const add = () => {
    const inp = $('#w-code');
    addWatch(inp && inp.value);
    if (inp) inp.value = '';
    showHints([]);
  };
  box.addEventListener('click', e => {
    if (e.target.closest('#w-add')) { add(); return; }
    const pick = e.target.closest('[data-wpick]');
    if (pick) {
      addWatch(pick.dataset.wpick);
      const i = $('#w-code');
      if (i) i.value = '';
      showHints([]);
      return;
    }
    if (e.target.closest('#w-check')) { checkWatchlist(true); return; }
    if (e.target.closest('#w-clear')) {
      api('/api/alerts/ack', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ all: true }),
      }).then(() => {
        ALERTS.sigs.clear();
        // 这些提醒已经被"清掉"了，别让下一轮 syncAlerts 又把它们捡回来
        ALERTS.dropped = new Set((S.alerts || []).map(a => a.sig));
        const ab = $('#alerts');
        if (ab) ab.innerHTML = '';
        S.alerts = [];
        S.watchHits = {};
        renderWatchlist();
        toast('提醒清掉了');
      }).catch(err => toast(err.message, true));
      return;
    }
    if (e.target.closest('#w-sound')) { toggleSound(); return; }
    const del = e.target.closest('[data-wdel]');
    if (del) { removeWatch(del.dataset.wdel); return; }
    const det = e.target.closest('[data-detail]');
    if (det) { openDetail(det.dataset.detail); return; }
    const row = e.target.closest('.wrow');
    if (row && !e.target.closest('button') && row.dataset.code) openDetail(row.dataset.code);
  });
  const inp = $('#w-code');
  if (inp) {
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') add(); });
    // 一边打字一边给候选：只给名字有重叠的那几只，点一个就加进去
    let t = 0;
    inp.addEventListener('input', () => {
      clearTimeout(t);
      const q = inp.value.trim();
      if (!q) { showHints([]); return; }
      t = setTimeout(async () => {
        try {
          const j = await api('/api/watch?q=' + encodeURIComponent(q));
          if (inp.value.trim() === q) showHints(j.rows || []);
        } catch (_) { showHints([]); }
      }, 300);
    });
  }
  syncSoundBtn();
}

/** 输入框下面那排候选字（点一下就加进自选） */
function showHints(rows) {
  const box = $('#w-hints');
  if (!box) return;
  box.innerHTML = rows.map(r => `<button class="wh" data-wpick="${esc(r.code)}">${esc(r.name)}<em>${esc(r.code)}</em></button>`).join('');
  box.hidden = !rows.length;
}

function syncSoundBtn() {
  const b = $('#w-sound');
  if (b) b.textContent = ALERTS.soundOn ? '🔔 声音开' : '🔕 声音关';
}

function toggleSound() {
  setAlertSound(!ALERTS.soundOn);
  syncSoundBtn();
  toast(ALERTS.soundOn ? '提醒会响' : '提醒不出声了（卡片照样弹）');
  if (ALERTS.soundOn) beep('buy');
}

/* ---------------------------------------------------------------- 记忆
   每天选完自动记一笔（后端 lxquant/memory.py 写 data/memory/YYYY-MM-DD.json），
   这一页把它读出来，用现在的收盘价算"那天选的票后来怎么样了"。
   目的不是好看，是回答一个问题：这套选股到底准不准。
   ---- */
const MEM = {
  days: [],          // [{date, at, hit, watch, scanned, names}]
  date: '',          // 当前看的那天
  src: 'all',        // all / hit / watch
  rv: null,          // 那天的回看结果
  ov: null,          // 三十天的总成绩
  loading: false,
};

function memKindOf(r) { return r.gap == null ? 'hit' : 'watch'; }

/** 拉日期列表（顺带把总成绩也拉下来，只请求一次） */
async function loadMemory(force) {
  if (MEM.loading && !force) return;
  MEM.loading = true;
  // 头一次进来（或手动重算）要等几秒，先把"在算"摆出来，别留白屏；已有数据时静默刷新，不闪
  if (!MEM.days || !MEM.days.length) renderMemBusy(true);
  try {
    const [d, o] = await Promise.all([
      fetch('/api/memory?n=90').then(r => r.json()),
      fetch('/api/memory?overview=1&n=30').then(r => r.json()),
    ]);
    MEM.days = (d && d.days) || [];
    MEM.ov = (o && o.ok) ? o : null;
  } catch (e) {
    MEM.days = [];
  } finally {
    MEM.loading = false;
  }
  renderMemDates();
  if (!MEM.days.length) {
    renderMemEmpty('还没有能回看的记录');
    return;
  }
  if (!MEM.date || !MEM.days.some(x => x.date === MEM.date)) MEM.date = MEM.days[0].date;
  await loadMemDay(MEM.date);
}

function renderMemDates() {
  const sel = $('#mem-date');
  if (!sel) return;
  sel.innerHTML = MEM.days.map(d => {
    const t = (d.at || '').slice(5, 16);
    const nm = (d.names || []).slice(0, 2).join('、');
    return `<option value="${d.date}" ${d.date === MEM.date ? 'selected' : ''}>${d.date}　留了 ${(d.hit || 0) + (d.watch || 0)} 只${nm ? '（' + esc(nm) + '…）' : ''}</option>`;
  }).join('') || '<option value="">—</option>';
}

function renderMemBusy(on) {
  const b = $('#mem-loading'); if (b) b.hidden = !on;
  if (on) ['#mem-kpis', '#mem-row2', '#mem-table', '#mem-days', '#mem-empty'].forEach(s => { const el = $(s); if (el) el.hidden = true; });
}

async function loadMemDay(date) {
  if (!date) return;
  renderMemBusy(true);          // 算一只一只的日线要好一会儿，先把"在算"摆出来
  let r = null;
  try {
    r = await fetch('/api/memory?review=1&date=' + encodeURIComponent(date)).then(x => x.json());
  } catch (e) { r = null; }
  MEM.rv = (r && r.ok) ? r : null;
  renderMemBusy(false);
  renderMemory();
}

function renderMemEmpty(txt) {
  const b0 = $('#mem-loading'); if (b0) b0.hidden = true;
  const box = $('#mem-empty'); if (box) { box.hidden = false; if (txt) { const b = $('#mem-empty-txt'); if (b && txt !== '还没有能回看的记录') b.textContent = txt; } }
  ['#mem-kpis', '#mem-row2', '#mem-table', '#mem-days'].forEach(s => { const el = $(s); if (el) el.hidden = true; });
}

function renderMemory() {
  const rv = MEM.rv;
  const items = memFiltered();
  if (!rv || (!items.length)) {
    const has = !!(rv && ((rv.rows || []).length || (rv.watch_rows || []).length));
    if (!has) { renderMemEmpty(); return; }
  }
  const rows = items.filter(x => x.ret != null);
  const pend = items.filter(x => x.ret == null);
  const box = $('#mem-empty'); if (box) box.hidden = true;
  const b1 = $('#mem-loading'); if (b1) b1.hidden = true;
  ['#mem-kpis', '#mem-row2', '#mem-table', '#mem-days'].forEach(s => { const el = $(s); if (el) el.hidden = false; });

  // ---- 上面那张成绩单
  const n = rows.length;
  const win = rows.filter(x => x.ret > 0).length;
  const avg = n ? rows.reduce((a, b) => a + b.ret, 0) / n : 0;
  const best = n ? rows.reduce((a, b) => (b.ret > a.ret ? b : a)) : null;
  const worst = n ? rows.reduce((a, b) => (b.ret < a.ret ? b : a)) : null;
  const hitT = rows.filter(x => x.sold_target).length;
  const hitS = rows.filter(x => x.sold_stop).length;
  $('#mem-kpis').innerHTML = [
    {
      k: '那天留了几只', v: String(items.length), c: '',
      s: rows.length ? `${rows.length} 只有收盘价，${pend.length ? `还有 ${pend.length} 只` : '全部'}能算` : '都在等收盘价',
    },
    { k: '到今天平均', v: n ? (avg > 0 ? '+' : '') + fmt(avg, 2) + '%' : '—', s: `${MEM.date} → 今天，收盘价算的`, c: n ? (avg >= 0 ? 'up' : 'down') : '' },
    { k: '赚钱的几只', v: n ? `${win} / ${n}` : '—', s: n ? `占 ${pct(win / n * 100, 0)}` : '还没有数据', c: n ? (win * 2 >= n ? 'up' : 'down') : '' },
    { k: '最好的一只', v: best ? '+' + fmt(best.ret, 1) + '%' : '—', s: best ? esc(best.name) : '', c: best ? 'up' : '' },
    { k: '最差的一只', v: worst ? (worst.ret > 0 ? '+' : '') + fmt(worst.ret, 1) + '%' : '—', s: worst ? esc(worst.name) : '', c: worst ? (worst.ret < 0 ? 'down' : 'up') : '' },
    { k: '摸到止盈 / 破止损', v: n ? `${hitT} / ${hitS}` : '—', s: '按软件当时给的价位算', c: '' },
  ].map(x => `<div class="kpi"><div class="k">${x.k}</div><div class="v ${x.c}">${x.v}</div><div class="s">${x.s}</div></div>`).join('');

  // ---- 右上角那段话
  const say = [];
  if (!n) {
    say.push(['还在等收盘', '这天是今天，日线还没出来。等收盘（或明天）再回来看，就有涨跌幅了。']);
  } else {
    if (avg >= 3) say.push(['这批是赚的', `平均 +${fmt(avg, 2)}%，${n} 只里 ${win} 只赚钱。`]);
    else if (avg <= -3) say.push(['这批是亏的', `平均 ${fmt(avg, 2)}%，${n} 只里只有 ${win} 只赚钱。`]);
    else say.push(['基本在原地', `平均 ${fmt(avg, 2)}%，好票和烂票互相抵消了。`]);
    say.push(['止损止盈管不管用', `按当时给的价位，${hitT} 只摸到过止盈，${hitS} 只跌破过止损。跌破止损说明当时那套判断没成立 —— 这不是软件算错，是行情没按预期走，该走就得走。`]);
    if (pend.length) say.push(['还有没算的', `${pend.length} 只今天刚选出来，等收盘价。`]);
  }
  $('#mem-why').innerHTML = say.map(([h, t]) => `<div class="rrow"><b>${h}</b><p>${t}</p></div>`).join('');

  // ---- 明细表
  $('#mem-meta').textContent = `${MEM.date} 选的 · ${items.length} 只`;
  $('#mem-sub').textContent = `涨停价按收盘价算；「最高/最低到过」是选出之后这一段时间里的极值`;
  const TB = $('#tb-mem');
  TB.innerHTML = items.map(x => {
    const kind = memKindOf(x);
    const retCls = x.ret == null ? '' : (x.ret > 0 ? 'up' : (x.ret < 0 ? 'down' : ''));
    return `<tr data-code="${esc(x.code)}">
      <td class="code">${esc(x.code)}</td>
      <td class="name">${esc(x.name || '')}</td>
      <td><span class="chip ${kind === 'hit' ? 'ok' : ''}">${kind === 'hit' ? '能买' : '值得盯着'}</span></td>
      <td class="num">${x.then == null ? '—' : fmt(x.then)}</td>
      <td class="num">${x.last == null ? '—' : fmt(x.last)}</td>
      <td class="num ${retCls}">${x.ret == null ? '等收盘' : (x.ret > 0 ? '+' : '') + fmt(x.ret, 2) + '%'}</td>
      <td class="num up">${x.best == null ? '—' : '+' + fmt(x.best, 2) + '%'}</td>
      <td class="num down">${x.worst == null ? '—' : fmt(x.worst, 2) + '%'}</td>
      <td class="num">${x.days == null ? '—' : x.days}</td>
      <td>${x.stop ? `止损 ${fmt(x.stop)}` : ''}${x.stop && x.target ? ' / ' : ''}${x.target ? `止盈 ${fmt(x.target)}` : ''}${!x.stop && !x.target ? '—' : ''}</td>
    </tr>`;
  }).join('') || '<tr class="empty"><td colspan="10">这一条筛选下没有票</td></tr>';

  // ---- 每天的成绩单
  const ov = MEM.ov;
  const TB2 = $('#tb-memdays');
  if (ov && (ov.days || []).length) {
    TB2.innerHTML = ov.days.map(d => `<tr data-date="${d.date}">
      <td>${d.date}</td>
      <td class="num">${d.n}</td>
      <td class="num">${d.hit}</td>
      <td class="num ${d.avg > 0 ? 'up' : (d.avg < 0 ? 'down' : '')}">${d.avg > 0 ? '+' : ''}${fmt(d.avg, 2)}%</td>
      <td class="num">${pct(d.win_rate, 0)}</td>
      <td class="num">${d.days}</td>
    </tr>`).join('');
  } else {
    TB2.innerHTML = '<tr class="empty"><td colspan="6">还没有足够的记录 —— 明天起就会有</td></tr>';
  }

  paintMemChart();
}

function memFiltered() {
  const rv = MEM.rv || {};
  const hit = (rv.rows || []).map(x => Object.assign({}, x, { gap: null }));
  const watch = (rv.watch_rows || []).map(x => Object.assign({}, x));
  if (MEM.src === 'hit') return hit;
  if (MEM.src === 'watch') return watch;
  return hit.concat(watch);
}

/** 一天之后这批票的走势：把每只从选出到今天的累计涨跌幅画成柱状图 */
function paintMemChart() {
  const cv = $('#mem-chart'); if (!cv) return;
  const rows = memFiltered().filter(x => x.ret != null);
  const box = $('#mem-row2'); if (box && box.hidden) return;
  if (!rows.length) { drawHint(cv, '还没有涨跌幅', '这是今天刚选出来的，等收盘就有了'); return; }
  rows.sort((a, b) => b.ret - a.ret);
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = 220;
  if (!W) return;
  cv.width = W * dpr; cv.height = H * dpr; cv.style.height = H + 'px';
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  const pad = { l: 42, r: 10, t: 12, b: 26 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const lo = Math.min(0, ...rows.map(r => r.ret)), hi = Math.max(0, ...rows.map(r => r.ret));
  const span = (hi - lo) || 1;
  const y = v => pad.t + ih - (v - lo) / span * ih;
  // 网格 + 0 轴
  const zero = y(0);
  g.strokeStyle = T().line; g.lineWidth = 1;
  g.beginPath(); g.moveTo(pad.l, pad.t); g.lineTo(pad.l, pad.t + ih); g.stroke();
  g.beginPath(); g.moveTo(pad.l, zero); g.lineTo(pad.l + iw, zero); g.stroke();
  g.font = '10px sans-serif'; g.fillStyle = T().txt3; g.textAlign = 'right';
  [hi, 0, lo].forEach(v => g.fillText(v.toFixed(1) + '%', pad.l - 6, y(v) + 3));
  const bw = Math.min(28, Math.max(6, iw / rows.length * 0.62));
  const step = iw / Math.max(rows.length, 1);
  rows.forEach((r, i) => {
    const cx = pad.l + step * (i + 0.5);
    const top = y(Math.max(r.ret, 0)), bot = y(Math.min(r.ret, 0));
    g.fillStyle = r.ret > 0 ? T().up : (r.ret < 0 ? T().down : T().txt3);
    g.fillRect(cx - bw / 2, top, bw, Math.max(bot - top, 1));
    if (rows.length <= 14) {
      g.save(); g.translate(cx, H - 14); g.rotate(-Math.PI / 6);
      g.textAlign = 'right'; g.fillStyle = T().txt3;
      g.fillText((r.name || r.code).slice(0, 4), 0, 0);
      g.restore();
    }
  });
}

function bindMemoryPanel() {
  const sel = $('#mem-date');
  if (sel) sel.onchange = () => { MEM.date = sel.value; loadMemDay(MEM.date); };
  const src = $('#mem-src');
  if (src) src.onchange = () => { MEM.src = src.value; renderMemory(); };
  const btn = $('#btn-mem-refresh');
  if (btn) btn.onclick = () => { loadMemory(true); toast('重新算了一遍'); };
  const tb2 = $('#tb-memdays');
  if (tb2) tb2.onclick = (e) => {
    const tr = e.target.closest('tr[data-date]');
    if (!tr) return;
    MEM.date = tr.dataset.date;
    if (sel) sel.value = MEM.date;
    loadMemDay(MEM.date);
  };
  const tb = $('#tb-mem');
  if (tb) tb.onclick = (e) => {
    const tr = e.target.closest('tr[data-code]');
    if (tr) openDetail(tr.dataset.code);
  };
}

function renderScan() {
  const items = S.scanItems;
  const pass = items.filter(a => a.checks.ma).length;
  $('#scan-meta').textContent = `一共看了 ${items.length} 只 · 今天价格还在平均成本上方的 ${pass} 只`;
  const tb = $('#tb-scan');
  if (!items.length) { tb.innerHTML = '<tr class="empty"><td colspan="11">还没有数据，点右上「马上看一眼」</td></tr>'; return; }
  const keys = [['ma', '站在平均成本上方'], ['chip', '上方没什么套牢盘'], ['pos', '价格在低位'], ['bottom', '底部横着走'], ['trend', '在 20 日均线上']];
  tb.innerHTML = items.map(a => `<tr data-code="${a.code}">
    <td class="code">${a.code}</td>
    <td class="name">${esc(a.name)}${boardBadge(a.code)}</td>
    <td class="num">${fmt(a.price)}</td>
    <td class="num ${cls(a.chg_pct)}">${a.chg_pct == null ? '—' : (a.chg_pct > 0 ? '+' : '') + fmt(a.chg_pct)}%</td>
    <td>${streakCells(a)}</td>
    <td class="num ${((a.avg && a.avg.today_surplus) || 0) >= 0 ? 'up' : 'down'}">${!a.avg || a.avg.today_surplus == null ? '—' : (a.avg.today_surplus > 0 ? '+' : '') + fmt(a.avg.today_surplus)}%</td>
    <td class="num">${!a.avg || a.avg.avg_surplus == null ? '—' : fmt(a.avg.avg_surplus)}%</td>
    <td class="num">${!a.chip || a.chip.profit_ratio == null ? '—' : pct(a.chip.profit_ratio * 100, 1)}</td>
    <td class="num">${!a.pos || a.pos.pos == null ? '—' : fmt(a.pos.pos * 100, 0)}%</td>
    <td><div class="checks warn">${keys.map(([k, n]) => `<span class="ck ${a.checks[k] ? 'y' : 'n'}" title="${n}">${a.checks[k] ? '✓' : '·'}</span>`).join('')}</div></td>
    <td class="c-act"><button class="btn sm ghost" data-detail="${a.code}">详情</button></td>
  </tr>`).join('');
}

/* ================================================================ 历史检验 */
const REASON_CN = {
  '止盈': '涨到目标价', '止损': '跌到止损价', '时间止损': '拿太久了',
  '移动止盈': '从高点回落', '跌破均价线': '跌破平均成本', '持仓中': '还没卖',
};

// 「跌破MA{n}」是动态拼的（ma_exit 可调），光靠 REASON_CN 的固定映射兜不住，统一走这里
function rc(k) {
  const s = String(k == null ? '' : k);
  return /^跌破MA\d+$/.test(s) ? '跌破 ' + s.slice(5) + ' 日均线' : (REASON_CN[s] || s);
}

async function runBacktest() {
  if (S.busy.bt) return;
  S.busy.bt = true;
  const btn = $('#btn-bt');
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span>正在检验…';
  $('#bt-prog').hidden = false;
  try {
    const j = await api('/api/backtest', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        limit: +$('#bt-limit').value, mode: 'balanced',
        lookback: +$('#bt-lookback').value,
        codes: S.items.length ? S.items.slice(0, +$('#bt-limit').value).map(a => a.code) : null,
      }),
    });
    await pollJob(j.job.id, $('#bt-msg'), $('#bt-pct'), $('#bt-bar'));
    const r = await api('/api/job/result?id=' + encodeURIComponent(j.job.id));
    if (r.state !== 'done') throw new Error(r.error || '任务未完成');
    S.bt = r.result;
    renderBacktest();
    toast(`检验完成，一共 ${r.result.summary.count} 笔`);
  } catch (e) { toast('检验失败：' + e.message, true); }
  finally {
    S.busy.bt = false;
    btn.disabled = false; btn.innerHTML = '<i data-ic="play"></i>开始检验'; paintIcons(btn);
    setTimeout(() => { $('#bt-prog').hidden = true; }, 700);
  }
}

/** 没跑过时，把结果区（KPI、图表、卡片、明细表）换成一句说明，别留一片黑 */
function renderBtEmpty() {
  const has = !!(S.bt && S.bt.summary);
  const box = $('#bt-empty'); if (box) box.hidden = has;
  ['#bt-kpis', '#view-backtest .row2', '#bt-table'].forEach(sel => {
    const el = document.querySelector(sel);
    if (el) el.hidden = !has;
  });
  paintBtCharts();
}

function renderPfEmpty() {
  const has = !!(S.pf && S.pf.summary);
  const box = $('#pf-empty'); if (box) box.hidden = has;
  ['#pf-kpis', '#view-portfolio .row2', '#pf-table'].forEach(sel => {
    const el = document.querySelector(sel);
    if (el) el.hidden = !has;
  });
  paintPfCharts();
}

function renderBacktest() {
  const r = S.bt; if (!r) return;
  renderBtEmpty();
  const s = r.summary;
  const kb = $('#bt-kpis');
  kb.innerHTML = [
    { k: '一共几笔', v: s.count, s: s.open ? `已卖掉 ${s.closed} 笔 · 还有 ${s.open} 笔没到卖出条件` : `全部卖掉后结算 ${s.closed} 笔`, c: '' },
    { k: '多少笔赚钱', v: pct(s.win_rate, 1), s: `赚的比亏的多 ${s.profit_factor} 倍`, c: s.win_rate >= 50 ? 'up' : 'down' },
    { k: '平均一笔赚', v: (s.avg_ret > 0 ? '+' : '') + pct(s.avg_ret), s: `中间那个数 ${pct(s.med_ret)}`, c: s.avg_ret > 0 ? 'up' : 'down' },
    { k: '一笔笔累加', v: (s.pnl > 0 ? '+' : '') + pct(s.pnl), s: '假设每笔都用全部钱', c: s.pnl > 0 ? 'up' : 'down' },
    { k: '赚最多的一笔', v: '+' + pct(s.max_win), s: `亏最多的一笔 ${pct(s.max_loss)}`, c: 'up' },
    { k: '平均拿几天', v: s.avg_hold + '天', s: '交易日，不含周末', c: 'warn' },
  ].map(x => `<div class="kpi ${x.c}"><div class="k">${x.k}</div><div class="v">${x.v}</div><div class="s">${x.s}</div></div>`).join('');

  drawEquity($('#eq-chart'), s.curve);

  const rs = Object.entries(s.reasons || {});
  const maxr = Math.max(1, ...rs.map(x => x[1]));
  const totalr = rs.reduce((a, b) => a + b[1], 0) || 1;
  $('#reason-box').innerHTML = rs.length ? rs.map(([k, v]) => `
    <div class="rs"><span>${esc(rc(k))}</span><div class="rbar"><i style="width:${v / maxr * 100}%"></i></div><b>${v}</b></div>`).join('')
    + `<div class="hintline">一共 ${totalr} 笔卖掉了。「从高点回落」占比最高是正常的 —— 这套规则本来就靠跟着趋势走；如果「跌到止损价」一大片，说明信号本身质量不够，别急着上手。</div>`
    : '<div class="muted">还没有交易记录</div>';

  const tb = $('#tb-bt');
  const rows = r.trades || [];
  $('#bt-meta').textContent = `看了 ${r.scanned} 只 · 用时 ${r.elapsed}s · ${r.note}`;
  tb.innerHTML = rows.length ? rows.map(t => `<tr data-code="${t.code}">
    <td class="code">${t.signal_date}</td><td>${t.buy_date}</td><td class="num">${fmt(t.buy)}</td>
    <td>${t.sell_date}</td><td class="num">${fmt(t.sell)}</td><td class="num">${t.hold}</td>
    <td class="num ${cls(t.ret)}">${t.ret > 0 ? '+' : ''}${fmt(t.ret)}%</td>
    <td>${esc(rc(t.reason))}</td><td class="num">${fmt(t.profit_ratio, 1)}</td><td class="num">${fmt(t.pos, 1)}</td>
  </tr>`).join('') : '<tr class="empty"><td colspan="10">没有产生交易</td></tr>';
}

/* ================================================================ 模拟账户
   参考 QUANTAXIS 的 QIFI 账户思路：策略只负责产出「信号」，
   账户负责判断现金够不够、持仓满没满、扣多少手续费。
   这才是真实收益——逐笔复利曲线会高估，因为它假设每笔都能拿满全部资金。 */
async function runPortfolio() {
  if (S.busy.pf) return;
  S.busy.pf = true;
  const btn = $('#btn-pf');
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span>正在模拟…';
  $('#pf-prog').hidden = false;
  try {
    const lim = +$('#pf-limit').value;
    const j = await api('/api/portfolio', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        limit: lim, mode: 'balanced', lookback: +$('#pf-lookback').value,
        codes: S.items.length ? S.items.slice(0, lim).map(a => a.code) : null,
        initial_cash: +$('#pf-cash').value,
        max_pos: +$('#pf-maxpos').value,
        pos_pct: +$('#pf-pospct').value,
        slippage: +$('#pf-slip').value,
        commission: 0.00025, stamp: 0.001,
      }),
    });
    await pollJob(j.job.id, $('#pf-msg'), $('#pf-pct'), $('#pf-bar'));
    const r = await api('/api/job/result?id=' + encodeURIComponent(j.job.id));
    if (r.state !== 'done') throw new Error(r.error || '任务未完成');
    S.pf = r.result;
    renderPortfolio();
    toast(`模拟完成，一共成交 ${r.result.summary.trades} 笔`);
  } catch (e) { toast('模拟失败：' + e.message, true); }
  finally {
    S.busy.pf = false;
    btn.disabled = false; btn.innerHTML = '<i data-ic="play"></i>模拟一遍'; paintIcons(btn);
    setTimeout(() => { $('#pf-prog').hidden = true; }, 700);
  }
}

function money(v) {
  const a = Math.abs(v);
  if (a >= 1e8) return (v / 1e8).toFixed(2) + '亿';
  if (a >= 1e4) return (v / 1e4).toFixed(a >= 1e6 ? 0 : 1) + '万';
  return v.toFixed(0);
}

function renderPortfolio() {
  const r = S.pf; if (!r) return;
  renderPfEmpty();
  const s = r.summary || {};
  $('#pf-kpis').innerHTML = [
    { k: '总共赚了', v: (s.total_ret > 0 ? '+' : '') + pct(s.total_ret), s: `最后剩下 ${money(s.final_equity)} 元`, c: s.total_ret > 0 ? 'up' : 'down' },
    { k: '折成一年', v: (s.annual > 0 ? '+' : '') + pct(s.annual), s: `一共 ${s.days} 个交易日`, c: s.annual > 0 ? 'up' : 'down' },
    { k: '最难受的时候', v: pct(s.mdd), s: `相对风险的性价比 ${s.calmar}`, c: 'down' },
    { k: '收益波动性价比', v: String(s.sharpe), s: s.sharpe >= 1 ? '不错' : s.sharpe >= 0.5 ? '一般' : '偏低', c: s.sharpe >= 1 ? 'up' : 'warn' },
    { k: '多少笔赚钱', v: pct(s.win_rate, 1), s: `赚的比亏的多 ${s.profit_factor} 倍`, c: s.win_rate >= 50 ? 'up' : 'down' },
    { k: '成交笔数', v: s.trades, s: `因为没钱/满仓跳过 ${s.skipped} 次`, c: 'warn' },
  ].map(x => `<div class="kpi ${x.c}"><div class="k">${x.k}</div><div class="v">${x.v}</div><div class="s">${x.s}</div></div>`).join('');

  drawPtf($('#pf-chart'), r.curve);

  // 成本与资金占用
  const fees = (r.trades || []).reduce((a, t) => a + (t.fee || 0), 0);
  const util = s.util || 0;
  $('#pf-cost').innerHTML = `
    <div class="rs"><span>钱真正在用的时候</span><div class="rbar"><i style="width:${Math.min(100, util).toFixed(2)}%"></i></div><b>${util}%</b></div>
    <div class="rs"><span>手续费一共交了</span><div class="rbar"><i style="width:${Math.min(100, fees / Math.max(1, s.initial_cash) * 100 * 20).toFixed(2)}%"></i></div><b>${money(fees)}</b></div>
    <div class="pf-notes">
      <div><b>${s.taken}</b> 个信号真的买进了，<b>${s.skipped}</b> 个因为满仓 / 钱不够被跳过</div>
      <div>平均每笔拿 <b>${s.avg_hold}</b> 个交易日</div>
      <div class="hintline">「钱真正在用的时候」太低，说明信号太少、钱大部分时间躺着。要么放宽条件，要么减少同时持有的只数。</div>
    </div>`;

  const tr = r.trades || [];
  $('#pf-meta').textContent = `看了 ${r.scanned} 只 · 能买的信号 ${r.candidates} 个 · 用时 ${r.elapsed}s`;
  $('#tb-pf').innerHTML = tr.length ? tr.map(t => `<tr data-code="${t.code}">
    <td class="code">${t.code}</td><td>${esc(t.name || '')}</td>
    <td>${t.buy_date}</td><td>${t.sell_date}</td>
    <td class="num">${t.shares}</td>
    <td class="num">${money(t.buy_amt)}</td><td class="num">${money(t.sell_amt)}</td>
    <td class="num">${fmt(t.fee, 0)}</td>
    <td class="num ${cls(t.pnl)}">${t.pnl > 0 ? '+' : ''}${fmt(t.pnl, 0)}</td>
    <td class="num ${cls(t.ret_net)}">${t.ret_net > 0 ? '+' : ''}${fmt(t.ret_net)}%</td>
    <td>${esc(rc(t.reason || ''))}</td>
  </tr>`).join('') : '<tr class="empty"><td colspan="11">没有产生成交</td></tr>';
}

function drawPtf(cv, curve) {
  // curve 是相对初始资金的百分比 [[date, pct], ...]，与资金曲线同口径
  if (!cv) return;
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth || 600, H = 220;
  cv.width = W * dpr; cv.height = H * dpr; cv.style.height = H + 'px';
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  if (!curve || curve.length < 2) {
    g.fillStyle = T().txt3; g.font = '12px sans-serif'; g.textAlign = 'center';
    g.fillText('还没有数据', W / 2, H / 2); return;
  }
  const pts = curve.map(p => p[1]);
  const mn = Math.min(0, ...pts), mx = Math.max(0, ...pts);
  const span = (mx - mn) || 1;
  const pad = { l: 46, r: 12, t: 12, b: 20 };
  const w = W - pad.l - pad.r, h = H - pad.t - pad.b;
  const X = i => pad.l + (w * i) / (curve.length - 1);
  const Y = v => pad.t + h - (h * (v - mn)) / span;

  g.strokeStyle = T().line; g.lineWidth = 1;
  g.font = '10px monospace'; g.fillStyle = T().txt3; g.textAlign = 'right';
  for (let i = 0; i <= 4; i++) {
    const v = mn + span * i / 4, y = Y(v);
    g.beginPath(); g.moveTo(pad.l, y); g.lineTo(pad.l + w, y); g.stroke();
    g.fillText(v.toFixed(1) + '%', pad.l - 6, y + 3);
  }
  g.strokeStyle = T().line2; g.setLineDash([3, 3]);
  g.beginPath(); g.moveTo(pad.l, Y(0)); g.lineTo(pad.l + w, Y(0)); g.stroke();
  g.setLineDash([]);

  const up = pts[pts.length - 1] >= 0;
  const col = up ? T().up : T().down;
  const grd = g.createLinearGradient(0, pad.t, 0, pad.t + h);
  grd.addColorStop(0, alpha(col, 0.24));
  grd.addColorStop(1, alpha(col, 0.01));
  g.beginPath(); g.moveTo(X(0), Y(0));
  curve.forEach((p, i) => g.lineTo(X(i), Y(p[1])));
  g.lineTo(X(curve.length - 1), Y(0)); g.closePath();
  g.fillStyle = grd; g.fill();

  g.beginPath();
  curve.forEach((p, i) => i ? g.lineTo(X(i), Y(p[1])) : g.moveTo(X(i), Y(p[1])));
  g.strokeStyle = col; g.lineWidth = 1.8; g.lineJoin = 'round'; g.stroke();

  const li = curve.length - 1;
  g.beginPath(); g.arc(X(li), Y(pts[li]), 3, 0, 7); g.fillStyle = col; g.fill();
  g.textAlign = 'left'; g.font = '11px monospace'; g.fillStyle = col;
  g.fillText(pts[li].toFixed(2) + '%', Math.min(X(li) - 46, W - 62), Y(pts[li]) - 8);

  g.fillStyle = T().txt3; g.font = '10px monospace';
  g.textAlign = 'left'; g.fillText(curve[0][0], pad.l, H - 5);
  g.textAlign = 'right'; g.fillText(curve[li][0], pad.l + w, H - 5);
}

function drawEquity(cv, curve) {
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth || 600, H = 220;
  cv.width = W * dpr; cv.height = H * dpr;
  cv.style.height = H + 'px';
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  if (!curve || curve.length < 2) {
    g.fillStyle = T().txt3; g.font = '12px sans-serif'; g.textAlign = 'center';
    g.fillText('还没有交易，没东西可画', W / 2, H / 2); return;
  }
  // 合并同日多笔
  const pts = curve.map(p => p[1]);
  const mn = Math.min(0, ...pts), mx = Math.max(0, ...pts);
  const pad = { l: 44, r: 10, t: 12, b: 20 };
  const w = W - pad.l - pad.r, h = H - pad.t - pad.b;
  const X = i => pad.l + (w * i) / (curve.length - 1);
  const Y = v => pad.t + h - (h * (v - mn)) / (mx - mn || 1);
  // 网格
  g.strokeStyle = T().line; g.lineWidth = 1;
  g.font = '10px monospace'; g.fillStyle = T().txt3; g.textAlign = 'right';
  for (let i = 0; i <= 4; i++) {
    const v = mn + (mx - mn) * i / 4, y = Y(v);
    g.beginPath(); g.moveTo(pad.l, y); g.lineTo(pad.l + w, y); g.stroke();
    g.fillText(v.toFixed(0) + '%', pad.l - 6, y + 3);
  }
  // 零轴
  g.strokeStyle = T().line2; g.setLineDash([3, 3]);
  g.beginPath(); g.moveTo(pad.l, Y(0)); g.lineTo(pad.l + w, Y(0)); g.stroke();
  g.setLineDash([]);
  // 面积
  const grd = g.createLinearGradient(0, pad.t, 0, pad.t + h);
  grd.addColorStop(0, alpha(T().ok, 0.26));
  grd.addColorStop(1, alpha(T().ok, 0.01));
  g.beginPath(); g.moveTo(X(0), Y(0));
  curve.forEach((p, i) => g.lineTo(X(i), Y(p[1])));
  g.lineTo(X(curve.length - 1), Y(0)); g.closePath();
  g.fillStyle = grd; g.fill();
  // 线
  g.beginPath();
  curve.forEach((p, i) => i ? g.lineTo(X(i), Y(p[1])) : g.moveTo(X(i), Y(p[1])));
  g.strokeStyle = T().ok; g.lineWidth = 1.8; g.lineJoin = 'round'; g.stroke();
  // 末点
  const li = curve.length - 1;
  g.beginPath(); g.arc(X(li), Y(curve[li][1]), 3, 0, 7); g.fillStyle = T().ok; g.fill();
  g.textAlign = 'left'; g.fillStyle = T().ok; g.font = '11px monospace';
  g.fillText(curve[li][1].toFixed(1) + '%', X(li) - 34, Y(curve[li][1]) - 8);
  // 日期
  g.fillStyle = T().txt3; g.font = '10px monospace';
  g.textAlign = 'left'; g.fillText(curve[0][0], pad.l, H - 5);
  g.textAlign = 'right'; g.fillText(curve[li][0], pad.l + w, H - 5);
}

/* ================================================================ 详情抽屉 */
async function openDetail(code) {
  const dw = $('#drawer');
  dw.classList.add('show'); $('#mask').classList.add('show');
  $('#dw-name').textContent = '加载中…'; $('#dw-code').textContent = code;
  $('#dw-price').textContent = '—'; $('#dw-chg').textContent = ''; $('#dw-date').textContent = '';
  $('#dw-body').innerHTML = '<div class="dw-sec" style="text-align:center;padding:40px"><span class="spin"></span> 正在算这只股票的五个条件…</div>';
  try {
    const r = await api('/api/detail?code=' + code);
    renderDetail(r.data);
  } catch (e) {
    $('#dw-body').innerHTML = `<div class="dw-sec" style="color:var(--bad)">没能加载出来：${esc(e.message)}（可能是网络或行情源临时不通，等一下再点）</div>`;
  }
}
function closeDrawer() {
  $('#drawer').classList.remove('show');
  $('#mask').classList.remove('show');
}

/* 技术指标面板（口径参考 QUANTAXIS QAIndicator / 通达信公式）——
   这一块是给想看细节的人准备的，全部用人话标注，不懂可以直接跳过。 */
function taBlock(t) {
  if (!t || !t.ma) return '';
  const m = t.ma || {}, mac = t.macd || {}, kd = t.kdj || {}, rs = t.rsi || {}, bo = t.boll || {}, at = t.atr || {};
  const tags = (t.tags || []).map(x => `<span class="tat">${esc(x)}</span>`).join('');
  const macCol = (mac.hist || 0) >= 0 ? 'up' : 'down';
  return `
    <div class="dw-sec">
      <h4>③ 技术指标（不懂可以跳过） <span class="spacer"></span><span class="muted">和通达信算的一样</span></h4>
      <div class="mini">
        <div class="mi"><div class="k">MACD 快慢线</div><div class="v ${macCol}" style="font-size:12.5px">${fmt(mac.dif, 2)} / ${fmt(mac.dea, 2)}</div></div>
        <div class="mi"><div class="k">MACD 柱子</div><div class="v ${macCol}">${fmt(mac.hist, 2)}</div></div>
        <div class="mi"><div class="k">KDJ（K / D）</div><div class="v" style="font-size:12.5px">${fmt(kd.k, 1)} / ${fmt(kd.d, 1)}</div></div>
        <div class="mi"><div class="k">RSI 强弱 6 / 14</div><div class="v" style="font-size:12.5px">${fmt(rs.r6, 1)} / ${fmt(rs.r14, 1)}</div></div>
        <div class="mi"><div class="k">在布林带的位置</div><div class="v">${pct(bo.pos, 0)}</div></div>
        <div class="mi"><div class="k">一天平均波动</div><div class="v">${fmt(at.pct, 2)}%</div></div>
      </div>
      <div class="tat-wrap">${tags || '<span class="muted" style="font-size:12px">这时候没什么特别的技术特征</span>'}</div>
      <div class="hintline">5 日均线 ${fmt(m.ma5)} · 10 日均线 ${fmt(m.ma10)} · 20 日均线 ${fmt(m.ma20)} · 60 日均线 ${fmt(m.ma60)}；KDJ 里的 J ${fmt(kd.j, 1)}；布林带上 ${fmt(bo.up)} / 中 ${fmt(bo.mid)} / 下 ${fmt(bo.dn)}（价格离上边越近越"贵"）。</div>
    </div>`;
}

function renderDetail(a) {
  S.detail = a;
  $('#dw-name').textContent = a.name || '';
  $('#dw-code').textContent = a.code;
  $('#dw-price').textContent = fmt(a.price);
  const ch = $('#dw-chg');
  ch.textContent = a.chg_pct == null ? '' : (a.chg_pct > 0 ? '+' : '') + fmt(a.chg_pct) + '%';
  ch.className = cls(a.chg_pct);
  // a.date 是分时数据的最后一天，盘前可能是空串/昨天；stock_date 是这根日线本身的日期，更可靠
  const sd = a.stock_date || a.date || '';
  $('#dw-date').textContent = sd;

  const c = a.checks;
  const plan = a.plan || {};
  // 用和这次名单同一套口径，别自己另判一套（否则会"判成符合、明细里全是✗"）
  const pa = pickAvg(a);
  const tailMode = pa.tail;
  const lab = pa.lab;
  const streakVal = pa.streak;
  const keys = [['ma', '价格站在成本上'], ['chip', '套牢盘少'], ['pos', '价格低'], ['bottom', '底部横着走'], ['trend', '趋势向上']];
  // 每条没过的给出原因，别只打个 ✗ 让人猜（阈值取用户实际设置的参数）
  const P = (S.cfg && S.cfg.params) || {};
  const chipCap = fmt(+(P.profit_cap ?? 0.25) * 100, 0);
  const posCap = fmt(+(P.pos_cap ?? 0.30) * 100, 0);
  const why = {
    ma: tailMode ? `${lab} 时价格没站在平均成本上方` : '收盘价没站在平均成本（分时黄线）上方',
    chip: `上方套牢盘 ${a.chip && a.chip.profit_ratio != null ? pct(a.chip.profit_ratio * 100, 1) : '—'}，要求 ≤ ${chipCap}%`,
    pos: `价格在 120 天区间的 ${a.pos && a.pos.pos != null ? fmt(a.pos.pos * 100, 0) + '%' : '—'} 位置，要求 ≤ ${posCap}%`,
    bottom: a.bottom && a.bottom.ok === false ? (a.bottom.note || '最近不是横盘') : '最近不是底部横盘',
    trend: `价在 ${a.trend && a.trend.period ? a.trend.period : 20} 日均线下方`,
  };
  const det = pa.detail;
  const days = det.map(d => `
    <div class="drow">
      <span class="dt">${d.date.slice(5)}</span>
      <span class="dv">${lab === '收盘' ? '收' : lab} ${fmt(d.close)}</span>
      <span class="dv">平均成本 ${fmt(d.avg)}</span>
      <span class="dp ${d.ok ? 'ok' : 'no'}">${d.surplus > 0 ? '+' : ''}${fmt(d.surplus)}% ${d.ok ? '✓' : '✗'}</span>
    </div>`).join('');

  $('#dw-body').innerHTML = `
    <div class="dw-sec">
      <h4>五个条件逐条看
        <span class="spacer"></span>
        <span class="chip ${c.ma && c.chip && c.pos ? 'warn' : ''}">${keys.filter(([k]) => c[k]).length}/5 条符合</span>
      </h4>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px">
        ${keys.map(([k, n]) => `<span class="ck ${c[k] ? 'y' : 'n'}" title="${esc(c[k] ? '这一条符合' : why[k])}" style="width:auto;padding:0 9px;border-radius:6px">${c[k] ? '✓' : '✗'} ${n}</span>`).join('')}
      </div>
      <div class="mini">
        <div class="mi"><div class="k">把握度</div><div class="v" style="color:${a.score >= 75 ? 'var(--ok)' : a.score >= 50 ? 'var(--accent-2)' : 'var(--gold)'}">${fmt(a.score, 1)}</div></div>
        <div class="mi"><div class="k">连着强于平均成本${tailMode ? '（按' + lab + '算）' : ''}</div><div class="v">${streakVal}<small style="font-size:11px;color:var(--txt-3)"> 天</small></div></div>
        <div class="mi"><div class="k">今天的平均成本</div><div class="v">${fmt(a.avg.today_avg)}</div></div>
        <div class="mi"><div class="k">现价比平均成本 ${tailMode ? (lab + ' ') : ''}高出</div><div class="v ${((tailMode ? a.avg.tail_surplus : a.avg.today_surplus) || 0) >= 0 ? 'up' : 'down'}">${(() => { const v = tailMode ? a.avg.tail_surplus : a.avg.today_surplus; return v == null ? '—' : (v > 0 ? '+' : '') + fmt(v) + '%'; })()}</div></div>
      </div>
      <div class="days">${days}</div>
      <div class="hintline">平均成本（也就是分时图上的黄线）= 当天累计成交额 ÷ 累计成交量，代表当天大家平均花的钱。价格一直站在黄线上方，说明后面进场的人比平均成本还肯出价，是有人在持续买的迹象。${tailMode ? `这里逐日比较的是 ${lab} 那一刻的价格和截至 ${lab} 的平均成本 —— 你是那个时候下单的，全天算完的平均成本你用不上。` : ''}</div>
    </div>

    <div class="dw-sec">
      <h4>② 筹码压在哪些价位 <span class="spacer"></span><span class="muted">${a.chip.real_turnover ? `按真实换手率估算 · 日均换手 ${pct((a.chip.avg_turnover || 0) * 100, 2)}` : '按换手衰减估算'}</span></h4>
      <div class="mini">
        <div class="mi"><div class="k">上方套牢盘</div><div class="v ${a.chip.profit_ratio <= 0.25 ? 'down' : 'up'}">${a.chip.profit_ratio == null ? '—' : pct(a.chip.profit_ratio * 100, 1)}</div></div>
        <div class="mi"><div class="k">大家的平均成本</div><div class="v">${fmt(a.chip.avg_cost)}</div></div>
        <div class="mi"><div class="k">价格在 120 天区间的位置</div><div class="v">${a.pos.pos == null ? '—' : pct(a.pos.pos * 100, 0)}</div></div>
        <div class="mi"><div class="k">离 120 天最高点</div><div class="v down">${a.pos.drawdown == null ? '—' : fmt(a.pos.drawdown, 1) + '%'}</div></div>
        <div class="mi"><div class="k">九成筹码落在</div><div class="v" style="font-size:12px">${fmt(a.chip.cost_5)} ~ ${fmt(a.chip.cost_95)}</div></div>
        <div class="mi"><div class="k">近 20 天波动</div><div class="v ${a.bottom.ok === false ? 'up' : ''}">${a.bottom.amp == null ? '—' : pct(a.bottom.amp * 100, 1)}</div></div>
      </div>
      <canvas id="chip-cv" class="kline" style="margin-top:9px" height="150"></canvas>
      <div class="hintline">横条表示不同价位上还压着多少筹码：<b>蓝色</b>是低于现价的（已经赚钱的人），<b>灰色</b>是高于现价的（被套着的人）。灰色越短，往上走时承压越小；黄色虚线是现在的价格。</div>
    </div>

    ${taBlock(a.ta)}

    <div class="dw-sec">
      <h4>日线走势 <span class="spacer"></span>
        <span class="tabs"><button class="tab active" data-tab="day">日线</button><button class="tab" data-tab="intraday">今天分时</button></span>
      </h4>
      <canvas id="k-cv" class="kline" height="260"></canvas>
      <div class="hintline" id="k-note"></div>
    </div>

    <div class="dw-sec">
      <h4>怎么买、怎么卖 <span class="spacer"></span><span class="muted">仅供参考，不构成投资建议</span></h4>
      <div class="mini">
        <div class="mi"><div class="k">买在</div><div class="v" style="font-size:13px;white-space:nowrap">${fmt(a.price)}<small style="font-size:10.5px;color:var(--txt-3)"> 附近</small></div></div>
        <div class="mi"><div class="k">跌到这里止损</div><div class="v down">${fmt(plan.stop)} <small style="font-size:11px;color:var(--txt-3)">${fmt(plan.stop_pct, 1)}%</small></div></div>
        <div class="mi"><div class="k">目标价（够高才值得做）</div><div class="v up">${fmt(plan.target)} <small style="font-size:11px;color:var(--txt-3)">+${fmt(plan.target_pct, 1)}%</small></div></div>
        <div class="mi"><div class="k">赚赔比</div><div class="v">${fmt(plan.rr, 2)} : 1</div></div>
        <div class="mi"><div class="k">建议投入</div><div class="v">${plan.position_pct}%</div></div>
        <div class="mi"><div class="k">20 日均线</div><div class="v">${fmt(a.trend.ma20)}</div></div>
      </div>
      <div class="hintline">
        <b style="color:var(--txt)">什么时候买：</b>当天<b style="color:var(--txt)">尾盘（${lab} 之后）</b>确认价格还站在平均成本上方，再下单，别等到收盘后 —— 收盘价好看往往第二天就低开。<br>
        <b style="color:var(--txt)">什么时候认错：</b>收盘跌破 <b style="color:var(--down)">${fmt(plan.stop)}</b>（比现价低 ${Math.abs(plan.stop_pct)}%），或者连续两天收盘落到当天平均成本下面，说明判断错了，走人。<br>
        <b style="color:var(--txt)">什么时候下车：</b>赚到 +5% 之后开始盯最高点，从最高点回落 7% 就清仓；最多拿 10 个交易日，不涨也走。上面的「目标价」用来衡量这单值不值得做（赚赔比 ≥ 1.5 才算够）。
        ${plan.ok ? '' : '<br><b style="color:var(--warn)">提示：</b>' + esc(plan.note || '')}
      </div>
    </div>

    <div class="dw-sec">
      <h4>这只股票过去出现过 ${(a.history && a.history.length) || 0} 次同样的信号 <span class="spacer"></span><span class="muted">近 250 个交易日</span></h4>
      ${(a.history && a.history.length) ? `<table class="htbl">
        <thead><tr><th>信号日</th><th>买入日</th><th class="num">买价</th><th>卖出日</th><th class="num">卖价</th><th class="num">赚了多少</th><th>为什么卖</th></tr></thead>
        <tbody>${a.history.map(t => `<tr><td>${t.signal_date}</td><td>${t.buy_date}</td><td class="num">${fmt(t.buy)}</td>
          <td>${t.sell_date}</td><td class="num">${fmt(t.sell)}</td>
          <td class="num ${cls(t.ret)}">${t.ret > 0 ? '+' : ''}${fmt(t.ret)}%</td><td>${esc(rc(t.reason))}</td></tr>`).join('')}</tbody>
      </table>` : '<div class="muted">近 250 个交易日没出现过同样的信号</div>'}
    </div>`;

  drawChip($('#chip-cv'), a);
  drawKline($('#k-cv'), a, 'day');
  $('#k-note').textContent = '红涨绿跌；蓝线是 5 日均线，金线是 20 日均线。近 180 个交易日。';
  $$('.tab').forEach(b => b.onclick = () => {
    $$('.tab').forEach(x => x.classList.toggle('active', x === b));
    drawKline($('#k-cv'), a, b.dataset.tab);
    $('#k-note').textContent = b.dataset.tab === 'day'
      ? '红涨绿跌；蓝线是 5 日均线，金线是 20 日均线。近 180 个交易日。'
      : '白线是价格，青线是平均成本（当天累计成交额÷累计成交量）；白线一直在青线上方，说明今天进场的人成本更低、在持续买。';
  });
}

function drawChip(cv, a) {
  if (!cv) return;
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth || 700, H = 150;
  cv.width = W * dpr; cv.height = H * dpr; cv.style.height = H + 'px';
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  const chips = a.chip.chips || [];
  if (!chips.length) { g.fillStyle = T().txt3; g.fillText('这只股票没有筹码数据', 10, 20); return; }
  const price = a.price;
  const lo = Math.min(...chips.map(c => c[0])), hi = Math.max(...chips.map(c => c[0]));
  const maxp = Math.max(...chips.map(c => c[1])) || 1;
  const pad = { l: 8, r: 60, t: 8, b: 16 };
  const w = W - pad.l - pad.r, h = H - pad.t - pad.b;
  const Y = p => pad.t + h - h * (p - lo) / (hi - lo || 1);
  chips.forEach(c => {
    const y = Y(c[0]), bh = Math.max(1.6, h / chips.length - 1);
    const bw = w * c[1] / maxp;
    g.fillStyle = c[0] < price ? alpha(T().up, 0.5) : alpha(T().txt3, 0.45);
    g.fillRect(pad.l, y - bh, bw, bh);
  });
  // 现价线
  const yp = Y(price);
  g.strokeStyle = T().gold; g.setLineDash([4, 3]); g.lineWidth = 1;
  g.beginPath(); g.moveTo(pad.l, yp); g.lineTo(pad.l + w, yp); g.stroke(); g.setLineDash([]);
  g.fillStyle = T().gold; g.font = '10.5px monospace'; g.textAlign = 'left';
  g.fillText('现价 ' + fmt(price), pad.l + w + 5, yp + 3);
  // 坐标
  g.fillStyle = T().txt3; g.font = '10px monospace';
  g.fillText(fmt(hi), pad.l + w + 5, pad.t + 9);
  g.fillText(fmt(lo), pad.l + w + 5, pad.t + h);
  g.fillStyle = alpha(T().up, 0.8);
  g.fillText(`上方套牢盘 ${pct((a.chip.profit_ratio || 0) * 100, 1)}`, pad.l + 4, pad.t + 10);
}

function drawKline(cv, a, tab) {
  if (!cv) return;
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth || 700, H = 260;
  cv.width = W * dpr; cv.height = H * dpr; cv.style.height = H + 'px';
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  if (tab === 'intraday') {
    const pts = (a.intraday && a.intraday.points) || [];
    const avg = (a.intraday && a.intraday.avg) || [];
    if (!pts.length) { g.fillStyle = T().txt3; g.font = '12px sans-serif'; g.fillText('今天还没有分时数据（没开盘或休市）', 12, 24); return; }
    const prices = pts.map(p => p[1]).concat(avg);
    const lo = Math.min(...prices), hi = Math.max(...prices);
    const pad = { l: 8, r: 56, t: 10, b: 18 };
    const w = W - pad.l - pad.r, h = H - pad.t - pad.b;
    const X = i => pad.l + w * i / (pts.length - 1);
    const Y = v => pad.t + h - h * (v - lo) / (hi - lo || 1);
    g.strokeStyle = T().line;
    for (let i = 0; i <= 4; i++) { const y = pad.t + h * i / 4; g.beginPath(); g.moveTo(pad.l, y); g.lineTo(pad.l + w, y); g.stroke(); }
    // 平均成本线（分时黄线）
    g.beginPath(); avg.forEach((v, i) => i ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v)));
    g.strokeStyle = T().ok; g.lineWidth = 1.4; g.stroke();
    // 价格
    g.beginPath(); pts.forEach((p, i) => i ? g.lineTo(X(i), Y(p[1])) : g.moveTo(X(i), Y(p[1])));
    g.strokeStyle = T().txt; g.lineWidth = 1.4; g.stroke();
    g.fillStyle = T().txt3; g.font = '10px monospace';
    g.textAlign = 'left'; g.fillText(fmt(hi), pad.l + w + 5, pad.t + 9);
    g.fillText(fmt(lo), pad.l + w + 5, pad.t + h);
    g.fillText('09:30', pad.l, H - 5);
    g.textAlign = 'right'; g.fillText('15:00', pad.l + w, H - 5);
    return;
  }
  const d = a.daily || [];
  if (!d.length) { g.fillStyle = T().txt3; g.font = '12px sans-serif'; g.fillText('这只股票没有日线数据', 12, 24); return; }
  const pad = { l: 8, r: 56, t: 10, b: 18 };
  const w = W - pad.l - pad.r, h = H - pad.t - pad.b;
  const hi = Math.max(...d.map(x => x.high)), lo = Math.min(...d.map(x => x.low));
  const Y = v => pad.t + h - h * (v - lo) / (hi - lo || 1);
  const bw = Math.max(1.2, w / d.length - 1);
  const X = i => pad.l + (w * i) / d.length + bw / 2;
  g.strokeStyle = T().line;
  for (let i = 0; i <= 4; i++) { const y = pad.t + h * i / 4; g.beginPath(); g.moveTo(pad.l, y); g.lineTo(pad.l + w, y); g.stroke(); }
  d.forEach((k, i) => {
    const up = k.close >= k.open;
    g.strokeStyle = g.fillStyle = up ? T().up : T().down;
    const x = X(i);
    g.beginPath(); g.moveTo(x, Y(k.high)); g.lineTo(x, Y(k.low)); g.stroke();
    const y1 = Y(Math.max(k.open, k.close)), y2 = Y(Math.min(k.open, k.close));
    g.fillRect(x - bw / 2, y1, bw, Math.max(1, y2 - y1));
  });
  [['ma5', T().accentSoft], ['ma20', T().gold]].forEach(([f, col]) => {
    g.beginPath(); let started = false;
    d.forEach((k, i) => {
      if (k[f] == null) return;
      started ? g.lineTo(X(i), Y(k[f])) : (g.moveTo(X(i), Y(k[f])), started = true);
    });
    g.strokeStyle = col; g.lineWidth = 1.2; g.stroke();
  });
  g.fillStyle = T().txt3; g.font = '10px monospace';
  g.textAlign = 'left'; g.fillText(fmt(hi), pad.l + w + 5, pad.t + 9);
  g.fillText(fmt(lo), pad.l + w + 5, pad.t + h);
  g.fillText(d[0].date, pad.l, H - 5);
  g.textAlign = 'right'; g.fillText(d[d.length - 1].date, pad.l + w, H - 5);
}

/* ================================================================ 设置 */
const SET_META = [
  { id: 'auto', title: '自动选股', tag: 'AUTO', fields: [
    { k: 'auto_scan', n: '打开软件就自动选股', t: 'bool', hint: '不用再手动点，软件自己按时间跑' },
    { k: 'auto_limit', n: '每次看多少只', t: 'int', min: 100, max: 6000, hint: '600 ≈ 40 秒；6000 ≈ 8 分钟' },
    { k: 'auto_hours', n: '几点到几点干活', t: 'text', hint: '例如 09:35-15:00' },
    { k: 'auto_every', n: '隔多久看一次（秒）', t: 'int', min: 60, max: 3600, hint: '300 = 每 5 分钟' },
    { k: 'auto_final_enabled', n: '尾盘最后确认一次', t: 'bool', hint: '每天收盘前再跑一遍，给出最终名单' },
    { k: 'auto_final', n: '最后确认的时间', t: 'text', hint: '默认 14:50' },
    { k: 'preview_at', n: '下午几点开始提前试算', t: 'select', opts: [['14:00', '14:00 开始'], ['14:10', '14:10 开始'], ['off', '不试算']], hint: '14:30 之前先用"截至现在"的价格算一遍，让你提前知道哪几只值得盯；最终以 14:30 的结果为准' },
    { k: 'workers', n: '同时开几个线程去抓', t: 'int', min: 8, max: 96, hint: '越大越快，但太快会被行情源限速（默认 48）' },
  ]},
  { id: 'avg', title: '① 价格和平均成本的关系', tag: '核心', fields: [
    { k: 'entry_mode', n: '拿什么价格去比', t: 'select', opts: [['tail', '尾盘价（推荐，和你实际下单一致）'], ['close', '收盘价（只有想复现老口径时才用，等于提前知道收盘）']], hint: '尾盘买入要用尾盘价，不然等于偷看未来' },
    { k: 'tail_from', n: '在几点判定', t: 'select', opts: [['14:30', '14:30（推荐）'], ['14:45', '14:45'], ['14:57', '14:57'], ['close', '收盘']] },
    { k: 'ma_days', n: '要连续几天都站上', t: 'int', min: 1, max: 10, hint: '默认 3 天' },
    { k: 'ma_ratio', n: '高出多少才算站上', t: 'float', step: 0.0005, min: 0.99, max: 1.05, hint: '1.0 = 平着也算；1.002 = 要高 0.2%' },
    { k: 'ma_tol', n: '允许几天不达标', t: 'int', min: 0, max: 3, hint: '0 = 一天都不能差' },
  ]},
  { id: 'chip', title: '② 上方没什么套牢盘', tag: '核心', fields: [
    { k: 'real_turnover', n: '按真实换手算（推荐）', t: 'bool', hint: '换手多的一天，老筹码就被冲掉得多，比拍系数准' },
    { k: 'turnover_intensity', n: '换手强度', t: 'float', step: 0.1, min: 0.3, max: 3, hint: '1.0 = 今天换手多少就冲掉多少旧筹码' },
    { k: 'chip_window', n: '往回看多少天', t: 'int', min: 30, max: 250, hint: '交易日数' },
    { k: 'chip_bins', n: '价位切多细', t: 'int', min: 20, max: 120, hint: '越细图越平滑' },
    { k: 'chip_decay', n: '老筹码遗忘速度', t: 'float', step: 0.005, min: 0.5, max: 1.0, hint: '只有关掉上面那项时才生效' },
    { k: 'profit_cap', n: '套牢盘最多能有多少', t: 'pct', min: 0, max: 1, step: 0.01, hint: '超过这个数就不要（默认 25%）' },
  ]},
  { id: 'pos', title: '③ 价格在低位', tag: '核心', note: '把最近 120 天的最高价和最低价拉一条线，看现价站在哪。0% = 正好是区间最低，100% = 正好是最高。<b>只买下面三成的位置</b> —— 不是因为它一定涨，而是跌无可跌，往下空间小、往上空间大。', fields: [
    { k: 'pos_cap', n: '价格在区间的位置最多到哪', t: 'pct', min: 0, max: 1, step: 0.01, hint: '默认 30%。调大能多选出票，但会买到已经涨起来' },
  ]},
  { id: 'bottom', title: '④ 底部横着走', tag: '过滤', note: '横盘 = 有人在同一个价位反复接货，卖的人已经卖得差不多了。<b>但下跌中途的小平台也长这样</b>，所以同时限住波动和斜率两个方向。', fields: [
    { k: 'bottom_enable', n: '启用这一关', t: 'bool' },
    { k: 'bottom_days', n: '看最近多少天', t: 'int', min: 5, max: 60 },
    { k: 'bottom_amp', n: '波动最大多少', t: 'pct', min: 0.04, max: 0.6, step: 0.01, hint: '最高价 ÷ 最低价 − 1 的上限（默认 40%）' },
    { k: 'bottom_slope', n: '允许单边走多少', t: 'float', step: 0.01, min: 0, max: 0.5, hint: '20 天回归斜率上限，越大越能接受已经在慢慢涨的（默认 0.12）' },
  ]},
  { id: 'trend', title: '⑤ 还在 20 日均线上', tag: '默认关', note: '<b>默认关着</b>：它和"价格在低位"天然矛盾 —— 真正在低位的股票，绝大多数已经在 20 日均线下方了。打开就基本选不出票，所以只在你想要极严格的时候开。', fields: [
    { k: 'ma_trend_enable', n: '启用这一关', t: 'bool', hint: '默认关。它和"价格在低位"天然矛盾 —— 真在低位的股票常常在 20 日均线下方，一开就基本选不出票' },
    { k: 'ma_trend_period', n: '用几日均线', t: 'int', min: 5, max: 120, hint: '上面那项打开才生效（默认 20）' },
  ]},
  { id: 'filter', title: '⑥ 先筛掉哪些股票', tag: '过滤', fields: [
    { k: 'min_price', n: '最低股价（元）', t: 'float', step: 0.1, hint: '太便宜的多半有问题' },
    { k: 'max_price', n: '最高股价（元）', t: 'float', step: 1, hint: '太贵的钱不够分配' },
    { k: 'exclude_st', n: '不要 ST / 要退市的', t: 'bool', hint: '这类股票随时可能退市，别碰' },
    { k: 'exclude_kcb', n: '不要科创板（688）', t: 'bool' },
    { k: 'exclude_cyb', n: '不要创业板（300/301）', t: 'bool' },
    { k: 'exclude_bj', n: '不要北交所', t: 'bool' },
    { k: 'exclude_new', n: '上市不满多少天不要', t: 'int', min: 0, max: 500, hint: '新股走势没参考价值，0 = 不过滤（默认 60 个交易日）' },
    { k: 'min_turnover_amt', n: '成交额低于多少不要（元）', t: 'float', step: 1000000, hint: '0 = 不限。想避开没人交易的僵尸股，填 50000000（五千万）' },
  ]},
  { id: 'trade', title: '⑦ 怎么买、怎么卖', tag: '交易', fields: [
    { k: 'buy_rule', n: '按什么价格成交（回测/模拟时用）', t: 'select', opts: [['pullback', '便宜一点才买（当前默认）'], ['same_day_tail', '当天尾盘就买'], ['next_open', '第二天开盘买'], ['next_open_break', '第二天突破昨天高点买']], hint: '只影响历史检验和模拟账户怎么算成交价；实盘怎么下单由你看着那个尾盘信号自己决定' },
    { k: 'buy_pullback', n: '便宜多少才买', t: 'pct', min: 0, max: 0.05, step: 0.002, hint: '等到收盘价 ×(1+这个数) 才动手' },
    { k: 'buy_chase_max', n: '高开超过多少就不追', t: 'pct', min: 0.01, max: 0.1, step: 0.005, hint: '第二天一开盘就涨太多，说明追不划算' },
    { k: 'stop_loss', n: '亏多少就走（上限）', t: 'pct', min: 0.02, max: 0.2, step: 0.005, hint: '实际止损取「这个幅度 / 平均成本线 / 20 日低点」里最近的那个' },
    { k: 'min_stop', n: '止损至少离现价多远', t: 'pct', min: 0.005, max: 0.08, step: 0.005, hint: '默认 2.5%。止损贴太近会被一天内的正常抖动打掉 —— 这是"买进去就拿得住"的关键一项' },
    { k: 'take_profit', n: '涨到多少算目标价', t: 'pct', min: 0.03, max: 0.5, step: 0.005, hint: '只有「赚了以后怎么卖」选"到目标价就卖"时才用；默认那套是靠回落离场' },
    { k: 'sell_mode', n: '赚了以后怎么卖', t: 'select', opts: [['atr', '从最高点回落就卖（推荐）'], ['fixed', '到目标价就卖']], hint: '推荐方式能让盈利继续跑一会儿' },
    { k: 'trail_drawdown', n: '从最高点跌多少就全卖', t: 'pct', min: 0.02, max: 0.2, step: 0.005 },
    { k: 'max_hold', n: '最多拿几天', t: 'int', min: 1, max: 60, hint: '到时间不管赚亏都走' },
    { k: 'ma_exit', n: '跌破几日均线就卖（0 = 不管）', t: 'int', min: 0, max: 120 },
  ]},
  { id: 'weight', title: '⑧ 把握度怎么算', tag: '打分', fields: [
    { k: 'w_surplus', n: '价格比平均成本高多少', t: 'float', step: 1, min: 0, max: 100, weight: 'surplus', hint: '高得越多，说明买的人越急' },
    { k: 'w_profit', n: '上方套牢盘有多少', t: 'float', step: 1, min: 0, max: 100, weight: 'profit', hint: '套牢盘越少，往上走阻力越小' },
    { k: 'w_position', n: '价格有多低', t: 'float', step: 1, min: 0, max: 100, weight: 'position', hint: '越低越安全' },
    { k: 'w_bottom', n: '底部横得好不好', t: 'float', step: 1, min: 0, max: 100, weight: 'bottom', hint: '横得越久越稳' },
    { k: 'w_trend', n: '大趋势好不好', t: 'float', step: 1, min: 0, max: 100, weight: 'trend', hint: '在 20 日均线上方加分' },
  ]},
];

function renderSettings() {
  if (!S.cfg) return;
  const p = S.cfg.params, w = S.cfg.weights;
  $('#set-grid').innerHTML = SET_META.map(cat => `
    <div class="set-card">
      <h3>${cat.title}<em>${cat.tag}</em></h3>
      ${cat.fields.map(f => {
        const val = f.weight ? w[f.weight] : p[f.k];
        if (f.t === 'bool') {
          return `<div class="frow"><label>${f.n}</label>
            <button class="toggle ${val ? 'on' : ''}" data-k="${f.k}" data-t="bool"></button></div>`;
        }
        if (f.t === 'select') {
          return `<div class="frow"><label>${f.n}${f.hint ? `<small>${f.hint}</small>` : ''}</label>
            <select data-k="${f.k}" data-t="str">${f.opts.map(o => `<option value="${o[0]}" ${o[0] == val ? 'selected' : ''}>${o[1]}</option>`).join('')}</select></div>`;
        }
        if (f.t === 'text') {
          return `<div class="frow"><label>${f.n}${f.hint ? `<small>${f.hint}</small>` : ''}</label>
            <input type="text" data-k="${f.k}" data-t="str" value="${String(val ?? '')}" /></div>`;
        }
        const step = f.step || (f.t === 'int' ? 1 : 0.01);
        return `<div class="frow"><label>${f.n}${f.hint ? `<small>${f.hint}</small>` : ''}</label>
          <input type="number" data-k="${f.k}" data-t="${f.t}" data-weight="${f.weight || ''}"
            value="${f.t === 'pct' ? (val * 100).toFixed(2) : val}" step="${f.t === 'pct' ? step * 100 : step}"
            ${f.min !== undefined ? `min="${f.t === 'pct' ? f.min * 100 : f.min}"` : ''}
            ${f.max !== undefined ? `max="${f.t === 'pct' ? f.max * 100 : f.max}"` : ''} /></div>`;
      }).join('')}
      ${cat.note ? `<p class="sc-note">${cat.note}</p>` : ''}
    </div>`).join('');

  $$('#set-grid .toggle').forEach(b => b.onclick = () => b.classList.toggle('on'));
}

function collectSettings() {
  const params = {}, weights = {};
  $$('#set-grid [data-k]').forEach(el => {
    const k = el.dataset.k, t = el.dataset.t;
    if (t === 'bool') { params[k] = el.classList.contains('on'); return; }
    if (t === 'str') { params[k] = el.value; return; }
    let v = parseFloat(el.value);
    if (Number.isNaN(v)) return;
    if (t === 'int') v = Math.round(v);
    if (t === 'pct') v = v / 100;
    if (el.dataset.weight) weights[el.dataset.weight] = v;
    else params[k] = v;
  });
  return { params, weights };
}

async function saveSettings() {
  try {
    const { params, weights } = collectSettings();
    const r = await api('/api/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ params, weights }),
    });
    S.cfg = r;
    if (typeof AUTO !== 'undefined') AUTO.st = null;
    try { pollAuto(); } catch (_) { }
    toast('设置已保存，下一次自动选股就按新的来');
    // 条件变了，屏幕上那份旧名单已经不代表新条件了，说清楚，别让人当成新结果
    if (S.lastResult) {
      const el = $('#res-meta');
      if (el) el.textContent = '参数刚改过，当前名单还是用旧条件算的 —— 点「立即选股」重新跑一次';
    }
  } catch (e) { toast('没保存成功：' + e.message, true); }
}

/* ================================================================ 初始化 */
async function init() {
  const _q = new URLSearchParams(location.search);
  const _v = _q.get('view') || _q.get('v');     // 切页时写的是 ?v=xxx，老链接 ?view=xxx 也认
  const _c = _q.get('code');
  initTheme();
  paintIcons();
  $('#theme-btn').onclick = () => applyTheme(themeNow() === 'dark' ? 'light' : 'dark');
  try {
    S.cfg = await api('/api/config');
    const c = S.cfg.cache || {};
    // 缓存最后写盘的日期就是行情最新的一天；一个缓存都没有时不写假的日期
    if (c.last_update) $('#f-data-date').textContent = c.last_update;
  } catch (e) { }

  $$('.ni').forEach(b => b.onclick = () => switchView(b.dataset.view));
  // 二级页面包屑的"← 操作台"：退回主页面（选股）
  const cb = $('#crumb-back');
  if (cb) cb.onclick = () => switchView('screen');
  // 表头里的"去别处看看"链接（成绩怎么样 → 策略检验，盘中扫一眼 → 盯盘）
  document.addEventListener('click', e => {
    const a = e.target.closest('[data-go]');
    if (!a || !(e instanceof MouseEvent)) return;      // 别把代码里 .click() 的跳转拦下来
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;   // 想新开页签就随他去
    e.preventDefault();
    switchView(a.dataset.go);
  });
  // 可折叠的次要小块：点标题展开 / 收起
  $$('[data-fold]').forEach(h => h.onclick = () => {
    const box = h.closest('.fold');
    if (box) box.classList.toggle('open');
  });
  $('#btn-run').onclick = runScreen;
  $('#btn-scan').onclick = runScan;
  bindWatchlistPanel();
  bindMemoryPanel();
  $('#btn-bt').onclick = runBacktest;
  $('#btn-pf').onclick = runPortfolio;
  $('#btn-save').onclick = saveSettings;
  $('#btn-reset').onclick = async () => {
    if (!confirm('恢复所有参数为默认值？')) return;
    const r = await api('/api/config/reset', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    S.cfg = r; renderSettings(); toast('已经全部改回默认值');
  };
  $('#btn-clear').onclick = async () => {
    const r = await api('/api/cache/clear', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
    toast(`清理完成，删掉了 ${r.removed} 个旧的行情缓存`);
  };
  $('#btn-stop').onclick = async () => {
    if (!S.job) return;
    await api('/api/job/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: S.job }) });
    toast('正在停止…');
    // 停止也可能让 runScreen 收不到结果，顺手把自动模式的让路解除，免得一直暂停
    try { await api('/api/auto/hold', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ on: false }) }); } catch { }
    try { await pollAuto(); } catch { }
  };
  $('#btn-export').onclick = () => { location.href = '/api/export?kind=screen'; };
  $('#q').oninput = e => { S.filter = e.target.value; renderScreen(); };
  // 搜索框里按 Esc 直接清空并还原表格
  $('#q').onkeydown = e => {
    if (e.key !== 'Escape' || !e.target.value) return;
    e.stopPropagation();   // 别让全局的 Esc 顺手把详情抽屉也关了
    e.target.value = ''; S.filter = ''; renderScreen(); e.target.blur();
  };

  $$('#tbl-screen thead th.sortable').forEach(th => th.onclick = () => {
    const k = th.dataset.s;
    if (S.sort.key === k) S.sort.dir *= -1;
    else S.sort = { key: k, dir: -(k === 'code' || k === 'name' ? -1 : 1) };
    renderScreen();
  });

  document.addEventListener('click', e => {
    const det = e.target.closest('[data-detail]');
    if (det) { e.stopPropagation(); openDetail(det.dataset.detail); return; }
    const row = e.target.closest('tr[data-code], .wrow[data-code]');
    if (row && !e.target.closest('button')) openDetail(row.dataset.code);
  });
  $('#dw-close').onclick = closeDrawer;
  $('#mask').onclick = closeDrawer;

  /* 细节弹窗：五关 / 汇总数字 / 值得盯着 三个页签，主页上只留「看看细节 / 全部数据」两个入口 */
  const wclose = $('#wm-close');
  if (wclose) wclose.onclick = closeWatchModal;
  $('#wm-mask').onclick = closeWatchModal;
  $$('#wm-tabs button').forEach(b => b.onclick = () => { S.modalTab = b.dataset.wt; setModalTab(b.dataset.wt); renderDetailModal(); });
  $$('#wm-filter button').forEach(b => b.onclick = () => { S.watchFilter = b.dataset.wf; renderDetailModal(); });
  // 结论条和名单头部上的两个入口（内容每次重画，用事件委托）
  $('#view-screen').addEventListener('click', e => {
    if (e.target.closest('#hl-more')) { openDetailModal('gates'); return; }
    if (e.target.closest('#btn-detail-more')) { openDetailModal('stats'); return; }
    const st = e.target.closest('[data-star]');
    if (st) {
      const code = st.dataset.star;
      if ((S.watchList || []).some(w => w.code === code)) {
        toast('已经在自选股里了，到「盯盘 / 自选」看');
        switchView('watch');
      } else {
        addWatch(code, st.dataset.name || '');
        st.textContent = '★';
      }
      return;
    }
    const k = e.target.closest('.kpi');
    if (k && k.dataset.kpi === 'watch') openDetailModal('watch');
  });

  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (S.watchModalOpen) closeWatchModal();
    else closeDrawer();
  });

  /* 窗口变大变小后重画所有画布：canvas 是位图，
     只靠 width:100% 拉伸会把 K 线和筹码图压扁/拉长，得按新宽度重绘 */
  let _rzT = 0;
  window.addEventListener('resize', () => {
    clearTimeout(_rzT);
    _rzT = setTimeout(() => { try { repaintCharts(); } catch { } }, 160);
  });

  // 自动加载上次结果（软件后台可能已经跑过了）
  try {
    const r = await api('/api/last');
    if (r.result) {
      applyResult(r.result, r.result.auto ? '（自动）' : '（上次的结果）');
    }
  } catch { }

  // 自动选股状态：进来先拉一次，之后每 15 秒看一次
  pollAuto();
  AUTO.timer = setInterval(pollAuto, 15000);
  setTimeout(pollAuto, 6000);

  // 买点卖点提醒：进来先补一遍（上次没看见的会补弹），之后每分钟问一次服务端
  initSoundPref();
  document.addEventListener('pointerdown', primeAudio, true);
  document.addEventListener('keydown', primeAudio, true);
  syncAlerts();
  loadWatchlist();
  ALERTS.timer = setInterval(syncAlerts, 60000);

  // 一次都没有结果时（第一次打开，或自动模式还没跑到），自己先跑一遍，
  // 用户不用点任何按钮就有名单看
  if (!S.items.length) {
    setTimeout(() => {
      try {
        if (S.items.length || S.busy.screen) return;
        if (AUTO.st && AUTO.st.busy) return;   // 后台正在跑，等它的结果
        runScreen();
      } catch (_) { }
    }, 1500);
  }

  if (_v && TITLES[_v] && (_v !== 'screen' || _c)) switchView(_v);
  if (_c && /^\d{6}$/.test(_c)) setTimeout(() => openDetail(_c), 120);
}
document.addEventListener('DOMContentLoaded', async () => {
  // 先把页面骨架整理好（主页面那块 + 二级页那个吸顶槽位），再走正常启动流程：
  // 这样后面所有按 id 取元素、绑事件的代码都不用改。
  // 注意这里必须用 moveViews（= rehomeViews + mountTopbar）：只 rehomeViews 的话真正的 #topbar
  // 还留在 main 下面，而选股页 .hd 里那个空的 <header class="topbar"> 占位照样有 52px 高，
  // 于是顶栏底下会空出一条灰带，直到切一次页才恢复。
  const _q0 = new URLSearchParams(location.search);
  const _v0 = _q0.get('view') || _q0.get('v') || 'screen';
  try { moveViews(TITLES[_v0] ? _v0 : 'screen'); } catch (_) { }
  await init();
});



