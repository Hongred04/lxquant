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
/** 今天（本地时区），YYYY-MM-DD。用来判断某条记录是不是"当天"的。 */
function todayStr() {
  const d = new Date();
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function toast(msg, isErr) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast show' + (isErr ? ' err' : '');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.className = 'toast'; }, 2600);
}

// 请求必须能超时退出。服务器卡住（抓行情卡住、线程池满了）时，
// 没有超时的话详情抽屉会永远停在"正在算…"，用户就只能干等。
// 后台任务走 /api/job 轮询，不经过这里，所以不会被这个上限掐掉。
const API_TIMEOUT = 90000;
async function api(url, opt) {
  const ac = (typeof AbortController !== 'undefined') ? new AbortController() : null;
  let timer = null;
  if (ac) timer = setTimeout(() => ac.abort(), API_TIMEOUT);
  const init = { ...(opt || {}) };
  if (ac) init.signal = ac.signal;
  let r;
  try {
    r = await fetch(url, init);
  } catch (e) {
    if (e && e.name === 'AbortError') throw new Error('等了 90 秒没回音，服务可能卡住了，刷新一下再试');
    throw new Error('连不上本地服务（' + (e && e.message || e) + '）');
  } finally {
    if (timer) clearTimeout(timer);
  }
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
    // 按钮上写"当前是什么"，点一下就换到另一个。
    // 图标挂在按钮内部的 <i> 上 —— 原来把 data-ic 设在按钮自己身上，
    // paintIcons(btn) 只遍历后代，那个 <i> 永远不变，图标一直是月亮。
    const ic = btn.querySelector('i') || btn;
    ic.dataset.ic = t === 'dark' ? 'sun' : 'moon';
    const txt = document.getElementById('theme-txt');
    if (txt) txt.textContent = t === 'dark' ? '亮色' : '暗色';
    btn.title = t === 'dark' ? '现在是暗色，点一下换成亮色' : '现在是亮色，点一下换成暗色';
    paintIcons(btn);
  }
  if (repaint) repaintCharts();
}

/** 主题切换后重绘所有画布（canvas 颜色不会跟随 CSS 变量自动更新） */
function repaintCharts() {
  if (S.detail && $('#drawer').classList.contains('show')) {
    const tab = document.querySelector('#k-tabs .tab.active');
    drawChip($('#chip-cv'), S.detail);
    drawKline($('#k-cv'), S.detail, tab ? tab.dataset.per : 'day');
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
  // 信号检验这一页不再画资金曲线：钱的事统一归「模拟账户」，
  // 免得同一个账户在两页里出现两个差 9 倍的「赚了多少」。
  if (S.bt && S.bt.summary) renderBtDist();
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
  ovn: null,          // 隔夜低吸（首阴套利）的账本，和主策略完全独立
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
  /* 可插拔策略方案：/api/strategies 拿回来的清单 + 当前选中的 key */
  strats: null,
};

/* ------------------------------------------------ 视图切换 */
const TITLES = { screen: '选股', watch: '盯盘 / 自选', memory: '记忆', overnight: '隔夜低吸', backtest: '信号检验', portfolio: '模拟账户', method: '使用说明', settings: '参数设置' };
/* 二级页层数：0 = 主页面（侧栏常驻、整块内容一起滚）；
   1 = 从主页面钻进去的工具页（信号检验 / 模拟账户 / 使用说明 / 参数设置），
       顶部只留一条面包屑 + 吸顶的工具条，别让人迷失在长表格里 */
const LEVEL = { screen: 0, overnight: 0, watch: 0, memory: 1, backtest: 1, portfolio: 1, method: 1, settings: 1 };
const REHOME = Object.keys(LEVEL).filter(v => LEVEL[v] === 0);   // 操作台：用 app-main 把二级页的头部还回去
// 顶栏副标题：默认留空。以前每页都挂一句「这页是干什么的」，
// 但页面标题（选股 / 自选 / 记忆 / 信号检验…）本身已经说清了，
// 再补一句等于让每个页面都先念一遍说明书。留空后由状态信息按需填充
// （扫描中、上次更新时间等），只有在真有动态内容时才出现。
const HINTS = {};

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
  if (v === 'overnight') { try { loadOvernight(); } catch (_) { } }
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
  // 关卡顺序和名字都由策略自己给，换一套方案这里自动跟着变
  const gates = (funnel.gates && funnel.gates.length)
    ? funnel.gates
    : [{ key: 'ma', label: '三天都强于平均成本' }, { key: 'chip', label: '上方套牢盘少' },
       { key: 'pos', label: '价格在低位' }, { key: 'bottom', label: '底部横着走' },
       { key: 'trend', label: '还在 20 日均线上' }];
  const CN = '①②③④⑤⑥⑦⑧';
  const items = [['扫过多少只', stats.scanned, 1, false, `一共看了 ${tot} 只`]];
  gates.forEach((g, i) => {
    const v = funnel[g.key];
    items.push([`${CN[i] || (i + 1) + '.'} ${g.label}`, v, (v || 0) / tot, false,
      g.key === 'ma'
        ? `看过的 ${tot} 只里，有 ${v} 只达到了「${g.label}」（按 ${basisTxt} 算）`
        : `有 ${v == null ? '—' : v} 只过了「${g.label}」这一关`]);
  });

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
const WATCH_KEYS_FALLBACK = [
  ['ma', '价格站在成本上', '连续 3 天价格都在当天平均成本上方'],
  ['chip', '套牢盘少', '头上压着等着解套的筹码不多'],
  ['pos', '价格低', '在近 120 天区间的下边'],
  ['bottom', '底部横着走', '最近 20 天没在一路往下掉'],
  ['trend', '趋势向上', '短期均线方向向上'],
];
/* 关卡从当前策略里取，换方案后这里跟着变；取不到就退回原来那五关 */
function gateKeys() {
  const cur = (S.strats && S.strats.items || []).find(x => x.key === (S.strats || {}).current);
  const gs = cur && cur.gates;
  if (gs && gs.length) return gs.map(g => [g.key, g.label, g.hint || g.label]);
  return WATCH_KEYS_FALLBACK;
}
/* 还差几项没过：策略的关卡里有几关没打勾（尾盘确认那一下只算提示，不进这组） */
function watchGap(a) {
  const c = a.checks || {};
  const known = gateKeys().filter(([k]) => k in c);
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
    <span class="checks warn">${gateKeys().map(([k, n]) => `<span class="ck ${a.checks && a.checks[k] ? 'y' : 'n'}" title="${n}${a.checks && a.checks[k] ? '：符合' : '：不符合'}">${a.checks && a.checks[k] ? '✓' : '·'}</span>`).join('')}</span>
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

/* ---------------- 细节弹窗：关卡 / 汇总数字 / 值得盯着 ---------------- */
/* 关卡层数由当前策略决定，标题跟着变（别写死「五关」） */
function modalTabLabel(k) {
  if (k === 'gates') return `${gateKeys().length} 关各筛掉多少`;
  return { stats: '汇总数字', watch: '值得盯着' }[k] || k;
}
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
  // 页签标题跟着当前策略的关卡数走
  $$('#wm-tabs button').forEach(b => {
    const t = b.dataset.wt;
    if (t) b.textContent = modalTabLabel(t);
  });
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

/** 市场状态条：告诉用户「现在该不该玩这套规则」 */
function renderMkt(r) {
  const el = $('#mkt-bar');
  if (!el) return;
  const ms = (r && r.stats && r.stats.market) || null;
  const gated = !!(r && r.stats && r.stats.gated);
  if (!ms || !ms.date) { el.hidden = true; return; }
  const tag = ms.mode === 'weak' ? '超跌主场'
    : (ms.mode === 'strong' ? '不适合这套规则' : '临界，建议观望');
  el.hidden = false;
  el.className = 'mktbar ' + (ms.mode || 'mid') + (gated ? ' gated' : '');
  el.innerHTML = `<span class="tag">${tag}</span>`
    + `<b>市场状态 ${esc(ms.date)}</b>大盘相对 20 日均线 <b>${fmt(ms.vs20, 2)}%</b>`
    + `（60 日 ${fmt(ms.vs60, 2)}% · 20 日涨跌 ${fmt(ms.ret20, 2)}% · 量能比 ${fmt(ms.volr, 2)}）`
    + `<br>${esc(ms.note || '')}`
    + (gated ? `<br><b style="color:var(--up)">已暂停买入：</b>`
      + ((r.stats.gated_n || 0) > 0
        ? `这 ${r.stats.gated_n} 只本来会选中的票放进观察池了，等大盘真弱再动手。`
        : `今天本来也没有全达标的票，跟市场状态无关。`)
      + `（参数里关掉「市场状态开关」可以不看这个）` : '');
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
  try { renderMkt(r); } catch (_) { }
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
  // 两种入参都要认：
  //   "13:05"                  —— next_run / 参数里的时间
  //   "2026-10-30 13:00:00"    —— last_run（服务端给的是完整时间串）
  // 以前只匹配第一种并在开头锚定，于是 last_run 永远显示成「上次 —」，
  // 看起来像从来没跑过（其实一直在跑）。取第一个 HH:MM 片段即可。
  const m = t.match(/(\d{1,2}:\d{2})/);
  return m ? m[1].padStart(5, '0') : '—';
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
    // 收盘后才补扫的那份，要说清是"补的"——否则晚上打开只会看到
    // 「收盘了 · 最后一次 20:15」，时间对不上交易时段，让人以为出了问题
    const late = /补扫/.test(String(st.last_reason || ''));
    if (!st.last_run) return `休息中 · ${h0} 开盘后自动开始`;
    return late ? `已补扫当天名单 · ${fmtHm(st.last_run)}`
      : `收盘了 · 最后一次 ${fmtHm(st.last_run)}`;
  }
  // 上次是今天的才叫"上次"，隔夜的那个名单不算今天的状态
  const today = st.now ? String(st.now).slice(0, 10) : '';
  const ranToday = st.last_run && (!today || String(st.last_run).slice(0, 10) === today);
  let s;
  if (ranToday && st.last_run) {
    // reason 常是「开盘首扫 · 扫了 600 只，选出 1 只」这种长串，只留第一段。
    // 具体扫了多少只下面状态栏还有，这里重复一遍会把顶栏撑爆（实测溢出 54px）。
    const head = String(st.last_reason || '')
      .replace(/（.*?）/g, '').split('·')[0].trim().slice(0, 12);
    s = `上次 ${fmtHm(st.last_run)}${head ? ' ' + head : ''}`;
  } else {
    s = '今天还没扫过';
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
    // 光记在浏览器里没用：刷新一次这份 Set 就没了，服务端队列里那条还在，
    // 打开软件又原样弹出来（"每次打开都弹"就是这么来的）。必须回写服务端。
    ackAlert(sig);
  } else {
    ALERTS.sigs.delete(sig);
  }
}

/** 告诉服务端"这条已经看过了"，从队列里删掉。失败就算了，下次还会弹，不会丢事 */
function ackAlert(sig) {
  try {
    api('/api/alerts/ack', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sig }),
    }).then(() => {
      // 服务端那份也更新一下，免得自选股页还挂着已经关掉的结论
      if (Array.isArray(S.alerts)) S.alerts = S.alerts.filter(a => a.sig !== sig);
    }).catch(() => { });
  } catch (_) { }
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
    // 盯盘扫描是诊断工具，不拦人；但大盘不配合时得提一句，否则这些票会被当成买点
    const sst = (r.result && r.result.stats) || {};
    toast(sst.gated ? '看完了 —— 大盘不配合，这些票先别急着买' : '看完了');
  } catch (e) { toast('没能看一眼：' + e.message, true); }
  finally {
    S.busy.scan = false;
    btn.disabled = false; btn.innerHTML = '<i data-ic="play"></i>马上看一眼'; paintIcons(btn);
    setTimeout(() => { $('#scan-prog').hidden = true; }, 700);
  }
}

/* ================================================================ 自选股（买点卖点） */
/* 自选股那一行的关卡跟着当前策略变；gateKeys() 取不到时退回原来那五关 */
const W_KEYS_FALLBACK = [['ma', '站上平均成本'], ['chip', '套牢盘不多'], ['pos', '价格在低位'],
  ['bottom', '底部横着走'], ['trend', '在均线上']];
function W_KEYS() { return gateKeys(); }
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
      <div class="wr-chk" title="五关：${W_KEYS().map(([k, n]) => n + (ck[k] ? '✓' : '✗')).join(' · ')}">${W_KEYS().map(([k, n]) => `<i class="ck ${ck[k] ? 'yes' : 'no'}" title="${n}${ck[k] ? '：符合' : '：不符合'}">${ck[k] ? '✓' : '✗'}</i>`).join('')}</div>
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
  src: 'hit',        // all / hit / watch —— 默认只看能买，值得买不进统计口径
  rv: null,          // 那天的回看结果
  ov: null,          // 三十天的总成绩
  loading: false,
};

function memKindOf(r) { return r.gap == null ? 'hit' : 'watch'; }

/** 这条记录是按什么口径定下来的 —— 后端 screener.basis_label 给的 */
function memBasisText(basis) {
  if (basis === 'tail') return '尾盘定的名单';
  if (basis === 'preview') return '盘中试算（那天没等到尾盘）';
  if (basis === 'close') return '收盘价口径';
  return '';
}

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
  if (!MEM.days.length) {
    renderMemEmpty('还没有能回看的记录');
    return;
  }
  if (!MEM.date || !MEM.days.some(x => x.date === MEM.date)) {
    // 优先落在「最近一个真选出过票」的那天。0 只的日子点进去 KPI 全是「—」、
    // 表格只有一行「没有票」，看起来像功能坏了 —— 其实只是那天没信号。
    const pick = MEM.days.find(x => (x.hit || 0) > 0) || MEM.days[0];
    if (pick) MEM.date = pick.date;
  }
  // ★ 先把日期定下来再渲染选择器：反过来的话选择器显示的是「最新那天」，
  //   而下面加载的内容已经跳到「最近有票的那天」，两者对不上。
  renderMemDates();
  await loadMemDay(MEM.date);
}

function renderMemDates() {
  const sel = $('#mem-date');
  if (!sel) return;
  sel.innerHTML = MEM.days.map(d => {
    const t = (d.at || '').slice(5, 16);
    const nm = (d.names || []).slice(0, 2).join('、');
    return `<option value="${d.date}" ${d.date === MEM.date ? 'selected' : ''}>${d.date}　留了 ${(d.hit || 0) + (d.watch || 0)} 只${d.late ? '（补扫）' : ''}${nm ? '（' + esc(nm) + '…）' : ''}</option>`;
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

/** 这一天有记录，但当前筛选下没票（最常见：那天一只「能买」都没选出）。
 *
 *  要跟「今天还没收盘」严格区分开 —— 这两件事以前共用一条提示，
 *  结果 10-28 这种历史日期也会说「这天是今天，日线还没出来」。
 *  区别在于：本函数的情况**已经有完整数据**，只是"筛选后为空"，
 *  所以要把话说明白，并给一个就地切换筛选的按钮，别让人以为软件坏了。
 */
function renderMemNoPick(rv) {
  const b0 = $('#mem-loading'); if (b0) b0.hidden = true;
  ['#mem-kpis', '#mem-row2', '#mem-table'].forEach(s => { const el = $(s); if (el) el.hidden = true; });
  const box = $('#mem-empty'); if (box) box.hidden = false;

  const nHit = (rv.rows || []).length;
  const nWatch = (rv.watch_rows || []).length;
  const b = $('#mem-empty-txt');
  const title = box.querySelector('b');
  const srcTxt = MEM.src === 'watch' ? '值得盯着' : (MEM.src === 'hit' ? '能买' : '全部');
  if (title) {
    title.textContent = nHit === 0 && nWatch > 0
      ? `${MEM.date} 这天没有「能买」的票`
      : `这一条筛选下没有票`;
  }
  if (b) {
    b.innerHTML = (nHit === 0 && nWatch > 0)
      ? `那天只留下了 ${nWatch} 只「值得盯着」的（差一两关），没有一只全部达标 —— `
        + `这是规则主动不出手，不是数据没出来。`
        + `<button class="btn sm ghost" id="mem-goto-watch" style="margin-left:8px">看那 ${nWatch} 只</button>`
      : `当前看的是「${srcTxt}」，这天这一类是空的。`;
  }
  // 「看那 N 只」——就地切到观察名单，不要让用户自己去猜下拉框
  const go = $('#mem-goto-watch');
  if (go) go.onclick = () => {
    MEM.src = 'watch';
    const s = $('#mem-src'); if (s) s.value = 'watch';
    renderMemory();
  };
}

function renderMemory() {
  const rv = MEM.rv;
  const items = memFiltered();
  if (!rv || (!items.length)) {
    const has = !!(rv && ((rv.rows || []).length || (rv.watch_rows || []).length));
    if (!has) { renderMemEmpty(); return; }
    // 这一天有记录，但**当前这个筛选**下没有票。
    // 最常见的场景：那天一只「能买」都没选出，只有观察票，而默认筛选是「只看能买的」。
    // 以前这里会掉进下面 n=0 的分支，弹出「这天是今天，日线还没出来」——
    // 明明是 10-28 的历史记录、明明有 30 只观察票，提示却说"是今天、在等收盘"，
    // 两句话都是错的，还会让人以为软件坏了。
    renderMemNoPick(rv);
    return;
  }
  const rows = items.filter(x => x.ret != null);
  const pend = items.filter(x => x.ret == null);
  const box = $('#mem-empty'); if (box) box.hidden = true;
  const b1 = $('#mem-loading'); if (b1) b1.hidden = true;
  ['#mem-kpis', '#mem-row2', '#mem-table', '#mem-days'].forEach(s => { const el = $(s); if (el) el.hidden = false; });

  // ---- 上面那张成绩单
  const n = rows.length;
  // days=0 分两种情况，必须区别对待：
  //  a) 买入价用的是**收盘价**（price_at 为空）→ then 和 last 是同一根，ret 恒为 0，
  //     显示 0.00% 会让人以为"这批一动不动"，其实还没开始走 → 打「—」；
  //  b) 买入价取自 **14:45 分时**（price_at 有值）→ then 和 last 是两个不同的价，
  //     ret 就是"尾盘买入到收盘"的真实当日盈亏，属于有效信息 → 照常显示。
  // 以前一律按 a) 处理（只看 days），于是当天选出的记录 KPI 全是「—」，
  // 收盘后打开会以为软件今天没出结论 —— 实际是把这个结论藏起来了。
  const todayPx = n > 0 && !!String((rv && rv.price_at) || '');
  const onlyToday = n > 0 && rows.every(x => (x.days || 0) <= 0);
  // 这一天的数字算不算"有效结论"：走过了后面的行情，或者至少是真实的尾盘买入价
  const effective = n > 0 && (!onlyToday || todayPx);
  // 这条记录是不是"当天"（而不是翻出来的历史某天）。
  // 判断依据只能是记录日期与今天是否相同 —— 以前用 days==0 反推，
  // 于是历史某天（比如 10-28）只要涨跌幅算不出来，也会被说成"这天是今天，还在等收盘"。
  const isToday = String(MEM.date || '') === todayStr();
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
    {
      // 当天上市（days=0）但买价是 14:45 时，"到今天平均"其实是"当天尾盘到收盘"
      k: (onlyToday && todayPx) ? '尾盘买 → 收盘' : '到今天平均',
      v: effective ? (avg > 0 ? '+' : '') + fmt(avg, 2) + '%' : '—',
      // 副标题只说"按哪个价算的"。日期在选择器和明细表抬头都有了，标题也已经写明
      // 「尾盘买 → 收盘」，这里再重复一遍"2026-10-29 14:45 买入价 → 收盘价"
      // 会被 .kpi .s 的省略号截掉半句（实测溢出 5px），看着像布局坏了。
      s: effective
        ? (onlyToday ? `按 ${rv.price_at} 分时价算` : '前复权算的')
        : '还没开始走',
      c: effective ? (avg >= 0 ? 'up' : 'down') : '',
    },
    { k: '赚钱的几只', v: effective ? `${win} / ${n}` : '—', s: effective ? `占 ${pct(win / n * 100, 0)}` : '还没有数据', c: effective ? (win * 2 >= n ? 'up' : 'down') : '' },
    { k: '最好的一只', v: (best && effective) ? (best.ret > 0 ? '+' : '') + fmt(best.ret, 1) + '%' : '—', s: (best && effective) ? esc(best.name) : '', c: (best && effective) ? (best.ret > 0 ? 'up' : 'down') : '' },
    { k: '最差的一只', v: (worst && effective) ? (worst.ret > 0 ? '+' : '') + fmt(worst.ret, 1) + '%' : '—', s: (worst && effective) ? esc(worst.name) : '', c: (worst && effective) ? (worst.ret < 0 ? 'down' : 'up') : '' },
    { k: '摸到止盈 / 破止损', v: effective ? `${hitT} / ${hitS}` : '—', s: '按软件当时给的价位算', c: '' },
  ].map(x => `<div class="kpi"><div class="k">${x.k}</div><div class="v ${x.c}">${x.v}</div><div class="s">${x.s}</div></div>`).join('');

  // ---- 右上角那段话
  const say = [];
  if (!n) {
    // 这里 n=0 是"这一类筛选下没有能算的行"，不一定等于"还没收盘"。
    // 只有记录日期确实是今天才说等收盘；历史某天算不出来，通常是那天没选出票。
    if (isToday) {
      say.push(['还在等收盘', '这天是今天，日线还没出来。等收盘（或明天）再回来看，就有涨跌幅了。']);
    } else {
      say.push(['这天没有可算的票', `${MEM.date} 这一条筛选下没有票，所以没有涨跌幅可看。换一个筛选看看，或者换一天。`]);
    }
  } else if (onlyToday && todayPx) {
    // 当天就能给出结论：唯一能算的是"尾盘买入到收盘"这一段
    if (avg >= 1) say.push(['尾盘买进，收盘还是赚的', `平均 +${fmt(avg, 2)}%，${n} 只里 ${win} 只收盘比买入价高。`]);
    else if (avg <= -1) say.push(['尾盘买进，收盘就浮亏', `平均 ${fmt(avg, 2)}%，${n} 只里只有 ${win} 只守住买入价。`]);
    else say.push(['尾盘买进，收盘基本平', `平均 ${fmt(avg, 2)}%，${n} 只里 ${win} 只收在买入价之上。`]);
    say.push(['这只是当天的那一段', `买入价取自 ${MEM.date} ${rv.price_at} 的分时，所以能算出"尾盘到收盘"的真实盈亏。但一天的走势代表不了这套规则准不准 —— 要等它走完几天，才谈得上判断。`]);
    if (hitS) say.push(['已经有票破位', `${hitS} 只跌破了当时给的止损价。按纪律该走就走，别扛。`]);
  } else if (onlyToday) {
    say.push(['今天刚选出来', `这一批是 ${MEM.date} 回看的，买入价和当天收盘价是同一个，涨跌幅本来就是 0。明天起才有真正的走势可看。`]);
    say.push(['别拿这一天当结论', '只有走过了后面的行情，才谈得上"选得准不准"。当天的 0% 不进总账 —— 记忆页统计里已经把它排除了。']);
  } else {
    if (avg >= 3) say.push(['这批是赚的', `平均 +${fmt(avg, 2)}%，${n} 只里 ${win} 只赚钱。`]);
    else if (avg <= -3) say.push(['这批是亏的', `平均 ${fmt(avg, 2)}%，${n} 只里只有 ${win} 只赚钱。`]);
    else say.push(['基本在原地', `平均 ${fmt(avg, 2)}%，好票和烂票互相抵消了。`]);
    say.push(['止损止盈管不管用', `按当时给的价位，${hitT} 只摸到过止盈，${hitS} 只跌破过止损。跌破止损说明当时那套判断没成立 —— 这不是软件算错，是行情没按预期走，该走就得走。`]);
    if (pend.length) say.push(['还有没算的', `${pend.length} 只今天刚选出来，等收盘价。`]);
  }
  $('#mem-why').innerHTML = say.map(([h, t]) => `<div class="rrow"><b>${h}</b><p>${t}</p></div>`).join('');

  // ---- 明细表
  const btxt = memBasisText(rv.basis);
  // 收盘后补扫的那天：名单是按收盘价判定达标的（因为白天没开软件），
  // 而买入价仍锚定 14:45 的分时 —— 两个口径不一致，必须写出来，
  // 否则会以为这份名单等同于 14:45 当场跑出来的那份。
  const lateTag = rv.late ? ' · 收盘后补扫' : '';
  $('#mem-meta').textContent = `${MEM.date} 选的 · ${items.length} 只${btxt ? ' · ' + btxt : ''}${lateTag}`;
  // 说清买入价是怎么来的：这是回看涨跌幅的起点，差 0.5% 结论就会偏。
  // 但那天一只票都没选出时（只有观察名单），根本没有「买入价」可言，
  // 再挂一句「旧记录/快照价」会让人误以为数据有问题。
  const pa = (rv && rv.price_at) || '';
  const atHm = String((rv && rv.at) || '').slice(11, 16);
  let paTxt = '';
  if (n > 0 || items.length) {
    if (pa) {
      paTxt = `买入价取自当天 ${pa} 的分时（你实际下单那个时点，不是收盘价）`;
    } else if (atHm && atHm >= '15:00') {
      paTxt = '买入价用的是当天收盘价（不是 14:45 的价，看涨跌幅要打个折扣）';
    } else {
      paTxt = '买入价用的是当时的盘中快照（没记录 14:45 的分时）';
    }
    // 补扫的日子：买入价虽然是 14:45 的，但"哪些票算达标"是按收盘价判的，
    // 这句话不能省 —— 它决定了这份名单能不能和盘中那份直接对比。
    if (rv.late) paTxt = `名单按收盘价判定（当天没开软件，收盘后补扫），${paTxt}`;
    paTxt += ' · ';
  }
  $('#mem-sub').textContent = `${paTxt}涨跌幅按前复权算（送转分红不算成暴跌）；最高/最低是选出后的区间极值`;
  const TB = $('#tb-mem');
  TB.innerHTML = items.map(x => {
    const kind = memKindOf(x);
    const retCls = x.ret == null ? '' : (x.ret > 0 ? 'up' : (x.ret < 0 ? 'down' : ''));
    // 带符号的百分比：正数补 +，负数让 fmt 自己带 -。
    // 以前这里写死 '+' + fmt(...)，最高价那一列在整段都在跌的时候会渲染成
    // 「+-0.23%」这种一眼就能看出是 bug 的东西；颜色也写死了 up/down，
    // 明明跌了还是绿的（A 股跌是绿，但"最高到过"是负的就不该显示成涨的色）。
    const sgnPct = (v, d) => (v == null ? '—' : (v > 0 ? '+' : '') + fmt(v, d) + '%');
    const dirCls = (v) => (v == null ? '' : (v > 0 ? 'up' : (v < 0 ? 'down' : '')));
    return `<tr data-code="${esc(x.code)}">
      <td class="code">${esc(x.code)}</td>
      <td class="name">${esc(x.name || '')}</td>
      <td><span class="chip ${kind === 'hit' ? 'ok' : ''}">${kind === 'hit' ? '能买' : '值得盯着'}</span></td>
      <td class="num">${x.then == null ? '—' : fmt(x.then)}</td>
      <td class="num">${x.last == null ? '—' : fmt(x.last)}</td>
      <td class="num ${retCls}">${x.ret == null ? '等收盘' : (x.ret > 0 ? '+' : '') + fmt(x.ret, 2) + '%'}</td>
      <td class="num ${dirCls(x.best)}">${sgnPct(x.best, 2)}</td>
      <td class="num ${dirCls(x.worst)}">${sgnPct(x.worst, 2)}</td>
      <td class="num">${x.days == null ? '—' : x.days}</td>
      <td>${x.stop ? `止损 ${fmt(x.stop)}` : ''}${x.stop && x.target ? ' / ' : ''}${x.target ? `止盈 ${fmt(x.target)}` : ''}${!x.stop && !x.target ? '—' : ''}</td>
    </tr>`;
  }).join('') || '<tr class="empty"><td colspan="10">这一条筛选下没有票</td></tr>';

  // ---- 每天的成绩单
  const ov = MEM.ov;
  const TB2 = $('#tb-memdays');
  const waitDays = (ov && ov.waiting) || [];
  const waitTip = waitDays.length
    ? `<tr class="empty"><td colspan="8">${waitDays.map(esc).join('、')} 还没走完一个交易日（或只是盘中试算），等明天起才有成绩，不进统计</td></tr>`
    : '';
  // 能买 / 值得买 分开显示；某天没有某一组时给「—」，不要补 0（0 会被读成"涨了 0%"）
  const sgn = v => (v == null ? '—' : (v > 0 ? '+' : '') + fmt(v, 2) + '%');
  const wr = v => (v == null ? '—' : pct(v, 0));
  const cls = v => (v == null ? '' : (v > 0 ? 'up' : (v < 0 ? 'down' : '')));
  if (ov && (ov.days || []).length) {
    const today = todayStr();
    // 「能买」的票还没走过一个完整交易日的，都算不出胜率。给个数出来，
    // 否则整张表一片「—」会被读成功能坏了。
    const withHit = (ov.days || []).filter(d => (d.hit || 0) > 0);
    const nHit = withHit.reduce((a, d) => a + (d.hit || 0), 0);
    const scored = (ov.days || []).filter(d => !d.partial && (d.days || 0) > 0 && (d.hit_n || 0) > 0).length;
    const rows = ov.days.map(d => {
      // 当天记的总只数（含还没走完一天的）；老记录没有 total 字段时用 n/hit 取大者兜底，
      // 免得又出现「记了 101、其中能买 117」这种自相矛盾的行
      const tot = d.total != null ? d.total : Math.max(d.n || 0, d.hit || 0);
      const hn = d.hit_n != null ? d.hit_n : d.hit;
      // partial：这天的「能买」票还没有一根走完的收盘价。
      //   · 就是今天  → 「当天 · 未走完」，数字是"尾盘买→收盘"，不进累计
      //   · 是前几天  → 不能写"当天"（10-29 的标签挂在 10-30 的页面上是错的），
      //                应说"等次日收盘"：次日的日线还没出来
      const pt = !!d.partial;
      const isToday = d.date === today;
      const tag = pt
        ? `<em class="ts" title="${esc(isToday
              ? `这天还没走完：数字是 ${d.price_at || '尾盘'} 买入到当天收盘的盈亏，不计入累计胜率`
              : '这天的票还没走过一个完整交易日（次日收盘价还没出来），所以暂时不计入累计胜率')}">`
          + `${isToday ? '当天 · 未走完' : '等次日收盘'}</em>`
        : '';
      return `<tr data-date="${d.date}"${pt ? ' class="pt"' : ''}>
      <td>${d.date}${tag}</td>
      <td class="num" title="当天共记 ${tot} 只，其中 ${d.n} 只已走过至少一个交易日，参与下面的涨跌统计">${tot}</td>
      <td class="num" title="当天全部达标的票">${hn}</td>
      <td class="num ${cls(d.hit_avg)}">${sgn(d.hit_avg)}</td>
      <td class="num">${wr(d.hit_win)}</td>
      <td class="num ${cls(d.watch_avg)}" title="差一两关的观察票，只作参考、不计入总胜率">${sgn(d.watch_avg)}</td>
      <td class="num">${wr(d.watch_win)}</td>
      <td class="num">${pt ? '—' : d.days}</td>
    </tr>`;
    }).join('');
    // 累计还是空的时候，说明「差在哪、还差多少」——比让用户自己猜强
    const NEED = 20;
    let foot = '';
    if (!ov.sum) {
      const why = !withHit.length
        ? '这几天都没有「能买」的票 —— 规则没给出信号，就没有对错可评（观察票不进统计）。'
        : `记了 ${withHit.length} 天有「能买」的票，共 ${nHit} 只，但还没有一只走过完整的下一个交易日，`
          + `所以累计胜率还是空的。收完今天的盘就会有第一笔。`;
      foot = `<tr class="foot-none"><td colspan="8">${esc(why)}`
        + `<br><span class="muted">谈胜率至少要 ${NEED} 个交易日，目前 ${scored}/${NEED}。</span></td></tr>`;
    }
    TB2.innerHTML = rows + waitTip + foot;
  } else {
    // 空成绩单最容易被读成「功能坏了」——尤其已经记了几天、却还是一片空的时候。
    // 所以把确切数字摆出来：记了几天、其中几天有「能买」的票、为什么还算不出胜率、
    // 还差多少。一句「明天起就会有」在已经记了两天的时候是错的。
    const rec = (ov && ov.days) || [];
    const withHit = rec.filter(d => (d.hit || 0) > 0);
    const nHit = withHit.reduce((a, d) => a + (d.hit || 0), 0);
    const NEED = 20;                       // 20 个交易日起步，才谈得上胜率
    let head, sub;
    if (!rec.length) {
      head = '还没有任何记录';
      sub = '今天 14:45 之后（或明天开盘）会自动记下第一份名单，之后每天一行。';
    } else if (!withHit.length) {
      head = `已记 ${rec.length} 天，但这几天都没有「能买」的票`;
      sub = '只有观察票不算成绩 —— 规则没给出信号，就没有对错可评。';
    } else {
      head = `已记 ${rec.length} 天，其中 ${withHit.length} 天有「能买」的票，共 ${nHit} 只`;
      sub = '这些票还没有一只走过完整的下一个交易日，所以现在算不出胜率；'
          + '等收盘（或明天）就有第一笔成绩。'
          + `要谈胜率至少要 ${NEED} 个交易日，目前 ${withHit.length}/${NEED}。`;
    }
    if (waitDays.length) sub += ` ${waitDays.map(esc).join('、')} 还在等收盘。`;
    TB2.innerHTML = `<tr class="empty"><td colspan="8"><div class="mem-none">`
      + `<b>${esc(head)}</b><span>${sub}</span></div></td></tr>`;
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

/** 检验范围：market=全市场抽样（默认） / today=只看今天的名单 */
function btScope() { const el = $('#bt-scope'); return el ? el.value : 'market'; }
function pfScope() { const el = $('#pf-scope'); return el ? el.value : 'market'; }

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
        // 默认全市场抽样：以前这里绑死"今天的名单"，今天只选出 2 只就只回测 2 只，
        // 几笔交易当然看不出任何结论（这是"信号检验没数据"最直接的原因）。
        codes: btScope() === 'today' && S.items.length
          ? S.items.slice(0, +$('#bt-limit').value).map(a => a.code) : null,
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
  const more = $('#bt-more'); if (more) more.hidden = !has;   // 没跑过就别摆「在整屏里看」
  ['#bt-verdict', '#bt-kpis', '#view-backtest .row2', '#bt-table'].forEach(sel => {
    const el = document.querySelector(sel);
    if (el) el.hidden = !has;
  });
  paintBtCharts();
}

function renderPfEmpty() {
  const has = !!(S.pf && S.pf.summary);
  const box = $('#pf-empty'); if (box) box.hidden = has;
  const more = $('#pf-more'); if (more) more.hidden = !has;   // 没模拟过就别摆「在整屏里看」
  ['#pf-kpis', '#view-portfolio .row2', '#pf-table'].forEach(sel => {
    const el = document.querySelector(sel);
    if (el) el.hidden = !has;
  });
  paintPfCharts();
}

/* 准入结论卡：这套规则够不够格当默认策略。
 *
 * 为什么单独一张卡、而且放在 KPI 上面：
 *   用户真正想知道的是"能不能用"，一堆指标只是证据。先给结论再给证据，
 *   比让人从六个 KPI 里自己推要快得多。
 *
 * 判定逻辑在 lxquant/verdict.py（纯函数、有单测），前端只负责画 ——
 * 门槛写在一处，改标准不用前后端各改一遍。
 */
function renderBtVerdict(v) {
  const box = $('#bt-verdict');
  if (!box) return;
  // 旧结果没有这个字段，或者后端算挂了：不要空着一张卡，直接藏起来
  if (!v || !v.level) { box.hidden = true; box.innerHTML = ''; return; }
  const icon = { pass: '✓', watch: '!', fail: '✗', insufficient: '?' }[v.level] || '·';
  const chips = (v.checks || []).map(c => {
    const val = (c.value === null || c.value === undefined) ? '—' : c.value;
    // 三态：ok 达标 / watch 在容忍范围内（标黄）/ no 真不行。
    // 只有两种颜色的话，"watch 档下面一片红叉"会让人觉得结论自相矛盾。
    const lv = c.level || (c.ok ? 'ok' : 'no');
    const mark = { ok: '✓', watch: '!', no: '✗' }[lv] || '·';
    return `<span class="vc ${lv}" title="${esc(c.text || '')} · 门槛 ${esc(c.need || '')}">
      <i>${mark}</i>${esc(c.label)}<b>${esc(val)}</b></span>`;
  }).join('');
  box.className = 'verdict v-' + v.level;
  box.hidden = false;
  box.innerHTML = `
    <div class="v-hd"><span class="v-ic">${icon}</span><b>${esc(v.label || '')}</b></div>
    <p class="v-note">${esc(v.note || '')}</p>
    <div class="v-chips">${chips}</div>`;
}

function renderBacktest() {
  const r = S.bt; if (!r) return;
  renderBtEmpty();
  renderBtVerdict(r.verdict);
  const s = r.summary;
  const kb = $('#bt-kpis');
  kb.innerHTML = [
    { k: '一共几笔', v: s.count, s: s.open ? `已卖掉 ${s.closed} 笔 · 还有 ${s.open} 笔没到卖出条件` : `全部卖掉后结算 ${s.closed} 笔`, c: '' },
    // 成本单独摆一格：先看毛利够不够付手续费和滑点，再看净收益才有意义
    { k: '扣成本前', v: (s.gross_ret > 0 ? '+' : '') + pct(s.gross_ret), s: `每笔来回成本约 ${(s.avg_cost || 0).toFixed(2)}%`, c: s.gross_ret > 0 ? 'up' : 'down' },
    { k: '扣成本后', v: (s.avg_ret > 0 ? '+' : '') + pct(s.avg_ret), s: s.gross_ret > 0 && s.avg_ret <= 0 ? '毛利被手续费吃光了' : `中间那个数 ${pct(s.med_ret)}`, c: s.avg_ret > 0 ? 'up' : 'down' },
    { k: '多少笔赚钱', v: pct(s.win_rate, 1), s: `不亏本至少要 ${pct(s.breakeven_wr || 0, 1)}`, c: s.win_rate >= (s.breakeven_wr || 50) ? 'up' : 'down' },
    { k: '亏小赚大', v: (s.payoff || 0).toFixed(2) + ' 倍', s: `赢的每笔平均 +${pct(s.avg_win)}，输的 ${pct(s.avg_loss)}`, c: s.payoff >= 1 ? 'up' : 'down' },
    // 稳健分：0.6×中位折 + 0.4×最差折（tick-stock-panel 的做法）。
    // 样本均值会被一笔幸运单拉高，看折间表现才说明不同环境下站不站得住。
    { k: '稳健分',
      v: s.robust == null ? '—' : (s.robust > 0 ? '+' : '') + pct(s.robust),
      s: s.robust == null ? (s.warn || '交易数不足 5 折')
        : `中位折 ${pct(s.median)} · 最差折 ${pct(s.worst)}${s.warn ? ' · ' + s.warn : ''}`,
      c: s.robust > 0 ? 'up' : 'down' },
    { k: '平均拿几天', v: s.avg_hold + '天', s: `赚最多一笔 +${pct(s.max_win)}，亏最多 ${pct(s.max_loss)}`, c: 'warn' },
  ].map(x => `<div class="kpi ${x.c}"><div class="k">${x.k}</div><div class="v">${x.v}</div><div class="s">${x.s}</div></div>`).join('');

  renderBtDist();

  const rs = Object.entries(s.reasons || {});
  const maxr = Math.max(1, ...rs.map(x => x[1]));
  const totalr = rs.reduce((a, b) => a + b[1], 0) || 1;
  // 按笔数从多到少排：后端 dict 的顺序是「首次出现」，不排会出现 11 笔排在 15 笔前面
  rs.sort((a, b) => b[1] - a[1]);
  $('#reason-box').innerHTML = rs.length ? rs.map(([k, v]) => `
    <div class="rs"><span>${esc(rc(k))}</span><div class="rbar"><i style="width:${v / maxr * 100}%"></i></div><b>${v}</b></div>`).join('')
    + `<div class="hintline">一共 ${totalr} 笔卖掉了。「从高点回落」占比最高是正常的 —— 这套规则本来就靠跟着趋势走；如果「跌到止损价」一大片，说明信号本身质量不够，别急着上手。</div>`
    : '<div class="muted">还没有交易记录</div>';

  const tb = $('#tb-bt');
  const rows = r.trades || [];
  const cov = r.coverage || {};
  const covTxt = cov.from
    ? ` · 实际检验 ${cov.from} ~ ${cov.to}（${cov.days} 个交易日；最前面约 120 个交易日用于筹码预热，不参与检验）`
    : '';
  $('#bt-meta').textContent = `看了 ${r.scanned} 只 · 用时 ${r.elapsed}s${covTxt} · ${r.note}`;
  tb.innerHTML = rows.length ? rows.map(t => `<tr data-code="${t.code}">
    <td class="code">${t.signal_date}</td><td>${t.buy_date}</td><td class="num">${fmt(t.buy)}</td>
    <td>${t.sell_date}</td><td class="num">${fmt(t.sell)}</td><td class="num">${t.hold}</td>
    <td class="num ${cls(t.ret)}">${t.ret > 0 ? '+' : ''}${fmt(t.ret)}%</td>
    <td class="num muted2">${t.gross != null ? (t.gross > 0 ? '+' : '') + fmt(t.gross) + '%' : '-'}</td>
    <td>${esc(rc(t.reason))}</td><td class="num">${fmt(t.profit_ratio, 1)}</td><td class="num">${fmt(t.pos, 1)}</td>
  </tr>`).join('') : '<tr class="empty"><td colspan="11">没有产生交易</td></tr>';
}

/* 单笔收益分布：按 -10% 以下 / -10~-5 / -5~0 / 0~5 / 5~10 / 10% 以上 六堆数一下。
   这一页不画资金曲线，改看「赢的赚多少、输的亏多少」，才是信号本身的质量。 */
function renderBtDist() {
  const box = $('#bt-dist'); if (!box) return;
  const r = S.bt; if (!r) return;
  const rows = (r.trades || []).filter(t => !t.open);
  if (!rows.length) { box.innerHTML = '<div class="muted">还没有卖掉的交易</div>'; return; }
  const bins = [
    ['亏 10% 以上', t => t.ret <= -10, 'down'],
    ['亏 5~10%', t => t.ret > -10 && t.ret <= -5, 'down'],
    ['亏 5% 以内', t => t.ret > -5 && t.ret < 0, 'down'],
    ['赚 5% 以内', t => t.ret >= 0 && t.ret < 5, 'up'],
    ['赚 5~10%', t => t.ret >= 5 && t.ret < 10, 'up'],
    ['赚 10% 以上', t => t.ret >= 10, 'up'],
  ].map(([k, f, c]) => [k, rows.filter(f).length, c]);
  const mx = Math.max(1, ...bins.map(b => b[1]));
  box.innerHTML = bins.map(([k, v, c]) => `
    <div class="rs"><span>${k}</span><div class="rbar"><i class="${c}" style="width:${v / mx * 100}%"></i></div><b>${v}</b></div>`).join('')
    + `<div class="hintline">赚的和亏的两头都得有：全是「赚 5% 以内」说明止盈太早、拿不住；「亏 10% 以上」冒头说明止损被跳空穿透了。</div>`;
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
        // 同信号检验：默认全市场抽样，不要绑死当天的名单
        codes: pfScope() === 'today' && S.items.length
          ? S.items.slice(0, lim).map(a => a.code) : null,
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
  const cov = r.coverage || {};
  const covTxt = cov.from ? ` · 覆盖 ${cov.from} ~ ${cov.to}（${cov.days} 个交易日，明细表按时间倒序，往下滚就是早年）` : '';
  $('#pf-meta').textContent = `看了 ${r.scanned} 只 · 能买的信号 ${r.candidates} 个 · 用时 ${r.elapsed}s${covTxt}`;
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

/* ================================================================ 详情抽屉 */
async function openDetail(code) {
  const dw = $('#drawer');
  // 大弹窗（page-modal，z=56）开着的时候，抽屉(z=55)会被压在它后面：
  // 用户看到的是弹窗没动、点什么都"没反应"，其实抽屉在底下已经开了。
  // 所以只要弹窗开着，先把弹窗收起来，再开抽屉。
  if (typeof pm !== 'undefined' && pm.id) closePane();
  dw.classList.add('show'); $('#mask').classList.add('show'); syncOverlayFlag();
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
  syncOverlayFlag();
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
  // 关卡以策略自己算的为准（后端 analyze 已经给了 key/label/ok/why，换方案自动跟着变）
  const rows0 = (a.gates && a.gates.length) ? a.gates : null;
  const keys = rows0
    ? rows0.map(g => [g.key, g.label])
    : gateKeys().map(([k, n]) => [k, n]);
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
  // 后端给了 why 就用后端的（策略自己解释得更准）
  const whyOf = (k) => {
    const g = rows0 && rows0.find(x => x.key === k);
    return (g && g.why) ? g.why : (why[k] || '这一条没通过');
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
      <h4>${keys.length} 条关卡逐条看
        <span class="spacer"></span>
        <span class="chip ${keys.every(([k]) => c[k]) ? 'warn' : ''}">${keys.filter(([k]) => c[k]).length}/${keys.length} 条符合</span>
      </h4>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px">
        ${keys.map(([k, n]) => `<span class="ck ${c[k] ? 'y' : 'n'}" title="${esc(c[k] ? '这一条符合' : whyOf(k))}" style="width:auto;padding:0 9px;border-radius:6px">${c[k] ? '✓' : '✗'} ${n}</span>`).join('')}
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

    <div class="dw-sec ksec">
      <h4>走势图 <span class="spacer"></span><span class="muted k-hint">滚轮缩放 · 拖动平移 · 双击复位</span></h4>
      <div class="kbar">
        <div class="tabs" id="k-tabs">
          <button class="tab active" data-per="day">日线</button><button class="tab" data-per="week">周线</button><button class="tab" data-per="month">月线</button><button class="tab" data-per="intraday">今天分时</button>
        </div>
        <div class="k-ovs" id="k-ovs">
          <button class="ktog on" data-ov="ma">均线</button><button class="ktog" data-ov="boll">布林</button>
        </div>
        <div class="k-sub" id="k-sub">
          <button class="ktog on" data-sub="vol">成交量</button><button class="ktog" data-sub="macd">MACD</button><button class="ktog" data-sub="kdj">KDJ</button><button class="ktog" data-sub="rsi">RSI</button>
        </div>
      </div>
      <canvas id="k-cv" class="kline"></canvas>
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
  // 走势图：日/周/月/分时 + 指标开关，状态记在 KLINE 里，换代码不会重来
  const cv = $('#k-cv');
  if (cv) {
    cv._kp = (cv._kp && PERIOD_NAME[cv._kp]) ? cv._kp : 'day';
    bindKlineInteraction(cv);
    const refresh = () => {
      if (!S.detail) return;
      drawKline(cv, S.detail, cv._kp);
      $('#k-note').innerHTML = klineNote(cv._kp);
    };
    $$('#k-tabs .tab').forEach(b => {
      b.classList.toggle('active', b.dataset.per === cv._kp);
      b.onclick = () => {
        cv._kp = b.dataset.per;
        if (PERIOD_NAME[cv._kp]) klineUI(cv._kp).off = 0;    // 切周期回到最新一段
        $$('#k-tabs .tab').forEach(x => x.classList.toggle('active', x === b));
        KLINE.hover = null; hideKlineTip();
        refresh();
      };
    });
    $$('#k-ovs .ktog').forEach(b => {
      const k = b.dataset.ov;
      b.classList.toggle('on', !!KLINE[k === 'ma' ? 'showMA' : 'showBOLL']);
      b.onclick = () => {
        if (k === 'ma') KLINE.showMA = !KLINE.showMA; else KLINE.showBOLL = !KLINE.showBOLL;
        b.classList.toggle('on', k === 'ma' ? KLINE.showMA : KLINE.showBOLL);
        refresh();
      };
    });
    $$('#k-sub .ktog').forEach(b => {
      b.classList.toggle('on', KLINE.sub === b.dataset.sub);
      b.onclick = () => {
        // 再点一次当前的指标 = 收起副图，把高度让给 K 线
        KLINE.sub = KLINE.sub === b.dataset.sub ? 'none' : b.dataset.sub;
        $$('#k-sub .ktog').forEach(x => x.classList.toggle('on', x.dataset.sub === KLINE.sub));
        refresh();
      };
    });
    refresh();
  }
}

/** 图下方的说明：换了周期 / 指标就换口径 */
function klineNote(per) {
  if (per === 'intraday') {
    return '白线是价格，黄线是平均成本（当天累计成交额÷累计成交量），以昨收为中轴对称画，上下距离一样 = 涨跌幅度一样；价格一直在黄线上方，说明今天进场的人成本被抬高、有人在持续买。';
  }
  const nm = PERIOD_NAME[per] || '日线';
  const sub = KLINE.sub === 'vol' ? '下面那排柱子是成交量'
    : KLINE.sub === 'macd' ? '副图是 MACD（柱子在零轴上红下绿）'
    : KLINE.sub === 'kdj' ? '副图是 KDJ（20 以下超卖、80 以上超买）'
    : KLINE.sub === 'rsi' ? '副图是 RSI（20 以下超卖、80 以上超买）' : '';
  return `红涨绿跌（和昨天比，不是和开盘比），空心是跌；${nm}，每一根就是${per === 'day' ? '一个交易日' : per === 'week' ? '一周' : '一个月'}。`
    + `${KLINE.showMA ? '均线按周期重新算，不是日线的均线硬缩成周线。' : ''}${sub ? sub + '，和 K 线逐根对齐。' : ''}`
    + `鼠标放上去看这一根的详细数据，滚轮缩放、按住拖动看更早的。`;
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

/* ================================================================ K 线图
   详情页的主图。三块面板竖着排：价格（K 线 + 均线 + 布林带）/ 成交量 / 副图指标，
   日、周、月共用同一套指标口径，切周期只换数据不换画法。

   几个和"画得好看"直接相关的决定：
   · 画在 canvas 里，但文字刻度、时间轴都自己算 —— 不能用 CSS 的字体度量，
     否则改了系统缩放比例就对不齐；
   · 右边留固定宽度放价格，十字光标只画在绘图区内，越界的线不画（之前那版
     价格标签会压在最后一根 K 线上，量柱和 K 线也对不齐）；
   · 时间轴不按"每根间隔画一个日期"来标，而是按**月份切换**打点 + 首尾和高低点，
     周线月线这样才不会一排日期挤在一起；
   · 悬停时把十字光标位置的整行数据（开高低收、涨跌、成交量、各指标值）列出来，
     比"只能看形状"有用得多 —— 这也是原来这张图最缺的东西。
   · 滚轮缩放 / 拖拽平移在 KLINE.ui 里记状态，切周期各自记各自的窗口。 */
const KLINE = {
  H: 470,
  showMA: true, showBOLL: false,
  sub: 'vol',                        // vol | macd | kdj | rsi | none
  ui: {},                            // period -> { z: 缩放倍率, off: 右端偏移(根) }
  tip: null,
  hover: null,
  MA_COL: ['#f2c14e', '#59b0ff', '#b07cff', '#28d1a6', '#ff8a4c'],
};
const KLINE_SUB = {
  vol: { name: '成交量', h: 84 },
  macd: { name: 'MACD', h: 92 },
  kdj: { name: 'KDJ', h: 92 },
  rsi: { name: 'RSI', h: 92 },
  none: { name: '', h: 0 },
};
const PERIOD_NAME = { day: '日线', week: '周线', month: '月线' };

/** 当前周期这份图的状态（缩放 / 右端偏移），没有就建一份 */
function klineUI(per) {
  if (!KLINE.ui[per]) KLINE.ui[per] = { z: 1, off: 0 };
  return KLINE.ui[per];
}
/** 某周期要画的根数：默认就是"把所有数据都塞进去"，缩小时最少 30 根 */
function klineView(dat, per) {
  const n = dat.length;
  const ui = klineUI(per);
  const size = Math.max(30, Math.min(n, Math.round(n / ui.z)));
  const off = Math.max(0, Math.min(n - size, Math.round(ui.off)));
  return { from: n - size - off, size, end: n - off };
}
/** 坐标点在绘图区里就画（十字光标 / 网格别溢到轴上去） */
function lineIn(g, x1, y1, x2, y2, box) {
  if (Math.min(x1, x2) > box.x + box.w || Math.max(x1, x2) < box.x) return;
  if (Math.min(y1, y2) > box.y + box.h || Math.max(y1, y2) < box.y) return;
  g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke();
}
/** 价格轴上的刻度值：取"好看"的步长（1/2/2.5/5 × 10^n），别出现 1327.43 这种刻度 */
function niceStep(range, n) {
  const raw = (range || 1) / Math.max(1, n);
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const f = raw / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
}
/** 成交量 / 金额的短写法：1.2 亿 / 3584 万 / 12.5 万 */
function volTxt(v) {
  v = +v || 0;
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(v >= 1e9 ? 1 : 2) + '亿';
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(v >= 1e6 ? 0 : 1) + '万';
  return String(Math.round(v));
}

function drawKline(cv, a, tab) {
  if (!cv) return;
  if (tab === 'intraday') { drawIntraday(cv, a); return; }
  const per = PERIOD_NAME[tab] ? tab : 'day';
  drawKChart(cv, a, per);
}

/* ------------------------------------------------ 当天分时 */
function drawIntraday(cv, a) {
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth || 700, H = 300;
  cv.width = W * dpr; cv.height = H * dpr; cv.style.height = H + 'px';
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  const pts = (a.intraday && a.intraday.points) || [];
  const avg = (a.intraday && a.intraday.avg) || [];
  if (!pts.length) {
    g.fillStyle = T().txt3; g.font = '12px sans-serif'; g.textAlign = 'left';
    g.fillText('今天还没有分时数据（没开盘或休市）', 12, 24); return;
  }
  const pad = { l: 8, r: 60, t: 10, b: 18 };
  const w = W - pad.l - pad.r, h = H - pad.t - pad.b;
  let lo = Math.min(...pts.map(p => p[1])), hi = Math.max(...pts.map(p => p[1]));
  avg.forEach(v => { if (v == null) return; lo = Math.min(lo, v); hi = Math.max(hi, v); });
  // 分时图以昨收为中心上下对称，涨跌幅度一眼可比（和看盘软件的习惯一致）
  const ref = (a.daily && a.daily.length) ? a.daily[a.daily.length - 1].close : (hi + lo) / 2;
  const half = Math.max(hi - ref, ref - lo) * 1.05 || 1;
  const cols = 241;                                   // 09:30-11:30 + 13:00-15:00
  const pos = t => {
    const [hh, mm] = String(t).split(':').map(Number);
    const m = hh * 60 + mm;
    return m <= 690 ? m - 570 : 120 + (m - 780);
  };
  const X = i => pad.l + w * Math.min(cols, pos(pts[i][0])) / (cols - 1);
  const Y = v => pad.t + h / 2 - (v - ref) / half * h / 2;
  g.strokeStyle = T().line; g.lineWidth = 1;
  [ref - half, ref - half / 2, ref, ref + half / 2, ref + half].forEach(v => lineIn(g, pad.l, Y(v), pad.l + w, Y(v), { x: pad.l, y: pad.t, w, h }));
  g.setLineDash([3, 3]); g.strokeStyle = T().txt3;
  [600, 690, 780].forEach(m => { const x = pad.l + w * Math.min(cols, (m <= 690 ? m - 570 : 120 + (m - 780))) / (cols - 1); lineIn(g, x, pad.t, x, pad.t + h, { x: pad.l, y: pad.t, w, h }); });
  g.setLineDash([]);
  g.beginPath(); avg.forEach((v, i) => { if (v == null) return; i ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v)); });
  g.strokeStyle = T().gold; g.lineWidth = 1.3; g.stroke();
  g.beginPath(); pts.forEach((p, i) => i ? g.lineTo(X(i), Y(p[1])) : g.moveTo(X(i), Y(p[1])));
  g.strokeStyle = T().accentSoft; g.lineWidth = 1.4; g.stroke();
  const last = pts[pts.length - 1][1];
  g.fillStyle = last >= ref ? T().up : T().down;
  g.beginPath(); g.arc(X(pts.length - 1), Y(last), 2.6, 0, Math.PI * 2); g.fill();
  g.font = '10px monospace'; g.textAlign = 'left';
  g.fillStyle = T().up; g.fillText(fmt(ref + half), pad.l + w + 5, pad.t + 9);
  g.fillStyle = T().txt3;
  g.fillText(fmt(ref + half / 2), pad.l + w + 5, Y(ref + half / 2) + 3);
  g.fillText(fmt(ref), pad.l + w + 5, Y(ref) + 3);
  g.fillText(fmt(ref - half / 2), pad.l + w + 5, Y(ref - half / 2) + 3);
  g.fillStyle = T().down; g.fillText(fmt(ref - half), pad.l + w + 5, pad.t + h);
  g.fillStyle = T().txt3;
  ['09:30', '10:30', '11:30/13:00', '14:00', '15:00'].forEach((s, i) => {
    const m = [570, 630, 690, 840, 900][i];
    const x = pad.l + w * Math.min(cols, (m <= 690 ? m - 570 : 120 + (m - 780))) / (cols - 1);
    g.textAlign = i === 0 ? 'left' : i === 4 ? 'right' : 'center';
    g.fillText(s, x, H - 5);
  });
}

/* ------------------------------------------------ 日 / 周 / 月 K 线主图 */
function drawKChart(cv, a, per) {
  const P = T();
  const dat = ((a.kline && a.kline[per]) || {}).bars || [];
  const K2 = (a.kline && a.kline[per]) || {};
  const dpr = window.devicePixelRatio || 1;
  // 高度跟着副图走：不显示副图时整张图矮一点，抽屉里不用滚半天
  const subH = KLINE_SUB[KLINE.sub] ? KLINE_SUB[KLINE.sub].h : 0;
  // 高度就按实际布局算出来，别写死 —— 否则副图一加，画布比内容矮，时间轴、图例全被裁掉
  const padT = 22, lgH = 30, priceH = 210, gap = 10;
  const showVol = !subH || KLINE.sub === 'vol';
  const volH = showVol ? 54 : 0;
  const H = padT + lgH + priceH + gap + volH + (subH ? 22 + subH + 16 : 16);
  cv.width = cv.clientWidth * dpr; cv.height = H * dpr;
  cv.style.height = H + 'px';
  const W = cv.clientWidth || 700;
  cv._k = { W, H, dpr, per };
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  if (!dat.length) {
    g.fillStyle = P.txt3; g.font = '12px sans-serif'; g.textAlign = 'left';
    g.fillText(`${PERIOD_NAME[per]}数据没取到（行情源可能临时不通，等会儿再点一次）`, 12, 24);
    return;
  }
  const v = klineView(dat, per);
  // 日线默认只放最近 240 根：把 641 根全塞进一屏，每根不到 1px，K 线和量柱全糊成一条、
  // 时间轴上的月份标签也会叠在一起。周线月线本身就不长（500+/120+），全放得下。
  if (per === 'day' && v.size > 240) {
    v.size = 240;
    v.from = Math.max(0, dat.length - 240 - klineUI(per).off);
    v.end = v.from + 240;
  }
  const N = v.size;
  // 主图下半的成交量，只有副图选"成交量"时才占位；选了 MACD/KDJ/RSI 就把它让给副图，
  // 不然一屏里有两块成交量，指标反而被挤成一条缝（showVol / volH 已在上面算好）

  const padL = 10, padR = 62;
  // 图例占两行：第一行均线/涨跌，第二行成交量均线 —— 全塞一行时和"涨/跌"挤在一起没法认
  const lgY1 = padT + 8;
  const w = W - padL - padR;

  // ---------------- 价格区间
  let lo = Infinity, hi = -Infinity;
  for (let i = v.from; i < v.end; i++) {
    lo = Math.min(lo, dat[i].l); hi = Math.max(hi, dat[i].h);
  }
  if (KLINE.showBOLL && K2.boll) {
    for (let i = v.from; i < v.end; i++) {
      const u = K2.boll.up[i], d2 = K2.boll.dn[i];
      if (u != null && isFinite(u)) hi = Math.max(hi, u);
      if (d2 != null && isFinite(d2)) lo = Math.min(lo, d2);
    }
  }
  const pad = (hi - lo) * 0.06 || hi * 0.02 || 1;
  hi += pad; lo -= pad;
  // 版面从上到下：图例两行 → 价格图 → 成交量条 → 副图 → 时间轴
  const priceTop = padT + lgH;
  const volTop = priceTop + priceH + gap, volBot = volTop + volH;
  const Yp2 = t => priceTop + priceH * (hi - t) / (hi - lo);   // 价格绘制区
  const hp = priceTop + priceH + gap + volH;                   // 主区底边
  const priceBox = { x: padL, y: priceTop, w, h: priceH };
  // "成交量 MA5 MA10" 这排字印在成交量块自己的顶上，把裁剪上移到这排字的上面；横向仍然裁在价格轴左边
  const clipTop = Math.max(0, volTop - 15);
  const subTop = hp + 22, subBot = subTop + subH;
  const axisY = subBot + 13;                    // 时间轴贴在整张图的最底下
  const cw = w / N;
  const bw = Math.max(1, Math.min(16, cw * 0.72));
  const X = i => padL + cw * (i - v.from) + cw / 2;
  const lastX = X(v.end - 1);

  // 裁到最右边：上面的图形只画到绘图区里，不遮右侧刻度标签
  g.save();
  g.beginPath(); g.rect(padL, 0, w, H); g.clip();
  const lastG = g;

  // ---------------- 网格 + 价格刻度
  const step = niceStep(hi - lo, 4);
  const firstG = Math.ceil(lo / step) * step;
  g.font = '10px monospace'; g.lineWidth = 1;
  for (let t = firstG; t <= hi; t += step) {
    const y = Yp2(t);
    g.strokeStyle = alpha(P.line, 0.55);
    lineIn(g, padL, y, padL + w, y, priceBox);
    g.strokeStyle = alpha(P.txt3, 0.16);
    lineIn(g, padL, y, padL + w, y, priceBox);
    g.fillStyle = P.txt3; g.textAlign = 'left';
    g.fillText((step < 0.1 ? t.toFixed(3) : fmt(t)), padL + w + 6, y + 3);
  }

  // ---------------- 布林带（放在 K 线下面，半透明填充）
  if (KLINE.showBOLL && K2.boll) {
    const drawBand = (arr, col) => {
      g.beginPath(); let started = false;
      for (let i = v.from; i < v.end; i++) {
        const y = arr[i];
        if (y == null || !isFinite(y)) { started = false; continue; }
        started ? g.lineTo(X(i), Yp2(y)) : (g.moveTo(X(i), Yp2(y)), started = true);
      }
      g.strokeStyle = col; g.lineWidth = 1; g.stroke();
    };
    drawBand(K2.boll.up, alpha('#b07cff', 0.75));
    drawBand(K2.boll.dn, alpha('#b07cff', 0.75));
    drawBand(K2.boll.mid, alpha('#b07cff', 0.45));
  }

  // ---------------- K 线（红涨绿跌）+ 成交量
  let vmax = 0;
  for (let i = v.from; i < v.end; i++) vmax = Math.max(vmax, dat[i].v || 0);
  const Yv = val => volBot - (volBot - volTop) * Math.max(0, val) / (vmax || 1);  for (let i = v.from; i < v.end; i++) {
    const k = dat[i];
    const pc = k.pc == null ? k.o : k.pc;
    const up = k.c >= pc;                       // 和看盘软件一致：和昨收比，不是和开盘比
    const col = up ? P.up : P.down;
    const x = X(i);
    g.strokeStyle = col; g.fillStyle = col;
    lineIn(g, x, Yp2(k.h), x, Yp2(k.l), priceBox);
    const y1 = Yp2(Math.max(k.o, k.c)), y2 = Yp2(Math.min(k.o, k.c));
    const bh = Math.max(1, y2 - y1);
    if (up) g.fillRect(x - bw / 2, y1, bw, bh);              // 涨：实心
    else {                                                   // 跌：空心（窄的时候实心，否则看不见）
      if (bw >= 3) { g.beginPath(); g.rect(x - bw / 2, y1, bw, bh); g.stroke(); }
      else g.fillRect(x - bw / 2, y1, bw, bh);
    }
    // 成交量柱：和 K 线用同一个颜色，涨跌一一对应
    if (showVol) {
      const yv = Yv(k.v);
      if (bw >= 3) { g.globalAlpha = 0.62; g.fillRect(x - bw / 2, yv, bw, volBot - yv); g.globalAlpha = 1; }
      else { g.fillStyle = alpha(col, 0.7); g.fillRect(x - bw / 2, yv, bw, volBot - yv); }
    }
  }

  // ---------------- 均线（价格区）
  if (KLINE.showMA && K2.ma) {
    [5, 10, 20, 60].forEach((n, j) => {
      const arr = K2.ma['ma' + n];
      if (!arr) return;
      g.beginPath(); let started = false;
      for (let i = v.from; i < v.end; i++) {
        const y = arr[i];
        if (y == null) { started = false; continue; }
        started ? g.lineTo(X(i), Yp2(y)) : (g.moveTo(X(i), Yp2(y)), started = true);
      }
      g.strokeStyle = KLINE.MA_COL[j]; g.lineWidth = 1; g.stroke();
    });
  }
  // ---------------- 成交量均线
  if (showVol && K2.vol && K2.vol.ma5) {
    [[K2.vol.ma5, alpha('#f2c14e', 0.85)], [K2.vol.ma10, alpha('#59b0ff', 0.8)]].forEach(([arr, col]) => {
      g.beginPath(); let started = false;
      for (let i = v.from; i < v.end; i++) {
        const y = arr[i];
        if (y == null) { started = false; continue; }
        started ? g.lineTo(X(i), Yv(y)) : (g.moveTo(X(i), Yv(y)), started = true);
      }
      g.strokeStyle = col; g.lineWidth = 1; g.stroke();
    });
  }
  g.strokeStyle = alpha(P.line, 0.9); g.lineWidth = 1;
  if (showVol) lineIn(g, padL, volBot, padL + w, volBot, priceBox);
  // 成交量那一块的标题（成交量 / MA5 / MA10 / 量比）统一在图例外画，见下方 drawKSubTitle

  // ---------------- 副图
  if (subH && KLINE.sub) drawKSub(g, P, K2, KLINE.sub, { X, v, N, padL, w, top: subTop, bot: subBot, cw,
    rows: (KLINE.hover && KLINE.hover.cv === cv && KLINE.hover.i >= v.from && KLINE.hover.i < v.end)
      ? KLINE.hover.i : v.end - 1 });

  // ---------------- 最新价线（价格轴上标出来，和现价对得上）
  const lastK = dat[v.end - 1];
  const yLast = Yp2(lastK.c);
  g.setLineDash([4, 3]); g.strokeStyle = alpha(P.gold, 0.7); g.lineWidth = 1;
  lineIn(g, padL, yLast, padL + w, yLast, priceBox);
  g.setLineDash([]);

  // ---------------- 十字光标 + 数据气泡
  const hv = KLINE.hover;
  const hasHover = !!(hv && hv.cv === cv && hv.i >= v.from && hv.i < v.end);
  if (hasHover) {
    const i = hv.i, x = X(i);
    const y = Math.max(priceTop, Math.min(priceTop + priceH, hv.y));
    g.strokeStyle = alpha(P.txt, 0.55); g.lineWidth = 1; g.setLineDash([3, 3]);
    lineIn(g, x, priceTop, x, showVol ? volBot : priceTop + priceH, priceBox);
    lineIn(g, padL, y, padL + w, y, priceBox);
    g.setLineDash([]);
    if (subTop < H) lineIn(g, x, subTop, x, subBot, priceBox);
    drawKlineTip(cv, a, per, K2, i, dat, x);
  } else hideKlineTip();
  g.restore();

  // ---------------- 时间轴：按月分界打竖线 + 标年月（周线月线不会挤）
  // 标签间距不够就隔几个月再标一次，否则 240 根日线的月份会叠成一坨。
  const MON_GAP = 64;
  g.textAlign = 'center';
  let lastMon = '', lastMX = -1e9;
  for (let i = v.from; i < v.end; i++) {
    const d = dat[i].d;
    const mon = d.slice(0, 7);
    if (mon !== lastMon) {
      if (lastMon) {
        g.strokeStyle = alpha(P.txt3, 0.16);
        lineIn(g, X(i) - cw / 2, priceTop, X(i) - cw / 2, showVol ? volBot : priceTop + priceH, priceBox);
        const lx0 = X(i);
        if (lx0 - lastMX >= MON_GAP && lastX - lx0 >= MON_GAP) {
          g.fillStyle = P.txt3;
          const lbl = mon.slice(0, 4) === lastMon.slice(0, 4) && per !== 'month' ? mon.slice(5) + '月' : mon.replace('-', '/');
          g.fillText(lbl, lx0, axisY);
          lastMX = lx0;
        }
      }
      lastMon = mon;
    }
  }
  // 首尾日期补在下方两端，让人知道窗口看到哪儿了（首尾日期宽约 70px、月份标签宽约 ±26px，
  // 间距不够就不画，免得叠成一坨）
  g.fillStyle = alpha(P.txt3, 0.85);
  const d0x = X(v.from), d1x = lastX;
  if (!(lastMX >= 0 && d0x + 70 + 26 > lastMX)) { g.textAlign = 'left'; g.fillText(dat[v.from].d, padL, axisY); }
  if (d1x - 26 - 36 > lastMX) { g.textAlign = 'right'; g.fillText(dat[v.end - 1].d, padL + w, axisY); }


  // 价格轴上的标签（最新价 / 鼠标价）要在裁剪外面画，否则会被裁掉
  {
    const gz = g;
    gz.fillStyle = alpha(P.gold, 0.92);
    gz.fillRect(padL + w + 1, yLast - 7, 58, 14);
    gz.fillStyle = P.chartBg || '#0b1017'; gz.font = 'bold 10px monospace'; gz.textAlign = 'left';
    gz.fillText(fmt(lastK.c), padL + w + 5, yLast + 3.5);
    if (hv && hv.cv === cv && hv.i >= v.from && hv.i < v.end) {
      const y = Math.max(priceTop, Math.min(priceTop + priceH, hv.y));
      const t = hi - (y - priceTop) / priceH * (hi - lo);
      gz.fillStyle = alpha(P.txt2, 0.22); gz.fillRect(padL + w + 1, y - 7, 58, 14);
      gz.fillStyle = P.txt; gz.textAlign = 'left';
      gz.fillText(fmt(t), padL + w + 5, y + 3.5);
    }
  }

  // ---------------- 图例 + 副图标题：都画在裁剪外面，免得被裁掉
  g.font = '10px monospace'; g.textAlign = 'left';
  let lx = padL;
  const chip = (y, col, txt) => {
    g.fillStyle = col; g.fillRect(lx, y - 4, 7, 3);
    g.fillStyle = P.txt3; g.fillText(txt, lx + 10, y);
    lx += 14 + g.measureText(txt).width + 6;
  };
  if (KLINE.showMA && K2.ma) [5, 10, 20, 60].forEach((n, j) => chip(lgY1, KLINE.MA_COL[j], 'MA' + n));
  if (KLINE.showBOLL) chip(lgY1, '#b07cff', 'BOLL');
  chip(lgY1, alpha(P.up, 0.95), '涨');
  chip(lgY1, alpha(P.down, 0.95), '跌');
  // 副图 / 成交量标题也走这一条带，给当前这一根的数值（默认最新一根）
  const titleRow = hasHover ? hv.i : v.end - 1;
  if (showVol) {
    drawKSubTitle(g, P, K2, 'vol', { padL, w, top: volTop + 11, rows: titleRow, dat });
  }
  if (subH && KLINE.sub && KLINE.sub !== 'vol') {
    drawKSubTitle(g, P, K2, KLINE.sub, { padL, w, top: subTop - 8, rows: titleRow, dat });
  }
  // 副图标题那一行给指标自己写
  cv._view = v;
}

/** 主图下半区的"成交量 MA5 MA10"标题 + 副图（MACD / KDJ / RSI）标题带数值。
    这一排必须画在裁剪外面，不然贴着成交量块顶上的字会被裁掉一半。 */
function drawKSubTitle(g, P, K2, sid, cfg) {
  const { padL, top } = cfg;
  const row = cfg.rows;
  g.font = '9.5px monospace';
  const right = padL + (cfg.w || 700) - 4;      // 不让字压到右边的价格刻度上去
  const seg = (x, col, txt) => {
    if (x + g.measureText(txt).width > right) return x;
    g.fillStyle = col; g.textAlign = 'left'; g.fillText(txt, x, top);
    return x + g.measureText(txt).width + 10;
  };
  if (sid === 'vol') {
    const k = (cfg.dat || [])[row] || {};
    let x = seg(padL + 2, P.txt3, '成交量 ' + volTxt(k.v) + '手');
    if (K2.vol && K2.vol.ratio && K2.vol.ratio[row] != null) x = seg(x, P.gold, '量比 ' + fmt(K2.vol.ratio[row], 2));
    if (K2.vol && K2.vol.ma5) x = seg(x, alpha('#f2c14e', 0.9), 'MA5 ' + volTxt(K2.vol.ma5[row]));
    if (K2.vol && K2.vol.ma10) seg(x, alpha('#59b0ff', 0.9), 'MA10 ' + volTxt(K2.vol.ma10[row]));
    return;
  }
  if (sid === 'macd' && K2.macd && K2.macd.dif) {
    let x = padL + 2;
    x = seg(x, P.gold, 'DIF ' + fmt(K2.macd.dif[row], 2));
    x = seg(x, P.accentSoft, 'DEA ' + fmt(K2.macd.dea[row], 2));
    seg(x, K2.macd.hist[row] >= 0 ? P.up : P.down, '柱 ' + fmt(K2.macd.hist[row], 2));
  }
  if (sid === 'kdj' && K2.kdj && K2.kdj.k) {
    let x = padL + 2;
    x = seg(x, P.gold, 'K ' + fmt(K2.kdj.k[row], 1));
    x = seg(x, P.accentSoft, 'D ' + fmt(K2.kdj.d[row], 1));
    seg(x, '#ff8a4c', 'J ' + fmt(K2.kdj.j[row], 1));
  }
  if (sid === 'rsi' && K2.rsi && K2.rsi.r6) {
    let x = padL + 2;
    x = seg(x, P.gold, 'RSI6 ' + fmt(K2.rsi.r6[row], 1));
    x = seg(x, P.accentSoft, 'RSI12 ' + fmt(K2.rsi.r12[row], 1));
    seg(x, '#b07cff', 'RSI24 ' + fmt(K2.rsi.r24[row], 1));
  }
}

/** 副图指标：成交量 / MACD / KDJ / RSI 四个里选一个，口径和通达信一致
    cfg.rows 指向"要看哪一根"（鼠标悬停的那根，否则最新一根），图例栏里直接给数值。 */
function drawKSub(g, P, K2, sid, cfg) {
  const { X, v, padL, w, top, bot } = cfg;
  const h = bot - top;
  if (sid === 'vol') return;                     // 成交量已经在主图下半，这里只是占位
  let lo = Infinity, hi = -Infinity;
  const put = x => { if (x == null || !isFinite(x)) return; lo = Math.min(lo, x); hi = Math.max(hi, x); };
  if (sid === 'macd') { [K2.macd.dif, K2.macd.dea, K2.macd.hist].forEach(a2 => { for (let i = v.from; i < v.end; i++) put(a2[i]); }); }
  if (sid === 'kdj') { ['k', 'd', 'j'].forEach(k => { const a2 = K2.kdj[k] || []; for (let i = v.from; i < v.end; i++) put(a2[i]); }); }
  if (sid === 'rsi') { ['r6', 'r12', 'r24'].forEach(k => { const a2 = K2.rsi[k] || []; for (let i = v.from; i < v.end; i++) put(a2[i]); }); }
  if (!isFinite(lo) || !isFinite(hi)) return;
  if (sid !== 'macd') { lo = Math.min(lo, 0); hi = Math.max(hi, 100); }
  const span = hi - lo || 1; lo -= span * 0.06; hi += span * 0.06;
  const Y = t => bot - h * (t - lo) / (hi - lo);
  const box = { x: padL, y: top, w, h };
  g.lineWidth = 1;
  g.strokeStyle = alpha(P.line, 0.5);
  if (sid === 'kdj' || sid === 'rsi') [0, 20, 50, 80, 100].forEach(t => lineIn(g, padL, Y(t), padL + w, Y(t), box));
  else if (sid === 'macd') [0].forEach(t => lineIn(g, padL, Y(t), padL + w, Y(t), box));
  g.fillStyle = P.txt3; g.font = '9.5px monospace'; g.textAlign = 'left';
  if (sid === 'kdj' || sid === 'rsi') [20, 80].forEach(t => g.fillText(String(t), padL + w + 6, Y(t) + 3));
  g.fillText(fmt(hi, sid === 'macd' ? 2 : 1), padL + w + 6, top + 9);
  g.fillText(fmt(lo, sid === 'macd' ? 2 : 1), padL + w + 6, bot);

  const lineOf = (arr, col, lw) => {
    g.beginPath(); let started = false;
    for (let i = v.from; i < v.end; i++) {
      const y = arr && arr[i];
      if (y == null) { started = false; continue; }
      started ? g.lineTo(X(i), Y(y)) : (g.moveTo(X(i), Y(y)), started = true);
    }
    g.strokeStyle = col; g.lineWidth = lw || 1; g.stroke();
  };
  if (sid === 'macd') {
    const hist = K2.macd.hist || [];
    for (let i = v.from; i < v.end; i++) {
      const val = hist[i]; if (val == null) continue;
      const y0 = Y(0), y1 = Y(val);
      g.fillStyle = val >= 0 ? alpha(P.up, 0.72) : alpha(P.down, 0.72);
      g.fillRect(X(i) - Math.max(0.7, cfg.cw * 0.3), Math.min(y0, y1), Math.max(1.2, cfg.cw * 0.6), Math.max(1, Math.abs(y1 - y0)));
    }
    lineOf(K2.macd.dif, P.gold, 1.1); lineOf(K2.macd.dea, P.accentSoft, 1.1);
  } else if (sid === 'kdj') {
    lineOf(K2.kdj.k, P.gold, 1.1); lineOf(K2.kdj.d, P.accentSoft, 1.1); lineOf(K2.kdj.j, '#ff8a4c', 1);
  } else if (sid === 'rsi') {
    lineOf(K2.rsi.r6, P.gold, 1); lineOf(K2.rsi.r12, P.accentSoft, 1.1); lineOf(K2.rsi.r24, '#b07cff', 1);
  }
}

/* ------------------------------------------------ 悬停气泡：这一根 K 线的全部数据
   原来只能看形状，想知道"这根涨了多少、量放没放、MACD 在哪"得自己数 ——
   现在鼠标一放上去，当天/当周/当月的开高低收、涨跌幅、振幅、量、量比、
   均线、布林、MACD/KDJ/RSI 全列出来。 */
function klineTipEl() {
  let el = document.getElementById('k-tip');
  if (!el) {
    el = document.createElement('div');
    el.id = 'k-tip'; el.className = 'k-tip'; el.hidden = true;
    document.body.appendChild(el);
  }
  return el;
}
function hideKlineTip() {
  const el = document.getElementById('k-tip');
  if (el) el.hidden = true;
}
function drawKlineTip(cv, a, per, K2, i, dat, x) {
  const el = klineTipEl();
  const k = dat[i];
  const pc = k.pc == null ? k.o : k.pc;
  const chg = pc ? (k.c / pc - 1) * 100 : null;
  const amp = pc ? (k.h - k.l) / pc * 100 : null;
  const cls2 = ch => ch > 0 ? 'up' : ch < 0 ? 'down' : '';
  const row = (n, val, c) => `<div class="tr"><i>${n}</i><b class="${c || ''}">${val}</b></div>`;
  let html = `<div class="tt">${esc(k.d)} <em>${PERIOD_NAME[per]}</em></div>`;
  html += `<div class="tg2">${row('开', fmt(k.o))}${row('高', fmt(k.h))}${row('低', fmt(k.l))}${row('收', fmt(k.c), cls2(chg))}</div>`;
  html += `<div class="tg2">${row('涨跌', chg == null ? '—' : (chg > 0 ? '+' : '') + fmt(chg) + '%', cls2(chg))}${row('振幅', amp == null ? '—' : fmt(amp) + '%')}</div>`;
  html += `<div class="tg2">${row('成交量', volTxt(k.v) + ' 手')}${row('量比', fmt(K2.vol && K2.vol.ratio && K2.vol.ratio[i], 2))}</div>`;
  const ma = K2.ma || {};
  const maVals = [5, 10, 20, 60].filter(n => ma['ma' + n] && ma['ma' + n][i] != null)
    .map(n => `<span style="color:${KLINE.MA_COL[[5, 10, 20, 60].indexOf(n)]}">MA${n} ${fmt(ma['ma' + n][i])}</span>`).join(' · ');
  if (maVals) html += `<div class="ts">${maVals}</div>`;
  if (K2.boll && K2.boll.up && K2.boll.up[i] != null) {
    html += `<div class="ts"><span style="color:#b07cff">BOLL ${fmt(K2.boll.up[i])} / ${fmt(K2.boll.mid[i])} / ${fmt(K2.boll.dn[i])}</span></div>`;
  }
  if (K2.macd && K2.macd.dif) html += `<div class="ts"><span style="color:var(--gold)">MACD ${fmt(K2.macd.dif[i], 2)}</span> · <span style="color:var(--accent-soft)">DEA ${fmt(K2.macd.dea[i], 2)}</span> · 柱 ${fmt(K2.macd.hist[i], 2)}</div>`;
  if (K2.kdj && K2.kdj.k) html += `<div class="ts"><span style="color:var(--gold)">K ${fmt(K2.kdj.k[i], 1)}</span> · <span style="color:var(--accent-soft)">D ${fmt(K2.kdj.d[i], 1)}</span> · <span style="color:#ff8a4c">J ${fmt(K2.kdj.j[i], 1)}</span></div>`;
  if (K2.rsi && K2.rsi.r6) html += `<div class="ts">RSI6 ${fmt(K2.rsi.r6[i], 1)} · RSI12 ${fmt(K2.rsi.r12[i], 1)} · RSI24 ${fmt(K2.rsi.r24[i], 1)}</div>`;
  el.innerHTML = html;
  el.hidden = false;
  // 贴着鼠标放，快出右边界就翻到左边（免得跑出屏幕看不见）
  const rc = cv.getBoundingClientRect();
  const tw = el.offsetWidth || 200, th = el.offsetHeight || 120;
  let bx = rc.left + x + 14, by = rc.top + 60;
  if (bx + tw > window.innerWidth - 8) bx = rc.left + x - tw - 14;
  if (by + th > window.innerHeight - 8) by = window.innerHeight - th - 8;
  el.style.left = Math.max(6, bx) + 'px';
  el.style.top = Math.max(6, by) + 'px';
}

/** 鼠标 / 滚轮 / 拖拽：给 K 线图绑交互（每张图只绑一次） */
function bindKlineInteraction(cv) {
  if (!cv || cv._kb) return;
  cv._kb = true;
  const idxAt = e => {
    const v = cv._view; if (!v) return -1;
    const r = cv.getBoundingClientRect();
    const padL = 10, padR = 62;
    const w = cv._k.W - padL - padR;
    if (e.clientX - r.left > padL + w) return -1;
    const cw = w / v.size;
    const i = v.from + Math.floor((e.clientX - r.left - padL) / cw);
    return Math.max(v.from, Math.min(v.end - 1, i));
  };
  const redraw = () => { const a = S.detail; if (a) drawKline(cv, a, cv._kp || 'day'); };
  cv.addEventListener('mousemove', e => {
    const i = idxAt(e);
    if (i < 0) { KLINE.hover = null; hideKlineTip(); redraw(); return; }
    if (cv._drag) {                       // 拖拽平移：鼠标往右拖 = 往过去看
      const per = cv._kp || 'day', dat = ((S.detail || {}).kline || {})[per] || {};
      const n = (dat.bars || []).length; if (!n) return;
      const ui = klineUI(per);
      const dx = e.clientX - cv._drag.x;
      const perPx = cv._k.W - 72;
      const size = Math.max(30, Math.min(n, Math.round(n / ui.z)));
      ui.off = Math.max(0, Math.min(n - size, cv._drag.off - dx * size / perPx));
      KLINE.hover = null; hideKlineTip(); redraw(); return;
    }
    KLINE.hover = { cv, i, y: e.clientY - cv.getBoundingClientRect().top };
    redraw();
  });
  cv.addEventListener('mouseleave', () => {
    KLINE.hover = null; hideKlineTip();
    const a = S.detail; if (a) redraw();
  });
  cv.addEventListener('mousedown', e => {
    const per = cv._kp || 'day', dat = ((S.detail || {}).kline || {})[per] || {};
    if (!((dat.bars || []).length)) return;
    const ui = klineUI(per);
    cv._drag = { x: e.clientX, off: ui.off };
    cv.style.cursor = 'grabbing';
  });
  window.addEventListener('mouseup', () => {
    if (cv._drag) { cv._drag = null; cv.style.cursor = 'crosshair'; }
  });
  cv.addEventListener('wheel', e => {
    const dat = ((S.detail || {}).kline || {})[cv._kp || 'day'] || {};
    if (!((dat.bars || []).length)) return;
    e.preventDefault();
    const ui = klineUI(cv._kp || 'day');
    ui.z = Math.max(1, Math.min(12, ui.z * (e.deltaY > 0 ? 0.82 : 1.22)));
    ui.off = 0;                       // 缩放后回到最右边（最新行情），最常看的就是这段
    KLINE.hover = null; hideKlineTip(); redraw();
  }, { passive: false });
  // 双击复位到"全部数据"
  cv.addEventListener('dblclick', () => {
    const per = cv._kp || 'day';
    KLINE.ui[per] = { z: 1, off: 0 };
    KLINE.hover = null; hideKlineTip(); redraw();
  });
}

/* ================================================================ 二级弹窗
   主页面上那些被挤窄的东西（自选股、全市场、记忆明细、检验/账户的细表、几组参数），
   在原来位置只留一句摘要 + 一个「⤢」；点「⤢」把整块摊到一屏里看 / 改。
   表格类不搬 DOM（表头排序、"点哪只"那些函数都是按 id 取的），而是现场再渲染一份，
   只在窄地方留摘要 —— 所以两边永远一致，也不会有重复 id。设置类相反：弹窗里改的是
   一份草稿，点保存才写回 #set-grid 再走原来的 POST。 */
const PANES = {
  watch: {
    t: '自选股', s: '按名字加，买点卖点自己弹。这里按整屏宽摆卡片',
    build: () => { paintWatchList($('#pm-body'), S.watchList || [], false); },
  },
  scan: {
    t: '全市场谁在托价', s: '人气股今天的变化，按整屏宽看列宽给足',
    build: () => {
      const box = $('#pm-body');
      box.innerHTML = '<div class="tablewrap pm-tw"><table class="grid" id="tbl-scan-pm"></table></div>';
      const src = $('#tbl-scan'), tgt = $('#tbl-scan-pm');
      if (!src) return;
      tgt.innerHTML = src.innerHTML;
      $$('#tbl-scan-pm tbody tr').forEach((tr, i) => tr.dataset.pmRow = i);   // 点行开着明细，和主页一致
      $('#pm-foot').textContent = `共 ${$$('#tbl-scan-pm tbody tr').length} 行 · 想看某只的明细就点那一行`;
    },
  },
  memday: {
    t: '那天之后的走势', s: '选了哪些、后来怎么走的，全屏看',
    build: () => {
      const box = $('#pm-body');
      const cv = $('#mem-chart'), tbl = $('#mem-table');
      if (!cv || !tbl || tbl.hidden) { box.innerHTML = '<div class="empty-state"><b>还没选到一天</b><span>先在「记忆」里点一天，再从这里打开</span></div>'; return; }
      box.innerHTML = `<div class="pm-panel">${cv.parentNode.querySelector('.ph').outerHTML}<canvas id="pm-mem-chart" class="cv" height="300"></canvas></div>
        <div class="pm-panel"><div class="ph"><b>一只一只看</b><span class="muted">${esc($('#mem-sub').textContent)}</span></div>
        <div class="tablewrap pm-tw">${tbl.querySelector('table').outerHTML}</div></div>`;
      $('#pm-sub').textContent = $('#mem-meta').textContent || '';
      drawChartTo('#pm-mem-chart', $('#mem-chart'));
    },
  },
  memdays: {
    t: '每天的成绩单', s: '一天一行，看这套规则稳不稳定',
    build: () => {
      const tbl = $('#mem-days');
      if (!tbl || tbl.hidden) { $('#pm-body').innerHTML = '<div class="empty-state"><b>还没有成绩单</b><span>选过几天之后这里会一天一行</span></div>'; return; }
      $('#pm-body').innerHTML = `<div class="tablewrap pm-tw">${tbl.querySelector('table').outerHTML}</div>`;
    },
  },
  bt: {
    t: '信号检验 · 全部结果', s: '只看这批信号本身好不好，赚多少钱请在「模拟账户」里看',
    build: () => {
      const box = $('#pm-body');
      if (!S.bt) {
        box.innerHTML = '<div class="empty-state"><b>还没检验过</b><span>先在本页点「开始检验」，跑完再回来看</span></div>'; return;
      }
      const tbl = $('#bt-table');
      // 结论卡跟着一起搬进来：大窗口里更该先看到"能不能用"，再谈细节
      const vd = $('#bt-verdict');
      const vdHtml = (vd && !vd.hidden) ? vd.outerHTML : '';
      box.innerHTML = `${vdHtml}<div class="pm-panel"><div class="ph"><b>一、信号质量</b></div><div class="kpis">${$('#bt-kpis').innerHTML}</div></div>
        <div class="pm-row2">
          <div class="pm-panel"><div class="ph"><b>一笔一笔赚了多少</b><span class="muted">每笔的净收益率 %，按区间分堆</span></div>${$('#bt-dist').innerHTML}</div>
          <div class="pm-panel"><div class="ph"><b>为什么卖出的</b></div>${$('#reason-box').innerHTML}</div>
        </div>
        <div class="pm-panel"><div class="ph"><b>二、一笔一笔看</b><span class="muted">${esc(($('#bt-meta') || {}).textContent || '')}</span></div>
          <div class="tablewrap pm-tw">${tbl.querySelector('table').outerHTML}</div></div>`;
    },
  },
  pf: {
    t: '模拟账户 · 全部明细', s: '钱只有一份，买满了就买不进，还要扣手续费和滑点',
    build: () => {
      const box = $('#pm-body'), tbl = $('#pf-table');
      if (!S.pf) {   // 还没模拟过：别把主页那几张空壳搬进来
        box.innerHTML = '<div class="empty-state"><b>还没模拟过</b><span>先在本页点「模拟一遍」，跑完再回来看全部明细。</span></div>';
        return;
      }
      box.innerHTML = `<div class="pm-panel"><div class="ph"><b>一、账户现在什么样</b></div><div class="kpis">${$('#pf-kpis').innerHTML}</div></div>
        <div class="pm-panel"><div class="ph"><b>账户余额怎么走的</b><span class="muted">现金 + 持仓市值，扣掉手续费和滑点</span></div><canvas id="pm-pf" class="cv" height="280"></canvas></div>
        <div class="pm-panel"><div class="ph"><b>二、一买一卖都记下来</b><span class="muted">${esc(($('#pf-meta') || {}).textContent || '')}</span></div>
          <div class="tablewrap pm-tw">${tbl.querySelector('table').outerHTML}</div></div>`;
      drawChartTo('#pm-pf', $('#pf-chart'));
    },
  },
  method: {
    t: '使用说明', s: '按类分开看，一屏一类',
    tabs: [['rule', '五个条件'], ['trade', '怎么买怎么卖'], ['data', '数据从哪来']],
    build: tab => {
      const src = $(`.meth-body[data-part="${tab}"]`);
      $('#pm-body').innerHTML = src
        ? `<div class="meth-body pm-meth">${src.innerHTML}</div>`
        : '<div class="empty-state"><b>这一节正在整</b></div>';
      if (src) { $('#pm-body').scrollTop = 0; }
    },
  },
  settings: {
    t: '参数设置', s: '一组一屏，改完点右上角保存',
    tabs: () => SET_META.map(c => [c.id, c.title]),
    save: true,
    build: (tab, h) => {
      const cat = SET_META.find(c => c.id === tab) || SET_META[0];
      const { params, weights } = h.draft || { params: S.cfg.params, weights: S.cfg.weights };
      $('#pm-body').innerHTML = `<div class="pm-set">${setCardHTML(cat, params, weights, h.dirty)}${cat.note ? `<p class="sc-note">${cat.note}</p>` : ''}</div>`;
      bindToggles($('#pm-body'));
    },
  },
};
/* canvas 不能 clone，弹窗里的图得照原图的像素重画一遍：原图和副本尺寸不一样，
   把原图的像素按比例铺满即可（曲线类图这样够用） */
function drawChartTo(sel, src) {
  const dst = $(sel);
  if (!dst || !src || !src.width) return;
  const k = Math.min(2, window.devicePixelRatio || 1);
  const W = dst.parentNode.clientWidth || 900, H = +dst.getAttribute('height') || 280;
  dst.width = W * k; dst.height = H * k; dst.style.height = H + 'px'; dst.style.width = W + 'px';
  const c = dst.getContext('2d');
  c.setTransform(k, 0, 0, k, 0, 0);
  c.drawImage(src, 0, 0, src.width, src.height, 0, 0, W, H);
}
/** 一张参数卡片（主页设置页和弹窗里共用一套渲染，免得两边样式/字段对不上） */
function setCardHTML(cat, p, w, dirty) {
  return `
    <div class="set-card${dirty ? ' dirty' : ''}" data-cat="${cat.id}">
      <h3>${cat.title}<em>${cat.tag}</em></h3>
      ${cat.fields.map(f => {
        const val = f.weight ? w[f.weight] : p[f.k];
        if (f.t === 'strat') {
          // 方案下拉：清单来自 /api/strategies，换一个就等于换一整套判定逻辑
          const list = (S.strats && S.strats.items) || [];
          const cur = p.strategy || (S.strats && S.strats.current) || 'oversold_bounce';
          const one = list.find(x => x.key === cur) || {};
          return `<div class="frow"><label>${f.n}${f.hint ? `<small>${f.hint}</small>` : ''}</label>
            <select data-k="strategy" data-t="str">${list.map(x =>
              `<option value="${x.key}" ${x.key === cur ? 'selected' : ''}>${esc(x.name)}${x.user ? '（自己写的）' : ''}</option>`
            ).join('')}</select></div>
            ${one.desc ? `<div class="strat-desc">${esc(one.desc)}</div>` : ''}
            ${one.gates && one.gates.length ? `<div class="strat-gates">${one.gates.map(g =>
              `<span class="sgat" title="${esc(g.hint || '')}">${esc(g.label)}</span>`).join('')}</div>` : ''}`;
        }
        if (f.t === 'stratops') {
          return `<div class="frow strat-ops">
            <label>自己做一套<small>放进 data/strategies 就能用，不用改程序</small></label>
            <span class="ops">
              <button class="btn sm ghost" id="btn-strat-tpl">取模板</button>
              <button class="btn sm ghost" id="btn-strat-reload">重新加载</button>
            </span></div>`;
        }
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
    </div>`;
}
function bindToggles(root) {
  $$('.toggle[data-k]', root || document).forEach(b => b.onclick = () => {
    b.classList.toggle('on');
    const box = b.closest('.mb');
    if (box) box.dispatchEvent(new Event('pm-dirty'));   // 开关也得算"改过"
  });
  // 「自己做一套」两个按钮：生成模板 = 在 data/strategies 里放一份能直接改的样板；重新加载 = 改完不用重启
  $$('#btn-strat-tpl', root || document).forEach(b => b.onclick = () => newStrategyFile());
  $$('#btn-strat-reload', root || document).forEach(b => b.onclick = () => reloadStrategies());
}

/** 在 data/strategies 里生成一份模板文件，用户拿记事本改就行 */
async function newStrategyFile() {
  try {
    const r = await api('/api/strategy/new', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    toast(`已生成：${r.path} —— 用记事本打开改数字，改完点「重新加载」`);
  } catch (e) { toast('生成失败：' + e.message, true); }
}

/** 重新加载 data/strategies/*.py（不用重启服务） */
async function reloadStrategies() {
  try {
    const r = await api('/api/strategy/reload');
    S.strats = { items: r.items, current: (S.cfg && S.cfg.params && S.cfg.params.strategy) || '' };
    const errs = r.errors || {};
    const bad = Object.keys(errs);
    if (bad.length) {
      toast(`加载完成，但有 ${bad.length} 个文件报错：${bad.join('、')}`, true);
      console.warn('策略加载错误', errs);
    } else {
      toast(`已重新加载，现在有 ${r.count} 套方案`);
    }
    renderSettings();
  } catch (e) { toast('重新加载失败：' + e.message, true); }
}
const pm = { id: null, tab: null, draft: null, dirty: false };
/** 抽屉/大弹窗开着时给 body 挂个标记，CSS 用它把右下角的提醒卡收掉，
    否则提醒卡（z=70）会压在抽屉（z=55）上面，把关闭按钮挡掉。 */
function syncOverlayFlag() {
  const dw = document.getElementById('drawer');
  const pg = document.getElementById('page-modal');
  const on = (dw && dw.classList.contains('show')) || (pg && !pg.hidden);
  document.body.classList.toggle('ovl-open', !!on);
}
/** 打开二级弹窗：id 见 PANES，tab 可选（参数分组 / 说明的小节） */
function openPane(id, tab) {
  const P = PANES[id];
  if (!P) return;
  pm.id = id;
  const tabs = typeof P.tabs === 'function' ? P.tabs() : P.tabs;
  pm.tab = tab || (tabs ? tabs[0][0] : null);
  pm.dirty = false;
  pm.draft = (id === 'settings' && S.cfg) ? { params: { ...S.cfg.params }, weights: { ...S.cfg.weights } } : null;
  $('#pm-title').textContent = P.t;
  $('#pm-sub').textContent = P.s || '';
  $('#pm-save').hidden = !P.save;
  const seg = $('#pm-tabs');
  seg.hidden = !tabs;
  seg.innerHTML = tabs ? tabs.map(([k, n]) => `<button data-pm-tab="${k}" class="${k === pm.tab ? 'on' : ''}">${n}</button>`).join('') : '';
  const bar = $('#pm-tabbar');
  if (bar) bar.hidden = !tabs;
  paintPanes();
  paintIcons($('#page-modal'));
  // 先摘掉 hidden 再测量：.modal 带 [hidden]{display:none}，藏着量 getBoundingClientRect 恒为 0
  $('#page-modal').hidden = false;
  $('#pm-mask').classList.add('show');
  syncOverlayFlag();
  fitPane();
  $('#pm-body').scrollTop = 0;
  setTimeout(() => ($('#pm-close') || {}).focus && $('#pm-close').focus(), 30);
}
/** 内容不够一屏就别留一大片空：按实际内容高度收，最多到 92vh（CSS 里是上限） */
function fitPane() {
  const m = $('#page-modal');
  m.style.height = 'auto';
  const h = Math.min(m.scrollHeight, Math.round(innerHeight * 0.92));
  m.style.height = h + 'px';
}
function paintPanes() {
  const P = PANES[pm.id];
  if (!P) return;
  $('#pm-body').innerHTML = '';
  P.build(pm.tab, pm);
  $$('#pm-tabs button').forEach(b => b.classList.toggle('on', b.dataset.pmTab === pm.tab));
  if ($('#page-modal') && !$('#page-modal').hidden) fitPane();   // 换页签后内容高度变了
}
function closePane() {
  if (!pm.id) return;
  const wasDirty = pm.dirty;
  const id = pm.id;
  pm.id = null; pm.dirty = false; pm.draft = null;
  $('#page-modal').hidden = true;
  $('#pm-mask').classList.remove('show');
  syncOverlayFlag();
  // 改到一半就关：说明白，别让人以为已经存了
  if (wasDirty && id === 'settings') toast('参数没保存，还是原来的');
}
/** 弹窗里点「保存」：把草稿写回主页设置页那份 DOM，再走原来的保存流程 */
function savePane() {
  if (pm.id !== 'settings' || !S.cfg) return;
  const { params, weights } = collectSettings($('#pm-body'));
  Object.assign(S.cfg.params, params);
  Object.assign(S.cfg.weights, weights);
  pm.dirty = false;
  pm.id = null;
  renderSettings();          // 主页那份跟着刷新
  $('#page-modal').hidden = true;
  $('#pm-mask').classList.remove('show');
  syncOverlayFlag();
  saveSettings();
}

/* ================================================================ 设置 */
const SET_META = [
  { id: 'strategy', title: '用哪套选股方案', tag: 'STRAT', fields: [
    { k: 'strategy', n: '选股方案', t: 'strat', hint: '换一套逻辑就换这里；自己写的方案放在 data/strategies 里会自动出现' },
    { k: '_strat_ops', n: '管理', t: 'stratops', hint: '' },
  ]},
  { id: 'market', title: '市场状态开关', tag: '环境',
    note: '这套规则是<b>超跌反转</b>，赚的是恐慌盘砸出来的错杀价。165 笔回测验证：<br>'
      + '· 大盘在 20 日均线下方 1% 以上时（真弱势）—— 60 笔、胜率 52%、每笔平均 <b>+1.51%</b><br>'
      + '· 大盘站上 20 日均线或贴近时 —— 69 笔、胜率 25%、每笔平均 <b>-1.27%</b><br>'
      + '开关打开后，市场状态不匹配就<b>不出可买名单</b>（本来会选中的进观察池），实测能把账户从 -5.5% 拉到 +22%。<br>'
      + '<span style="opacity:.75">注意：量能（成交量放大/缩小）不是有效判据，组间差不到 1 个百分点。</span>',
    fields: [
      { k: 'market_gate', n: '市场状态不匹配时暂停买入', t: 'bool', hint: '推荐开。关掉就是不看大盘、硬跑，回测 -5.5%' },
      { k: 'market_gate_pct', n: '放行阈值（大盘比 MA20 低几个百分点）', t: 'float', step: 0.5, min: 0, max: 20, hint: '默认 1。调大更保守（只在大盘更弱时才买），调到 0 表示只要大盘在均线下面就买' },
    ]},
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
    { k: 'tail_from', n: '在几点判定（等于你实际下单的时间）', t: 'select', opts: [['14:45', '14:45（推荐）'], ['14:30', '14:30'], ['14:50', '14:50'], ['14:57', '14:57'], ['close', '收盘']], hint: '定在这儿之后，名单才定型、才会进记忆；记下来的买入价就是这个时点的价' },
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

/** 主页那份分组卡片：每组只显示前 4 项，剩下的进弹窗看。
    设置项和弹窗共用 setCardHTML，字段/单位不会两边不一致 */
function renderSettings() {
  if (!S.cfg) return;
  // ---- 顶部的「锁定 / 解锁」横幅 ----
  // 默认锁定：80 个参数对大多数场景是负担，而误改一个阈值就足以让整套逻辑跑偏。
  // 锁定时只挡主页的快捷编辑（防误触）；点进弹窗是明确要改，那里仍然可编辑。
  const locked = S.paramsLocked !== false;
  const bar = $('#param-lock-bar');
  if (bar) {
    bar.className = 'param-lock ' + (locked ? 'on' : 'off');
    bar.innerHTML = `
      <b>${locked ? '参数已锁定（推荐设置）' : '参数已解锁'}</b>
      <span>${locked
        ? '当前是 40 笔回测、稳健分 +3.08 那一套，不用改也能直接用。'
        : '改完记得点右上角「保存」。改坏了可以用右边一键恢复。'}</span>
      <button class="btn sm" id="param-lock-btn">${locked ? '我要自己调' : '锁定回去'}</button>
      ${locked ? '' : '<button class="btn sm ghost" id="param-reset-btn">恢复推荐设置</button>'}`;
    const btn = $('#param-lock-btn');
    if (btn) btn.onclick = () => { S.paramsLocked = !locked; renderSettings(); };
    const rb = $('#param-reset-btn');
    if (rb) rb.onclick = async () => {
      try {
        await api('/api/config/reset', {}, 'POST');
        await loadConfig();
        toast('已恢复推荐设置');
      } catch (e) { toast('恢复失败：' + (e.message || e), true); }
      renderSettings();
    };
  }
  $('#set-grid').innerHTML = SET_META.map(cat => {
    const head = cat.fields.slice(0, 4), rest = cat.fields.length - head.length;
    return `
    <div class="set-card" data-cat="${cat.id}">
      <h3>${cat.title}<em>${cat.tag}</em><button class="btn sm ghost set-open" data-open="settings" data-tab="${cat.id}">${rest > 0 ? `还有 ${rest} 项` : '开'}<em>⤢</em></button></h3>
      ${setCardBody(cat, head, S.cfg.params, S.cfg.weights)}
      ${rest > 0 ? `<button class="set-more" data-open="settings" data-tab="${cat.id}">这组还有 ${rest} 项 →</button>` : ''}
    </div>`;
  }).join('');
  // 渲染完再禁用：锁定时主页的快捷编辑框全部置灰（防误触）。
  // 弹窗是用户明确要改，那里仍然可编辑。
  if (locked) {
    $$('#set-grid [data-k]').forEach(el => { el.disabled = true; });
  }
  bindToggles($('#set-grid'));
  initRunlog();
}

/** 运行日志：默认收起，展开时才去拉 —— 平时不看，出事时第一个要看的东西。
 *
 *  为什么放在设置页最底部：它属于"维护信息"，不该占主界面的位置；
 *  但也不能只藏在文件系统里 —— 用户不一定会去翻 data/logs/。
 */
function initRunlog() {
  const box = $('#runlog-box');
  if (!box || box.dataset.wired) return;
  box.dataset.wired = '1';
  const meta = $('#runlog-meta'), pre = $('#runlog-pre');
  box.addEventListener('toggle', async () => {
    if (!box.open) return;
    meta.textContent = '加载中…';
    try {
      const r = await api('/api/log?n=100');
      const lines = r.lines || [];
      const bad = (r.last_error || '').trim();
      meta.textContent = `今天 ${r.line_count || 0} 条` + (bad ? ' · 有异常' : ' · 无异常')
        + (r.file ? ` · ${String(r.file).split(/[\\/]/).pop()}` : '');
      pre.textContent = lines.length ? lines.join('\n') : '今天还没有记录';
      pre.scrollTop = pre.scrollHeight;
      pre.classList.toggle('has-err', !!bad);
    } catch (e) {
      meta.textContent = '读不到日志';
      pre.textContent = String((e && e.message) || e);
    }
  });
}
/** 一张卡里那些 frow（head 为空就是全部字段） */
function setCardBody(cat, head, p, w) {
  const sub = { ...cat, fields: head };
  const html = setCardHTML(sub, p, w, false);
  // 只要卡片内部那几行 .frow，外面那层 .set-card 和 <h3> 标题都由调用方自己带
  // （setCardHTML 输出形如 `<div class="set-card" ...><h3>...</h3>行...</div>`，
  //   把开标签吃掉之后再掐掉 h3，剩下的就是纯字段行）
  const inner = html.slice(html.indexOf('>') + 1, html.lastIndexOf('</div>'));
  return inner.replace(/^\s*<h3>[\s\S]*?<\/h3>/, '');
}

/**
 * 从 DOM 收集参数。
 *
 * ⚠️ 关键：主页 #set-grid 每组只渲染前 4 项、弹窗 #pm-body 只渲染当前页签那一组。
 * 所以「DOM 上没出现的字段」必须保留 S.cfg 里原来的值，不能被丢掉 ——
 * 否则点保存就等于把没显示出来的参数（比如创业板过滤）全清空/回滚成默认。
 * 这里以 S.cfg 为底，DOM 上找到的字段覆盖上去。
 */
function collectSettings(root = $('#set-grid')) {
  const params = { ...((S.cfg && S.cfg.params) || {}) };
  const weights = { ...((S.cfg && S.cfg.weights) || {}) };
  $$('[data-k]', root).forEach(el => {
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

/* ================================================================ 隔夜低吸（首阴套利）
   和「选股」页那套完全独立的一条线：
     那边 14:45 决策、按收盘价买、持有几天跌破均价线才走；
     这边收盘后出名单、次日开盘买、当天收盘必须卖，不留隔夜。
   账本在 data/overnight/，不并进 data/memory/ —— 持有期不同，混在一起算总账两边都失真。 */
async function loadOvernight() {
  const busy = $('#ovn-loading');
  if (busy) busy.hidden = false;
  try { S.ovn = await api('/api/overnight'); } catch (_) { S.ovn = null; }
  if (busy) busy.hidden = true;
  renderOvernight();
}

async function rescanOvernight() {
  const btn = $('#btn-ovn-scan');
  const old = btn ? btn.innerHTML : '';
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spin"></span>生成中…'; }
  try {
    S.ovn = await api('/api/overnight/scan', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}'
    });
    toast('已按最新行情重新生成明日名单');
  } catch (e) {
    toast('生成失败：' + (e && e.message ? e.message : e), true);
  }
  if (btn) { btn.disabled = false; btn.innerHTML = old; }
  renderOvernight();
}

/** 隔夜低吸页的全部用户可见文案 —— 只按 pending_ctx 选一套。

    为什么单独拎出来：这些句子原来散在 100 多行渲染代码里，写死了"明日待买"，
    周一盘中打开就会说错话（那份名单其实是今天要买的，9:25 可能已经过了）。
    现在只有这一个函数决定措辞，改文案不用碰渲染，也不会再出现"标题说今天、数字说待买"。

    phase 的取值来自 overnight._pending_ctx()：
      waiting(offset 0/1/-1)  有待买，买点是今天 / 之后 / 已过期
      signaled                今天已经出过信号（待买为空；买没买看每行 exec）
      fresh                   扫过了，确实没有符合条件的票
      no_scan                 还没跑过扫描 —— 和"没有票"是两件事
*/
function overnightCopy(ctx, signals) {
  const off = ctx.offset, buyOn = ctx.buy_date || '';
  const phase = ctx.phase || 'fresh';

  if (phase === 'waiting') {
    if (off === 0) {
      return { kpi: '今天待买', sub: '今天 9:25 挂单', title: '今天待买',
        note: '今天 9:25 集合竞价挂单，成交价就是开盘价', how: '今天 9:25 挂市价' };
    }
    if (off === -1) {
      return { kpi: '待买·已过期', sub: (buyOn || '') + ' 的开盘已过', title: '待买（已过期）',
        note: `这批该在 ${buyOn} 开盘买，已经过了；收盘后会自动记一笔「错过」`, how: '已过期',
        empty: `这批信号（${ctx.signal_date || '—'} 收盘选出）的买点已经过去，不会再执行` };
    }
    return { kpi: '明日待买', sub: `次日 ${buyOn} 9:25 挂单`, title: '明日待买',
      note: `${buyOn} 9:25 集合竞价挂单，成交价就是开盘价`, how: '次日 9:25 挂市价' };
  }
  if (phase === 'signaled') {
    const n = (signals || []).length;
    return { kpi: '今天信号', sub: '在下面标记买没买', title: '今天这批已记录',
      note: '见下面「今日信号」—— 买没买点一下，收盘后按影子收益结算',
      empty: `今天记录了 ${n} 只，见下面「今日信号」；买没买随手标一下就行` };
  }
  if (phase === 'no_scan') {
    return { kpi: '待买', sub: '名单还没生成', title: '待买名单还没生成',
      note: `上次生成：${ctx.scan || '从未'}　·　点左上角「重新生成明日名单」`,
      empty: '还没跑过收盘扫描，所以没有名单 —— 不是"没有票"' };
  }
  return { kpi: '明日待买', sub: '没有符合条件的票', title: '明日待买',
    note: '收盘后自动生成',
    empty: '今天没有符合条件的票 —— 连板 ≥3 且收实体阴线的，全市场一只都没有' };
}

function renderOvernight() {
  const d = S.ovn;
  const st = (d && d.stats) || {};
  const pend = (d && d.pending) || [];
  // signals = 今天的「信号」，不是你买了的持仓。买没买看每行的 exec：
  // null=还没标 / true=买了 / false=没买。价格和影子收益跟这个字段无关，一律留档。
  const signals = (d && d.signals) || [];
  const recent = (d && d.recent) || [];
  const show = (sel, on) => { const el = $(sel); if (el) el.hidden = !on; };

  const b = $('#btn-ovn-scan');
  if (b && !b.onclick) b.onclick = rescanOvernight;
  // 导出的 CSV 就是账本本身：验证"弱板是不是更差"这类假设得在表格里分组，
  // 界面上只能看单笔，点不出结论。
  const bx = $('#btn-ovn-export');
  if (bx && !bx.onclick) bx.onclick = () => {
    if (!(d.recent || []).length) { toast('还没有成交记录，导出来只有表头', true); return; }
    location.href = '/api/overnight/export';
  };

  if (!d) {
    show('#ovn-empty', true);
    show('#ovn-kpis', false);
    ['#ovn-pending', '#ovn-open', '#ovn-recent'].forEach(s => show(s, false));
    const m = $('#ovn-meta'); if (m) m.textContent = '读取失败，刷新一下试试';
    return;
  }
  show('#ovn-empty', false);

  const pct = v => (v == null ? '—' : (v > 0 ? '+' : '') + fmt(v, 2) + '%');
  const cls = v => (v == null ? '' : (v > 0 ? 'up' : (v < 0 ? 'down' : '')));

  // 文案表单独成函数（overnightCopy），这里只取结果 —— 改文案不用翻渲染逻辑
  const ctx = d.pending_ctx || {};
  const phase = ctx.phase || 'fresh';
  const COPY = overnightCopy(ctx, signals);

  // 数量要跟标题对上：写"今天信号"，数字就得是今天抓到的条数，不是待买数。
  const todaySig = signals.filter(o => String(o.buy_date || '') === String(ctx.buy_date || '')).length;
  const kv = phase === 'signaled' ? todaySig : pend.length;
  const sg = st.signal || {}, rl = st.real || {};
  const uns = signals.filter(x => x.exec == null).length;

  // 两张核心卡：全部信号（衡量规则） / 实际买入（衡量执行）。
  // 分开摆是刻意的 —— 混在一起就分不清"规则不行"还是"我没执行好"。
  $('#ovn-kpis').innerHTML = [
    { k: COPY.kpi, v: kv ? kv + ' 只' : '0 只', s: COPY.sub },
    { k: '待标记', v: uns ? uns + ' 只' : '0 只',
      s: uns ? '点一下买没买，不点也留档' : '都标过了' },
    { k: '全部信号', v: (sg.n || 0) + ' 笔',
      s: sg.n ? '影子收益，衡量规则本身' : '收盘结算后就有' },
    { k: '实际买入', v: (rl.n || 0) + ' 笔',
      s: rl.n ? '只算你标记买了的' : '还没有标记过成交' },
    { k: '平均每笔（全部信号）', v: sg.avg == null ? '—' : pct(sg.avg),
      c: cls(sg.avg),
      s: sg.n ? `胜率 ${fmt(sg.win_rate, 0)}% · 中位 ${pct(sg.med)}` : '样本还不够' },
    { k: '盈亏比（全部信号）', v: sg.payoff == null ? '—' : fmt(sg.payoff, 2),
      s: sg.payoff == null ? (sg.n ? '还没出现亏损样本' : '样本不够') : '赚的比亏的多多少倍' },
  ].map(x => `<div class="kpi"><div class="k">${x.k}</div><div class="v ${x.c || ''}">${x.v}</div><div class="s">${x.s || ''}</div></div>`).join('');

  // 板块格子：有板块就说「板块 · 今天同板块几只涨停」，没有就老实说没有。
  // 同板块今天还有票在涨停 = 题材没死，明天低开才有承接 —— 这是"题材核心"的唯一可行代理。
  // 炸板次数是判断"板结不结实"的唯一直接证据：
  // 实测 4 连板的光洋股份当天炸板 17 次、封单只剩 853 万、换手 27.9% —— 弱板。
  // 弱板的首阴次日反弹也弱，值得在名单上直接标出来。
  const zbcTag = x => {
    const n = Number(x.zbc) || 0;
    if (!n) return '';
    return `<em class="ts" title="上一个交易日封板期间被打开 ${n} 次，次数越多板越弱">炸${n}次</em>`;
  };

  const boardCell = x => {
    if (!x.board) return '<span class="muted">—</span>';
    const n = Number(x.n_board) || 0;
    return `${esc(x.board)}<span class="muted">${n ? ' · 今日 ' + n + ' 只涨停' : ' · 今日该板块无涨停'}</span>`;
  };

  const marks = d.marks || {}, pa = d.params || {};
  const meta = $('#ovn-meta');
  if (meta) {
    meta.textContent = `上次生成 ${marks.scan || '还没跑过'}　·　连板 ≥${pa.min_streak}、实体阴线 ≥1%`
      + `　·　执行率 ${st.exec_rate == null ? '—' : fmt(st.exec_rate, 0) + '%'}`
      + (st.gaps ? `（另有 ${st.gaps} 天开盘价没抓到）` : '')
      + (d.emotion && d.emotion.n
        ? `　·　${d.emotion.date} 涨停 ${d.emotion.n} 只、最高 ${d.emotion.max_lbc} 板`
        : '');
  }

  // ---- 待买：只在"真有待买"或"该说清为什么没有"时显示。
  // phase=signaled 时下面是「今日信号」，再摆一块空表格纯属占版面。
  show('#ovn-pending', pend.length > 0 || phase === 'fresh' || phase === 'no_scan');
  const ph = document.querySelector('#ovn-pending .ph');
  if (ph) {
    const b = ph.querySelector('b'), sp = ph.querySelector('.muted');
    if (b) b.textContent = COPY.title;
    if (sp) sp.textContent = COPY.note;
  }
  $('#tb-ovn-pending').innerHTML = pend.length
    ? pend.map(x => `<tr>
        <td class="code">${esc(x.code)}</td>
        <td class="name">${esc(x.name || '')}</td>
        <td class="num">${x.streak == null ? '—' : x.streak}${zbcTag(x)}</td>
        <td>${boardCell(x)}</td>
        <td class="num">${x.signal_close == null ? '—' : fmt(x.signal_close)}</td>
        <td class="num ${cls(x.chg)}">${x.chg == null ? '—' : fmt(x.chg, 2) + '%'}</td>
        <td class="muted">${COPY.how || '9:25 集合竞价挂市价'}</td>
      </tr>`).join('')
    : `<tr class="empty"><td colspan="7">${esc(COPY.empty)}</td></tr>`;

  // 记录状态：补记的要说清"几点抓的"，否则分不清是盘中真做了决定还是事后补的
  const capState = x => {
    if (x.deferred) return '跌停卖不掉，顺延 ' + x.deferred + ' 天';
    const at = String(x.captured_at || '');
    if (x.flag) return x.flag;
    if (at && x.on_time === false) return `补记于 ${at}`;
    return at ? `开盘 ${at} 记录` : '已记录';
  };

  // ---- 今日信号：不管买没买都在这儿，买没买由你点
  show('#ovn-open', signals.length > 0);
  if (signals.length) {
    $('#tb-ovn-open').innerHTML = signals.map(x => {
      const ex = x.exec;            // null / true / false
      return `<tr data-code="${esc(x.code)}" data-date="${esc(x.buy_date || '')}">
        <td class="code">${esc(x.code)}</td>
        <td class="name">${esc(x.name || '')}</td>
        <td class="num">${x.streak == null ? '—' : x.streak}</td>
        <td class="num">${x.open == null ? '—' : fmt(x.open)}</td>
        <td class="num ${cls(x.gap)}">${x.gap == null ? '—' : fmt(x.gap, 2) + '%'}</td>
        <td>${execBtns(ex)}</td>
        <td class="muted">${esc(capState(x))}</td>
      </tr>`;
    }).join('');
    // 绑定一次，不重复绑
    $$('#tb-ovn-open .ex-b').forEach(b => b.onclick = () => markExec(b));
  }

  // 标记按钮三态：买了 / 没买 / 还没说。点已选中的那个 = 取消标记（回到未说）。
  function execBtns(ex) {
    const one = (v, txt, on) => `<button class="ex-b${on ? ' on' : ''}" data-exec="${v}">${txt}</button>`;
    return `<span class="exg">${one('true', '买了', ex === true)}${one('false', '没买', ex === false)}</span>`;
  }

  // ---- 最近记录
  show('#ovn-recent', recent.length > 0);
  if (recent.length) {
    const sub = $('#ovn-recent-sub');
    if (sub) sub.textContent = `最近 ${recent.length} 笔 · 影子收益=按规则开盘买收盘卖 · 可导出 CSV 分组验证`;
    $('#tb-ovn-recent').innerHTML = recent.map(x => {
      const gap = x.status === 'gap';
      const ex = x.exec;
      const exTxt = ex === true ? '<span class="up">买了</span>'
        : (ex === false ? '<span class="muted">没买</span>'
          : '<span class="muted">未标</span>');
      return `<tr${gap ? ' class="pt"' : ''} data-code="${esc(x.code)}" data-date="${esc(x.buy_date || '')}">
        <td>${esc(x.buy_date || x.signal_date || '')}</td>
        <td class="code">${esc(x.code)}</td>
        <td class="name">${esc(x.name || '')}</td>
        <td class="num">${x.streak == null ? '—' : x.streak}</td>
        <td class="num">${x.open == null ? '—' : fmt(x.open)}</td>
        <td class="num">${x.close == null ? '—' : fmt(x.close)}</td>
        <td class="num ${cls(x.ret)}">${gap ? '—' : pct(x.ret)}</td>
        <td class="muted">${gap ? '开盘价没抓到' : (ex == null ? '未标' : exTxt)}</td>
      </tr>`;
    }).join('');
  }
}

/** 标记「这一笔我买了 / 没买」。再点一次同一个 = 取消标记，回到"还没说"。 */
async function markExec(btn) {
  const tr = btn.closest('tr');
  const code = tr.dataset.code, date = tr.dataset.date;
  const want = btn.dataset.exec === 'true';
  const cur = tr.querySelector('.ex-b.on');
  const next = (cur && cur.dataset.exec === String(want)) ? null : want;   // 再点一次 = 取消
  try {
    S.ovn = await api('/api/overnight/mark', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, buy_date: date, exec: next }),
    });
    renderOvernight();
    toast(next === null ? '已取消标记（回到未确认）'
      : (next ? '记为「买了」，收益进「实际买入」那一栏' : '记为「没买」，信号和影子收益照留'));
  } catch (e) {
    toast('标记失败：' + (e && e.message ? e.message : e), true);
  }
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
  // 策略清单：界面上换方案用（拿不到就按老样子只跑内置那套）
  try { S.strats = await api('/api/strategies'); } catch (e) { S.strats = { items: [], current: '' }; }

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
  // 二级弹窗：任何带 data-open 的按钮都把那一块摊到一屏里
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-open]');
    if (b) { openPane(b.dataset.open, b.dataset.tab); return; }
    if (e.target.closest('#pm-close') || e.target.id === 'pm-mask') { closePane(); return; }
    if (e.target.closest('#pm-save')) { savePane(); return; }
    const t = e.target.closest('[data-pm-tab]');
    if (t) { pm.tab = t.dataset.pmTab; paintPanes(); return; }
  });
  $('#pm-body').addEventListener('input', e => {
    if (pm.id !== 'settings') return;
    pm.dirty = true;
    const card = e.target.closest('.set-card');
    if (card) card.classList.add('dirty');
  });
  $('#pm-body').addEventListener('change', e => {
    if (pm.id === 'settings') pm.dirty = true;
  });
  $('#pm-body').addEventListener('pm-dirty', () => {
    if (pm.id === 'settings') pm.dirty = true;
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
    const row = e.target.closest('tr[data-code], .wrow[data-code], tr[data-pm-row]');
    if (!row || e.target.closest('button')) return;
    // 弹窗里那份清单是主页表格的翻版：按行号回主页那张表里取代码
    if (row.dataset.pmRow) {
      const src = $$('#tbl-scan tbody tr')[+row.dataset.pmRow];
      if (src) openDetail(src.dataset.code);
      return;
    }
    openDetail(row.dataset.code);
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
    // 一层一层退：先关最上面那个
    if (pm.id) closePane();
    else if (S.detail) closeDrawer();
    else if (S.watchModalOpen) closeWatchModal();
  });

  /* 窗口变大变小后重画所有画布：canvas 是位图，
     只靠 width:100% 拉伸会把 K 线和筹码图压扁/拉长，得按新宽度重绘 */
  let _rzT = 0;
  window.addEventListener('resize', () => {
    clearTimeout(_rzT);
    _rzT = setTimeout(() => { try { repaintCharts(); } catch { } }, 160);
  });

  // 自动加载上次结果（软件后台可能已经跑过了）
  // _lastDay 记下"服务端上次扫描是哪天"——自动补扫的判据全靠它，见下面那个块
  let _lastDay = '';
  try {
    const r = await api('/api/last');
    if (r.result) {
      applyResult(r.result, r.result.auto ? '（自动）' : '（上次的结果）');
      _lastDay = String(r.result.generated_at || '').slice(0, 10);
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
  // 用户不用点任何按钮就有名单看。
  // ★ 判据必须是「服务端上次扫描不是今天」，而不是「这个页面还没拿到名单」——
  //   以前只看 S.items.length：/api/last 万一没按时回来（新标签页、代理抖动、
  //   异常被吞），页面就会在 1.5 秒后擅自发起一次全市场扫描。
  //   收盘后打开页面时这招是灾难：盘后快照选出的名单跟 14:45 实盘那份完全不同，
  //   还会被 force=True 记进当天记忆，把定型名单覆盖掉（2026-10-29 实测 40 → 5）。
  //   只要今天跑过（哪怕选出 0 只），就老老实实展示服务端那份，不再自作主张。
  if (_lastDay !== todayStr() && !S.items.length) {
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



