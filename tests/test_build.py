import hashlib
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from console_utf8 import enable_utf8_stdout
enable_utf8_stdout()  # 英文 Windows 控制台是 cp1252，print 中文会崩
import build_web
ROOT=Path(__file__).resolve().parents[1]

class BuildTests(unittest.TestCase):
    def test_compilation_is_deterministic(self):
        path=ROOT/'docs/index.html'
        before=hashlib.sha256(path.read_bytes()).digest()
        build_web.main()
        after=hashlib.sha256(path.read_bytes()).digest()
        self.assertEqual(before,after,'构建后的网页与仓库提交产物不一致')

    def test_browser_offline_and_safety(self):
        page=(ROOT/'docs/index.html').read_text('utf-8')
        self.assertEqual(page.count('class="lesson-chip"'),0) # 由 JS 生成
        self.assertIn('const LESSONS = [',page)
        self.assertNotIn('/*__',page)
        self.assertNotIn('innerHTML',page)
        self.assertNotIn('课后习题',page)
        self.assertNotIn('http://fonts',page)
        self.assertFalse(re.search(r'<script\s+[^>]*src=',page))
        self.assertFalse(re.search(r'<link\s+[^>]*rel="stylesheet"\s+[^>]*href=',page))

    def test_js_escape(self):
        val=build_web.safe_js([{'x':'</script><script>alert(1)</script>'}])
        self.assertNotIn('</script>',val)
        self.assertIn('\\u003c',val)
        self.assertEqual(json.loads(val),[{'x':'</script><script>alert(1)</script>'}])

    def test_contest_files(self):
        for name in ['README.md','CONTEST_DECLARATION.md','MCP_INTEGRATION.md','mcp-config.example.json','SKILL.md']:
            self.assertTrue((ROOT/name).exists(),name)
        config=json.loads((ROOT/'mcp-config.example.json').read_text('utf-8'))
        self.assertEqual(config['mcpServers']['mcd-mcp']['headers']['Authorization'],'Bearer ${MCD_MCP_TOKEN}')
        self.assertEqual(config['mcpServers']['mcd-mcp']['url'],'https://mcp.mcd.cn')

    def test_cli_json(self):
        proc=subprocess.run([sys.executable,str(ROOT/'mcd_chinese.py'),'--items','巨无霸,薯条,可乐','--json'],text=True,capture_output=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        obj=json.loads(proc.stdout)
        self.assertTrue(obj['title'])
        self.assertNotIn('orderId',obj)

    def test_survives_non_utf8_console(self):
        """英文 Windows 的控制台是 cp1252，print 中文会 UnicodeEncodeError 崩掉进程。

        用 PYTHONIOENCODING 在本机复现同样的条件，而不是等用户撞到才发现。
        """
        import os
        env={**os.environ,'PYTHONIOENCODING':'cp1252'}
        for label,args in [('命令行',['mcd_chinese.py','--demo']),
                           ('构建',['build_web.py'])]:
            with self.subTest(label):
                proc=subprocess.run([sys.executable,*args],cwd=str(ROOT),env=env,
                                    capture_output=True)
                self.assertNotIn(b'UnicodeEncodeError',proc.stderr,
                                 f'{label}在 cp1252 下崩了')
                self.assertEqual(proc.returncode,0)

if __name__=='__main__':unittest.main()
