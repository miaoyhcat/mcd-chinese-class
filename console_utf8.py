#!/usr/bin/env python3
"""把命令行输出切成 UTF-8。

Windows 的控制台编码跟着系统区域走：中文环境是 GBK（凑巧能编中文），
英文环境是 cp1252 —— 后者一 print 中文就 UnicodeEncodeError 把进程打崩。
用户的操作系统是什么语言，不该决定这个工具能不能用。
"""
import sys


def enable_utf8_stdout():
    """把 stdout / stderr 切成 UTF-8。

    errors='replace' 是兜底：万一真遇到编不出的字符，显示成 ? 也好过崩掉。
    被测试框架或管道接管（拿不到 reconfigure）时静默跳过。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
