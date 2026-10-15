// 网页端到端测试（离线 file:// + 本地构建产物）
//
// 跨平台：浏览器由 tests/browser.js 按可用性选择，不写死任何绝对路径。
// 没有可用浏览器时报告 SKIP 并以退出码 2 结束 —— **不是通过**。
//
// 退出码：0 = 全部通过；1 = 有失败；2 = 跳过（环境不具备）
//
// 跑法：node tests/test_web.js

const path = require('path');
const fs = require('fs');
const { launch, shutdown } = require('./browser');

const P = [], F = [];
const check = (n, ok, d) => {
  (ok ? P : F).push(n);
  console.log(`  ${ok ? '✓' : '✗'} ${n}${!ok && d ? '   ' + d : ''}`);
};
const skip = (why) => {
  console.log(`\n  SKIP  网页测试未执行：${why}`);
  console.log('  （SKIP 不是通过 —— 需要在有浏览器的环境重跑）\n');
  process.exitCode = 2;
};

const PAGE = 'file:///' + path.resolve(__dirname, '..', 'docs', 'index.html')
  .split(path.sep).join('/');

(async () => {
  const { browser, reason, label } = await launch();
  if (!browser) return skip(reason);
  console.log(`\n  浏览器：${label}`);

  const ctx = await browser.newContext({
    viewport: { width: 900, height: 1200 }, acceptDownloads: true,
  });
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push('JS: ' + e.message));
  p.on('dialog', async d => { errs.push('意外弹窗: ' + d.message()); await d.dismiss(); });

  await p.goto(PAGE, { waitUntil: 'load' });
  await p.waitForTimeout(700);

  console.log('\n[基本功能]');
  check('打开即有课文', await p.$eval('#lesson', e => e.classList.contains('show')));
  check('课文按钮 16 个', (await p.$$eval('#lessons .chip', e => e.length)) === 16);
  check('没有习题区块', (await p.locator('.qhead, .qs').count()) === 0);
  const body = await p.$eval('#lesson', e => e.innerText);
  check('有「课文完」', body.includes('课 文 完'));
  check('正文里没有习题字样', !body.includes('习题'));
  check('显示了文体标注', (await p.$eval('.style-tag', e => e.textContent)).length > 0);

  console.log('\n[16 篇逐篇生成]');
  let broken = 0;
  for (let i = 0; i < 16; i++) {
    await p.$$eval('#lessons .chip', (els, k) => els[k].click(), i);
    await p.click('#go');
    await p.waitForTimeout(90);
    const t = await p.$eval('#lesson', e => e.innerText);
    if (/\{\w+\}/.test(t) || t.includes('习题')) broken++;
  }
  check('16 篇无残留占位符、无习题', broken === 0, `${broken} 篇有问题`);

  console.log('\n[注入测试]');
  const payloads = [
    '<script>window.__xss=1</script>',
    '<img src=x onerror="window.__xss=2">',
    '"><script>window.__xss=3</script>',
    "'\"><svg/onload=window.__xss=4>",
    '</div><script>window.__xss=5</script>',
    '巨无霸<img src=x onerror=window.__xss=6>',
    'A'.repeat(3000),
    '🍔🍟🥤 emoji 测试',
  ];
  let xssHit = 0, layoutBroken = 0;
  for (const pl of payloads) {
    await p.evaluate(() => { window.__xss = 0; });
    await p.fill('#custom', pl);
    await p.click('#go');
    await p.waitForTimeout(150);
    if (await p.evaluate(() => window.__xss || 0)) xssHit++;
    if (!(await p.$eval('#lesson', e => e.querySelectorAll('.body p').length > 0))) layoutBroken++;
  }
  check('8 组恶意输入均未执行脚本', xssHit === 0, `${xssHit} 组注入成功`);
  check('注入输入未破坏页面结构', layoutBroken === 0, `${layoutBroken} 组破坏`);
  check('课文区域内没有被注入的 script/img',
        (await p.$eval('#lesson', e => e.querySelectorAll('script, img').length)) === 0);

  console.log('\n[导出课文图片]');
  await p.fill('#custom', '巨无霸,中薯条,可乐');
  await p.click('#go');
  await p.waitForTimeout(300);
  const dl = p.waitForEvent('download', { timeout: 20000 });
  await p.click('#img');
  try {
    const d = await dl;
    const f = await d.path();
    const size = fs.statSync(f).size;
    check('下载了一张 PNG', d.suggestedFilename().endsWith('.png'), d.suggestedFilename());
    check('图片体积合理（>20KB）', size > 20000, `${(size / 1024).toFixed(0)} KB`);
    fs.copyFileSync(f, path.join(__dirname, '..', '_exported.png'));
  } catch (e) {
    check('下载了一张 PNG', false, e.message);
  }

  console.log('\n[复制]');
  await ctx.grantPermissions(['clipboard-read', 'clipboard-write']).catch(() => {});
  await p.click('#copy');
  await p.waitForTimeout(400);
  const clip = await p.evaluate(() => navigator.clipboard.readText()).catch(() => '');
  check('复制内容含标题和正文', clip.includes('《') && clip.length > 100, `长度 ${clip.length}`);
  check('复制内容不含习题', !clip.includes('习题'));

  console.log('\n[手机宽度]');
  for (const w of [390, 360]) {
    const m = await ctx.newPage();
    await m.setViewportSize({ width: w, height: 844 });
    await m.goto(PAGE, { waitUntil: 'load' });
    await m.waitForTimeout(500);
    const overflow = await m.evaluate(() =>
      document.documentElement.scrollWidth > window.innerWidth + 2);
    check(`${w}px 无横向滚动`, !overflow);
    const h = await m.$eval('#lesson', e => e.getBoundingClientRect().height);
    check(`${w}px 课文卡片高度正常`, h > 200 && h < 6000, `${Math.round(h)}px`);
    await m.close();
  }

  check('全程无 JS 报错', errs.length === 0, errs.join(' | '));

  console.log('\n' + '═'.repeat(46));
  console.log(`  通过 ${P.length}/${P.length + F.length}` +
              (F.length ? `，失败 ${F.length}` : '，全部通过 ✓'));
  if (F.length) F.forEach(x => console.log('    · ' + x));
  console.log('═'.repeat(46));

  await shutdown(ctx, browser);
  process.exitCode = F.length ? 1 : 0;
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
