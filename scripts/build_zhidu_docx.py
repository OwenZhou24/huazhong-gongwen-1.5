# -*- coding: utf-8 -*-
"""制度类 docx 生成器（参考实现）

按《制度类文件格式与写作规范》实测参数生成制度类 docx：
  A4 纵向（11906×16838 twips）；页边距 上/下 2041、左/右 1531、页眉 851、页脚 992
  全段行距固定值 30 磅（w:line="600" w:lineRule="exact"）、段前段后 0
  章 = 黑体三号居中（显式清零缩进）；节 = 仿宋_GB2312 三号加粗居中
  条 = 条号仿宋_GB2312 三号加粗 + 条文仿宋_GB2312 三号，首行缩进 2 字符
  款/项/目 = 仿宋_GB2312 三号，首行缩进 2 字符
  章/节/条号后统一 2 个半角空格；章名「附则」两字间补足 2 个半角空格；页码 = 页脚居中「- 1 -」，宋体四号
  生成后自动清理主题字体 / 主题色 / 自动间距 / 段落边框 / 内置蓝（对齐 SKILL.md「XML 七查」）

用法（命令行）：
    python build_zhidu_docx.py <输入.txt> <输出.docx>

输入文本约定（行首标记）：
    T|HD融资担保股份有限公司   → 文件标题行（居中，方正小标宋简体 二号）
    C|（征求意见稿）                      → 副题（居中，楷体 三号）
    Z|第一章  总则                        → 章（黑体 三号居中；序号后自动规范为 2 个半角空格）
    J|第一节  总则                        → 节（仿宋_GB2312 三号加粗居中）
    第X条  ……                            → 条（自动识别；条号加粗，后接 2 个半角空格）
    其他任意行（（一）… / 1.… / 正文段落） → 款/项/目（仿宋_GB2312 三号，首行缩进 2 字符）
"""
import argparse
import io
import os
import re
import sys
import zipfile

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Emu

TWIP = 635                                  # 1 twip = 635 EMU
TW = lambda t: Emu(int(t) * TWIP)           # twips → EMU

SZ_2HAO, SZ_3HAO, SZ_4HAO = 44, 32, 28      # half-points
F_SONG, F_FANGSONG, F_HEITI, F_KAITI, F_XIAOBIAOSONG = (
    '宋体', '仿宋_GB2312', '黑体', '楷体', '方正小标宋简体')
BUILTIN_BLUES = ('4F81BD', '1F497D', '2E74B5', '5B9BD5', '4472C4', '2F5496',
                 '365F91', '1F4E79', '44546A')


def _set_run(run, text, font, sz, bold=False):
    """写 run 的字体 / 字号 / 加粗（西文一律 Times New Roman，东亚字体由 font 指定）。"""
    if text:
        run.text = text
    rPr = run._r.get_or_add_rPr()
    ascii_font = 'Times New Roman' if font == F_FANGSONG else font
    rf = OxmlElement('w:rFonts')
    rf.set(qn('w:ascii'), ascii_font)
    rf.set(qn('w:hAnsi'), ascii_font)
    rf.set(qn('w:eastAsia'), font)
    rf.set(qn('w:cs'), ascii_font)
    rf.set(qn('w:hint'), 'eastAsia')
    rPr.append(rf)
    if bold:
        rPr.append(OxmlElement('w:b'))
        rPr.append(OxmlElement('w:bCs'))
    s = OxmlElement('w:sz')
    s.set(qn('w:val'), str(sz))
    rPr.append(s)
    scs = OxmlElement('w:szCs')
    scs.set(qn('w:val'), str(sz))
    rPr.append(scs)
    return run


def _para(doc, align=None, indent=True):
    """建段并写 pPr：spacing(600 exact + 前后 0) → ind → jc（严格按 schema 顺序）。"""
    p = doc.add_paragraph()
    pPr = p._p.get_or_add_pPr()
    sp = OxmlElement('w:spacing')
    for k, v in (('w:before', '0'), ('w:after', '0'),
                 ('w:line', '600'), ('w:lineRule', 'exact')):
        sp.set(qn(k), v)
    pPr.append(sp)
    ind = OxmlElement('w:ind')
    if indent:
        ind.set(qn('w:firstLineChars'), '200')
        ind.set(qn('w:firstLine'), '640')
    else:
        ind.set(qn('w:leftChars'), '0')
        ind.set(qn('w:left'), '0')
        ind.set(qn('w:firstLineChars'), '0')
        ind.set(qn('w:firstLine'), '0')
    pPr.append(ind)
    if align:
        jc = OxmlElement('w:jc')
        jc.set(qn('w:val'), align)
        pPr.append(jc)
    return p


def _norm_head(text):
    """把「第X章 / 第X节」后的空白统一为 2 个半角空格；
    章名为「附则」时，两字之间补足 2 个半角空格。"""
    t = re.sub(r'^(第[一二三四五六七八九十百]+[章节])[\s\u3000]*',
               lambda m: m.group(1) + '\u0020\u0020', text.strip())
    return re.sub(r'附[ \u3000]*则\s*$', '附\u0020\u0020则', t)


def _field(p, font, sz):
    """在段落内插入 PAGE 域，形如 - 1 -。"""
    _set_run(p.add_run(), '- ', font, sz)
    for t, val in (('begin', None), ('instr', None), ('separate', None),
                   ('text', '1'), ('end', None)):
        r = p.add_run()
        _set_run(r, '', font, sz)
        if t == 'instr':
            el = OxmlElement('w:instrText')
            el.set(qn('xml:space'), 'preserve')
            el.text = ' PAGE '
        elif t == 'text':
            el = OxmlElement('w:t')
            el.text = val
        else:
            el = OxmlElement('w:fldChar')
            el.set(qn('w:fldCharType'), t)
        r._r.append(el)
    _set_run(p.add_run(), ' -', font, sz)


def _footer(sec):
    sec.footer.is_linked_to_previous = False
    p = sec.footer.paragraphs[0]
    # 注意：不可用 p.alignment=，否则 w:jc 会先于 w:spacing 落位、违反 pPr 子元素顺序
    pPr = p._p.get_or_add_pPr()
    sp = OxmlElement('w:spacing')
    for k, v in (('w:before', '0'), ('w:after', '0')):
        sp.set(qn(k), v)
    pPr.append(sp)
    jc = OxmlElement('w:jc')
    jc.set(qn('w:val'), 'center')
    pPr.append(jc)
    _field(p, F_SONG, SZ_4HAO)


def build(lines, out_path):
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = TW(11906), TW(16838)
    sec.top_margin = sec.bottom_margin = TW(2041)
    sec.left_margin = sec.right_margin = TW(1531)
    sec.header_distance, sec.footer_distance = TW(851), TW(992)

    for raw in lines:
        line = raw.rstrip('\n').rstrip()
        if not line.strip():
            continue
        if line.startswith('T|'):
            p = _para(doc, align='center', indent=False)
            _set_run(p.add_run(), line[2:].strip(), F_XIAOBIAOSONG, SZ_2HAO)
        elif line.startswith('C|'):
            p = _para(doc, align='center', indent=False)
            _set_run(p.add_run(), line[2:].strip(), F_KAITI, SZ_3HAO)
        elif line.startswith('Z|'):
            p = _para(doc, align='center', indent=False)
            _set_run(p.add_run(), _norm_head(line[2:]), F_HEITI, SZ_3HAO)
        elif line.startswith('J|'):
            p = _para(doc, align='center', indent=False)
            _set_run(p.add_run(), _norm_head(line[2:]), F_FANGSONG, SZ_3HAO, bold=True)
        elif re.match(r'^第[一二三四五六七八九十百]+条', line.strip()):
            t = line.strip()
            m = re.match(r'^(第[一二三四五六七八九十百]+条)[\s\u3000]*(.*)$', t, re.S)
            p = _para(doc)
            _set_run(p.add_run(), m.group(1) + '\u0020\u0020', F_FANGSONG, SZ_3HAO, bold=True)
            _set_run(p.add_run(), m.group(2), F_FANGSONG, SZ_3HAO)
        else:
            p = _para(doc)
            _set_run(p.add_run(), line.strip(), F_FANGSONG, SZ_3HAO)

    _footer(sec)
    tmp = out_path + '.raw'
    doc.save(tmp)
    clean(tmp, out_path)
    return out_path


def clean(src, dst):
    """zip 级清理：主题字体 / 主题色 / 自动间距 / 段落边框 / 内置蓝（长名正则须在短名前）。"""
    with zipfile.ZipFile(src) as zin:
        with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename.endswith('.xml') and not item.filename.startswith('word/theme/'):
                    s = data.decode('utf-8')
                    s = re.sub(r'\s+w:(?:ascii|eastAsia|hAnsi|cs)Theme="[^"]*"', '', s)
                    s = re.sub(r'\s+w:theme(?:FillShade|FillTint|Fill|Color|Shade|Tint)="[^"]*"', '', s)
                    s = re.sub(r'\s+w:(?:before|after)Autospacing="[^"]*"', '', s)
                    s = re.sub(r'<w:pBdr>.*?</w:pBdr>', '', s, flags=re.S)
                    for b in BUILTIN_BLUES:
                        s = re.sub(b, '000000', s, flags=re.I)
                    data = s.encode('utf-8')
                zout.writestr(item, data)
    os.remove(src)


def main():
    ap = argparse.ArgumentParser(description='制度类 docx 生成器（参考实现）')
    ap.add_argument('txt', help='输入文本（行首 T| C| Z| J| 标记，见模块 docstring）')
    ap.add_argument('docx', help='输出 docx 路径')
    args = ap.parse_args()
    lines = io.open(args.txt, encoding='utf-8').read().split('\n')
    build(lines, args.docx)
    print('已生成：', args.docx)


if __name__ == '__main__':
    main()
