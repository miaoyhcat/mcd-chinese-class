// 跨平台浏览器启动器。
//
// 原先把 playwright-core 的路径和 Edge 可执行文件写死在 Windows 的绝对路径上，
// 换一台机器（或 CI）就必然失败。这里改成按可用性依次尝试：
//   1. 系统已装的 Edge  2. 系统已装的 Chrome  3. playwright 自带的 chromium
// 一个都起不来时返回 null，调用方必须报告 SKIP —— **不能当作通过**。

const ATTEMPTS = [
  { channel: 'msedge', label: 'system Edge' },
  { channel: 'chrome', label: 'system Chrome' },
  { label: 'bundled chromium' },
];

function loadChromium() {
  for (const mod of ['playwright-core', 'playwright', '@playwright/test']) {
    try {
      const m = require(mod);
      if (m && m.chromium) return { chromium: m.chromium, from: mod };
    } catch {
      /* 换下一个模块名 */
    }
  }
  return null;
}

async function launch(opts = {}) {
  const found = loadChromium();
  if (!found) {
    return { browser: null, reason: '未安装 playwright-core / playwright（可执行 npm install）' };
  }
  const errors = [];
  for (const a of ATTEMPTS) {
    const cfg = { headless: true, ...opts };
    if (a.channel) cfg.channel = a.channel;
    try {
      const browser = await found.chromium.launch(cfg);
      return { browser, label: a.label, from: found.from };
    } catch (e) {
      errors.push(`${a.label}: ${e.message.split('\n')[0]}`);
    }
  }
  return { browser: null, reason: '没有可用浏览器 —— ' + errors.join(' | ') };
}

// 需要走代理时（例如访问 GitHub Pages），从环境变量取，不写死端口
function proxyOption() {
  const p = process.env.HTTPS_PROXY || process.env.https_proxy ||
            process.env.HTTP_PROXY || process.env.http_proxy;
  return p ? { proxy: { server: p } } : {};
}

module.exports = { launch, proxyOption };

// 统一收尾。
//
// Playwright 在「页面还在导航时关闭浏览器」会抛一个来自内部处理器的
// TargetClosedError（unhandled rejection），导致测试明明全通过、进程却带错误退出。
// 这里先关 context 再关 browser，并在收尾阶段只吞掉这一个错误 ——
// 其它异常照常抛出，不会掩盖真正的失败。
async function shutdown(ctx, browser) {
  const swallow = (e) => {
    const msg = String((e && e.message) || e);
    return msg.includes('Target page, context or browser has been closed')
        || msg.includes('TargetClosedError');
  };
  const onRej = (e) => { if (!swallow(e)) throw e; };
  process.on('unhandledRejection', onRej);
  try {
    await new Promise(r => setTimeout(r, 200));
    if (ctx) await ctx.close().catch(() => {});
    if (browser) await browser.close().catch(() => {});
    await new Promise(r => setTimeout(r, 300));
  } finally {
    process.off('unhandledRejection', onRej);
  }
}

module.exports = { launch, proxyOption, shutdown };
