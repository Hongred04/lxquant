#!/usr/bin/env node
/**
 * 构建脚本：把 web/ 下的源码压成 _.min.* 产物，服务端优先返回压缩版。
 *
 *   node tools/build.js          压缩并写出 web/app.min.js、web/style.min.css
 *   node tools/build.js --check  只比对体积，不写文件（CI 用）
 *
 * 压缩是无损的：只删注释和多余空白，不改任何逻辑、不重命名变量。
 * 语法校验失败时不写文件（避免发布坏产物）。
 */
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const { minify } = require('./minify.js');

const WEB = path.join(__dirname, '..', 'web');
const CHECK = process.argv.includes('--check');

function kb(n) { return (n / 1024).toFixed(1) + ' KB'; }
function gz(n) { return zlib.gzipSync(n, { level: 6 }).length; }

const jobs = [
  { src: 'app.js', out: 'app.min.js', fn: minify },
  // CSS 用同一个状态机也能处理（它只认字符串/注释/括号），但为稳妥只做保守清理
  { src: 'style.css', out: 'style.min.css', fn: minifyCSS },
];

/** CSS 压缩：删注释、合并空白、去多余分号。不碰 url() 和引号里的内容。
 *  注意：calc()/min()/max()/clamp() 里 + - * / 两侧的空格是语法要求，必须原样保留，
 *  否则 transform:translateX(calc(100% + 60px)) 会变成 calc(100%+60px)，浏览器直接丢弃该声明。 */
function minifyCSS(s) {
  let out = '';
  let i = 0;
  const n = s.length;
  // calc 类函数的嵌套深度：>0 时空白一律保留
  let calcDepth = 0;
  const CALC_FN = /^(calc|min|max|clamp|var)\(/i;
  while (i < n) {
    const c = s[i];
    if (c === '/' && s[i + 1] === '*') {
      const end = s.indexOf('*/', i + 2);
      i = end < 0 ? n : end + 2;
      if (calcDepth === 0) out += ' ';
      continue;
    }
    if (c === '"' || c === "'") {
      const q = c, st = i;
      i++;
      while (i < n) {
        if (s[i] === '\\') { i += 2; continue; }
        if (s[i] === q) { i++; break; }
        i++;
      }
      out += s.slice(st, i);
      continue;
    }
    // 识别函数名开头，进入保护模式
    if (/[A-Za-z-]/.test(c)) {
      let j = i;
      while (j < n && /[A-Za-z0-9_-]/.test(s[j])) j++;
      const word = s.slice(i, j);
      out += word;
      i = j;
      if (s[i] === '(' && /^(calc|min|max|clamp|var)$/i.test(word)) { calcDepth++; out += '('; i++; }
      continue;
    }
    if (c === ')') { if (calcDepth > 0) calcDepth--; out += ')'; i++; continue; }
    if (calcDepth > 0) { out += c; i++; continue; }
    if (/\s/.test(c)) {
      while (i < n && /\s/.test(s[i])) i++;
      // 空白在 calc 内一律保留；否则看前后字符，紧贴标点就丢掉
      if (calcDepth > 0) { out += ' '; continue; }
      const prev = out[out.length - 1], next = s[i];
      const PUNCT = '{};:,>+~';
      if (prev && PUNCT.includes(prev) || next && PUNCT.includes(next)) continue;
      out += ' ';
      continue;
    }
    out += c;
    i++;
  }
  // 只剩 @media 的空格规整和结尾分号清理，标点两侧的空白已在主循环处理
  return out
    .replace(/@media\s*\(/g, '@media(')
    .replace(/;}/g, '}')
    .trim();
}

let bad = 0;
for (const j of jobs) {
  const sp = path.join(WEB, j.src);
  if (!fs.existsSync(sp)) { console.log('跳过（不存在）: ' + j.src); continue; }
  const src = fs.readFileSync(sp, 'utf8');
  let res;
  try {
    res = j.fn(src);
  } catch (e) {
    console.error('❌ ' + j.src + ' 压缩失败: ' + e.message);
    bad++;
    continue;
  }
  if (j.out.endsWith('.js')) {
    try { new Function(res); } catch (e) {
      console.error('❌ ' + j.src + ' 压缩后语法错误: ' + e.message);
      bad++;
      continue;
    }
  }
  const a = Buffer.byteLength(src), b = Buffer.byteLength(res);
  const ga = gz(src), gb = gz(res);
  console.log(
    j.src.padEnd(12) + (a / 1024).toFixed(1).padStart(7) + ' KB -> ' +
    (b / 1024).toFixed(1).padStart(6) + ' KB  (' +
    (100 - b / a * 100).toFixed(1) + '% 省)   gzip ' +
    (ga / 1024).toFixed(1).padStart(6) + ' -> ' + (gb / 1024).toFixed(1).padStart(5) + ' KB'
  );
  if (!CHECK) {
    const op = path.join(WEB, j.out);
    fs.writeFileSync(op, res);
    console.log('   写出 ' + j.out);
  }
}
if (bad) { console.error('构建失败：' + bad + ' 个文件'); process.exit(1); }
console.log(CHECK ? '✅ 检查完成' : '✅ 构建完成');
