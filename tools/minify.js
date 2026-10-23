#!/usr/bin/env node
/**
 * 无损压缩器：只去注释和多余空白，不改逻辑、不重命名。
 * 用状态栈正确处理 代码/字符串/模板/正则 的嵌套，尤其模板里 ${...} 可以再嵌模板。
 *
 * 用法: node minify.js <输入.js> [输出.js]
 */
const fs = require('fs');
const zlib = require('zlib');

function minify(src) {
  const n = src.length;
  let i = 0;
  let out = '';
  // 栈元素: {t:'code', brace:0} 或 {t:'tmpl'}
  const stack = [{ t: 'code' }];
  let prevTok = '';      // 上一个有意义 token 的末字符，用于判定 / 是正则还是除号
  let prevWord = '';     // 上一个词（判断 return/typeof 后跟正则）

  const ID = /[A-Za-z0-9_$\u00a0-\uffff]/;
  const IDSTART = /[A-Za-z_$\u00a0-\uffff]/;

  function push(format) {
    if (!format) return;
    out += format;
  }

  const REGEX_AFTER = new Set(['(', ',', '=', ':', '[', '!', '&', '|', '?', ';', '{', '+', '-', '*', '%', '~', '^', 'return', 'typeof', 'case', 'in', 'of', 'new', 'delete', 'void', 'throw', 'do', 'else']);

  while (i < n) {
    const top = stack[stack.length - 1];

    if (top.t === 'tmpl') {
      const c = src[i];
      if (c === '\\') { push(src.substr(i, 2)); i += 2; continue; }
      if (c === '`') { push('`'); i++; stack.pop(); prevTok = '`'; prevWord = ''; continue; }
      // ${ 里的表达式：brace 从 1 起算（${ 自带一个未闭合的 {），减到 0 才回到模板
      if (c === '$' && src[i + 1] === '{') { push('${'); i += 2; stack.push({ t: 'code', brace: 1, expr: true }); prevTok = '{'; prevWord = ''; continue; }
      // 模板里原样保留（包括空白和换行）
      out += c; i++; continue;
    }

    // ---- code 状态 ----
    const c = src[i];
    const c2 = src[i + 1];

    // 注释
    if (c === '/' && c2 === '/') { while (i < n && src[i] !== '\n') i++; continue; }
    if (c === '/' && c2 === '*') { i += 2; while (i < n && !(src[i] === '*' && src[i + 1] === '/')) i++; i += 2; continue; }

    // 空白
    if (c === ' ' || c === '\t' || c === '\r' || c === '\n' || c === '\f' || c === '\v') {
      let j = i;
      while (j < n && /[ \t\r\n\f\v]/.test(src[j])) j++;
      const a = out[out.length - 1] || '';
      const b = src[j] || '';
      // 两侧都是标识符字符（含 $、数字、中文）时必须留一个空格
      const bothId = ID.test(a) && ID.test(b);
      // 拼起来会变成别的运算符时也要留
      const combo = a + b;
      const danger = (combo === '++' || combo === '--' || combo === '//' || combo === '/*' || combo === '/=');
      if (bothId || danger) out += ' ';
      i = j;
      continue;
    }

    // 字符串
    if (c === '"' || c === "'") {
      let s = c; i++;
      while (i < n) {
        const d = src[i];
        if (d === '\\') { s += d + (src[i + 1] || ''); i += 2; continue; }
        s += d; i++;
        if (d === c) break;
      }
      push(s); prevTok = c; prevWord = ''; continue;
    }

    // 模板开始
    if (c === '`') { push('`'); i++; stack.push({ t: 'tmpl' }); prevTok = '`'; prevWord = ''; continue; }

    // 正则 or 除号
    if (c === '/') {
      const isRegex = REGEX_AFTER.has(prevWord) || REGEX_AFTER.has(prevTok);
      if (isRegex) {
        let s = '/'; i++;
        let inClass = false;
        while (i < n) {
          const d = src[i];
          if (d === '\\') { s += d + (src[i + 1] || ''); i += 2; continue; }
          if (d === '\n') break;
          s += d; i++;
          if (d === '[') inClass = true;
          else if (d === ']') inClass = false;
          else if (d === '/' && !inClass) break;
        }
        while (i < n && /[a-z]/i.test(src[i])) { s += src[i]; i++; }
        push(s); prevTok = 'x'; prevWord = ''; continue;
      }
      push('/'); i++; prevTok = '/'; prevWord = ''; continue;
    }

    // 花括号：只有 ${...} 里的表达式需要配对追踪，顶层代码不计数
    if (c === '{') { if (top.expr) top.brace++; push('{'); i++; prevTok = '{'; prevWord = ''; continue; }
    if (c === '}') {
      if (top.expr) {
        top.brace--;
        if (top.brace === 0) { push('}'); i++; stack.pop(); prevTok = '}'; prevWord = ''; continue; }
      }
      push('}'); i++; prevTok = '}'; prevWord = ''; continue;
    }

    // 标识符/数字：整词读，更新 prevWord
    if (IDSTART.test(c)) {
      let j = i;
      while (j < n && ID.test(src[j])) j++;
      const w = src.substr(i, j - i);
      push(w); prevTok = w[w.length - 1]; prevWord = w; i = j;
      continue;
    }

    push(c); prevTok = c; prevWord = ''; i++;
  }
  return out;
}

// ---------- 校验：压缩前后括号/引号数量必须一致 ----------
function balance(code) {
  const cnt = {};
  let i = 0, n = code.length;
  while (i < n) {
    const c = code[i];
    if (c === '\\') { i += 2; continue; }
    if (c === '"' || c === "'") { const q = c; i++; while (i < n) { if (code[i] === '\\') { i += 2; continue; } if (code[i] === q) { i++; break; } i++; } continue; }
    if (c === '`') { i++; continue; }
    if ('(){}[]'.includes(c)) cnt[c] = (cnt[c] || 0) + 1;
    i++;
  }
  return cnt;
}

module.exports = { minify };

if (require.main !== module) { /* 被 require 时只导出 */ }
else {
const [,, inp, outp] = process.argv;
if (!inp) { console.error('用法: node minify.js <输入.js> [输出.js]'); process.exit(1); }
const src = fs.readFileSync(inp, 'utf8');
const res = minify(src);

// 校验
const b1 = balance(src), b2 = balance(res);
const bad = Object.keys(b1).filter(k => b1[k] !== b2[k]);
if (bad.length) {
  console.error('❌ 校验失败，括号数量不一致:', bad.map(k => `${k}: ${b1[k]} -> ${b2[k]}`).join(', '));
  process.exit(2);
}
try { new Function(res); } catch (e) { console.error('❌ 语法校验失败: ' + e.message); process.exit(3); }

const outPath = outp || inp.replace(/\.js$/, '.min.js');
fs.writeFileSync(outPath, res, 'utf8');

const before = Buffer.byteLength(src, 'utf8');
const after = Buffer.byteLength(res, 'utf8');
const gz = zlib.gzipSync(Buffer.from(res), { level: 9 }).length;
const gzb = zlib.gzipSync(Buffer.from(src), { level: 9 }).length;
console.log(`✅ 语法校验通过，括号配平正确`);
console.log(`输出: ${outPath}`);
console.log(`原始:   ${before.toLocaleString()} B  (gzip ${gzb.toLocaleString()} B)`);
console.log(`压缩后: ${after.toLocaleString()} B  (gzip ${gz.toLocaleString()} B)`);
console.log(`省下:   ${(100 - after / before * 100).toFixed(1)}%  (gzip 省 ${(100 - gz / gzb * 100).toFixed(1)}%)`);
}
