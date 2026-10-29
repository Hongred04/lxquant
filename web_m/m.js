/* ===================================================================
   量价选股 · 手机版
   一个文件搞定：接口、五个主页面 + 两个二级页、详情抽屉、通用弹层、七种图表
   =================================================================== */
'use strict';

/* ---------------------------------------------------------------- 小工具 */
const $ = s => document.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = v => (v == null || v === '' || Number.isNaN(+v)) ? null : +v;
const fmt = (v, n = 2) => { const x = num(v); return x == null ? '—' : x.toFixed(n); };
const pct = (v, n = 1) => { const x = num(v); return x == null ? '—' : x.toFixed(n) + '%'; };
const p2 = v => { const x = num(v); return x == null ? '—' : (x > 0 ? '+' : '') + x.toFixed(2); };
const cls = v => { const x = num(v); return x == null ? '' : x > 0 ? 'up' : x < 0 ? 'down' : ''; };
const money = v => {
  const x = num(v); if (x == null) return '—';
  const a = Math.abs(x);
  if (a >= 1e8) return (x / 1e8).toFixed(2) + '亿';
  if (a >= 1e4) return (x / 1e4).toFixed(2) + '万';
  return x.toFixed(0);
};
const sleep = ms => new Promise(r => setTimeout(r, ms));
const THEME_KEY = 'lxq-m-theme', SOUND_KEY = 'lxq-m-sound';

/* ---------------------------------------------------------------- 接口 */
// 请求必须能超时退出。服务器卡住（抓行情卡住、线程池满了）时，
// 没有超时的话抽屉会永远停在"加载中…"，用户看到的就是一个关不掉的面板。
const API_TIMEOUT = 90000;   // 兜底上限；后台任务是轮询的，不走这里
async function api(url, opt) {
  const ac = (typeof AbortController !== 'undefined') ? new AbortController() : null;
  let timer = null;
  if (ac) timer = setTimeout(() => ac.abort(), API_TIMEOUT);
  const init = opt ? { ...opt, headers: { 'Content-Type': 'application/json', ...(opt.headers || {}) } } : {};
  if (ac) init.signal = ac.signal;
  let r;
  try {
    r = await fetch(url, init);
  } catch (e) {
    if (e && e.name === 'AbortError') throw new Error('等太久了（' + Math.round(API_TIMEOUT / 1000) + ' 秒没回音），点右上角关掉再来一次');
    throw new Error('连不上本地服务（' + ((e && e.message) || e) + '）');
  } finally {
    if (timer) clearTimeout(timer);
  }
  const txt = await r.text();
  let j = null;
  try { j = JSON.parse(txt); } catch (_) { throw new Error('服务器返回的不是数据（' + r.status + '）'); }
  if (!j || j.ok === false) throw new Error((j && j.error) || ('请求失败 ' + r.status));
  return j;
}
const post = (url, body) => api(url, { method: 'POST', body: JSON.stringify(body || {}) });

/** 轮询异步任务：能拿到 pct / msg 就回调进度，直到 done */
async function pollJob(id, onProg, ms = 450) {
  for (let i = 0; i < 2400; i++) {
    let s;
    try { s = await api('/api/job?id=' + encodeURIComponent(id)); } catch (e) { await sleep(600); continue; }
    if (onProg) onProg(s);
    if (s.state === 'done') return s;
    if (s.state === 'error') throw new Error(s.error || '任务出错');
    if (s.state === 'cancelled') throw new Error('已停止');
    await sleep(ms);
  }
  throw new Error('等太久了');
}
const jobResult = id => api('/api/job/result?id=' + encodeURIComponent(id));

/* ---------------------------------------------------------------- 状态 */
const S = {
  cfg: null, auto: null, last: null, items: [], near: [],
  view: 'screen', filter: 'all', sort: 'score', dir: -1, q: '',
  scanItems: [], bt: null, pf: null, watchList: [], watchHits: {}, watchAt: '',
  alerts: [], busy: {}, memDays: [], memRv: null, memOv: null, memDate: '', memSrc: 'all',
  detail: null, datesCache: {},
  strats: null,   // 可插拔策略方案
};

/* ---------------------------------------------------------------- 主题 */
function themeNow() { return document.documentElement.dataset.theme || 'dark'; }
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem(THEME_KEY, t); } catch (_) { }
  const m = document.querySelector('meta[name=theme-color]');
  if (m) m.setAttribute('content', t === 'light' ? '#f2f4f7' : '#0b0e13');
  // 画过的图全部重画（颜色都从 CSS 变量里取）
  try { if (S.view === 'backtest') drawBtChart(); if (S.view === 'portfolio') drawPfChart(); } catch (_) { }
  if (S.detail && !$('#sheet').hidden) paintDetail(S.detail);
}
function initTheme() {
  let t = 'dark';
  try { t = localStorage.getItem(THEME_KEY) || 'dark'; } catch (_) { }
  if (!localStorage.getItem(THEME_KEY)) {
    t = (window.matchMedia && matchMedia('(prefers-color-scheme: light)').matches) ? 'light' : 'dark';
  }
  setTheme(t);
}
/** 画布取色：直接把 CSS 变量解析成颜色，深浅色都能用 */
const C = {};
function readColors() {
  const cs = getComputedStyle(document.documentElement);
  ['--txt', '--txt-2', '--txt-3', '--up', '--down', '--acc', '--gold', '--bad', '--ok', '--line', '--card', '--card-2', '--bg']
    .forEach(k => { C[k.replace('--', '')] = cs.getPropertyValue(k).trim() || '#888'; });
}
function cssVar(k) { return getComputedStyle(document.documentElement).getPropertyValue('--' + k).trim() || '#888'; }

/* ---------------------------------------------------------------- Toast */
let toastT = null;
function toast(msg, bad) {
  const el = $('#toast');
  el.textContent = msg;
  el.classList.toggle('bad', !!bad);
  el.hidden = false;
  clearTimeout(toastT);
  toastT = setTimeout(() => { el.hidden = true; }, bad ? 3600 : 2200);
}

/* ---------------------------------------------------------------- 路由 */
const VIEWS = {
  screen: { t: '今日选股', tab: 'screen' },
  watch: { t: '盯盘', tab: 'watch' },
  backtest: { t: '信号检验', tab: 'backtest' },
  portfolio: { t: '模拟账户', tab: 'portfolio' },
  memory: { t: '选股记忆', tab: null },
  me: { t: '我的', tab: 'me' },
  method: { t: '策略说明', tab: 'me' },
  settings: { t: '参数设置', tab: 'me' },
};
function go(v, opt) {
  if (!VIEWS[v]) v = 'screen';
  S.view = v;
  $$('.pg').forEach(p => p.classList.toggle('on', p.id === 'pg-' + v));
  const meta = VIEWS[v];
  $('#v-title').textContent = meta.t;
  $('#btn-back').hidden = !(v === 'method' || v === 'settings' || v === 'memory');
  $$('#tabbar button').forEach(b => b.classList.toggle('on', b.dataset.go === meta.tab));
  $('#tabbar').style.visibility = 'visible';
  const pg = $('#pg-' + v);
  if (pg) pg.scrollTop = 0;
  if (!opt || opt.load !== false) loadView(v);
  try { history.replaceState(null, '', '#' + v); } catch (_) { }
}
function loadView(v) {
  if (v === 'screen') { paintScreen(); pollAuto(); }
  if (v === 'watch') { loadWatchList(); }
  if (v === 'memory') { loadMemory(); }
  if (v === 'settings') { renderSettings(); }
  if (v === 'method') { paintMethod(); }
  if (v === 'me') { paintMe(); }
  if (v === 'backtest') { paintBacktest(); }
  if (v === 'portfolio') { paintPortfolio(); }
}
function setSub(t) { $('#v-sub').textContent = t || ''; }

/* ---------------------------------------------------------------- 中线口径 */
/** 这一次名单按哪个价判定：tail / preview 看尾盘价，close 看收盘价 */
function basisMode() {
  const st = (S.last && S.last.stats) || {};
  if (st.basis === 'tail' || st.basis === 'preview') return 'tail';
  if (st.basis === 'close') return 'close';
  const fm = (S.last && S.last.funnel) || {};
  if (fm.entry_mode) return fm.entry_mode === 'close' ? 'close' : 'tail';
  return 'tail';
}
function pickAvg(a) {
  const d = a.avg || {};
  const tail = basisMode() === 'tail';
  const det = tail ? ((d.tail_detail && d.tail_detail.length) ? d.tail_detail : d.detail) : d.detail;
  return {
    tail,
    streak: tail ? (d.tail_streak != null ? d.tail_streak : d.streak) : d.streak,
    surplus: tail ? (d.tail_surplus != null ? d.tail_surplus : d.avg_surplus) : d.avg_surplus,
    detail: det || [],
    lab: tail ? (d.tail_from || '14:30') : '收盘',
  };
}
const GATE_KEYS_FB = [['ma', '站上成本'], ['chip', '套牢少'], ['pos', '位置低'], ['bottom', '底部横'], ['trend', '均在线上']];
/* 关卡从当前策略里取，换方案后这里跟着变；取不到就退回原来那五关 */
function GATE_KEYS() {
  const cur = ((S.strats && S.strats.items) || []).find(x => x.key === (S.strats || {}).current);
  const gs = cur && cur.gates;
  if (gs && gs.length) return gs.map(g => [g.key, g.label]);
  return GATE_KEYS_FB;
}
function gapOf(a) {
  const c = a.checks || {};
  const ks = GATE_KEYS().filter(([k]) => k in c);
  if (ks.length) return ks.filter(([k]) => !c[k]).length;
  return a.watch ? 2 : 0;
}

/* ---------------------------------------------------------------- 选股页 */
function paintScreen() {
  const r = S.last;
  const st = (r && r.stats) || {};
  const hits = (S.items || []).length;
  const near = (S.near || []).length;
  // ---- 主卡
  $('#hero-hit').textContent = r ? (st.hit != null ? st.hit : hits) : '—';
  const basis = st.basis ? ({ tail: '尾盘价', preview: '试算价', close: '收盘价' }[st.basis] || st.basis) : '';
  $('#hero-time').textContent = st.generated_at ? `${String(st.generated_at).slice(5, 16)} · ${basis}` : (st.basis ? basis : '—');
  if (!r) {
    $('#hero-sub').textContent = '点下面的按钮，开始看今天的机会';
  } else if (st.basis === 'preview') {
    $('#hero-sub').textContent = `${fmt(st.elapsed, 0)} 秒看完 ${st.scanned || 0} 只 · 这是 ${(r.funnel || {}).preview_at || '14:00'} 的试算，等 14:50 再确认`;
  } else {
    $('#hero-sub').textContent = `一共看了 ${st.scanned || 0} 只 · 用了 ${fmt(st.elapsed, 0)} 秒${st.failed ? ` · ${st.failed} 只没取到` : ''}`;
  }
  // ---- 三宫格
  $('#m-watch').textContent = near ? near : (r ? '0' : '—');
  $('#m-scan').textContent = (S.scanItems || []).length || (S.scanItems && S.scanItems.length === 0 && S.scanRan ? '0' : '—');
  const ov = (S.memOv && S.memOv.days) || [];
  if (ov.length) {
    // 每天的记录里只有 win_rate 和 n，没有原始「赢了几只」，所以按 n×胜率反推
    const tot = ov.reduce((a, d) => a + (+d.n || 0), 0);
    const win = ov.reduce((a, d) => a + (+d.n || 0) * (+d.win_rate || 0) / 100, 0);
    $('#m-mem').textContent = tot ? Math.round(win / tot * 100) + '%' : '—';
  } else {
    $('#m-mem').textContent = '—';
  }
  // ---- 列表
  $('#seg-screen').querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.f === S.filter));
  $('#sorts').querySelectorAll('button').forEach(b => {
    b.classList.toggle('on', b.dataset.s === S.sort);
    if (b.dataset.s === S.sort) b.textContent = b.textContent.replace(/[ ▲▼]$/, '') + (S.dir > 0 ? ' ▲' : ' ▼');
    else b.textContent = b.textContent.replace(/[ ▲▼]$/, '');
  });
  let rows;
  if (S.filter === 'real') rows = (S.items || []).map(a => ({ ...a, _kind: 'hit' }));
  else if (S.filter === 'near') rows = (S.near || []).map(a => ({ ...a, _kind: 'near' }));
  else rows = (S.items || []).map(a => ({ ...a, _kind: 'hit' })).concat((S.near || []).map(a => ({ ...a, _kind: 'near' })));
  const q = (S.q || '').trim().toLowerCase();
  if (q) rows = rows.filter(a => String(a.code).includes(q) || String(a.name || '').toLowerCase().includes(q));
  const key = S.sort;
  const get = a => {
    if (key === 'chg') return num(a.chg_pct);
    if (key === 'chip') return a.chip ? num(a.chip.profit_ratio) : null;
    if (key === 'pos') return a.pos ? num(a.pos.pos) : null;
    return num(a.score);
  };
  rows.sort((x, y) => {
    const a = get(x), b = get(y);
    if (a == null || b == null) return (a == null) - (b == null);   // 空值永远沉底
    return (a > b ? 1 : a < b ? -1 : 0) * S.dir;
  });
  const box = $('#list'), emp = $('#list-empty');
  if (!rows.length) {
    box.innerHTML = '';
    emp.hidden = false;
    emp.innerHTML = (S.items.length || S.near.length)
      ? `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/></svg><p>没有匹配的股票，换个关键词试试。</p>`
      : `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M4 18h16M4 12h16M4 6h16"/><circle cx="9" cy="6" r="2"/></svg><p><b>今天没有全部达标的股票。</b><br>点「差一点」看看接近的，或者到「参数设置」把条件放宽一点。</p>`;
  } else {
    emp.hidden = true;
    box.innerHTML = rows.map((a, i) => stockCard(a, i, rows.length)).join('');
  }
}

/** 一只股票一张卡：谁 / 多少钱 / 三条进度 / 该不该动手 / 为什么 */
function stockCard(a, i, n) {
  const pa = pickAvg(a);
  const c = a.checks || {};
  const plan = a.plan || {};
  const near = a._kind === 'near';
  const pr = a.chip ? num(a.chip.profit_ratio) : null;
  const pos = a.pos ? num(a.pos.pos) : null;
  const capChip = num(S.cfg && S.cfg.params ? S.cfg.params.profit_cap : 0.25) ?? 0.25;
  const capPos = num(S.cfg && S.cfg.params ? S.cfg.params.pos_cap : 0.3) ?? 0.3;
  const badge = /^688/.test(a.code) ? '科创' : /^(300|301)/.test(a.code) ? '创业' : /^(8|4|9)/.test(a.code) ? '北交' : '';
  const streakTxt = pa.streak == null ? '—' : pa.streak + ' 天';
  const sur = num(pa.surplus);
  const tags = [];
  if (plan.stop) tags.push(`<span class="tag">止损 ${fmt(plan.stop)}</span>`);
  if (plan.target) tags.push(`<span class="tag">目标 ${fmt(plan.target)}</span>`);
  if (plan.rr != null) tags.push(`<span class="tag">赔 ${fmt(plan.rr, 1)} 比 1</span>`);
  if (plan.ok === false && plan.note) tags.push(`<span class="tag y">${esc(String(plan.note).slice(0, 12))}</span>`);
  const why = (a.watch || '').replace(/^（[^）]*）\s*/, '');
  return `<div class="stk ${near ? 'near' : ''}" data-code="${esc(a.code)}">
    <div class="stk-h">
      <div>
        <div class="stk-nm"><b>${esc(a.name || a.code)}</b>${badge ? `<i>${badge}</i>` : ''}</div>
        <div class="code-m">${esc(a.code)}${a.score != null ? ` · 把握 ${fmt(a.score, 1)}` : ''}</div>
      </div>
      <div class="stk-pr">
        <b>${fmt(a.price)}</b>
        <span class="${cls(a.chg_pct)}">${a.chg_pct == null ? '—' : (a.chg_pct > 0 ? '+' : '') + fmt(a.chg_pct) + '%'}</span>
      </div>
    </div>
    <div class="stk-bars">
      <div class="bl"><span>站上成本</span><div class="track"><i style="width:${Math.min(100, (pa.streak || 0) / 3 * 100)}%;background:var(--ok)"></i></div><b>${streakTxt}</b></div>
      <div class="bl"><span>套牢盘</span><div class="track"><i style="width:${pr == null ? 0 : Math.min(100, pr * 100)}%;background:${pr != null && pr <= capChip ? 'var(--ok)' : 'var(--bad)'}"></i><u style="left:${Math.min(100, capChip * 100)}%"></u></div><b>${pr == null ? '—' : pct(pr * 100, 0)}</b></div>
      <div class="bl"><span>价格位置</span><div class="track"><i style="width:${pos == null ? 0 : Math.min(100, pos * 100)}%;background:${pos != null && pos <= capPos ? 'var(--ok)' : 'var(--gold)'}"></i><u style="left:${Math.min(100, capPos * 100)}%"></u></div><b>${pos == null ? '—' : pct(pos * 100, 0)}</b></div>
    </div>
    <div class="stk-f">
      ${near ? `<span class="tag y">差 ${gapOf(a)} 项</span>` : `<span class="tag g">可以买</span>`}
      ${sur == null ? '' : `<span class="tag ${sur >= 0 ? 'g' : ''}">高于成本 ${sur > 0 ? '+' : ''}${fmt(sur)}%</span>`}
      ${tags.join('')}
      <span class="stk-go">详情<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 5l7 7-7 7"/></svg></span>
    </div>
    ${near && why ? `<div class="stk-why">还差：${esc(why)}</div>` : ''}
  </div>`;
}

async function runScreen() {
  if (S.busy.screen) return;
  S.busy.screen = true;
  $('#btn-run').disabled = true;
  $('#btn-stop').hidden = false;
  $('#hero-sub').textContent = '正在看全市场的股票…';
  $('#hero-prog').style.width = '2%';
  try {
    const j = await post('/api/screen', {});
    S.curJob = j.job.id;
    let lastPct = 0;
    const st = await pollJob(j.job.id, s => {
      lastPct = Math.max(lastPct, +s.pct || 0);
      $('#hero-prog').style.width = Math.max(2, lastPct) + '%';
      if (s.msg) $('#hero-sub').textContent = s.msg;
    });
    const r = await jobResult(j.job.id);
    if (r.state !== 'done') throw new Error(r.error || '没跑完');
    applyResult(r.result);
    const n = (S.items || []).length;
    const gd = !!(r.result.stats && r.result.stats.gated);
    toast(n ? `选股完成，能买 ${n} 只`
      : (gd ? '大盘不配合，这批先放「差一点」里盯着' : '这次没有全部达标的，看看「差一点」'));
  } catch (e) {
    toast('选股失败：' + e.message, true);
    $('#hero-sub').textContent = '出了点问题：' + e.message;
  } finally {
    S.curJob = null;
    S.busy.screen = false;
    $('#btn-run').disabled = false;
    $('#btn-stop').hidden = true;
    setTimeout(() => { $('#hero-prog').style.width = '0'; }, 600);
  }
}

/** 把一次选股结果灌进界面 */
function applyResult(r) {
  if (!r) return;
  S.last = r;
  S.items = r.items || [];
  S.near = r.watch || r.watch_items || [];
  paintScreen();
  pollAuto();
}
async function stopJob() {
  try {
    const id = S.curJob;
    if (id) post('/api/job/stop', { id }).catch(() => { });
    toast('已停止');
  } catch (e) { toast(e.message, true); }
}

/* ---- 自动选股状态条 */
let autoT = null;
async function pollAuto() {
  clearTimeout(autoT);
  try {
    const a = await api('/api/auto');
    S.auto = a;
    const pill = $('#auto-pill');
    const on = !!(S.cfg && S.cfg.params && S.cfg.params.auto_scan);
    pill.hidden = !on;
    if (on) {
      const st = a.running ? '正在跑' : (a.next ? `下次 ${a.next}` : '待命');
      pill.textContent = st;
      pill.classList.toggle('warn', !a.running && !a.next);
    }
  } catch (_) { }
  autoT = setTimeout(pollAuto, 30000);
}

/* ---------------------------------------------------------------- 明细弹层 */
let MD = { id: '', tab: '' };
/* 抽屉/弹层开着时给 body 挂个标记，CSS 用它把顶上的提醒卡收掉，
   否则提醒卡盖住抽屉右上角的关闭按钮，用户会以为"没有退出按钮"。 */
function syncOverlayFlag() {
  const on = !$('#sheet').hidden || !$('#modal').hidden;
  document.body.classList.toggle('ovl-open', on);
}
function openModal(id, title, sub) {
  MD.id = id;
  $('#modal').hidden = false;
  $('#modal-mask').hidden = false;
  $('#md-title').textContent = title || '';
  $('#md-sub').textContent = sub || '';
  $('#md-tabs').hidden = true;
  $('#md-body').innerHTML = '';
  syncOverlayFlag();
  paintModal();
}
function closeModal() {
  $('#modal').hidden = true;
  $('#modal-mask').hidden = true;
  MD.id = '';
  syncOverlayFlag();
}
function paintModal() {
  const r = S.last;
  if (MD.id === 'detail') {
    const st = (r && r.stats) || {}, f = (r && r.funnel) || {};
    let mk = '';
    if (r && st.market && st.market.date && st.market.vs20 != null) {
      const v = +st.market.vs20;
      mk = ` · 大盘 ${v >= 0 ? '+' : ''}${v.toFixed(1)}%（对 MA20）`;
      if (st.gated) mk += ' · 暂停买入';
    }
    $('#md-sub').textContent = r ? `看了 ${st.scanned || 0} 只 · 能买 ${(S.items || []).length} 只 · 差点 ${(S.near || []).length} 只${mk}` : '还没跑过';
    if (!r) { $('#md-body').innerHTML = '<div class="empty"><p>还没跑过 —— 点「立即选股」跑一次就有了。</p></div>'; return; }
    const tot = st.scanned || 1;
    const basisTxt = basisMode() === 'tail' ? (f.tail_from || '14:30') : '收盘';
    const rows = [
      ['扫过', st.scanned, null, '一共看了多少只'],
      ['① 连上 3 天平均成本', f.ma, `按 ${basisTxt} 算`, '最难过的一关'],
      ['② 上方套牢盘少', f.chip, '', ''],
      ['③ 价格在低位', f.pos, '', ''],
      ['④ 底部横着走', f.bottom, '', ''],
      ['⑤ 还在 20 日线上', f.trend, '', ''],
    ];
    if (f.ma_close != null) rows.push(['参考：按收盘价能过', f.ma_close, '只作对照', '']);
    if (f.tail_watch > 0) rows.push([`${f.preview_at || '14:00'} 试算选中`, f.tail_watch, '等尾盘确认', '']);
    $('#md-body').innerHTML = `<div class="dsec"><div class="rank">${rows.map(([k, v, tip, g]) => `
        <div class="rr" title="${esc(g || '')}">
          <span>${esc(k)}</span>
          <div class="bar"><i style="width:${v == null ? 0 : Math.max(1.5, (v / tot) * 100)}%"></i></div>
          <b>${v == null ? '—' : v}</b>
        </div>
        ${tip ? `<div class="hint" style="margin:-4px 0 2px 0">${esc(tip)}</div>` : ''}`).join('')}</div>
      <div class="hint">这些数字只解释「为什么选出这几只」，不影响买卖。${(f.streak && f.streak.length === 0) ? '' : ''}</div>
    </div>
    <div class="dsec"><h4>值得盯着 <span class="em">${(S.near || []).length} 只</span></h4>
      ${(S.near || []).length ? `<div class="dl">${S.near.map(a => {
        const why = (a.watch || '').replace(/^（[^）]*）\s*/, '');
        return `<div class="dr ok" data-code="${esc(a.code)}" style="grid-template-columns:1fr auto"><span style="font-family:var(--mono);color:var(--txt)">${esc(a.code)}</span><span style="text-align:left;color:var(--txt)">${esc(a.name || '')}</span></div>
          <div class="hint" style="margin:-3px 0 4px 8px">差 ${gapOf(a)} 项${why ? '：' + esc(why) : ''}</div>`;
      }).join('')}</div>` : '<div class="wempty">这一次没有差一点的股票</div>'}
    </div>`;
  }
}

/* ---------------------------------------------------------------- 详情抽屉 */
let detailSeq = 0;
async function openStock(code) {
  const seq = ++detailSeq;
  $('#sheet').hidden = false;
  $('#sheet-mask').hidden = false;
  syncOverlayFlag();
  $('#dw-name').textContent = '加载中…';
  $('#dw-code').textContent = code;
  $('#dw-date').textContent = '';
  $('#dw-price').textContent = '—';
  $('#dw-chg').textContent = '';
  $('#dw-chg').className = '';
  $('#dw-body').innerHTML = `<div class="dsec" style="text-align:center;padding:50px 0;color:var(--txt-3)">第一次看这只票要抓行情、算筹码，大约 5–15 秒…</div>`;
  try {
    const r = await api('/api/detail?code=' + encodeURIComponent(code));
    if (seq !== detailSeq) return;
    S.detail = r.data;
    paintDetail(r.data);
  } catch (e) {
    if (seq !== detailSeq) return;
    $('#dw-body').innerHTML = `<div class="dsec" style="color:var(--bad)">没能加载出来：${esc(e.message)}<br><span style="color:var(--txt-3)">可能是行情源临时不通，过一会儿再点一次。</span></div>`;
  }
}
function closeStock() {
  detailSeq++;
  $('#sheet').hidden = true;
  $('#sheet-mask').hidden = true;
  syncOverlayFlag();
}
let DW_TAB = 'day';
function paintDetail(a) {
  if (!a) return;
  readColors();
  $('#dw-name').textContent = a.name || '—';
  $('#dw-code').textContent = a.code || '';
  $('#dw-date').textContent = a.stock_date || a.date || '';
  $('#dw-price').textContent = fmt(a.price);
  const ch = $('#dw-chg');
  ch.textContent = a.chg_pct == null ? '' : (a.chg_pct > 0 ? '+' : '') + fmt(a.chg_pct) + '%';
  ch.className = cls(a.chg_pct);

  const c = a.checks || {};
  const plan = a.plan || {};
  const pa = pickAvg(a);
  const P = (S.cfg && S.cfg.params) || {};
  const chipCap = fmt(num(P.profit_cap ?? 0.25) * 100, 0);
  const posCap = fmt(num(P.pos_cap ?? 0.3) * 100, 0);
  // 关卡以策略自己算的为准（后端 analyze 给了 key/label/ok/why），换方案自动跟着变
  const gRows = (a.gates && a.gates.length) ? a.gates : null;
  const gKeys = gRows ? gRows.map(g => [g.key, g.label]) : GATE_KEYS();
  const why = {
    ma: pa.tail ? `${pa.lab} 的价格没站在当天平均成本上方` : '收盘价没站在当天平均成本（分时黄线）上方',
    chip: `套牢盘 ${a.chip && a.chip.profit_ratio != null ? pct(a.chip.profit_ratio * 100, 1) : '—'}，要求 ≤ ${chipCap}%`,
    pos: `价格在 120 天区间的 ${a.pos && a.pos.pos != null ? fmt(a.pos.pos * 100, 0) + '%' : '—'}，要求 ≤ ${posCap}%`,
    bottom: (a.bottom && a.bottom.note) || '最近不是底部横盘',
    trend: `价在 ${a.trend && a.trend.period ? a.trend.period : 20} 日均线下方`,
  };
  // 后端给了 why 就优先用（策略自己解释得更准）
  const whyOf = (k) => {
    const g = gRows && gRows.find(x => x.key === k);
    return (g && g.why) ? g.why : (why[k] || '这一条没通过');
  };
  const passed = gKeys.filter(([k]) => c[k]).length;
  const det = pa.detail || [];
  const planRows = [
    ['建议止损', plan.stop != null ? `${fmt(plan.stop)} 元（${plan.stop_pct != null ? fmt(plan.stop_pct, 1) + '%' : '—'}）` : '—'],
    ['参考目标', plan.target != null ? `${fmt(plan.target)} 元（${plan.target_pct != null ? '+' + fmt(plan.target_pct, 1) + '%' : '—'}）` : '—'],
    ['平均成本线', plan.avg_line != null ? fmt(plan.avg_line) + ' 元' : '—'],
    ['赚钱概率 / 赔率', plan.rr != null ? `赚 ${fmt(plan.rr, 1)} 元，亏 1 元` : '—'],
    ['建议仓位', plan.position_pct != null ? fmt(plan.position_pct, 0) + '%' : '—'],
  ];
  if (plan.note) planRows.push(['一句话', plan.note]);

  const chips = (a.chip && a.chip.chips) || [];
  $('#dw-body').innerHTML = `
    <div class="dsec">
      <h4>关卡 <span class="em">${passed}/${gKeys.length} 条符合</span></h4>
      <div class="oks">${gKeys.map(([k, n]) => `<span class="ok ${c[k] ? 'y' : 'n'}">${c[k] ? '✓' : '✗'} ${n}</span>`).join('')}</div>
      <div class="mini">
        <div class="mi"><div class="k">把握度</div><div class="v" style="color:${a.score >= 75 ? 'var(--ok)' : a.score >= 50 ? 'var(--acc)' : 'var(--gold)'}">${fmt(a.score, 1)}</div></div>
        <div class="mi"><div class="k">连续强于成本</div><div class="v">${pa.streak != null ? pa.streak : '—'}<span style="font-size:11px;color:var(--txt-3)"> 天</span></div></div>
        <div class="mi"><div class="k">今天平均成本</div><div class="v">${fmt(a.avg && a.avg.today_avg)}</div></div>
      </div>
      <div class="hint">${gKeys.filter(([k]) => !c[k]).map(([k]) => '✗ ' + esc(whyOf(k))).join('<br>') || '所有关卡全部符合。'}</div>
      ${det.length ? `<div class="dl" style="margin-top:10px">${det.map(d => `
        <div class="dr ${d.ok ? 'ok' : 'no'}">
          <span>${esc(String(d.date).slice(5))}</span>
          <span>${esc(pa.tail ? pa.lab : '收')} ${fmt(d.close)}</span>
          <span>成本 ${fmt(d.avg)}</span>
          <span>${num(d.surplus) > 0 ? '+' : ''}${fmt(d.surplus)}%</span>
        </div>`).join('')}</div>` : ''}
    </div>

    <div class="dsec">
      <h4>走势 <span class="em">${a.kline && a.kline.day ? ((a.kline.day.bars || []).length) + ' 根' : ''}</span></h4>
      <div class="seg mini-seg" id="dw-tabs">
        <button data-t="day" class="${DW_TAB === 'day' ? 'on' : ''}">日线</button>
        <button data-t="week" class="${DW_TAB === 'week' ? 'on' : ''}">周线</button>
        <button data-t="month" class="${DW_TAB === 'month' ? 'on' : ''}">月线</button>
        <button data-t="intraday" class="${DW_TAB === 'intraday' ? 'on' : ''}">分时</button>
      </div>
      <canvas class="cv" id="dw-cv" style="height:230px"></canvas>
    </div>

    <div class="dsec">
      <h4>筹码压在哪些价位 <span class="em">${a.chip && a.chip.real_turnover ? '按真实换手率估算' : '按换手衰减估算'}</span></h4>
      <canvas class="cv" id="dw-chip" style="height:170px"></canvas>
      <div class="mini">
        <div class="mi"><div class="k">上方套牢盘</div><div class="v ${a.chip && a.chip.profit_ratio <= num(P.profit_cap ?? 0.25) ? 'down' : 'up'}">${a.chip && a.chip.profit_ratio != null ? pct(a.chip.profit_ratio * 100, 1) : '—'}</div></div>
        <div class="mi"><div class="k">平均成本</div><div class="v">${fmt(a.chip && a.chip.avg_cost)}</div></div>
        <div class="mi"><div class="k">筹码集中度</div><div class="v">${a.chip && a.chip.concentration != null ? fmt(a.chip.concentration * 100, 1) + '%' : '—'}</div></div>
      </div>
      <div class="hint">立柱越长说明这个价位上的人越多。价格上方还压着很多筹码，一涨就有人卖。</div>
    </div>

    <div class="dsec">
      <h4>买卖计划</h4>
      <div class="kv">${planRows.map(([k, v]) => `<div class="r"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join('')}</div>
    </div>

    ${a.ta && a.ta.ma ? `<div class="dsec">
      <h4>技术指标 <span class="em">和通达信一个口径</span></h4>
      <div class="mini">
        <div class="mi"><div class="k">MACD 柱</div><div class="v ${cls(a.ta.macd && a.ta.macd.hist)}">${fmt(a.ta.macd && a.ta.macd.hist)}</div></div>
        <div class="mi"><div class="k">KDJ（K/D）</div><div class="v" style="font-size:13px">${fmt(a.ta.kdj && a.ta.kdj.k, 1)}/${fmt(a.ta.kdj && a.ta.kdj.d, 1)}</div></div>
        <div class="mi"><div class="k">A 常波动</div><div class="v">${fmt(a.ta.atr && a.ta.atr.pct, 2)}%</div></div>
      </div>
      <div class="hint">5/10/20/60 日均线 ${fmt(a.ta.ma.ma5)} / ${fmt(a.ta.ma.ma10)} / ${fmt(a.ta.ma.ma20)} / ${fmt(a.ta.ma.ma60)}</div>
    </div>` : ''}

    <div class="dsec" style="display:flex;gap:8px">
      <button class="btn soft" style="flex:1" data-wact="add">加入自选</button>
      <button class="btn soft" style="flex:1" data-wact="check">看买点卖点</button>
    </div>`;

  drawKlineChart($('#dw-cv'), a, DW_TAB);
  drawChipChart($('#dw-chip'), a);
}

/* ---------------------------------------------------------------- 盯盘 */
async function loadWatchList() {
  try {
    const r = await api('/api/watch');
    S.watchList = r.items || r.list || [];
    S.watchAt = r.check_at || '';
    paintWatch();
    setSub(S.watchList.length ? `${S.watchList.length} 只 · ${S.watchAt ? '上次检查 ' + String(S.watchAt).slice(5, 16) : '还没检查过'}` : '还没加自选股');
  } catch (e) { toast('读取自选股失败：' + e.message, true); }
}
function paintWatch() {
  const box = $('#w-list');
  const items = S.watchList || [];
  if (!items.length) {
    box.innerHTML = '<div class="wempty">还没有自选股。在下面填 6 位代码加进来。</div>';
  } else {
    box.innerHTML = items.map(it => {
      const last = it.last || {};
      const hits = (S.watchHits || {})[it.code] || [];
      const k0 = hits[0] || '';
      const k = k0.startsWith('sell') ? 'stop' : k0.startsWith('buy') ? 'hit' : '';
      const cn = { 'buy.ma': '可买', 'buy.near': '差一点', 'buy.pull': '到低吸位', 'sell.stop': '破止损', 'sell.target': '到目标', 'sell.ma': '破成本', 'sell.trail': '回落' }[k0] || '';
      return `<div class="wchip ${k}" data-code="${esc(it.code)}">
        <b>${esc(it.name || it.code)}</b>
        <i>${esc(it.code)}</i>
        <span class="${cls(last.chg_pct)}">${fmt(last.price)} ${last.chg_pct == null ? '' : (last.chg_pct > 0 ? '+' : '') + fmt(last.chg_pct) + '%'}</span>
        ${cn ? `<span class="tag ${k0.startsWith('sell') ? 'i' : 'g'}" style="margin-top:3px">${cn}</span>` : ''}
      </div>`;
    }).join('');
  }
}
async function checkWatch(force) {
  try {
    const r = await post('/api/watch/check', { force: !!force });
    S.watchHits = {};
    (r.rows || []).forEach(x => { if (x.hits && x.hits.length) S.watchHits[x.code] = x.hits; });
    if (r.alerts) S.alerts = r.alerts;
    S.watchAt = r.checked_at || S.watchAt;
    await loadWatchList();
    paintWatch();
    const n = (r.rows || []).filter(x => (x.hits || []).length).length;
    toast(r.skipped ? '刚看过了，3 分钟后再看' : (n ? `${n} 只有买点卖点` : '看完了，暂时没有信号'));
    if (r.new && r.new.length) showAlerts(r.new);
  } catch (e) { toast('检查失败：' + e.message, true); }
}
async function addWatch(code, name) {
  code = String(code || '').trim();
  if (!/^\d{6}$/.test(code)) { toast('请输入 6 位股票代码', true); return; }
  try {
    await post('/api/watch/add', { code, name: name || '' });
    toast('已加入自选');
    await loadWatchList();
    checkWatch(true);
  } catch (e) { toast('没加上：' + e.message, true); }
}

function showAlerts(list) {
  const box = $('#alerts');
  (list || []).slice(0, 3).forEach(a => {
    const d = document.createElement('div');
    const buy = String(a.kind || a.why || '').startsWith('buy');
    d.className = 'alert ' + (buy ? 'buy' : 'sell');
    d.innerHTML = `<div style="flex:1"><b>${esc(a.name || a.code)} ${buy ? '买点' : '卖点'}</b><p>${esc(a.msg || '')}</p></div><button class="ax">×</button>`;
    d.querySelector('.ax').onclick = () => d.remove();
    box.appendChild(d);
    setTimeout(() => d.remove(), 26000);
  });
}
async function runScan() {
  if (S.busy.scan) return;
  S.busy.scan = true;
  $('#btn-scan').disabled = true;
  $('#scan-prog').hidden = false;
  try {
    const lim = +(($('#seg-scan .on') || {}).dataset || {}).n || 80;
    const j = await post('/api/scan', { limit: lim });
    await pollJob(j.job.id, s => {
      const sp = $('#scan-prog span');
      if (sp) sp.textContent = s.msg ? `${s.msg}` : '扫描中…';
    });
    const r = await jobResult(j.job.id);
    if (r.state !== 'done') throw new Error(r.error || '没跑完');
    S.scanItems = (r.result && r.result.items) || [];
    S.scanRan = true;
    paintScan();
    const sst = (r.result && r.result.stats) || {};
    toast(sst.gated ? `看完 ${S.scanItems.length} 只 —— 大盘不配合，先别急着买`
      : `看完 ${S.scanItems.length} 只`);
  } catch (e) { toast('扫描失败：' + e.message, true); }
  finally {
    S.busy.scan = false;
    $('#btn-scan').disabled = false;
    setTimeout(() => { $('#scan-prog').hidden = true; }, 600);
    paintScreen();
  }
}
function paintScan() {
  const items = S.scanItems || [];
  $('#scan-meta').textContent = items.length ? `${items.length} 只` : '还没扫过';
  const box = $('#scan-list');
  if (!items.length) {
    box.innerHTML = `<div class="empty"><p><b>还没扫过。</b><br>点「开始扫描」看自己关注的这批股票现在什么情况。</p></div>`;
    return;
  }
  const sorted = items.slice().sort((a, b) => (num(b.score) || 0) - (num(a.score) || 0));
  box.innerHTML = sorted.map((a, i) => stockCard({ ...a, _kind: (a.rank || (a.checks && a.checks.ma && a.checks.chip && a.checks.pos && a.checks.bottom)) ? 'hit' : 'near' }, i, sorted.length)).join('');
}

/* ---------------------------------------------------------------- 检验 */
function segVal(sel) { const b = $(sel + ' .on'); return b ? b.dataset.n : null; }
function paintBacktest() {
  const r = S.bt;
  $('#bt-out').hidden = !r;
  $('#bt-empty').hidden = !!r;
  if (!r) return;
  const s = r.summary || {};
  $('#bt-kpis').innerHTML = [
    ['一共几笔', s.count, s.open ? `已卖 ${s.closed} · 还拿着 ${s.open}` : `全部卖出 ${s.closed} 笔`, ''],
    // 成本单独一格：先看毛利够不够付手续费，再看净收益才有意义
    // 这里必须留 2 位小数，不然 -0.02% 会被显示成 -0.0%，看着像刚好打平
    ['扣成本前', (s.gross_ret > 0 ? '+' : '') + pct(s.gross_ret, 2), `每笔来回成本约 ${(s.avg_cost || 0).toFixed(2)}%`, s.gross_ret > 0 ? 'up' : 'down'],
    ['扣成本后', (s.avg_ret > 0 ? '+' : '') + pct(s.avg_ret, 2), s.gross_ret > 0 && s.avg_ret <= 0 ? '毛利被手续费吃光了' : `中间那笔 ${pct(s.med_ret, 2)}`, s.avg_ret > 0 ? 'up' : 'down'],
    ['赚钱的占比', pct(s.win_rate, 1), `不亏本至少要 ${pct(s.breakeven_wr || 0, 1)}`, s.win_rate >= (s.breakeven_wr || 50) ? 'up' : 'down'],
    ['亏小赚大', `${s.payoff || 0} 倍`, `赢的 +${pct(s.avg_win)}，输的 ${pct(s.avg_loss)}`, s.payoff >= 1 ? 'up' : 'down'],
    ['平均拿几天', `${s.avg_hold} 天`, `赚最多 +${pct(s.max_win)}，亏最多 ${pct(s.max_loss)}`, ''],
  ].map(([k, v, sub, c]) => `<div class="kpi"><div class="k">${esc(k)}</div><div class="v ${c}">${esc(String(v))}</div><div class="s">${esc(String(sub))}</div></div>`).join('');
  $('#bt-dist').innerHTML = distBars(r.trades);
  $('#bt-reasons').innerHTML = reasonBars(s.reasons);
  const tr = r.trades || [];
  $('#bt-meta').textContent = `看了 ${r.scanned} 只 · 用时 ${r.elapsed}s`;
  $('#bt-list').innerHTML = tr.length ? tr.map(t => `
    <div class="stk" data-code="${esc(t.code)}">
      <div class="stk-h">
        <div><div class="stk-nm"><b>${esc(t.name || t.code)}</b></div><div class="code-m">${esc(t.code)} · 拿 ${t.hold} 天</div></div>
        <div class="stk-pr"><b class="${cls(t.ret)}">${t.ret > 0 ? '+' : ''}${fmt(t.ret)}%</b><span style="color:var(--txt-3)">${esc(rc(t.reason))}</span></div>
      </div>
      <div class="stk-f"><span class="tag">买 ${esc(t.buy_date)} · ${fmt(t.buy)}</span><span class="tag">卖 ${esc(t.sell_date)} · ${fmt(t.sell)}</span>${t.gross != null ? `<span class="tag">扣前 ${t.gross > 0 ? '+' : ''}${fmt(t.gross)}%</span>` : ''}</div>
    </div>`).join('') : '<div class="wempty">没有产生交易</div>';
}
/* 单笔收益分布：亏的红的、赚的绿的，两头都得有才算健康 */
function distBars(trades) {
  const rows = (trades || []).filter(t => !t.open);
  if (!rows.length) return '<div class="wempty">还没有卖掉的交易</div>';
  const bins = [
    ['亏 10% 以上', t => t.ret <= -10, 'down'],
    ['亏 5~10%', t => t.ret > -10 && t.ret <= -5, 'down'],
    ['亏 5% 以内', t => t.ret > -5 && t.ret < 0, 'down'],
    ['赚 5% 以内', t => t.ret >= 0 && t.ret < 5, 'up'],
    ['赚 5~10%', t => t.ret >= 5 && t.ret < 10, 'up'],
    ['赚 10% 以上', t => t.ret >= 10, 'up'],
  ].map(([k, f, c]) => [k, rows.filter(f).length, c]);
  const mx = Math.max(1, ...bins.map(b => b[1]));
  return `<div class="rank">${bins.map(([k, v, c]) => `
    <div class="rr"><span>${k}</span><div class="bar"><i class="${c}" style="width:${v / mx * 100}%"></i></div><b>${v}</b></div>`).join('')}
  </div><div class="hint">赚的和亏的两头都得有：全是「赚 5% 以内」说明止盈太早、拿不住；「亏 10% 以上」冒头说明止损被跳空穿透了。</div>`;
}
function rc(k) {
  return ({
    'take_profit': '到目标价', 'fixed_target': '到目标价', 'stop_loss': '跌到止损',
    'trail': '从高点回落', 'ma_exit': '跌破均线', 'max_hold': '拿太久', 'ma': '跌破均线', 'end': '还没卖',
  })[k] || k || '—';
}
function reasonBars(reasons) {
  const rs = Object.entries(reasons || {});
  if (!rs.length) return '<div class="wempty">还没有交易记录</div>';
  const total = rs.reduce((a, b) => a + b[1], 0) || 1;
  // 按笔数从多到少排：后端 dict 的插入顺序是按「首次出现」来的，
  // 不排序的话 11 笔会排在 15 笔前面，看起来像条长画错了。
  rs.sort((a, b) => b[1] - a[1]);
  return `<div class="rank">${rs.map(([k, v]) => `
    <div class="rr"><span>${esc(rc(k))}</span><div class="bar"><i style="width:${v / total * 100}%"></i></div><b>${v}</b></div>`).join('')}
  </div><div class="hint">「从高点回落」占比最高是正常的 —— 这套规则本来就跟着趋势走。如果「跌到止损」占了一大片，说明信号质量不够，别急着上手。</div>`;
}
async function runBacktest() {
  if (S.busy.bt) return;
  S.busy.bt = true;
  $('#btn-bt').disabled = true;
  $('#bt-prog').hidden = false;
  $('#bt-empty').hidden = true;
  try {
    const j = await post('/api/backtest', {
      limit: +(segVal('#seg-bt-limit') || 40),
      lookback: +(segVal('#seg-bt-look') || 250),
      mode: 'balanced',
      codes: (S.items || []).length ? S.items.slice(0, +(segVal('#seg-bt-limit') || 40)).map(a => a.code) : null,
    });
    await pollJob(j.job.id, s => { const sp = $('#bt-prog span'); if (sp) sp.textContent = s.msg || '正在检验…'; });
    const r = await jobResult(j.job.id);
    if (r.state !== 'done') throw new Error(r.error || '没跑完');
    S.bt = r.result;
    paintBacktest();
    toast(`检验完成，一共 ${r.result.summary.count} 笔`);
  } catch (e) {
    toast('检验失败：' + e.message, true);
    $('#bt-empty').hidden = false;
  } finally {
    S.busy.bt = false;
    $('#btn-bt').disabled = false;
    setTimeout(() => { $('#bt-prog').hidden = true; }, 600);
  }
}
function drawBtChart() {
  // 检验页不再画资金曲线：钱的事统一归「账户」，免得两页给出两个差 9 倍的数
}

/* ---------------------------------------------------------------- 账户 */
function paintPortfolio() {
  const r = S.pf;
  $('#pf-out').hidden = !r;
  $('#pf-empty').hidden = !!r;
  if (!r) return;
  const s = r.summary || {};
  $('#pf-kpis').innerHTML = [
    ['总共赚了', (s.total_ret > 0 ? '+' : '') + pct(s.total_ret), `最后剩 ${money(s.final_equity)} 元`, s.total_ret > 0 ? 'up' : 'down'],
    ['折成一年', (s.annual > 0 ? '+' : '') + pct(s.annual), `一共 ${s.days} 个交易日`, s.annual > 0 ? 'up' : 'down'],
    ['最难受的时候', pct(s.mdd), `相对风险的性价比 ${s.calmar}`, 'down'],
    ['收益波动比', String(s.sharpe), s.sharpe >= 1 ? '不错' : s.sharpe >= 0.5 ? '一般' : '偏低', s.sharpe >= 1 ? 'up' : 'warn'],
    ['赚钱的占比', pct(s.win_rate, 1), `赚的比亏的多 ${s.profit_factor} 倍`, s.win_rate >= 50 ? 'up' : 'down'],
    ['成交笔数', s.trades, `没钱/满仓跳过 ${s.skipped} 次`, 'warn'],
  ].map(([k, v, sub, c]) => `<div class="kpi"><div class="k">${esc(k)}</div><div class="v ${c}">${esc(String(v))}</div><div class="s">${esc(String(sub))}</div></div>`).join('');
  const fees = (r.trades || []).reduce((a, t) => a + (num(t.fee) || 0), 0);
  const util = num(s.util) || 0;
  $('#pf-cost').innerHTML = `<div class="rank">
      <div class="rr"><span>钱真正在用</span><div class="bar"><i style="width:${Math.min(100, util)}%"></i></div><b>${util}%</b></div>
      <div class="rr"><span>手续费一共</span><div class="bar"><i style="width:${Math.min(100, fees / Math.max(1, s.initial_cash) * 100 * 20)}%"></i></div><b>${money(fees)}</b></div>
    </div>
    <div class="hint">${s.taken} 个信号真买进了，${s.skipped} 个因为满仓或钱不够被跳过；平均每笔拿 ${s.avg_hold} 个交易日。「钱真正在用」太低，说明钱大部分时间躺着。</div>`;
  const tr = r.trades || [];
  $('#pf-meta').textContent = `看了 ${r.scanned} 只 · 信号 ${r.candidates} 个`;
  $('#pf-list').innerHTML = tr.length ? tr.map(t => `
    <div class="stk" data-code="${esc(t.code)}">
      <div class="stk-h">
        <div><div class="stk-nm"><b>${esc(t.name || t.code)}</b></div><div class="code-m">${esc(t.code)} · ${t.shares} 股 · 拿 ${t.hold} 天</div></div>
        <div class="stk-pr"><b class="${cls(t.ret_net)}">${t.ret_net > 0 ? '+' : ''}${fmt(t.ret_net)}%</b><span class="${cls(t.pnl)}">${t.pnl > 0 ? '+' : ''}${money(t.pnl)} 元</span></div>
      </div>
      <div class="stk-f"><span class="tag">${esc(t.buy_date)} → ${esc(t.sell_date)}</span><span class="tag">手续费 ${money(t.fee)}</span><span class="tag i">${esc(rc(t.reason))}</span></div>
    </div>`).join('') : '<div class="wempty">没有产生成交</div>';
  drawPfChart();
}
async function runPortfolio() {
  if (S.busy.pf) return;
  S.busy.pf = true;
  $('#btn-pf').disabled = true;
  $('#pf-prog').hidden = false;
  $('#pf-empty').hidden = true;
  try {
    const lim = 40;
    const j = await post('/api/portfolio', {
      limit: lim, lookback: 250, mode: 'balanced',
      codes: (S.items || []).length ? S.items.slice(0, lim).map(a => a.code) : null,
      initial_cash: +(segVal('#seg-pf-cash') || 1000000),
      max_pos: +(segVal('#seg-pf-pos') || 5),
      pos_pct: +(segVal('#seg-pf-pct') || 0.2),
      slippage: 0.001, commission: 0.00025, stamp: 0.001,
    });
    await pollJob(j.job.id, s => { const sp = $('#pf-prog span'); if (sp) sp.textContent = s.msg || '正在模拟…'; });
    const r = await jobResult(j.job.id);
    if (r.state !== 'done') throw new Error(r.error || '没跑完');
    S.pf = r.result;
    paintPortfolio();
    toast(`模拟完成，成交 ${r.result.summary.trades} 笔`);
  } catch (e) {
    toast('模拟失败：' + e.message, true);
    $('#pf-empty').hidden = false;
  } finally {
    S.busy.pf = false;
    $('#btn-pf').disabled = false;
    setTimeout(() => { $('#pf-prog').hidden = true; }, 600);
  }
}
function drawPfChart() {
  if (!S.pf) return;
  drawEquity($('#pf-chart'), S.pf.curve, true);
}

/* ---------------------------------------------------------------- 记忆 */
async function loadMemory() {
  try {
    if (!S.memDays.length) {
      const r = await api('/api/memory?n=60');
      S.memDays = r.days || [];
      const sel = $('#mem-date');
      sel.innerHTML = S.memDays.map(d => `<option value="${esc(d.date)}">${esc(d.date)} · 选 ${d.hit} 只能买 / ${d.watch} 只差点</option>`).join('') ||
        '<option value="">还没有记录</option>';
      if (S.memDays.length && !S.memDate) S.memDate = S.memDays[0].date;
      sel.value = S.memDate;
    }
    if (!S.memOv) {
      try { S.memOv = await api('/api/memory?overview=1&n=30'); } catch (_) { S.memOv = { days: [] }; }
    }
    if (S.memDate) {
      const rv = await api('/api/memory?review=1&date=' + encodeURIComponent(S.memDate));
      S.memRv = rv;
    }
    paintMemory();
    setSub(S.memDate ? `${S.memDate} 的记录` : '还没有历史记录');
  } catch (e) {
    toast('读取记忆失败：' + e.message, true);
  }
}
function memKindOf(x) {
  if (x.kind) return x.kind;
  if (x.hit === false || x.is_watch) return 'watch';
  return 'hit';
}
function memRows() {
  const rv = S.memRv || {};
  const a = (rv.rows || []).map(x => ({ ...x, _k: 'hit' }));
  const b = (rv.watch_rows || []).map(x => ({ ...x, _k: 'watch' }));
  const all = a.concat(b);
  if (S.memSrc === 'hit') return all.filter(x => x._k === 'hit');
  if (S.memSrc === 'watch') return all.filter(x => x._k === 'watch');
  return all;
}
function paintMemory() {
  const rv = S.memRv;
  const items = memRows();
  const box = $('#mem-kpis');
  if (!rv || !items.length) {
    box.innerHTML = `<div class="kpi"><div class="k">还没有记录</div><div class="v">—</div><div class="s">软件每天收盘后会记一笔，之后就能回看</div></div>`;
    $('#mem-say').innerHTML = '<div class="hint">这里会把过去几天选出来的股票拉出来，看看后来涨没涨 —— 用来判断这套条件最近靠不靠谱。</div>';
    $('#mem-list').innerHTML = '';
  } else {
    const rows = items.filter(x => x.ret != null);
    const pend = items.filter(x => x.ret == null);
    const n = rows.length;
    const win = rows.filter(x => x.ret > 0).length;
    const avg = n ? rows.reduce((a, b) => a + num(b.ret), 0) / n : 0;
    const best = n ? rows.reduce((a, b) => (num(b.ret) > num(a.ret) ? b : a)) : null;
    const worst = n ? rows.reduce((a, b) => (num(b.ret) < num(a.ret) ? b : a)) : null;
    const hitT = rows.filter(x => x.sold_target).length;
    const hitS = rows.filter(x => x.sold_stop).length;
    box.innerHTML = [
      ['当时选中', items.length, '只', ''],
      ['到今天平均', n ? (avg > 0 ? '+' : '') + fmt(avg, 2) + '%' : '—', '按收盘价算', n ? (avg >= 0 ? 'up' : 'down') : ''],
      ['赚钱的', n ? `${win}/${n}` : '—', n ? `占 ${pct(win / n * 100, 0)}` : '等收盘', n ? (win * 2 >= n ? 'up' : 'down') : ''],
      ['最好 / 最差', best ? '+' + fmt(best.ret, 1) + '%' : '—', worst ? `${esc(worst.name || '')} 最差 ${fmt(worst.ret, 1)}%` : '等收盘', 'up'],
    ].map(([k, v, s, c]) => `<div class="kpi"><div class="k">${esc(k)}</div><div class="v ${c}">${esc(String(v))}</div><div class="s">${s}</div></div>`).join('');
    const say = [];
    if (!n) say.push(['还在等收盘', '这一天是今天，日线还没出来。等收盘或明天再回来看就有涨跌幅了。']);
    else {
      if (avg >= 3) say.push(['这批是赚的', `平均 +${fmt(avg, 2)}%，${n} 只里 ${win} 只赚钱。`]);
      else if (avg <= -3) say.push(['这批是亏的', `平均 ${fmt(avg, 2)}%，${n} 只里只有 ${win} 只赚钱。`]);
      else say.push(['基本在原地', `平均 ${fmt(avg, 2)}%，好票烂票互相抵消了。`]);
      say.push(['止损止盈管不管用', `按当时给的价位，${hitT} 只摸到过止盈、${hitS} 只跌破过止损。跌破止损说明当时那套判断没成立 —— 不是软件算错，是行情没按预期走。`]);
      if (pend.length) say.push(['还有没算的', `${pend.length} 只刚选出来，等收盘价。`]);
    }
    $('#mem-say').innerHTML = `<div class="say">${say.map(([h, t]) => `<div class="sr"><b>${esc(h)}</b><p>${esc(t)}</p></div>`).join('')}</div>`;
    $('#mem-list').innerHTML = items.map(x => {
      const kind = x._k;
      return `<div class="stk" data-code="${esc(x.code)}">
        <div class="stk-h">
          <div><div class="stk-nm"><b>${esc(x.name || x.code)}</b>${kind === 'hit' ? '<i style="color:var(--up);border-color:color-mix(in srgb,var(--up) 40%,transparent)">当时能买</i>' : '<i>当时差点</i>'}</div>
          <div class="code-m">${esc(x.code)}${x.stop || x.target ? ` · 止损 ${fmt(x.stop)} / 目标 ${fmt(x.target)}` : ''}</div></div>
          <div class="stk-pr"><b class="${cls(x.ret)}">${x.ret == null ? '等收盘' : (x.ret > 0 ? '+' : '') + fmt(x.ret, 2) + '%'}</b><span style="color:var(--txt-3)">当时 ${fmt(x.then)} → 现在 ${fmt(x.last)}</span></div>
        </div>
        <div class="stk-f">
          <span class="tag">最高 ${x.best == null ? '—' : '+' + fmt(x.best, 1) + '%'}</span>
          <span class="tag">最低 ${x.worst == null ? '—' : fmt(x.worst, 1) + '%'}</span>
          <span class="tag">${x.days == null ? '—' : '已过 ' + x.days + ' 天'}</span>
        </div>
      </div>`;
    }).join('');
  }
  // 每天的成绩
  const ov = (S.memOv && S.memOv.days) || [];
  $('#mem-days').innerHTML = ov.length ? ov.map(d => `
    <div class="day" data-date="${esc(d.date)}">
      <b>${esc(d.date)}</b>
      <span>能买 ${d.hit} · 差点 ${d.watch}</span>
      <span class="${cls(d.avg_ret)}">${d.avg_ret == null ? '—' : (d.avg_ret > 0 ? '+' : '') + fmt(d.avg_ret, 2) + '%'}</span>
    </div>`).join('') : '<div class="wempty">还没有记录</div>';
}

/* ---------------------------------------------------------------- 说明 */
function paintMethod() {
  const P = (S.cfg && S.cfg.params) || {};
  const cap = { profit_cap: pct(num(P.profit_cap) * 100, 0), pos_cap: pct(num(P.pos_cap) * 100, 0) };
  $$('[data-p]').forEach(el => {
    const k = el.dataset.p;
    let v = P[k];
    if (v == null) return;
    if (k in cap) v = cap[k];
    if (k === 'entry_mode') v = v === 'close' ? '收盘价' : '尾盘价';
    el.textContent = v;
  });
  $$('[data-p-on]').forEach(el => {
    const on = !!P[el.dataset.pOn];
    el.textContent = on ? '已打开' : '默认关';
  });
}

/* ---------------------------------------------------------------- 我的 */
async function paintMe() {
  $('#me-ver').textContent = `v${((S.cfg && S.cfg.version) || '1.8.8')} · 手机版`;
  const c = (S.cfg && S.cfg.cache) || {};
  const n = c.files != null ? c.files : (c.count != null ? c.count : null);
  const mb = c.size_mb != null ? c.size_mb : (c.bytes != null ? (c.bytes / 1048576).toFixed(1) : null);
  $('#me-cache-size').textContent = n != null ? `${n} 个文件${mb != null ? ' · ' + mb + ' MB' : ''}` : '点一下清掉';
  $('#me-data').textContent = c.last_update ? `最新数据 ${c.last_update}` : '—';
}

/* ---------------------------------------------------------------- 设置 */
const SET_META = [
  { id: 'strategy', t: '用哪套选股方案', tag: 'STRAT', f: [
    ['strategy', '选股方案', 'strat', '换一套逻辑就换这里'],
    ['_strat_ops', '管理', 'stratops', ''],
  ] },
  { id: 'auto', t: '自动选股', tag: 'AUTO', f: [
    ['auto_scan', '打开软件就自动选股', 'bool', '不用再手动点'],
    ['auto_limit', '每次看多少只', 'int', '600 ≈ 40 秒；6000 ≈ 8 分钟'],
    ['auto_hours', '几点到几点干活', 'text', '例如 09:35-15:00'],
    ['auto_every', '隔多久看一次（秒）', 'int', '300 = 每 5 分钟'],
    ['auto_final_enabled', '尾盘最后确认一次', 'bool', '收盘前再跑一遍给最终名单'],
    ['auto_final', '最后确认的时间', 'text', '默认 14:50'],
    ['workers', '同时开几个线程抓', 'int', '太快会被行情源限速'],
  ] },
  { id: 'avg', t: '① 价格和平均成本', tag: '核心', f: [
    ['ma_days', '要连续几天都站上', 'int', '默认 3 天'],
    ['ma_ratio', '高出多少才算站上', 'float', '1.0 = 平着也算'],
    ['ma_tol', '允许几天不达标', 'int', '0 = 一天都不能差'],
    ['entry_mode', '拿什么价格去比', 'sel', '', [['tail', '尾盘价'], ['close', '收盘价']]],
    ['tail_from', '在几点判定', 'sel', '', [['14:30', '14:30'], ['14:45', '14:45'], ['14:57', '14:57'], ['close', '收盘']]],
  ] },
  { id: 'chip', t: '② 上方套牢盘', tag: '核心', f: [
    ['profit_cap', '套牢盘最多能有多少', 'pct', '默认 25%'],
    ['chip_window', '往回看多少天', 'int', '交易日数'],
    ['chip_bins', '价位切多细', 'int', '越细图越平滑'],
    ['real_turnover', '按真实换手算', 'bool', '比拍系数准'],
    ['chip_decay', '老筹码遗忘速度', 'float', '关掉真实换手才生效'],
  ] },
  { id: 'pos', t: '③ 价格在低位', tag: '核心', f: [
    ['pos_cap', '价格位置最多到哪', 'pct', '默认 30%，调大会多选出票'],
  ] },
  { id: 'bottom', t: '④ 底部横着走', tag: '过滤', f: [
    ['bottom_enable', '启用这一关', 'bool', ''],
    ['bottom_days', '看最近多少天', 'int', ''],
    ['bottom_amp', '波动最大多少', 'pct', '最高÷最低−1 的上限'],
    ['bottom_slope', '允许单边走多少', 'float', '越大越能接受慢慢涨的'],
  ] },
  { id: 'trend', t: '⑤ 还在 20 日线上', tag: '默认关', f: [
    ['ma_trend_enable', '启用这一关', 'bool', '打开就基本选不出票'],
    ['ma_trend_period', '用几日均线', 'int', ''],
  ] },
  { id: 'filter', t: '⑥ 先筛掉哪些', tag: '过滤', f: [
    ['min_price', '最低股价（元）', 'float', '太便宜的多半有问题'],
    ['max_price', '最高股价（元）', 'float', '太贵的钱不够分配'],
    ['exclude_st', '不要 ST / 退市风险', 'bool', ''],
    ['exclude_kcb', '不要科创板（688）', 'bool', ''],
    ['exclude_cyb', '不要创业板（300）', 'bool', ''],
    ['exclude_bj', '不要北交所', 'bool', ''],
    ['exclude_new', '上市不满多少天不要', 'int', '0 = 不过滤'],
    ['min_turnover_amt', '成交额低于多少不要', 'float', '0 = 不限'],
  ] },
  { id: 'trade', t: '⑦ 怎么买怎么卖', tag: '交易', f: [
    ['buy_rule', '按什么价格成交', 'sel', '只影响检验和模拟', [['pullback', '便宜一点才买'], ['same_day_tail', '当天尾盘买'], ['next_open', '第二天开盘买'], ['next_open_break', '第二天突破买']]],
    ['buy_pullback', '便宜多少才买', 'pct', ''],
    ['stop_loss', '亏多少就走（上限）', 'pct', '取最近的那个止损'],
    ['min_stop', '止损至少离现价多远', 'pct', '贴太近会被抖动打掉'],
    ['take_profit', '涨到多少算目标', 'pct', ''],
    ['sell_mode', '赚了以后怎么卖', 'sel', '', [['atr', '从最高点回落就卖'], ['fixed', '到目标价就卖']]],
    ['trail_drawdown', '回落多少就卖', 'pct', ''],
    ['max_hold', '最多拿几天', 'int', ''],
  ] },
];
const WEIGHT_META = [['surplus', '高出成本'], ['profit', '套牢盘'], ['position', '价格位置'], ['bottom', '底部结构'], ['trend', '趋势']];

function renderSettings() {
  const P = (S.cfg && S.cfg.params) || {};
  const W = (S.cfg && S.cfg.weights) || {};
  const row = (k, n, kind, hint, opts) => {
    if (kind === 'strat') {
      const items = (S.strats && S.strats.items) || [];
      const cur = P[k] || (S.strats && S.strats.current) || '';
      const one = items.find(x => x.key === cur) || {};
      const opts2 = items.map(x => `<option value="${esc(x.key)}" ${x.key === cur ? 'selected' : ''}>${esc(x.name)}${x.user ? '（自己写的）' : ''}</option>`).join('');
      const gates2 = (one.gates && one.gates.length)
        ? `<div class="strat-gates">${one.gates.map(g => `<span class="sgat" title="${esc(g.hint || '')}">${esc(g.label)}</span>`).join('')}</div>`
        : '';
      return `<div class="frow"><div class="fl"><b>${esc(n)}</b>${hint ? `<span>${esc(hint)}</span>` : ''}</div>
        <select data-k="${k}" data-t="str">${opts2}</select></div>
        ${one.desc ? `<div class="strat-desc">${esc(one.desc)}</div>` : ''}${gates2}`;
    }
    if (kind === 'stratops') {
      return `<div class="frow strat-ops">
        <div class="fl"><b>自己做一套</b><span>放进 data/strategies 就能用，不用改程序</span></div>
        <button class="btn sm ghost" id="btn-strat-tpl" type="button">取模板</button>
        <button class="btn sm ghost" id="btn-strat-reload" type="button">重新加载</button></div>`;
    }
    if (kind === 'bool') {
      return `<div class="frow"><div class="fl"><b>${esc(n)}</b>${hint ? `<span>${esc(hint)}</span>` : ''}</div>
        <div class="sw ${P[k] ? 'on' : ''}" data-k="${k}" data-t="bool"></div></div>`;
    }
    if (kind === 'sel') {
      return `<div class="frow"><div class="fl"><b>${esc(n)}</b>${hint ? `<span>${esc(hint)}</span>` : ''}</div>
        <select data-k="${k}" data-t="str">${(opts || []).map(([v, t]) => `<option value="${esc(v)}" ${String(P[k]) === String(v) ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></div>`;
    }
    if (kind === 'text') {
      return `<div class="frow"><div class="fl"><b>${esc(n)}</b>${hint ? `<span>${esc(hint)}</span>` : ''}</div>
        <input type="text" data-k="${k}" data-t="str" value="${esc(P[k] == null ? '' : P[k])}"></div>`;
    }
    const isPct = kind === 'pct';
    const v = isPct ? (num(P[k]) != null ? +(num(P[k]) * 100).toFixed(4) : '') : (P[k] == null ? '' : P[k]);
    return `<div class="frow"><div class="fl"><b>${esc(n)}${isPct ? '（%）' : ''}</b>${hint ? `<span>${esc(hint)}</span>` : ''}</div>
      <input type="number" data-k="${k}" data-t="${isPct ? 'pct' : kind}" step="${isPct ? '0.1' : (kind === 'float' ? '0.01' : '1')}" value="${esc(v)}"></div>`;
  };
  let html = SET_META.map(cat => `<div class="set-card"><h3>${esc(cat.t)}<span class="em">${esc(cat.tag)}</span></h3>
    ${cat.f.map(([k, n, kind, hint, opts]) => row(k, n, kind, hint, opts)).join('')}</div>`).join('');
  html += `<div class="set-card"><h3>⑧ 评分权重<span class="em">合计 100</span></h3>
    ${WEIGHT_META.map(([k, n]) => `<div class="frow"><div class="fl"><b>${esc(n)}</b></div>
      <input type="number" data-k="${k}" data-t="int" data-w="${k}" step="1" value="${esc(W[k] == null ? '' : W[k])}"></div>`).join('')}
    <div class="frow"><div class="fl"><span>四个数字加起来不是 100 也能用，软件会按比例折算。</span></div></div></div>`;
  $('#set-body').innerHTML = html;
}
/* 选股方案：取一份模板 / 改完重新加载（不用重启服务） */
async function newStrategyFile() {
  try {
    const r = await post('/api/strategy/new', { name: '' });
    if (r.items) S.strats = { items: r.items, current: (S.strats || {}).current || '' };
    toast('模板已放好：' + r.path + '\n用记事本改数字，改完点「重新加载」');
    renderSettings();
  } catch (e) { toast('没生成成功：' + e.message, true); }
}
async function reloadStrategies() {
  try {
    const r = await api('/api/strategy/reload');
    S.strats = { items: r.items || [], current: (S.strats || {}).current || '' };
    const n = Object.keys(r.errors || {}).length;
    if (n) { toast('有 ' + n + ' 个方案没加载成功，看日志', true); console.warn('策略加载失败', r.errors); }
    else toast('已重新加载，现在有 ' + (r.items || []).length + ' 套方案');
    renderSettings();
  } catch (e) { toast('重新加载失败：' + e.message, true); }
}

function collectSettings() {
  const params = { ...((S.cfg && S.cfg.params) || {}) };
  const weights = { ...((S.cfg && S.cfg.weights) || {}) };
  $$('#set-body [data-k]').forEach(el => {
    const k = el.dataset.k, t = el.dataset.t;
    if (t === 'bool') { params[k] = el.classList.contains('on'); return; }
    if (t === 'str') { params[k] = el.value; return; }
    let v = parseFloat(el.value);
    if (Number.isNaN(v)) return;
    if (t === 'int') v = Math.round(v);
    if (t === 'pct') v = v / 100;
    if (el.dataset.w) weights[k] = v; else params[k] = v;
  });
  return { params, weights };
}
async function saveSettings() {
  try {
    const { params, weights } = collectSettings();
    const r = await post('/api/config', { params, weights });
    S.cfg = r;
    toast('已保存，下一次就按新条件跑');
    pollAuto();
  } catch (e) { toast('没保存成功：' + e.message, true); }
}

/* ===================================================================
   图表（全部用 canvas 手画，量级小、不依赖任何库）
   =================================================================== */
function prepCanvas(cv, h) {
  if (!cv) return null;
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth || 320;
  const H = h || cv.clientHeight || 220;
  cv.width = Math.round(W * dpr);
  cv.height = Math.round(H * dpr);
  cv.style.height = H + 'px';
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  return { g, W, H };
}
function niceTicks(mn, mx, n) {
  const span = mx - mn || 1;
  const step0 = span / n;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const norm = step0 / mag;
  const step = (norm >= 5 ? 5 : norm >= 2 ? 2 : 1) * mag;
  const out = [];
  for (let v = Math.ceil(mn / step) * step; v <= mx + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

/** 资金曲线（账户页专用）：curve 是百分比数组 [[date, pct], ...] */
function drawEquity(cv, curve, isAccount) {
  const o = prepCanvas(cv, 190);
  if (!o) return;
  const { g, W, H } = o;
  const line = cssVar('line'), t3 = cssVar('txt-3'), acc = cssVar('acc');
  const pts0 = (curve || []).map(p => num(p[1])).filter(v => v != null);
  if (pts0.length < 2) {
    g.fillStyle = t3; g.font = '12px system-ui'; g.textAlign = 'center';
    g.fillText('还没有足够的交易，没东西可画', W / 2, H / 2);
    return;
  }
  const pad = { l: 44, r: 10, t: 12, b: 22 };
  const w = W - pad.l - pad.r, h = H - pad.t - pad.b;
  const mn = Math.min(0, ...pts0), mx = Math.max(0, ...pts0);
  const tk = niceTicks(mn, mx, 4);
  const lo = Math.min(mn, tk[0]), hi = Math.max(mx, tk[tk.length - 1]);
  const X = i => pad.l + (w * i) / (pts0.length - 1);
  const Y = v => pad.t + h - (h * (v - lo)) / (hi - lo || 1);
  g.font = '10px system-ui'; g.textAlign = 'right'; g.fillStyle = t3;
  tk.forEach(v => {
    g.strokeStyle = line; g.lineWidth = 1;
    g.beginPath(); g.moveTo(pad.l, Y(v)); g.lineTo(W - pad.r, Y(v)); g.stroke();
    g.fillText(v.toFixed(0) + '%', pad.l - 6, Y(v) + 3);
  });
  // 零轴
  g.strokeStyle = t3; g.setLineDash([3, 3]);
  g.beginPath(); g.moveTo(pad.l, Y(0)); g.lineTo(W - pad.r, Y(0)); g.stroke();
  g.setLineDash([]);
  const grad = g.createLinearGradient(0, pad.t, 0, pad.t + h);
  const up = pts0[pts0.length - 1] >= 0;
  const col = up ? cssVar('up') : cssVar('down');
  grad.addColorStop(0, up ? 'rgba(255,77,94,.35)' : 'rgba(18,196,139,.35)');
  grad.addColorStop(1, 'rgba(0,0,0,0)');
  g.beginPath();
  pts0.forEach((v, i) => (i ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v))));
  g.lineTo(X(pts0.length - 1), Y(0)); g.lineTo(X(0), Y(0)); g.closePath();
  g.fillStyle = grad; g.fill();
  g.beginPath();
  pts0.forEach((v, i) => (i ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v))));
  g.strokeStyle = col; g.lineWidth = 2; g.lineJoin = 'round'; g.stroke();
  // 终点
  const last = pts0[pts0.length - 1];
  g.beginPath(); g.arc(X(pts0.length - 1), Y(last), 3.2, 0, 7); g.fillStyle = col; g.fill();
  g.fillStyle = col; g.textAlign = 'right'; g.font = '600 11px system-ui';
  g.fillText((last > 0 ? '+' : '') + last.toFixed(1) + '%', W - pad.r, Math.max(pad.t + 9, Y(last) - 7));
  // 起点日期
  const c0 = curve[0] && curve[0][0];
  if (c0) { g.fillStyle = t3; g.font = '10px system-ui'; g.textAlign = 'left'; g.fillText(String(c0).slice(5), pad.l, H - 6); }
}

/** K 线：日 / 周 / 月 */
function drawKlineChart(cv, a, tab) {
  const o = prepCanvas(cv, 230);
  if (!o) return;
  const { g, W, H } = o;
  const t3 = cssVar('txt-3'), line = cssVar('line'), upc = cssVar('up'), dnc = cssVar('down');
  if (tab === 'intraday') { drawIntraday(g, W, H, a); return; }
  const bars = (((a.kline || {})[tab] || {}).bars) || [];
  if (!bars.length) {
    g.fillStyle = t3; g.font = '12px system-ui'; g.textAlign = 'center';
    g.fillText('这只股票没有这段历史数据', W / 2, H / 2); return;
  }
  const n = Math.min(bars.length, tab === 'day' ? 120 : tab === 'week' ? 104 : 60);
  const bs = bars.slice(-n);
  let lo = Math.min(...bs.map(b => b.l)), hi = Math.max(...bs.map(b => b.h));
  const mas = [5, 10, 20].map(p => ({ p, v: bs.map(b => b['ma' + p]) })).filter(x => x.v.some(v => v != null));
  mas.forEach(m => m.v.forEach(v => { if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }));
  const padL = 6, padR = 46, padT = 10, padB = 18;
  const w = W - padL - padR, h = H - padT - padB;
  const span = (hi - lo) || 1;
  const Y = v => padT + h - (h * (v - lo)) / span;
  const bw = Math.max(1.2, (w / bs.length) * 0.66);
  const X = i => padL + (w * (i + 0.5)) / bs.length;
  bs.forEach((b, i) => {
    const c = num(b.c), op = num(b.o), hh = num(b.h), ll = num(b.l);
    const col = c >= op ? upc : dnc;
    g.strokeStyle = col; g.fillStyle = col; g.lineWidth = 1;
    g.beginPath(); g.moveTo(X(i), Y(hh)); g.lineTo(X(i), Y(ll)); g.stroke();
    const y1 = Y(Math.max(op, c)), y2 = Y(Math.min(op, c));
    g.fillRect(X(i) - bw / 2, y1, bw, Math.max(0.8, y2 - y1));
  });
  const MA_C = ['#f5b544', '#3d8bff', '#b07bff'];
  mas.forEach((m, k) => {
    g.strokeStyle = MA_C[k]; g.lineWidth = 1.2; g.beginPath();
    let started = false;
    m.v.forEach((v, i) => {
      if (v == null) return;
      if (!started) { g.moveTo(X(i), Y(v)); started = true; } else g.lineTo(X(i), Y(v));
    });
    g.stroke();
    g.fillStyle = MA_C[k]; g.font = '10px system-ui'; g.textAlign = 'left';
    g.fillText('MA' + m.p, padL + k * 40, padT + 10);
  });
  // 右侧现价 + 止损线
  const px = num(a.price);
  if (px != null) {
    const y = Y(px);
    g.strokeStyle = t3; g.setLineDash([2, 3]); g.lineWidth = 1;
    g.beginPath(); g.moveTo(padL, y); g.lineTo(padL + w, y); g.stroke(); g.setLineDash([]);
    g.fillStyle = t3; g.font = '10px system-ui'; g.textAlign = 'left';
    g.fillText(px.toFixed(2), W - padR + 4, y + 3);
  }
  g.fillStyle = t3; g.font = '10px system-ui'; g.textAlign = 'left';
  g.fillText(String(bs[0].t || bs[0].d || '').slice(0, 10), padL, H - 5);
  g.textAlign = 'right';
  g.fillText(String(bs[bs.length - 1].t || bs[bs.length - 1].d || '').slice(0, 10), padL + w, H - 5);
}

/** 当天分时 */
function drawIntraday(g, W, H, a) {
  const t3 = cssVar('txt-3'), line = cssVar('line'), acc = cssVar('acc'), gold = cssVar('gold');
  const pts = ((a.intraday || {}).points) || [];
  const avg = ((a.intraday || {}).avg) || [];
  if (!pts.length) {
    g.fillStyle = t3; g.font = '12px system-ui'; g.textAlign = 'center';
    g.fillText('今天还没有分时数据（没开盘或休市）', W / 2, H / 2); return;
  }
  const vals = pts.map(p => num(p[1] != null ? p[1] : p.price)).filter(v => v != null)
    .concat(avg.map(p => num(p[1] != null ? p[1] : p.avg)).filter(v => v != null));
  const pre = num(a.prev_close) || num(a.price) || vals[0];
  const lo = Math.min(pre, ...vals), hi = Math.max(pre, ...vals);
  const pad = { l: 6, r: 44, t: 10, b: 18 };
  const w = W - pad.l - pad.r, h = H - pad.t - pad.b;
  const Y = v => pad.t + h - (h * (v - lo)) / ((hi - lo) || 1);
  const X = i => pad.l + (w * i) / Math.max(1, pts.length - 1);
  g.strokeStyle = line; g.lineWidth = 1;
  g.beginPath(); g.moveTo(pad.l, Y(pre)); g.lineTo(pad.l + w, Y(pre)); g.stroke();
  const pctOf = v => (v / pre - 1) * 100;
  g.font = '10px system-ui'; g.textAlign = 'left';
  [[hi, ''], [pre, ''], [lo, '']].forEach(([v]) => {
    g.fillStyle = t3; g.fillText(pctOf(v).toFixed(1) + '%', W - pad.r + 4, Y(v) + 3);
  });
  const pathOf = (arr, key) => {
    g.beginPath();
    arr.forEach((p, i) => {
      const v = num(p[1] != null ? p[1] : p[key]);
      if (v == null) return;
      if (i === 0) g.moveTo(X(i), Y(v)); else g.lineTo(X(i), Y(v));
    });
  };
  if (avg.length) { pathOf(avg, 'avg'); g.strokeStyle = gold; g.lineWidth = 1.2; g.stroke(); }
  pathOf(pts, 'price'); g.strokeStyle = acc; g.lineWidth = 1.6; g.stroke();
}

/** 筹码分布：横着画的柱（价格竖轴） */
function drawChipChart(cv, a) {
  const o = prepCanvas(cv, 170);
  if (!o) return;
  const { g, W, H } = o;
  const t3 = cssVar('txt-3'), upc = cssVar('up'), dnc = cssVar('down'), line = cssVar('line');
  const chips = (a.chip && a.chip.chips) || [];
  if (!chips.length) {
    g.fillStyle = t3; g.font = '12px system-ui'; g.textAlign = 'center';
    g.fillText('这只股票没有筹码数据', W / 2, H / 2); return;
  }
  const px = num(a.price) || 0;
  const lo = Math.min(...chips.map(c => num(c[0]))), hi = Math.max(...chips.map(c => num(c[0])));
  const mx = Math.max(...chips.map(c => num(c[1]))) || 1;
  const pad = { l: 40, r: 10, t: 8, b: 8 };
  const w = W - pad.l - pad.r, h = H - pad.t - pad.b;
  const Y = v => pad.t + h - (h * (v - lo)) / ((hi - lo) || 1);
  chips.forEach(c => {
    const p = num(c[0]), v = num(c[1]);
    g.fillStyle = p <= px ? 'rgba(18,196,139,.55)' : 'rgba(255,77,94,.55)';
    const bh = Math.max(1, h / chips.length - 0.6);
    g.fillRect(pad.l, Y(p) - bh / 2, (v / mx) * w, bh);
  });
  if (px) {
    g.strokeStyle = line; g.setLineDash([2, 3]);
    g.beginPath(); g.moveTo(pad.l, Y(px)); g.lineTo(pad.l + w, Y(px)); g.stroke(); g.setLineDash([]);
    g.fillStyle = t3; g.font = '10px system-ui'; g.textAlign = 'right';
    g.fillText(px.toFixed(2), pad.l - 4, Y(px) + 3);
    g.textAlign = 'left';
    g.fillStyle = dnc; g.fillText('盈利', pad.l + w - 46, Y(px) + 12);
    g.fillStyle = upc; g.fillText('套牢', pad.l + w - 46, Y(px) - 6);
  }
}

/* ===================================================================
   事件绑定 & 启动
   =================================================================== */
function bindSegs() {
  // 选股：全部 / 差一点 / 能买
  $('#seg-screen').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    S.filter = b.dataset.f; paintScreen();
  });
  // 排序
  $('#sorts').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    if (S.sort === b.dataset.s) S.dir = -S.dir; else { S.sort = b.dataset.s; S.dir = -1; }
    paintScreen();
  });
  // 通用分段：点哪只哪只亮，值由 segVal() 去读
  ['#seg-scan', '#seg-bt-limit', '#seg-bt-look', '#seg-pf-cash', '#seg-pf-pos', '#seg-pf-pct', '#seg-mem'].forEach(sel => {
    const el = $(sel); if (!el) return;
    el.addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      el.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
      if (sel === '#seg-mem') { S.memSrc = b.dataset.f; paintMemory(); }
    });
  });
  // 详情抽屉里的周期切换 + 加入自选
  $('#dw-body').addEventListener('click', e => {
    const t = e.target.closest('#dw-tabs button');
    if (t) {
      DW_TAB = t.dataset.t;
      $$('#dw-tabs button').forEach(b => b.classList.toggle('on', b === t));
      drawKlineChart($('#dw-cv'), S.detail, DW_TAB);
      return;
    }
    const w = e.target.closest('[data-wact]');
    if (w && S.detail) {
      const code = S.detail.code, nm = S.detail.name;
      if (w.dataset.wact === 'add') addWatch(code, nm);
      else { closeStock(); go('watch'); addWatch(code, nm); }
    }
  });
}
function bindGlobal() {
  // 底部导航 & 任意 data-go
  document.addEventListener('click', e => {
    const g = e.target.closest('[data-go]');
    if (g) { go(g.dataset.go); return; }
    const s = e.target.closest('[data-code]');
    if (s && !e.target.closest('[data-wact]')) { openStock(s.dataset.code); return; }
    const d = e.target.closest('[data-date]');
    if (d) {
      S.memDate = d.dataset.date;
      const sel = $('#mem-date'); if (sel) sel.value = S.memDate;
      loadMemory();
    }
  });
  $('#btn-back').onclick = () => go('me');
  $('#btn-theme').onclick = () => setTheme(themeNow() === 'dark' ? 'light' : 'dark');
  $('#btn-run').onclick = runScreen;
  $('#btn-stop').onclick = stopJob;
  $('#btn-detail').onclick = () => openModal('detail', '这次选股的细节');
  $('#btn-scan').onclick = runScan;
  $('#btn-bt').onclick = runBacktest;
  $('#btn-pf').onclick = runPortfolio;
  // 搜索：输入即筛（防抖）
  let qt = null;
  $('#q').addEventListener('input', e => {
    clearTimeout(qt);
    const v = e.target.value;
    qt = setTimeout(() => { S.q = v; paintScreen(); }, 120);
  });
  // 自选股
  $('#w-add').onclick = () => { const v = $('#w-code').value; if (addWatch(v)) $('#w-code').value = ''; };
  $('#w-code').addEventListener('keydown', e => { if (e.key === 'Enter') $('#w-add').click(); });
  $('#w-check').onclick = () => checkWatch(true);
  // 记忆
  $('#mem-date').addEventListener('change', e => { S.memDate = e.target.value; loadMemory(); });
  $('#mem-refresh').onclick = () => { S.memDays = []; S.memOv = null; loadMemory(); };
  // 设置
  $('#set-body').addEventListener('click', e => {
    const sw = e.target.closest('.sw');
    if (sw) sw.classList.toggle('on');
  });
  const tpl = $('#btn-strat-tpl');
  if (tpl) tpl.onclick = newStrategyFile;
  const rl = $('#btn-strat-reload');
  if (rl) rl.onclick = reloadStrategies;
  $('#btn-save').onclick = saveSettings;
  $('#btn-reset').onclick = async () => {
    if (!confirm('恢复所有参数为默认值？')) return;
    try { const r = await post('/api/config/reset', {}); S.cfg = r; renderSettings(); toast('已恢复默认'); }
    catch (e) { toast('没恢复成功：' + e.message, true); }
  };
  // 我的
  $('#me-export').onclick = () => {
    if (!(S.items || []).length) { toast('现在没有名单可以导出'); return; }
    try { window.open('/api/export', '_blank'); } catch (_) { location.href = '/api/export'; }
  };
  $('#me-cache').onclick = async () => {
    if (!confirm('清掉本机存的行情缓存？下次会重新抓（不影响名单和参数）。')) return;
    try { const r = await post('/api/cache/clear', {}); toast(`清了 ${r.removed} 个文件`); S.cfg = { ...S.cfg, cache: r.cache }; paintMe(); }
    catch (e) { toast('没清掉：' + e.message, true); }
  };
  // 弹层
  $('#sheet-mask').onclick = closeStock;
  $('#dw-close').onclick = closeStock;
  $('#modal-mask').onclick = closeModal;
  $('#md-close').onclick = closeModal;
  // 安卓返回键 / 浏览器后退：先关弹层
  window.addEventListener('popstate', () => {
    if (!$('#sheet').hidden) { closeStock(); return; }
    if (!$('#modal').hidden) { closeModal(); return; }
    if (S.view !== 'screen') go('screen', { load: false });
  });
  // 切回前台时刷一下自动状态
  document.addEventListener('visibilitychange', () => { if (!document.hidden && S.view === 'screen') pollAuto(); });
}

async function boot() {
  initTheme();
  readColors();
  bindSegs();
  bindGlobal();
  // 主状态：参数 + 最近一次名单 + 记忆成绩
  try {
    S.cfg = await api('/api/config');
  } catch (e) { toast('连不上后台：' + e.message, true); }
  // 选股方案清单（换策略就在设置页换）
  try { S.strats = await api('/api/strategies'); } catch (_) { S.strats = { items: [], current: '' }; }
  try {
    const r = await api('/api/last');
    if (r.result) applyResult(r.result);
    else { paintScreen(); }
  } catch (e) { paintScreen(); }
  paintScreen();
  paintAutoSub();
  // 深链接：#watch / #memory …
  const h = (location.hash || '').replace('#', '');
  go(VIEWS[h] ? h : 'screen', { load: h !== 'screen' });
  if (h === 'screen' || !h) pollAuto();
  // 记忆成绩要读上千个缓存文件，慢（几秒）；放到首屏画完再拉，别卡住启动
  api('/api/memory?overview=1&n=30').then(r => {
    S.memOv = r;
    if (S.view === 'screen') paintScreen();     // 拿到了再补画一次三宫格
  }).catch(() => { });
  api('/api/watch').then(w => {
    S.watchList = w.items || w.list || [];
    if (w.alerts) S.alerts = w.alerts;
    if (S.view === 'watch') paintWatch();
  }).catch(() => { });
}
function paintAutoSub() {
  const c = (S.cfg && S.cfg.cache) || {};
  if (c.last_update) setSub(`行情更新到 ${String(c.last_update).slice(5, 16)}`);
  else setSub('数据还没抓过，点「立即选股」开始');
}
window.addEventListener('error', e => { try { console.warn('页面出错', e.message); } catch (_) { } });

boot();
