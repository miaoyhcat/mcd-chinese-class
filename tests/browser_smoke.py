"""端到端浏览器检查；通过 set_content 注入自包含 HTML，可离线运行。"""
import json
import re
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from console_utf8 import enable_utf8_stdout
enable_utf8_stdout()  # 英文 Windows 控制台是 cp1252，print 中文会崩
from engine import compose,stable_number
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print('缺少 Playwright，请运行 pip install playwright && python -m playwright install chromium')
    sys.exit(2)

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'docs/index.html').read_text('utf-8')
CHECKS=[]
def check(name,ok):
    CHECKS.append((name,bool(ok)))
    print(('PASS' if ok else 'FAIL')+' '+name)

def main():
    with sync_playwright() as p:
        # CI 使用 Playwright 安装的 Chromium，本地允许 CHROME_PATH 覆盖。
        import os
        executable=os.getenv('CHROME_PATH')
        kwargs={'headless':True,'args':['--no-sandbox']}
        if executable:kwargs['executable_path']=executable
        elif Path('/usr/bin/chromium').exists():kwargs['executable_path']='/usr/bin/chromium'
        browser=p.chromium.launch(**kwargs)
        page=browser.new_page(viewport={'width':1350,'height':980},accept_downloads=True)
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.set_content(HTML,wait_until='load')
        check('16 篇课文列表',page.locator('.lesson-chip').count()==16)
        check('首页生成真实内容',len(page.locator('#lessonBody p').all())>=4)
        check('无课后习题', '习题' not in page.locator('#reader').inner_text())
        for lesson in json.loads((ROOT/'lessons.json').read_text('utf-8'))['lessons']:
            page.locator(f'.lesson-chip[data-id="{lesson["id"]}"]').click()
            text=page.locator('#lessonBody').inner_text()
            check('课文无漏填: '+lesson['id'],len(text)>140 and not re.search(r'\{[a-z]+\}',text))
        for items in [['巨无霸','可乐'],['🍔套餐','𠮷野家'],['水果派','矿泉水']]:
            result=page.evaluate('(names)=>window.MCD_TEST.stableNumber(names.map(name=>({name,quantity:1})))',items)
            check('Python 与 JS 课号一致 '+repr(items),result==stable_number(items))
        # JS 生成文本与 Python 的完整结果相等，不只是校验课号
        for key in ['beiying','hezhou','chun']:
            expected=compose(['巨无霸','雪碧'],key)
            actual=page.evaluate('([items,key])=>window.MCD_TEST.compose(items,LESSONS.find(x=>x.id===key))',
                                 [[{'name':'巨无霸','quantity':1},{'name':'雪碧','quantity':1}],key])
            check('Python 与 JS 内容一致 '+key,expected==actual)
        page.locator('#customInput').fill('<svg/onload=window.__hacked=1>,🍔套餐')
        page.locator('#generateButton').click()
        check('恶意输入不触发代码执行',page.evaluate('window.__hacked===undefined'))
        check('恶意标签显示为文本',page.locator('#lessonBody svg').count()==0)
        # 导入真正的本地脱敏订单格式
        data={'format':'mcd-chinese-class/items-v1','items':[{'name':'麦香鱼','quantity':2},{'name':'雪碧','quantity':1}]}
        page.locator('#importFile').set_input_files({'name':'order-local.json','mimeType':'application/json','buffer':json.dumps(data,ensure_ascii=False).encode()})
        check('导入订单成功', '麦香鱼 ×2' in page.locator('#lessonItems').inner_text())
        check('导入订单无脚本错误',not errors)
        # 非法配置不得被当成脱敏订单（防止意外将原始订单数据直接渲染）
        illegal={'format':'mcd-chinese-class/items-v1','items':[{'name':'麦香鱼','quantity':1}],'orderId':'PRIVATE-ID'}
        page.locator('#importFile').set_input_files({'name':'raw.json','mimeType':'application/json','buffer':json.dumps(illegal,ensure_ascii=False).encode()})
        check('带订单号的输入文件被拒绝', '额外字段' in page.locator('#error').inner_text())
        check('拒绝输入后原课文仍可查看', '麦香鱼' in page.locator('#lessonItems').inner_text())
        # 压力测试：超长多段课文必须分成多页，不能截断或缩成不可读的小字。
        pages=page.evaluate('''() => {
          const d=window.MCD_TEST.currentDoc();
          const huge={...d,body:Array(110).fill(d.body[0])};
          const pages=window.MCD_TEST.imageLayout(huge);
          return {count:pages.length,lines:pages.reduce((n,p)=>n+p.length,0)};
        }''')
        check('极长课文自动分页且保留内容', pages['count']>1 and pages['lines']>110)
        
        with page.expect_download(timeout=20000) as dl:
            page.locator('#imageButton').click()
        file=dl.value
        content=Path(file.path()).read_bytes()
        check('成功保存 PNG',file.suggested_filename.endswith('.png') and len(content)>20000 and content[:8]==b'\x89PNG\r\n\x1a\n')
        page.locator('#customInput').fill('巨无霸,可乐')
        page.locator('#generateButton').click()
        for width in [390,375,320]:
            mobile=browser.new_page(viewport={'width':width,'height':844})
            mobile.set_content(HTML)
            check(f'{width}px 手机无横向溢出',not mobile.evaluate('document.documentElement.scrollWidth>innerWidth+2'))
            check(f'{width}px 页面内容正常',mobile.locator('#reader').bounding_box()['height']>280)
            mobile.close()
        check('浏览器 JS 无错误',not errors)
        browser.close()
    failed=[name for name,ok in CHECKS if not ok]
    print('\nRESULT: '+str(len(CHECKS)-len(failed))+'/'+str(len(CHECKS))+' passed')
    if failed:print('FAILED: '+'; '.join(failed))
    return 1 if failed else 0
if __name__=='__main__':sys.exit(main())
