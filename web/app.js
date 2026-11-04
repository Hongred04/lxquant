/* 大金融中长线 —— 一个策略的仪表盘。
   四块数据各司其职：
     进场信号（现在该不该买）/ 两只票（买什么）/ 我的持仓（第几天）
     净值曲线 + 年度柱 + 历史机会（这套规则过去到底怎么赚的）
   图表全部手写 canvas，不引第三方库 —— 这个项目从第一天就是零依赖。 */

const $ = s => document.querySelector(s);
const S = { fin: null, hist: null, trades: null, pos: null, range: 0, hover: -1 };
const HOLD = 40;

/* ---------------- 基础工具 ---------------- */
const cssv = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const sgn = v => (v > 0 ? '+' : '');
const dir = v => (v > 0 ? 'up' : v < 0 ? 'down' : 'flat');
const pct = v => (v == null ? '—' : sgn(v) + (+v).toFixed(1) + '%');

async function api(path, body) {
  const r = await fetch(path, body ? {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  } : undefined);
  return r.json();
}

/* ---------------- 启动 ---------------- */
async function boot() {
  try {
    const [fin, hist, trades, pos] = await Promise.all([
      api('/api/fin'), api('/api/fin/history'),
      api('/api/fin/trades'), api('/api/fin/pos'),
    ]);
    if (!fin || !fin.ready) { setTimeout(boot, 2000); return; }
    S.fin = fin; S.hist = hist; S.trades = trades; S.pos = pos;
    $('#boot').hidden = true;
    $('#app').hidden = false;
    renderAll();
  } catch (_) {
    setTimeout(boot, 2500);
  }
}

function renderAll() {
  renderBar(S.fin);
  renderDecision(S.fin);
  renderPicks(S.fin);
  renderPos(S.pos);
  renderStats(S.hist);
  renderTrades(S.trades);
  requestAnimationFrame(paintAll);
}

function paintAll() {
  drawRail(S.fin);
  drawCurve();
  drawYearly();
}

/* ---------------- 顶栏 ---------------- */
function renderBar(f) {
  const m = f.market || {};
  $('#mkt-spot').textContent = m.spot == null ? '—' : (+m.spot).toFixed(2);
  const el = $('#mkt-chg');
  const chg = +f.vs20;
  el.textContent = sgn(chg) + chg.toFixed(2) + '%';
  el.className = 'mkt-v ' + dir(chg);
  el.title = '相对 20 日均线';
  $('#asof').textContent = f.asof || '—';
  $('#foot-l').textContent = `选股池 ${f.scanned} 只 · 算一次 ${f.elapsed} 秒`;
}

/* ---------------- 进场信号 ---------------- */
function renderDecision(f) {
  const v = +f.vs20;
  $('#vs-num').textContent = sgn(v) + v.toFixed(2);

  const on = !!f.allow;
  const vd = $('#verdict');
  vd.className = 'verdict' + (on ? ' on' : '');
  vd.querySelector('b').textContent = on ? '可以买' : '等待';

  const gate = f.gate;
  const hint = $('#hint');
  if (on) {
    hint.className = 'hint on';
    hint.innerHTML = `已跌破 <b>−${gate}%</b>，在进场窗口内。`
      + `按规则买下面两只、各一半，拿满 <b>${f.hold_days} 个交易日</b>。`;
  } else {
    const gap = (gate - Math.abs(v)).toFixed(2);
    hint.className = 'hint';
    hint.innerHTML = `还差 <b>${gap} 个百分点</b>才到进场线（−${gate}%）。`
      + `现在买属于提前，历史上提前买的平均收益明显更差。`;
  }

  const ser = (f.market && f.market.ser) || [];
  $('#rail-cap').innerHTML = `<span>近 ${ser.length} 个交易日</span>`
    + `<span>虚线 = 进场线 −${gate}%</span>`;
}

/* 偏离度轨道图：把「现在离进场线多远」画成位置，而不是只给一个数 */
function drawRail(f) {
  if (!f) return;
  const cv = $('#rail'); if (!cv) return;
  const ser = (f.market && f.market.ser) || [];
  const box = fit(cv); if (!box) return;
  const { g, W, H } = box;
  if (ser.length < 5) return;

  const pad = { l: 1, r: 1, t: 8, b: 8 };
  const w = W - pad.l - pad.r, h = H - pad.t - pad.b;
  const vals = ser.map(p => +p[1]);
  const gate = -f.gate;
  const lo = Math.min(gate - 1.2, ...vals), hi = Math.max(1.5, ...vals);
  const X = i => pad.l + w * i / (vals.length - 1);
  const Y = v => pad.t + h - h * (v - lo) / ((hi - lo) || 1);

  // 进场线以下填淡色，一眼能看出「什么时候在窗口里」
  g.save();
  g.beginPath();
  g.rect(pad.l, Y(gate), w, pad.t + h - Y(gate));
  g.clip();
  g.beginPath();
  vals.forEach((v, i) => (i ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v))));
  g.lineTo(X(vals.length - 1), Y(gate)); g.lineTo(X(0), Y(gate)); g.closePath();
  g.fillStyle = 'rgba(37,99,235,.12)'; g.fill();
  g.restore();

  // 0 线与进场线
  [[0, cssv('--line'), false], [gate, cssv('--accent-line'), true]].forEach(([v, c, dash]) => {
    if (v < lo || v > hi) return;
    g.strokeStyle = c; g.lineWidth = 1;
    g.setLineDash(dash ? [3, 3] : []);
    g.beginPath(); g.moveTo(pad.l, Y(v)); g.lineTo(pad.l + w, Y(v)); g.stroke();
    g.setLineDash([]);
  });

  // 曲线
  g.beginPath();
  vals.forEach((v, i) => (i ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v))));
  g.strokeStyle = cssv('--accent'); g.lineWidth = 1.5;
  g.lineJoin = 'round'; g.stroke();

  // 当前点
  const last = vals[vals.length - 1];
  g.beginPath(); g.arc(X(vals.length - 1), Y(last), 2.6, 0, Math.PI * 2);
  g.fillStyle = cssv('--accent'); g.fill();
}

/* ---------------- 两只票 ---------------- */
function renderPicks(f) {
  const picks = f.picks || [];
  $('#pick-sub').textContent = picks.length >= 2
    ? `银行 ${picks[0].rank_total} 只 / 保险 ${picks[1].rank_total} 只，各取第 1`
    : '—';

  $('#picks').innerHTML = picks.map(p => `
    <article class="pick">
      <div class="pick-h">
        <span class="pick-tag">${esc(p.board)}</span>
        <span class="pick-rank">${p.rank}/${p.rank_total}</span>
      </div>
      <div class="pick-nm" title="${esc(p.name)}">${esc(p.name)}</div>
      <div class="pick-cd">${esc(p.code)}</div>
      <div class="pick-px">
        <b>${(+p.price).toFixed(2)}</b><em>元</em>
        <span class="chg ${dir(p.chg)}">${sgn(p.chg)}${(+p.chg).toFixed(2)}%</span>
      </div>
      <div class="fac">
        <div><span>超跌</span><b>${pct(p.ma60r)}</b></div>
        <div><span>波动</span><b>${(+p.std20).toFixed(2)}%</b></div>
        <div><span>量价</span><b>${(+p.corr20).toFixed(2)}</b></div>
      </div>
    </article>`).join('');
}

/* ---------------- 持仓 ---------------- */
function renderPos(p) {
  const box = $('#pos-body');
  const a = p && p.active;

  // 持仓期间收起规则卡：进度信息比规则更该占这块地方，
  // 而且规则在顶栏副标题里已经有一句话版本。左栏一超右栏，整页就要滚。
  const rules = $('#card-rules');
  if (rules) rules.hidden = !!a;

  if (!a) {
    $('#pos-sub').textContent = '';
    box.innerHTML = `
      <div class="pos-empty">
        <span>买了就在这记一笔，之后每天能看到第几天、还剩几天、赚了多少。</span>
        <button class="btn primary" id="btn-open">记一笔买入</button>
      </div>`;
    $('#btn-open').onclick = openPos;
    return;
  }

  const cls = dir(a.ret);
  // 持仓状态比空状态多出四行内容，左栏一长整页就要滚 —— 所以这里刻意压成
  // 两行文字 + 一条进度 + 一行两只票，不写「第几天」和「还剩几天」各占一行。
  $('#pos-sub').textContent = a.due ? '已到期待卖' : `第 ${a.held} / ${HOLD} 天`;

  box.innerHTML = `
    <div class="pos-row">
      <span>${esc(a.buy_date)} 买入 · ${a.due ? `已拿满 ${HOLD} 天` : `还剩 ${a.left} 天`}
        · 预计 <b>${esc(a.due_date)}</b> 到期</span>
      <span class="${cls}"><b class="${cls}">${pct(a.ret)}</b></span>
    </div>
    <div class="pos-bar"><i style="width:${a.pct}%"></i></div>
    <div class="pos-items">
      ${(a.items || []).map(it => `
        <div class="pos-item">
          <span class="pi-n">${esc(it.name)}</span>
          <span class="pi-p">${it.buy} → ${it.now}</span>
          <span class="pi-r ${dir(it.ret)}">${pct(it.ret)}</span>
        </div>`).join('')}
    </div>
    <div style="margin-top:9px">
      <button class="btn" id="btn-close">${a.due ? '到期了，平掉这笔' : '提前卖出，平掉这笔'}</button>
    </div>`;

  $('#btn-close').onclick = closePos;
}

async function openPos() {
  const b = $('#btn-open');
  if (b) { b.disabled = true; b.textContent = '记录中…'; }
  const r = await api('/api/fin/pos', { action: 'open' });
  if (!r.ok) { alert(r.msg || '记录失败'); renderPos(S.pos); return; }
  S.pos = r; renderPos(r);
}

async function closePos() {
  const r = await api('/api/fin/pos', { action: 'close' });
  if (!r.ok) { alert(r.msg || '操作失败'); return; }
  S.pos = r; renderPos(r);
}

/* ---------------- 净值统计 ---------------- */
function renderStats(h) {
  const s = (h && h.stat) || {};
  $('#stats').innerHTML = `
    <div><span>年化</span><b class="${dir(s.ann)}">${pct(s.ann)}</b></div>
    <div><span>最大回撤</span><b class="down">${s.mdd == null ? '—' : (+s.mdd).toFixed(1) + '%'}</b></div>
    <div title="标准误 ±${s.se == null ? '—' : (+s.se).toFixed(2)}。10 年样本只能把夏普估到这个精度，别把 0.61 当成精确值">
      <span>夏普</span><b>${s.sharpe == null ? '—' : (+s.sharpe).toFixed(2)}</b></div>
    <div><span>卡玛</span><b>${s.calmar == null ? '—' : (+s.calmar).toFixed(2)}</b></div>`;
}

/* ---------------- 净值曲线 ---------------- */
function sliced() {
  const all = (S.hist && S.hist.curve) || [];
  if (!S.range || all.length < 2) return all;
  const days = S.range * 365;
  const t1 = Date.parse(all[all.length - 1][0]);
  return all.filter(p => Date.parse(p[0]) >= t1 - days * 864e5);
}

function drawCurve() {
  const cv = $('#cv'); if (!cv) return;
  const box = fit(cv); if (!box) return;
  const { g, W, H } = box;
  const pts = sliced();
  if (pts.length < 2) return;

  const pad = { l: 2, r: 2, t: 14, b: 20 };
  const w = W - pad.l - pad.r, h = H - pad.t - pad.b;
  const t0 = Date.parse(pts[0][0]), t1 = Date.parse(pts[pts.length - 1][0]);
  let lo = Infinity, hi = -Infinity;
  for (const [, v] of pts) { if (v < lo) lo = v; if (v > hi) hi = v; }
  lo = Math.min(lo, 1); hi = Math.max(hi, 1);
  const span = (hi - lo) || 1;
  lo -= span * 0.10; hi += span * 0.10;

  const X = t => pad.l + w * (t - t0) / ((t1 - t0) || 1);
  const Y = v => pad.t + h - h * (v - lo) / ((hi - lo) || 1);

  // 横向刻度（净值，不是百分比 —— 曲线本身是 1.00 起步）
  g.font = '10px -apple-system,BlinkMacSystemFont,sans-serif';
  g.textAlign = 'left'; g.textBaseline = 'middle';
  for (let i = 0; i <= 2; i++) {
    const v = lo + (hi - lo) * i / 2, y = Y(v);
    g.strokeStyle = cssv('--line-2'); g.lineWidth = 1;
    g.beginPath(); g.moveTo(pad.l, y); g.lineTo(pad.l + w, y); g.stroke();
    g.fillStyle = cssv('--ink-3');
    g.fillText(v.toFixed(2), pad.l + 3, y - 6);
  }

  // 1.00 基准
  if (lo < 1 && hi > 1) {
    g.strokeStyle = cssv('--line'); g.setLineDash([3, 4]);
    g.beginPath(); g.moveTo(pad.l, Y(1)); g.lineTo(pad.l + w, Y(1)); g.stroke();
    g.setLineDash([]);
  }

  // 面积
  const grad = g.createLinearGradient(0, pad.t, 0, pad.t + h);
  grad.addColorStop(0, 'rgba(37,99,235,.16)');
  grad.addColorStop(1, 'rgba(37,99,235,0)');
  g.beginPath();
  pts.forEach(([d, v], i) => { const x = X(Date.parse(d)), y = Y(v); i ? g.lineTo(x, y) : g.moveTo(x, y); });
  g.lineTo(X(t1), pad.t + h); g.lineTo(X(t0), pad.t + h); g.closePath();
  g.fillStyle = grad; g.fill();

  // 线
  g.beginPath();
  pts.forEach(([d, v], i) => { const x = X(Date.parse(d)), y = Y(v); i ? g.lineTo(x, y) : g.moveTo(x, y); });
  g.strokeStyle = cssv('--accent'); g.lineWidth = 1.7;
  g.lineJoin = 'round'; g.lineCap = 'round'; g.stroke();

  // 横轴年份
  g.textBaseline = 'top'; g.fillStyle = cssv('--ink-3');
  const y0 = +pts[0][0].slice(0, 4), y1 = +pts[pts.length - 1][0].slice(0, 4);
  const marks = [];
  for (let y = y0; y <= y1; y++) marks.push(String(y));
  const step = Math.max(1, Math.ceil(marks.length / 4));
  marks.filter((_, i) => i % step === 0 || i === marks.length - 1).forEach(y => {
    const i = pts.findIndex(p => p[0].startsWith(y));
    if (i < 0) return;
    const x = X(Date.parse(pts[i][0]));
    if (x < pad.l + 12 || x > pad.l + w - 12) return;
    g.textAlign = 'center';
    g.fillText(y, x, pad.t + h + 5);
  });

  // hover
  if (S.hover >= 0 && S.hover < pts.length) {
    const [d, v] = pts[S.hover];
    const x = X(Date.parse(d)), y = Y(v);
    g.strokeStyle = cssv('--line'); g.lineWidth = 1;
    g.beginPath(); g.moveTo(x, pad.t); g.lineTo(x, pad.t + h); g.stroke();
    g.beginPath(); g.arc(x, y, 3.4, 0, Math.PI * 2);
    g.fillStyle = cssv('--accent'); g.fill();
    g.strokeStyle = cssv('--surface'); g.lineWidth = 1.6; g.stroke();
  }
}

/* 悬停：找最近的点，更新 tooltip */
(function bindHover() {
  const cv = $('#cv'), tip = $('#tip');
  if (!cv) return;
  cv.addEventListener('mousemove', e => {
    const pts = sliced();
    if (pts.length < 2) return;
    const r = cv.getBoundingClientRect();
    const t0 = Date.parse(pts[0][0]), t1 = Date.parse(pts[pts.length - 1][0]);
    const ratio = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    const t = t0 + ratio * (t1 - t0);
    let best = 0, bd = Infinity;
    pts.forEach((p, i) => {
      const d = Math.abs(Date.parse(p[0]) - t);
      if (d < bd) { bd = d; best = i; }
    });
    S.hover = best;
    drawCurve();

    const [d, v] = pts[best];
    const ret = (v / pts[0][1] - 1) * 100;
    tip.innerHTML = `<div class="t-d">${esc(d)}</div>`
      + `<div class="t-v ${dir(ret)}">${sgn(ret)}${ret.toFixed(1)}%</div>`
      + `<div class="t-s">净值 ${(+v).toFixed(3)}</div>`;
    tip.hidden = false;
    const px = ratio * r.width;
    tip.style.left = Math.max(48, Math.min(r.width - 48, px)) + 'px';
    tip.style.top = Math.max(34, e.clientY - r.top - 6) + 'px';
  });
  cv.addEventListener('mouseleave', () => {
    S.hover = -1; tip.hidden = true; drawCurve();
  });
})();

/* ---------------- 年度柱 ---------------- */
function drawYearly() {
  const cv = $('#yc'); if (!cv) return;
  const box = fit(cv); if (!box) return;
  const { g, W, H } = box;
  const y = (S.hist && S.hist.yearly) || {};
  const keys = Object.keys(y).sort();
  if (!keys.length) return;

  const pad = { l: 2, r: 2, t: 12, b: 14 };
  const w = W - pad.l - pad.r, h = H - pad.t - pad.b;
  const vals = keys.map(k => +y[k]);
  const mx = Math.max(4, ...vals.map(Math.abs));
  const zero = pad.t + h / 2;
  const bw = w / keys.length;

  g.font = '9px -apple-system,BlinkMacSystemFont,sans-serif';
  g.textBaseline = 'middle';

  keys.forEach((k, i) => {
    const v = vals[i];
    const x = pad.l + bw * i + bw * 0.2;
    const bwid = bw * 0.6;
    const hh = Math.abs(v) / mx * (h / 2 - 2);
    const top = v >= 0 ? zero - hh : zero;
    g.fillStyle = v >= 0 ? cssv('--up') : cssv('--down');
    g.globalAlpha = 0.82;
    roundRect(g, x, top, bwid, Math.max(1.5, hh), Math.min(2, bwid / 2));
    g.fill();
    g.globalAlpha = 1;

    if (bw > 26) {
      g.fillStyle = cssv('--ink-3');
      g.textAlign = 'center';
      g.fillText(k, x + bwid / 2, pad.t + h + 6);
    }
  });

  g.strokeStyle = cssv('--line'); g.lineWidth = 1;
  g.beginPath(); g.moveTo(pad.l, zero); g.lineTo(pad.l + w, zero); g.stroke();

  const pos = vals.filter(v => v > 0).length;
  $('#year-sub').textContent = `${pos}/${keys.length} 年正收益`;
}

function roundRect(g, x, y, w, h, r) {
  g.beginPath();
  g.moveTo(x + r, y);
  g.arcTo(x + w, y, x + w, y + h, r);
  g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r);
  g.arcTo(x, y, x + w, y, r);
  g.closePath();
}

/* ---------------- 历史机会 ---------------- */
function renderTrades(t) {
  const items = (t && t.items) || [];
  const s = (t && t.summary) || {};
  $('#trade-sub').textContent = s.n
    ? `${s.n} 次 · 胜 ${s.win}/${s.settled} · 平均 ${pct(s.avg)}`
    : '—';

  $('#trades').innerHTML = items.map(it => {
    const pair = (it.picks || []).map(p => `
      <i><span>${esc(p.name)}</span>
      <b class="${p.ret == null ? 'flat' : dir(p.ret)}">${p.ret == null ? '—' : pct(p.ret)}</b></i>`).join('');
    return `<tr>
      <td>${esc(it.date)}</td>
      <td class="num">${(+it.vs20).toFixed(1)}%</td>
      <td><div class="buy-pair">${pair}</div></td>
      <td class="num">${it.ret == null
        ? '<span class="pend">未到期</span>'
        : `<b class="${dir(it.ret)}">${pct(it.ret)}</b>`}</td>
      <td class="num ${it.mkt == null ? 'flat' : dir(it.mkt)}">${it.mkt == null ? '—' : pct(it.mkt)}</td>
    </tr>`;
  }).join('');
}

/* ---------------- 画布自适应 ---------------- */
function fit(cv) {
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight;
  if (!W || !H) return null;
  cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  return { g, W, H };
}

/* ---------------- 交互 ---------------- */
$('#seg').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  [...$('#seg').children].forEach(x => x.classList.toggle('on', x === b));
  S.range = +b.dataset.r;
  S.hover = -1;
  $('#tip').hidden = true;
  drawCurve();
});

$('#btn-refresh').onclick = async function () {
  this.classList.add('spin');
  try {
    await api('/api/fin/refresh', {});
    S.fin = await api('/api/fin');
    renderBar(S.fin); renderDecision(S.fin); renderPicks(S.fin);
    paintAll();
  } catch (_) { }
  this.classList.remove('spin');
};

$('#btn-theme').onclick = () => {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  localStorage.setItem('fin-theme', next);
  requestAnimationFrame(paintAll);
};

(function initTheme() {
  const saved = localStorage.getItem('fin-theme');
  const dark = saved ? saved === 'dark'
    : window.matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
})();

let rt = null;
window.addEventListener('resize', () => {
  clearTimeout(rt);
  rt = setTimeout(paintAll, 120);
});

boot();
