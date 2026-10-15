// 线上演示页验证（GitHub Pages）
//
// 跨平台：浏览器由 tests/browser.js 选择；代理从环境变量读，不写死端口。
//   需要代理时：HTTPS_PROXY=http://127.0.0.1:7897 node tests/test_live.js
// 无法联网或没有浏览器时报告 SKIP 并以退出码 2 结束 —— **不是通过**。
//
// 退出码：0 = 全部通过；1 = 有失败；2 = 跳过（环境不具备）

const fs = require('fs');
const { launch, proxyOption, shutdown } = require('./browser');

const URL = process.env.LIVE_URL || 'https://miaoyhcat.github.io/mcd-chinese-class/';

const P = [], F = [];
const check = (n, ok, d) => {
  (ok ? P : F).push(n);
  console.log(`  ${ok ? '✓' : '✗'} ${n}${!ok && d ? '   ' + d : ''}`);
};
const skip = (why) => {
  console.log(`\n  SKIP  线上测试未执行：${why}`);
  console.log('  （SKIP 不是通过）\n');
  process.exitCode = 2;
};

(async () => {
  const { browser, reason, label } = await launch(proxyOption());
  if (!browser) return skip(reason);
  console.log(`\n  浏览器：${label}`);
  console.log(`  目标：${URL}`);

  const ctx = await browser.newContext({
    viewport: { width: 900, height: 1200 }, acceptDownloads: true,
  });
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push(e.message));
  p.on('response', r => { if (r.status() >= 400) errs.push(r.status() + ' ' + r.url()); });

  let reached = true;
  try {
    const r = await p.goto(URL + '?v=' + Date.now(), { waitUntil: 'load', timeout: 60000 });
    if (!r || r.status() >= 400) reached = false;
  } catch (e) {
    reached = false;
    console.log(`      连不上：${e.message.split('\n')[0]}`);
  }
  if (!reached) return skip('线上页面访问失败（网络或代理不可用）');

  await p.waitForTimeout(1500);

  console.log('\n[内容]');
  check('页面标题正确', (await p.title()).includes('麦门语文课'));
  check('课文按钮 16 个', (await p.$$eval('#lessons .chip', e => e.length)) === 16);
  check('没有习题区块', (await p.locator('.qhead, .qs').count()) === 0);
  const txt = await p.$eval('#lesson', e => e.innerText);
  check('有「课文完」', txt.includes('课 文 完'));
  check('无习题字样', !txt.includes('习题'));
  check('显示文体', (await p.$eval('.style-tag', e => e.textContent)).trim().length > 0);

  console.log('\n[生成]');
  let broken = 0;
  for (let i = 0; i < 16; i++) {
    await p.$$eval('#lessons .chip', (els, k) => els[k].click(), i);
    await p.click('#go');
    await p.waitForTimeout(100);
    const t = await p.$eval('#lesson', e => e.innerText);
    if (/\{\w+\}/.test(t) || t.includes('习题')) broken++;
  }
  check('16 篇逐篇生成无异常', broken === 0, `${broken} 篇有问题`);

  console.log('\n[注入]');
  let hit = 0;
  for (const pl of ['<script>window.__x=1</script>', '<img src=x onerror=window.__x=2>',
                    '</div><script>window.__x=3</script>', 'A'.repeat(3000)]) {
    await p.evaluate(() => { window.__x = 0; });
    await p.fill('#custom', pl);
    await p.click('#go');
    await p.waitForTimeout(140);
    if (await p.evaluate(() => window.__x || 0)) hit++;
  }
  check('恶意输入未执行脚本', hit === 0, `${hit} 组注入成功`);

  console.log('\n[导出图片]');
  await p.fill('#custom', '巨无霸，中薯条，可乐');
  await p.click('#go');
  await p.waitForTimeout(300);
  const dl = p.waitForEvent('download', { timeout: 25000 });
  await p.click('#img');
  try {
    const d = await dl;
    const st = fs.statSync(await d.path());
    check('导出 PNG 成功', d.suggestedFilename().endsWith('.png') && st.size > 20000,
          `${d.suggestedFilename()} ${(st.size / 1024).toFixed(0)}KB`);
  } catch (e) {
    check('导出 PNG 成功', false, e.message);
  }

  console.log('\n[复制]');
  await ctx.grantPermissions(['clipboard-read', 'clipboard-write']).catch(() => {});
  await p.click('#copy');
  await p.waitForTimeout(400);
  const clip = await p.evaluate(() => navigator.clipboard.readText()).catch(() => '');
  check('复制内容完整且无习题', clip.length > 100 && !clip.includes('习题'));

  console.log('\n[手机宽度]');
  for (const w of [390, 360]) {
    const m = await ctx.newPage();
    await m.setViewportSize({ width: w, height: 844 });
    await m.goto(URL + '?v=' + Date.now(), { waitUntil: 'load', timeout: 60000 });
    await m.waitForTimeout(900);
    check(`${w}px 无横向滚动`,
          !(await m.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2)));
    await m.close();
  }

  check('无 JS 报错 / 无 404', errs.length === 0, errs.slice(0, 3).join(' | '));

  console.log('\n' + '═'.repeat(46));
  console.log(`  线上验证 通过 ${P.length}/${P.length + F.length}` +
              (F.length ? `，失败 ${F.length}` : '，全部通过 ✓'));
  if (F.length) F.forEach(x => console.log('    · ' + x));
  console.log('═'.repeat(46));

  await shutdown(ctx, browser);
  process.exitCode = F.length ? 1 : 0;
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
