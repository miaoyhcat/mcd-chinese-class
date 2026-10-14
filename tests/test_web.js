const { chromium } = require('C:/Users/windows/ZCodeProject/ai-galgame/electron/node_modules/playwright-core');
const path = require('path');
const fs = require('fs');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';

const P = [], F = [];
const check = (n, ok, d) => { (ok ? P : F).push(n); console.log(`  ${ok ? '✓' : '✗'} ${n}${!ok && d ? '   ' + d : ''}`); };

(async () => {
  const b = await chromium.launch({ channel: 'msedge', headless: true, executablePath: EDGE });
  const ctx = await b.newContext({ viewport: { width: 900, height: 1200 }, acceptDownloads: true });
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push('JS: ' + e.message));
  p.on('dialog', async d => { errs.push('意外弹窗: ' + d.message()); await d.dismiss(); });

  await p.goto('file:///' + path.resolve('docs/index.html').split(path.sep).join('/'), { waitUntil: 'load' });
  await p.waitForTimeout(700);

  console.log('\n[基本功能]');
  check('打开即有课文', await p.$eval('#lesson', e => e.classList.contains('show')));
  check('课文按钮 16 个', (await p.$$eval('#lessons .chip', e => e.length)) === 16);
  check('没有习题区块', (await p.locator('.qhead, .qs').count()) === 0);
  const body = await p.$eval('#lesson', e => e.innerText);
  check('有「课文完」', body.includes('课 文 完'));
  check('正文里没有习题字样', !body.includes('习题'));
  check('显示了文体', (await p.$eval('.style-tag', e => e.textContent)).length > 0);

  console.log('\n[16 篇逐篇生成]');
  let broken = 0;
  for (let i = 0; i < 16; i++) {
    await p.$$eval('#lessons .chip', (els, k) => els[k].click(), i);
    await p.click('#go'); await p.waitForTimeout(90);
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
    await p.waitForTimeout(160);
    const v = await p.evaluate(() => window.__xss || 0);
    if (v) { xssHit++; console.log(`     注入成功：${pl.slice(0, 40)} → __xss=${v}`); }
    // 页面结构没被破坏：课文容器还在、课号还在
    const ok = await p.$eval('#lesson', e => e.querySelectorAll('.body p').length > 0);
    if (!ok) layoutBroken++;
  }
  check('8 组恶意输入均未执行脚本', xssHit === 0, `${xssHit} 组注入成功`);
  check('注入输入未破坏页面结构', layoutBroken === 0, `${layoutBroken} 组破坏`);
  const injected = await p.$eval('#lesson', e => e.querySelectorAll('script, img').length);
  check('课文区域内没有被注入的 script/img 元素', injected === 0, `发现 ${injected} 个`);

  console.log('\n[导出课文图片]');
  await p.fill('#custom', '巨无霸,中薯条,可乐');
  await p.click('#go'); await p.waitForTimeout(300);
  const dl = p.waitForEvent('download', { timeout: 20000 });
  await p.click('#img');
  try {
    const d = await dl;
    const f = await d.path();
    const size = fs.statSync(f).size;
    check('点击后下载了一张 PNG', d.suggestedFilename().endsWith('.png'), d.suggestedFilename());
    check('图片体积合理（>20KB）', size > 20000, `${(size / 1024).toFixed(0)} KB`);
    // 存一份出来看
    fs.copyFileSync(f, '_exported.png');
  } catch (e) {
    check('点击后下载了一张 PNG', false, e.message);
  }

  console.log('\n[复制]');
  await ctx.grantPermissions(['clipboard-read', 'clipboard-write']);
  await p.click('#copy'); await p.waitForTimeout(400);
  const clip = await p.evaluate(() => navigator.clipboard.readText()).catch(() => '');
  check('复制内容含标题和正文', clip.includes('《') && clip.length > 100, `长度 ${clip.length}`);
  check('复制内容不含习题', !clip.includes('习题'));

  console.log('\n[手机端]');
  const m = await ctx.newPage();
  await m.setViewportSize({ width: 390, height: 844 });
  await m.goto('file:///' + path.resolve('docs/index.html').split(path.sep).join('/'), { waitUntil: 'load' });
  await m.waitForTimeout(600);
  const overflow = await m.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2);
  check('手机端无横向溢出', !overflow);
  const blanks = await m.evaluate(() => {
    const el = document.getElementById('lesson');
    return el ? el.getBoundingClientRect().height : 0;
  });
  check('课文卡片高度正常（无大段空白）', blanks > 200 && blanks < 6000, `${Math.round(blanks)}px`);

  check('全程无 JS 报错', errs.length === 0, errs.join(' | '));

  console.log('\n' + '═'.repeat(46));
  console.log(`  通过 ${P.length}/${P.length + F.length}` + (F.length ? `，失败 ${F.length}` : '，全部通过 ✓'));
  if (F.length) F.forEach(x => console.log('    · ' + x));
  console.log('═'.repeat(46));
  await new Promise(r => setTimeout(r, 300));   // 等挂起的导航事件收尾
  await b.close().catch(() => {});
  process.exitCode = F.length ? 1 : 0;
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
