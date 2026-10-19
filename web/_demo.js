// 仅用于截图验收：注入演示数据 / 自动执行动作，然后加载正常前端脚本
(function () {
  const Q = new URLSearchParams(location.search);
  const DEMO = Q.get('demo');
  if (DEMO) {
    const orig = window.fetch;
    window.fetch = function (url, opt) {
      if (typeof url === 'string' && url === '/api/last') url = '/api/last?demo=' + encodeURIComponent(DEMO);
      // 详情也带上 demo：这样它才会用演示名单里那套条件去算，分数和列表对得上
      if (typeof url === 'string' && url.startsWith('/api/detail?') && !url.includes('demo=')) {
        url = url + '&demo=' + encodeURIComponent(DEMO);
      }
      return orig.call(window, url, opt);
    };
  }
  // 截图时自动打开详情：?code=600519
  const CODE = Q.get('code');
  if (CODE) {
    let tries = 0;
    const iv = setInterval(() => {
      const b = document.querySelector(`[data-detail="${CODE}"]`);
      if (b) { clearInterval(iv); b.click(); }
      if (++tries > 60) clearInterval(iv);
    }, 300);
  }
  // 截图时用预存结果假装跑完组合回测：?pf=pf_demo
  const PF = Q.get('pf');
  if (PF) {
    const orig = window.fetch;
    const jr = (obj) => Promise.resolve(new Response(JSON.stringify(obj), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    window.fetch = function (url, opt) {
      const u = typeof url === 'string' ? url : '';
      if (u.startsWith('/api/portfolio')) return jr({ ok: true, job: { id: 'demo' } });
      if (u.startsWith('/api/job/result')) {
        return orig.call(window, '/api/last?demo=' + encodeURIComponent(PF), opt)
          .then(res => res.json())
          .then(o => jr({ ok: true, state: 'done', result: o.result }));
      }
      if (u.startsWith('/api/job?')) return jr({ ok: true, state: 'done', pct: 100, msg: '完成' });
      return orig.call(window, url, opt);
    };
  }
  // 截图时自动跑一次组合账户回测：?run=pf
  if (Q.get('run') === 'pf' || PF) {
    setTimeout(() => {
      const nav = document.querySelector('.ni[data-view="portfolio"]');
      if (nav) nav.click();
      setTimeout(() => { const b = document.querySelector('#btn-pf'); if (b) b.click(); }, 400);
    }, 1200);
  }
})();
