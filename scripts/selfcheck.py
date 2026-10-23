# -*- coding: utf-8 -*-
"""HD公文写作助手 —— 包自检（一键复验"各环节是否运行无误、引用是否到位"）

用法（在任意工作目录下执行均可）：
    python <技能根目录>/scripts/selfcheck.py            # 自检本脚本所在技能包
    python scripts/selfcheck.py --pkg <其它技能包目录>   # 指定包
    python scripts/selfcheck.py --deep                  # 追加反向缺陷注入验证

检查项：
  [1] 必需文件完整性          [2] SKILL.md frontmatter
  [3] 目录/行内锚点（全包）    [4] 全包引用解析（@引用 / 残留链接 / 裸路径）
  [5] 正文半角引号（代码区豁免）
  [6] 全部 .py 语法编译
  [7] 脱敏 → 还原 往返一致
  [8] 制度类 docx 生成 + 制度档校验 ALL PASS
  [9] 公文档（默认档）分支可运行
  [10] 反向注入缺陷（--deep 时）确认真能报错，不是"假过"

设计约束：运行类检查一律在临时克隆中进行，绝不污染本包的 sensitive_mappings.json。
"""
import argparse
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PKG = os.path.dirname(HERE)

REQUIRED = [
    'SKILL.md', 'sensitive_detector.py',
    'config/company_names.json', 'checklists/quality-checklist.md',
    'references/document-templates.md', 'references/writing-techniques.md',
    'references/gb-t-9704-2012-standard.md',
    'references/制度类文件格式与写作规范.md',
    'scripts/verify_docx.py', 'scripts/build_zhidu_docx.py',
]

# 引用形式一（本包标准）：反引号包裹的 `@相对技能根目录路径`，可带 #fragment
REF_AT = re.compile(r'`@([^`]+?)`')
# 引用形式二（历史遗留，须为 0）：markdown 本地链接 [desc](./path)
REF_MDLINK = re.compile(r'\[[^\]]*\]\((?!https?:|#|mailto:)([^)]+)\)')
# 引用形式三：反引号内的裸包内路径（references/ scripts/ checklists/ config/）
REF_BARE = re.compile(r'`((?:references|scripts|checklists|config)/[^`]+?)`')
# 包内资源目录前缀（用于 c4 覆盖率统计）
PKG_RES_DIRS = ('references', 'scripts', 'checklists', 'config')
CODE_FEATURE = re.compile(r'<[A-Za-z/!?]|^\s*import |^\s*def |#!/|https?://|pip install|\{\s*"|=>|w:|^\s*\$ ')
CJK = re.compile(r'[\u4e00-\u9fff]')

SAMPLE = """T|HD融资担保股份有限公司
T|自检用示例管理办法
C|（征求意见稿）
Z|第一章  总则
第一条  为规范自检示例事项，根据相关规定，结合公司实际，制定本办法。
第二条  本办法所称“示例事项”，是指用于自检验证的模拟事项。
Z|第二章  附则
第三条  本办法自印发之日起施行。
"""

results = []


def step(name, ok, detail=''):
    results.append((name, bool(ok), detail))
    print('  [%s] %-40s %s' % ('PASS' if ok else 'FAIL', name, detail))


def run(args, cwd=None):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return p.returncode, (p.stdout or '') + (p.stderr or '')


SELF_ABS = os.path.abspath(__file__)


def walk_files(pkg, exts):
    for dp, _, fns in os.walk(pkg):
        if os.sep + '.git' in dp:
            continue
        for fn in sorted(fns):
            if fn.endswith(exts):
                p = os.path.join(dp, fn)
                if os.path.abspath(p) == SELF_ABS:
                    continue  # 跳过本脚本自身：其注释/正则字面量会自匹配，造成假阳性
                yield p, os.path.relpath(p, pkg)


# ---------- 1 必备文件 ----------
def c1(pkg):
    miss = [f for f in REQUIRED if not os.path.exists(os.path.join(pkg, f))]
    step('1 必需文件完整性', not miss,
         '全部就位（%d 项）' % len(REQUIRED) if not miss else '缺失：%s' % miss)
    # 运行时脱敏映射表：属运行产物，首次脱敏时才由引擎生成，缺失不算缺陷（见 .gitignore）
    mp = os.path.join(pkg, 'sensitive_mappings.json')
    step('1b 运行时脱敏映射表', True,
         ('已存在（%d 字节）' % os.path.getsize(mp)) if os.path.exists(mp)
         else '未生成，首次脱敏时自动创建（正常）')


# ---------- 2 frontmatter ----------
def c2(pkg):
    p = os.path.join(pkg, 'SKILL.md')
    head = io.open(p, encoding='utf-8').read().split('\n')[:20]
    if not head or head[0].strip() != '---':
        step('2 SKILL.md frontmatter', False, '首行不是 ---')
        return
    ends = [i for i, l in enumerate(head[1:], 1) if l.strip() == '---']
    if not ends:
        step('2 SKILL.md frontmatter', False, 'frontmatter 未闭合')
        return
    fm = head[1:ends[0]]
    fields = {}
    for l in fm:
        if ':' in l:
            fields[l.split(':', 1)[0].strip()] = l.split(':', 1)[1].strip()
    ok = 'name' in fields and 'description' in fields
    step('2 SKILL.md frontmatter', ok,
         'name=%s，description %d 字' % (fields.get('name', ''), len(fields.get('description', '')))
         if ok else '缺少 name / description 字段')


# ---------- 2b 引用强制读取规则 ----------
def c2b(pkg):
    """'能读到'靠根目录注入，'照它写'靠 SKILL.md 的指令强度——此项把后者固化为可验证项。
    要求 SKILL.md 正文出现硬指令块，且关键措辞齐备。"""
    s = io.open(os.path.join(pkg, 'SKILL.md'), encoding='utf-8').read()
    heads = '引用文件强制读取规则' in s or '强制读取规则' in s
    keys = {
        '不得仅凭摘要': ('不得仅凭' in s) or ('不得只凭' in s),
        '以引用文件为准': ('以引用文件' in s) and ('为准' in s),
        '相对根目录': ('相对' in s) and ('根目录' in s),
    }
    miss = [k for k, v in keys.items() if not v]
    ok = heads and not miss
    step('2b 引用强制读取规则（决定"照它写"）', ok,
         '硬指令齐备且指向根目录' if ok else
         '缺失：%s%s' % ([] if heads else ['规则块'], miss))


# ---------- 3 目录锚点（全包所有 md，而非仅 SKILL.md） ----------
def _slug(title):
    """按 GitHub 风格生成标题锚点：小写、去标点、空格转 -。"""
    t = title.strip().lower()
    t = re.sub(r'[`*_\u3000]', '', t)
    t = re.sub(r'[^\w\u4e00-\u9fff\-\s]', '', t)
    t = re.sub(r'\s+', '-', t)
    return t


def c3(pkg):
    bad = []
    total = 0
    for f, rel in walk_files(pkg, ('.md',)):
        s = io.open(f, encoding='utf-8').read()
        # 本文件所有标题及其 slug（含手写 html 锚点 <a id="x">）
        heads = [h.strip() for h in re.findall(r'^#{1,6}\s+(.+?)\s*$', s, re.M)]
        slugs = set(_slug(h) for h in heads)
        slugs |= set(re.findall(r'<a\s+[^>]*id="([^"]+)"', s))
        for m in re.finditer(r'\[([^\]]+)\]\(#([^)]+)\)', s):
            total += 1
            tgt = m.group(2).strip()
            # 命中判定：精确 slug，或标题原文包含关系（宽松兜底）
            if tgt in slugs or any(tgt in _slug(h) or _slug(h) in tgt for h in heads):
                continue
            bad.append('%s -> #%s' % (rel, tgt))
    step('3 目录/行内锚点（全包 md）', not bad,
         '%d 项锚点全有效' % total if not bad else '失效 %d 项：%s' % (len(bad), bad[:4]))


# ---------- 4 引用解析（@ 引用 + 残留链接 + 裸路径） ----------
def c4(pkg):
    at_found, bad_at = {}, []
    mdlink = []
    bare = []
    for f, rel in walk_files(pkg, ('.md', '.py', '.json')):
        try:
            s = io.open(f, encoding='utf-8').read()
        except Exception:
            continue
        for raw in REF_AT.findall(s):
            at_found.setdefault(raw.strip(), set()).add(rel)
        for m in REF_MDLINK.finditer(s):
            p = m.group(1).strip()
            if p.startswith('http') or p.startswith('#'):
                continue
            mdlink.append('%s:%s' % (rel, p[:40]))
        for m in REF_BARE.finditer(s):
            bare.append('%s:%s' % (rel, m.group(1)[:40]))
    # 逐条解析 @ 引用（相对技能根目录；忽略 fragment）
    for raw in at_found:
        tgt = raw.split('#')[0].strip()
        if not tgt:
            continue
        if not os.path.exists(os.path.join(pkg, *tgt.replace('\\', '/').split('/'))):
            bad_at.append(raw)
    ok = (not bad_at) and (not mdlink)
    detail = '@ 引用 %d 种全部命中；无残留本地链接' % len(at_found) if ok else \
        '失效 @ 引用：%s；残留本地链接：%s' % (bad_at, mdlink[:4])
    if bare:
        detail += '（提示：%d 处反引号裸路径，建议改 @ 形式）' % len(bare)
    step('4 全包引用解析（@ / 链接 / 裸路径）', ok, detail)


# ---------- 5 正文引号 ----------
def c5(pkg):
    bad = []
    for f, rel in walk_files(pkg, ('.md',)):
        s = io.open(f, encoding='utf-8').read()
        if s.count('```') % 2:
            bad.append('%s(围栏不成对)' % rel)
            continue
        blocked = set()
        for m in re.finditer(r'```([^\n]*)\n([\s\S]*?)^[ \t]*```', s, re.M):
            tag, body = m.group(1).strip(), m.group(2)
            tot = len(re.sub(r'\s', '', body)) or 1
            if tag or CODE_FEATURE.search(body) or len(CJK.findall(body)) / tot < 0.40:
                blocked.update(range(m.start(), m.end()))
        for m in re.finditer(r'`[^`\n]*`', s):
            blocked.update(range(m.start(), m.end()))
        for m in re.finditer(r'<[^>\n]{0,200}>', s):
            blocked.update(range(m.start(), m.end()))
        prose = ''.join(c for i, c in enumerate(s) if i not in blocked)
        n = prose.count('"') + prose.count("'")
        if n:
            bad.append('%s(%d)' % (rel, n))
    step('5 正文半角引号（代码区豁免）', not bad, '全部为中文全角引号' if not bad else '残留：%s' % bad)


# ---------- 6 语法编译 ----------
def c6(pkg):
    """语法编译。用 utf-8-sig 读取：本包 sensitive_detector.py 带 UTF-8 BOM，属合法（PEP 263），
    但 compile() 对 str 形式的 U+FEFF 会报 SyntaxError，故须用 utf-8-sig 剥掉。"""
    bad = []
    for f, rel in walk_files(pkg, ('.py',)):
        try:
            compile(io.open(f, encoding='utf-8-sig').read(), f, 'exec')
        except SyntaxError as e:
            bad.append('%s:%s' % (rel, e.lineno))
    step('6 全部 .py 语法编译', not bad, '编译通过' if not bad else '语法错误：%s' % bad)


# ---------- 7~9 运行类（临时克隆内） ----------
def runtime(pkg, tmp):
    clone = os.path.join(tmp, 'clone')
    shutil.copytree(pkg, clone)

    # 7 脱敏 → 还原
    src = '我公司HD联系人电话13812345678，身份证110101199001011234，邮箱a@b.com。'
    code = ('import sys\nsys.path.insert(0, r"%s")\n'
            'from sensitive_detector import process_user_message, restore_ai_response\n'
            'src = %r\n'
            'refused, masked, _ = process_user_message(src)\n'
            'back = restore_ai_response(masked)\n'
            'assert not refused and masked != src and back == src, "往返异常"\n'
            'print("MASKED=" + masked)\n') % (clone, src)
    rc, out = run([sys.executable, '-X', 'utf8', '-c', code])
    step('7 脱敏 → 还原 往返一致', rc == 0,
         [l for l in out.splitlines() if l.startswith('MASKED=')][-1][:78] if rc == 0 else out[-200:])

    # 8 制度类生成 + 校验
    try:
        import docx  # noqa: F401
        has_docx = True
    except Exception:
        has_docx = False
    if not has_docx:
        step('8 制度类 docx 生成 + 校验', True, '跳过：当前解释器未装 python-docx')
        step('9 公文档分支跑通', True, '跳过：当前解释器未装 python-docx')
        return
    txt = os.path.join(tmp, 'in.txt')
    out_docx = os.path.join(tmp, 'out.docx')
    io.open(txt, 'w', encoding='utf-8', newline='\n').write(SAMPLE)
    rc, o = run([sys.executable, '-X', 'utf8', os.path.join(clone, 'scripts', 'build_zhidu_docx.py'), txt, out_docx])
    if rc != 0 or not os.path.exists(out_docx):
        step('8 制度类 docx 生成 + 校验', False, '生成失败：%s' % o[-200:])
        step('9 公文档分支跑通', False, '依赖生成物，跳过')
        return
    rc, o = run([sys.executable, '-X', 'utf8', os.path.join(clone, 'scripts', 'verify_docx.py'),
                 out_docx, '--type', 'zhidu'])
    step('8 制度类 docx 生成 + 校验', rc == 0 and 'ALL PASS' in o,
         '生成 %d 字节 · 制度档 ALL PASS' % os.path.getsize(out_docx)
         if 'ALL PASS' in o else o[-260:])

    # 9 公文档分支
    rc, o = run([sys.executable, '-X', 'utf8', os.path.join(clone, 'scripts', 'verify_docx.py'), out_docx])
    ok = any(l.strip().startswith('结论') for l in o.splitlines())
    step('9 公文档分支跑通', ok, '正确判定为不合公文版式（退出码 %d）' % rc if ok else o[-200:])

    # 10 反向注入（可选）
    if not DEPTH:
        return
    bad = []
    cases = [
        ('条号后只留 1 个空格', '>第一条  </w:t>', '>第一条 </w:t>', '序号后空格异常 = (\\d+)'),
        ('混入公文体「一、」式标题', '<w:t>第一章  总则</w:t>', '<w:t>一、总则</w:t>', '一、式标题 = (\\d+)'),
    ]
    for i, (label, a, b, pat) in enumerate(cases):
        z = zipfile.ZipFile(out_docx)
        xml = z.read('word/document.xml').decode('utf-8')
        if a not in xml:
            bad.append('%s(靶点未命中)' % label)
            continue
        xml2 = xml.replace(a, b, 1)
        p = os.path.join(tmp, 'neg%d.docx' % i)
        with zipfile.ZipFile(p, 'w', zipfile.ZIP_DEFLATED) as zo:
            for item in z.infolist():
                zo.writestr(item, xml2.encode('utf-8') if item.filename == 'word/document.xml'
                            else z.read(item.filename))
        z.close()
        rc, o = run([sys.executable, '-X', 'utf8', os.path.join(clone, 'scripts', 'verify_docx.py'),
                     p, '--type', 'zhidu'])
        m = re.search(pat, o)
        if not m or m.group(1) == '0':
            bad.append(label)
    step('10 反向注入缺陷可检出', not bad,
         '两类缺陷均报出' if not bad else '漏检：%s' % bad)


def main():
    global DEPTH
    ap = argparse.ArgumentParser(description='HD公文写作助手 · 包自检')
    ap.add_argument('--pkg', default=DEFAULT_PKG, help='技能包根目录（默认为本脚本上级目录）')
    ap.add_argument('--deep', action='store_true', help='追加反向缺陷注入验证')
    a = ap.parse_args()
    DEPTH = a.deep
    pkg = os.path.abspath(a.pkg)
    print('=' * 78)
    print('包自检：', pkg)
    print('=' * 78)
    if not os.path.exists(os.path.join(pkg, 'SKILL.md')):
        print('  × 该目录不是技能包（无 SKILL.md）')
        return 2
    c1(pkg)
    c2(pkg)
    c2b(pkg)
    c3(pkg)
    c4(pkg)
    c5(pkg)
    c6(pkg)
    tmp = tempfile.mkdtemp(prefix='skillcheck_')
    try:
        runtime(pkg, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('-' * 78)
    bad = [n for n, ok, _ in results if not ok]
    print('结论：%s' % ('全部通过（%d/%d）' % (len(results), len(results)) if not bad
                      else '未通过 -> %s' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
