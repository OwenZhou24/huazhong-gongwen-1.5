# 公文写作与敏感信息脱敏技能

一个面向**国企 / 事业单位公文写作**场景的 AI Agent 技能（Skill）。把「公文写作规范」与「敏感信息可逆脱敏」整合成一条完整流水线：写作前自动脱敏、写作后自动还原，全过程保护真实企业名称、人名、电话、身份证号等信息。

## 核心能力

| 能力 | 说明 |
| --- | --- |
| 可逆脱敏 | 处理前把敏感信息替换为占位符（如 `[COMPANY_4a0afdfc]`），处理完自动还原 |
| 公文格式规范 | 内置 GB/T 9704-2012《党政机关公文格式》完整规格 |
| 制度类文件规范 | 办法、规定、制度、细则、操作规程、工作指引等格式与写作规范 |
| 写作技巧库 | 公文语言规范、常见病句、修改技巧 |
| 模板库 | 常用公文模板，支持套写 |
| 质量自检 | 格式、字体、引号、页边距等逐项校验清单 |
| docx 排版脚本 | 按公文规范生成 / 校验 Word 文档 |

## 目录结构

```
.
├── SKILL.md                              # 技能主文件（入口，含执行流程）
├── sensitive_detector.py                 # 敏感信息检测与可逆脱敏引擎
├── config/
│   ├── company_names.json                # 企业敏感名称列表（按需修改）
│   └── company_names.example.json        # 脱敏模板
├── scripts/
│   ├── selfcheck.py                      # 引用文件完备性与可解析性自检
│   ├── build_zhidu_docx.py               # 制度类文件 docx 构建
│   └── verify_docx.py                    # docx 排版校验（字体/行距/引号/页边距）
├── checklists/
│   └── quality-checklist.md              # 公文质量检查清单
└── references/
    ├── gb-t-9704-2012-standard.md        # 公文格式国标规格
    ├── 制度类文件格式与写作规范.md          # 制度类文件专项规范
    ├── writing-techniques.md             # 公文写作技巧
    └── document-templates.md             # 公文模板合集
```

## 安装

把本目录整体放入 Agent 平台的 skills 目录即可：

```bash
# WorkBuddy / Claude Code 风格（用户级）
git clone <本仓库地址> ~/.workbuddy/skills/gongwen-writing-skill

# 或项目级
git clone <本仓库地址> <你的项目>/.workbuddy/skills/gongwen-writing-skill
```

## 配置

`config/company_names.json` 是敏感企业名称清单，**使用前请按你的实际情况替换**：

```bash
cp config/company_names.example.json config/company_names.json
# 然后编辑 company_names.json，填入需要检测的企业名称
```

修改后无需重启，下次匹配自动生效。

环境要求：Python 3.8+。

## 主要脚本用法

```bash
# 自检：确认所有 @ 引用的文件都存在且可解析
python scripts/selfcheck.py

# 校验生成的 docx 是否符合公文规范
python scripts/verify_docx.py <文件路径>
```

## ⚠️ 使用须知

1. **本技能含企业真实名称清单**（`config/company_names.json`）。若需公开仓库，请先替换为 `company_names.example.json` 的脱敏内容。
2. `sensitive_mappings.json` 为运行时生成文件，已在 `.gitignore` 中排除，请勿提交。
3. 生成的公文正文（`.docx` / `.pdf`）默认不纳入版本控制，避免涉密内容外流。

## 许可

内部使用。
