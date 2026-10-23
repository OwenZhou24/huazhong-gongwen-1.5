# -*- coding: utf-8 -*-
"""公文 / 制度类 docx 校验器（可复用）

用法：
    python verify_docx.py <docx路径> [--type gongwen|zhidu]

检查项（与 SKILL.md「docx 生成后必做的 XML 七查」一一对应）：
  1 主题字体残留        2 主题颜色残留        3 自动间距残留
  4 装饰边框 / 内置蓝    5 pPr 子元素顺序      6 段落级显式落地
  7 制度类专项（仅 --type zhidu 时展开：一、式标题 / 序号后2个半角空格 /
    附则章名两字间2个半角空格 / 条号大流水连续 / 章·节标题居中且清零缩进）
另附：页边距、固定行距取值、全角引号、页码域、表格固定布局、命名样式核查。

两档差异：
  公文   gongwen  页边距 37/35/28/26mm  行距 28 磅(560)  页码 2 部件（奇偶页不同）
  制度   zhidu    页边距 36/36/27/27mm  行距 30 磅(600)  页码 页脚居中（≥1 部件）

退出码 0 = 全过，1 = 有问题，2 = 用法错误。
"""
import argparse
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter

# OOXML 规定的 pPr 子元素顺序（违反则 Word 静默忽略属性）
PPR_ORDER = ['w:pStyle', 'w:keepNext', 'w:keepLines', 'w:pageBreakBefore',
             'w:framePr', 'w:widowControl', 'w:numPr', 'w:suppressLineNumbers',
             'w:pBdr', 'w:shd', 'w:tabs', 'w:suppressAutoHyphens', 'w:kinsoku',
             'w:wordWrap', 'w:overflowPunct', 'w:topLinePunct', 'w:autoSpaceDE',
             'w:autoSpaceDN', 'w:bidi', 'w:adjustRightInd', 'w:snapToGrid',
             'w:spacing', 'w:ind', 'w:contextualSpacing', 'w:mirrorIndents',
             'w:suppressOverlap', 'w:jc', 'w:textDirection', 'w:textAlignment',
             'w:textboxTightWrap', 'w:outlineLvl', 'w:divId', 'w:cnfStyle',
             'w:rPr', 'w:sectPr', 'w:pPrChange']

BUILTIN_BLUES = ('4F81BD', '1F497D', '2E74B5', '5B9BD5', '4472C4', '2F5496',
                 '365F91', '1F4E79', '44546A')

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

# 期望值（按文书类型切换：--type gongwen | zhidu）
PROFILES = {
    'gongwen': {
        'label': '公文',
        'margin': (37.0, 35.0, 28.0, 26.0),   # 上 下 左 右 mm
        'line': 560,                          # 28 磅
        'footer_parts': 2, 'page_fields': 2, 'footer_exact': True,
        'require_styles': True,
        'styles': {'Title': ('方正小标宋简体',), 'Heading1': ('黑体',),
                   'Heading2': ('楷体_GB2312',), 'BodyText': ('仿宋_GB2312',)},
    },
    'zhidu': {
        'label': '制度类',
        'margin': (36.0, 36.0, 27.0, 27.0),   # 上 下 左 右 mm
        'line': 600,                          # 固定值 30 磅
        'footer_parts': 1, 'page_fields': 1, 'footer_exact': False,
        'require_styles': False,              # 制度标本未必装载命名样式，存在才校验
        'styles': {'Title': ('方正小标宋简体',), 'BodyText': ('仿宋_GB2312',)},
    },
}

CN_DIGITS = '一二三四五六七八九十百'


def cn2num(t):
    """中文数字转阿拉伯数字（覆盖 1-199 的常见写法）。"""
    d = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
         '六': 6, '七': 7, '八': 8, '九': 9}
    if t == '十':
        return 10
    if '百' in t:
        a, b = t.split('百')
        return d.get(a, 1) * 100 + cn2num(b) if b else d.get(a, 1) * 100
    if '十' in t:
        a, b = t.split('十')
        return (d.get(a, 1)) * 10 + (d.get(b, 0) if b else 0)
    return d.get(t, 0)


def load(path):
    z = zipfile.ZipFile(path)
    parts = {}
    for n in z.namelist():
        if n.endswith('.xml') or n.endswith('.rels'):
            try:
                parts[n] = z.read(n).decode('utf-8')
            except UnicodeDecodeError:
                pass
    return parts


def para_text(p):
    return ''.join(t.text or '' for t in p.iter(W + 't'))


def p_pr(p):
    return p.find(W + 'pPr')


def check_zhidu(doc_xml, issues):
    """制度类专项：体例层面的 4 项校验。"""
    root = ET.fromstring(doc_xml)
    paras = [(p, para_text(p)) for p in root.iter(W + 'p')]

    bad_head = []          # ① 「一、」式一级标题
    bad_space = []         # ② 章/节/条号后非 2 个半角空格
    bad_fuze = []          # ②b 章名「附则」两字间未空 2 个半角空格
    not_center = []        # ④ 章/节标题未居中或缩进未清零
    tiao_seq = []          # ③ 段首条号

    for p, txt in paras:
        s = txt.strip()
        if not s:
            continue
        if re.match(r'^[%s]+、' % CN_DIGITS, s):
            bad_head.append(s[:20])
            continue
        m = re.match(r'^(第[%s]+[章节条])(.*)$' % CN_DIGITS, s, re.S)
        if m:
            tail = m.group(2)
            if not tail.startswith('\u0020\u0020'):
                bad_space.append(s[:20])
            if m.group(1)[-1] in '章节':
                pPr = p_pr(p)
                jc = pPr.find(W + 'jc') if pPr is not None else None
                ind = pPr.find(W + 'ind') if pPr is not None else None
                centered = jc is not None and jc.get(W + 'val') == 'center'
                # 无 <w:ind> 即视为无缩进；有则要求 firstLineChars / firstLine 为 0
                if ind is None:
                    zero = True
                else:
                    zero = (ind.get(W + 'firstLineChars') in (None, '0')
                            and ind.get(W + 'firstLine') in (None, '0'))
                if not (centered and zero):
                    not_center.append(s[:20])
            nm = tail.strip()
            if m.group(1)[-1] == '章' and re.fullmatch(r'附[\s\u3000]*则', nm) \
                    and nm != '附\u0020\u0020则':
                bad_fuze.append(s[:20])
            if m.group(1)[-1] == '条':
                tiao_seq.append(cn2num(m.group(1)[1:-1]))

    # 条号大流水连续（按出现顺序去重后应严格 1,2,3,…）
    uniq, seen = [], set()
    for n in tiao_seq:
        if n in seen:
            continue
        seen.add(n)
        uniq.append(n)
    gaps = [i + 1 for i, n in enumerate(uniq) if n != i + 1]
    # 段首条号若出现重复编号（同号两次）也提示
    dup = len(tiao_seq) != len(set(tiao_seq))

    print('[7] 制度类：一、式标题 = %d | 序号后空格异常 = %d | 章/节未居中或未清零缩进 = %d'
          ' | 附则章名空格异常 = %d'
          % (len(bad_head), len(bad_space), len(not_center), len(bad_fuze)))
    print('    段首条号序列 = %s' % (uniq[:12],))
    if gaps:
        print('    条号断号位（应为 n 的位置）= %s' % gaps)
    if bad_head:
        print('    ⚠️ 疑似公文体一级标题：', bad_head[:5])
        issues.append('制度类 一、式标题')
    if bad_space:
        print('    ⚠️ 序号后空格异常：', bad_space[:5])
        issues.append('制度类 序号后空格')
    if not_center:
        print('    ⚠️ 章/节标题居中或缩进未清零：', not_center[:5])
        issues.append('制度类 章/节居中')
    if bad_fuze:
        print('    ⚠️ 「附则」两字间未空 2 个半角空格：', bad_fuze[:5])
        issues.append('制度类 附则章名空格')
    if gaps:
        print('    ⚠️ 条号不连续（断号）')
        issues.append('制度类 条号断号')
    if dup:
        print('    ⚠️ 段首条号出现重复编号')
        issues.append('制度类 条号重复')


def main(path, prof):
    parts = load(path)
    # 生效部件（排除主题色板定义）
    live = {n: v for n, v in parts.items()
            if n != 'word/theme/theme1.xml' and not n.endswith('.rels')}
    L = '\n'.join(live.values())
    doc_xml = parts.get('word/document.xml', '')
    styles_xml = parts.get('word/styles.xml', '')
    issues = []

    print('=' * 68)
    print('%s docx 校验：%s' % (prof['label'], os.path.basename(path)))
    print('=' * 68)

    # 七查（1-6 通用）
    c1 = len(re.findall(r'w:(?:ascii|eastAsia|hAnsi|cs)Theme="', L))
    c2 = len(re.findall(r'w:theme(?:Fill|Color|Shade|Tint)[A-Za-z]*="', L))
    c3 = len(re.findall(r'w:(?:before|after)Autospacing="', L))
    c4a = len(re.findall(r'<w:pBdr>', doc_xml))            # 正文段落边框（硬要求 = 0）
    c4a_other = len(re.findall(r'<w:pBdr>', L)) - c4a      # 页眉页脚/命名样式中的（仅提示）
    c4b = sum(len(re.findall(b, L, re.I)) for b in BUILTIN_BLUES)
    print('[1] 主题字体残留 = %d' % c1)
    print('[2] 主题颜色残留 = %d' % c2)
    print('[3] 自动间距残留 = %d' % c3)
    print('[4] 正文段落边框 = %d | 其他部件段落边框 = %d（仅提示） | 内置蓝色值 = %d'
          % (c4a, c4a_other, c4b))
    if c1 or c2 or c3 or c4a or c4b:
        issues.append('1-4 残留未清')

    # 5 pPr 顺序
    bad_ppr = []
    for n, s in live.items():
        for m in re.finditer(r'<w:pPr>(.*?)</w:pPr>', s, re.S):
            tags = [t for t in re.findall(r'<w:(\w+)', m.group(1))
                    if ('w:' + t) in PPR_ORDER]
            ranks = [PPR_ORDER.index('w:' + t) for t in tags]
            if ranks != sorted(ranks):
                bad_ppr.append(n)
                break
    print('[5] pPr 顺序违规部件 = %s' % (sorted(set(bad_ppr)) or '无'))
    if bad_ppr:
        issues.append('5 pPr 顺序')

    # 6 段落级显式落地（document.xml 内逐段统计）
    n_paras = len(re.findall(r'<w:p [^>]*>|<w:p>', doc_xml))
    n_ind = doc_xml.count('w:firstLineChars="200"')
    n_spc = doc_xml.count('w:lineRule="exact"')
    n_jc = doc_xml.count('<w:jc ')
    print('[6] 段落总数 = %d | 段落级缩进 = %d | 固定行距 = %d | 对齐 = %d'
          % (n_paras, n_ind, n_spc, n_jc))

    # 6b 固定行距取值（按档校验）
    spacings = re.findall(r'<w:spacing\b[^>]*/>', doc_xml)
    exact_vals = [int(re.search(r'w:line="(\d+)"', s).group(1))
                  for s in spacings
                  if 'w:lineRule="exact"' in s and re.search(r'w:line="(\d+)"', s)]
    cnt = Counter(exact_vals)
    main_val = cnt.most_common(1)[0][0] if cnt else None
    print('[6b] 固定行距取值分布 = %s（主口径 %s，期望 %d）'
          % (dict(sorted(cnt.items())), main_val, prof['line']))
    if main_val is not None and main_val != prof['line']:
        issues.append('行距 %s' % main_val)
    elif cnt and len(cnt) > 1:
        print('     提示：存在非主口径行距 %s（多为空段/附件段，请人工确认）'
              % {k: v for k, v in sorted(cnt.items()) if k != main_val})

    # 页边距（按档）
    m = re.search(r'<w:pgMar([^/]*)/>', doc_xml)
    if m:
        a = dict(re.findall(r'w:(\w+)="(-?\d+)"', m.group(1)))
        cv = lambda k: round(int(a.get(k, 0)) / 1440 * 25.4, 1)
        got = (cv('top'), cv('bottom'), cv('left'), cv('right'))
        print('[页边距mm] 上/下/左/右 = %s (期望 %s)' % (got, prof['margin']))
        if got != prof['margin']:
            issues.append('页边距 %s' % (got,))

    # 引号
    try:
        root = ET.fromstring(doc_xml)
        blob = ''.join(t.text or '' for t in root.iter(W + 't'))
        half = len(re.findall(r'["\']', blob))
        print('[引号] 半角 = %d | 全角 “%d ”%d'
              % (half, blob.count('\u201c'), blob.count('\u201d')))
        if half or blob.count('\u201c') != blob.count('\u201d'):
            issues.append('引号')
    except Exception as e:
        print('[引号] 解析失败', e)

    # 页码（按档）
    foot = [n for n in live if 'footer' in n]
    npg = sum(live[n].count('PAGE') for n in foot)
    print('[页码] 页脚部件 = %d | PAGE域 = %d' % (len(foot), npg))
    if prof['footer_exact']:
        bad_page = (len(foot) != prof['footer_parts'] or npg != prof['page_fields'])
    else:
        bad_page = (len(foot) < prof['footer_parts'] or npg < prof['page_fields'])
    if bad_page:
        issues.append('页码')

    # 表格
    print('[表格] 固定布局 = %d' % L.count('w:tblLayout w:type="fixed"'))

    # 样式核查（制度档仅提示：制度类多直接在段落层设格式，不一定装载命名样式）
    print('[样式核查]%s' % ('' if prof['require_styles'] else '（制度档：仅提示，不判定）'))
    for sid, (font,) in prof['styles'].items():
        blk = re.search(r'<w:style [^>]*w:styleId="%s".*?</w:style>' % sid,
                        styles_xml, re.S)
        if blk:
            ok = 'w:eastAsia="%s"' % font in blk.group(0)
            print('   %-9s 字体=%s' % (sid, ok))
            if not ok and prof['require_styles']:
                issues.append('样式字体 ' + sid)
        else:
            print('   %-9s 未找到' % sid)
            if prof['require_styles']:
                issues.append('缺样式 ' + sid)

    # 7 制度类专项
    if prof['label'] == '制度类':
        check_zhidu(doc_xml, issues)

    # XML 可解析
    import xml.dom.minidom as md
    bad = []
    for n, v in live.items():
        try:
            md.parseString(v)
        except Exception:
            bad.append(n)
    print('[XML] 解析异常 = %s' % (bad or '无'))
    if bad:
        issues.append('XML')

    print('-' * 68)
    print('结论：', 'ALL PASS' if not issues else 'FAIL -> ' + str(issues))
    return 0 if not issues else 1


if __name__ == '__main__':
    ap = argparse.ArgumentParser(
        description='公文 / 制度类 docx 校验器（XML 七查 + 版式 + 页码）')
    ap.add_argument('docx', nargs='?', help='待校验的 docx 路径')
    ap.add_argument('--type', dest='doctype', choices=['gongwen', 'zhidu'],
                    default='gongwen', help='文书类型：gongwen（公文，默认）/ zhidu（制度类）')
    args = ap.parse_args()
    if not args.docx:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(args.docx, PROFILES[args.doctype]))
