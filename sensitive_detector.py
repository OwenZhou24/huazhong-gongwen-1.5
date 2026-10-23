"""
Sensitive Information Detector & Reversible Desensitization v2.0
跨平台版本 - Zero external deps (pure Python 3.7+)
"""

import re, os, hashlib, json, time
from typing import Tuple, List, Dict, Optional, Any
from dataclasses import dataclass
from enum import Enum

class RiskLevel(str, Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

CATEGORY_PREFIX = {'api_key': 'API_KEY', 'openai_key': 'OPENAI', 'anthropic_key': 'ANTHROPIC', 'github_token': 'GITHUB', 'slack_token': 'SLACK', 'discord_token': 'DISCORD', 'telegram_token': 'TELEGRAM', 'stripe_key': 'STRIPE', 'google_key': 'GOOGLE', 'aws_key': 'AWS', 'azure_key': 'AZURE', 'password': 'CRED', 'db_uri': 'DB_URI', 'ssh_key': 'SSH_KEY', 'jwt_token': 'JWT', 'id_card': 'IDCARD', 'bank_card': 'BANK', 'phone': 'PHONE', 'email': 'EMAIL', 'qq': 'QQ', 'license_plate': 'PLATE', 'ip_address': 'IP', 'credit_card': 'CARD', 'eth_address': 'ETH', 'btc_address': 'BTC', 'private_key': 'PRIV_KEY', 'mnemonic': 'MNEMONIC', 'secret': 'SECRET', 'company_name': 'COMPANY'}


# === 从配置文件加载企业名称（如有则覆盖硬编码列表） ===
_CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "company_names.json")
if os.path.exists(_CONFIG_FILE):
    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8-sig") as _f:
            _cfg = json.load(_f)
            _loaded = _cfg.get("company_names", [])
            if _loaded:
                COMPANY_SENSITIVE_NAMES = _loaded
    except Exception:
        pass

# 也检查上一级目录（插件结构：skills/skill-name/ -> 上级是插件根目录）
_ALT_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "company_names.json")
if os.path.exists(_ALT_CONFIG):
    try:
        with open(_ALT_CONFIG, "r", encoding="utf-8-sig") as _f:
            _cfg = json.load(_f)
            _loaded = _cfg.get("company_names", [])
            if _loaded:
                COMPANY_SENSITIVE_NAMES = _loaded
    except Exception:
        pass

# 未加载到配置时使用硬编码默认值
if "COMPANY_SENSITIVE_NAMES" not in dir() or not COMPANY_SENSITIVE_NAMES:

    COMPANY_SENSITIVE_NAMES = ['HD', 'HD融资担保股份有限公司', 'HD控股集团', 'HD金控', 'ZB融资担保股份有限公司', 'ZB担保', 'GT保理', 'HD融资租赁有限公司', 'HD信用投资集团有限公司', 'HB农担', 'HB农业信贷融资担保有限公司']


def _match_company_names(text):
    results = []
    if not text:
        return results
    sorted_names = sorted(COMPANY_SENSITIVE_NAMES, key=len, reverse=True)
    positions = []
    for name in sorted_names:
        idx = 0
        while True:
            idx = text.find(name, idx)
            if idx == -1:
                break
            overlap = any(not (idx + len(name) <= s or idx >= e) for s, e in positions)
            if not overlap:
                positions.append((idx, idx + len(name)))
                results.append({"name": "企业名称_" + name, "type": "company_name", "value": name, "start": idx, "end": idx + len(name), "risk_score": 7.0})
            idx += 1
    return results

SENSITIVE_PATTERNS = [
    {'name': 'SSH私钥', 'pattern': '-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----', 'type': 'ssh_key', 'risk_score': 9.5},
    {'name': 'AWS访问密钥', 'pattern': 'AKIA[0-9A-Z]{16}', 'type': 'aws_key', 'risk_score': 9.5},
    {'name': '区块链私钥', 'pattern': '(?:private[_\\s]?key|priv[_\\s]?key)\\s*[=:]\\s*[\\x27\\x22]?0x[a-fA-F0-9]{64}[\\x27\\x22]?', 'type': 'private_key', 'risk_score': 9.5},
    {'name': '区块链助记词', 'pattern': '(?:mnemonic|seed|recovery)\\s*(?:phrase|words?)?\\s*[=:]\\s*[\\x27\\x22]?(?:[a-z]{3,8}\\s+){11,23}[a-z]{3,8}[\\x27\\x22]?', 'type': 'mnemonic', 'risk_score': 9.5},
    {'name': 'OpenAI API密钥', 'pattern': 'sk-(?:proj-)?[a-zA-Z0-9]{8,}', 'type': 'openai_key', 'risk_score': 9.0},
    {'name': 'Anthropic API密钥', 'pattern': 'sk-ant-[a-zA-Z0-9\\-]{8,}', 'type': 'anthropic_key', 'risk_score': 9.0},
    {'name': '数据库连接串', 'pattern': '(?:mysql|postgres|postgresql|mongodb|redis)://[^\\s]+', 'type': 'db_uri', 'risk_score': 9.0},
    {'name': 'GitHub令牌', 'pattern': 'ghp_[a-zA-Z0-9]{20,}', 'type': 'github_token', 'risk_score': 8.5},
    {'name': 'GitHub细粒度令牌', 'pattern': 'github_pat_[a-zA-Z0-9_]{22,}', 'type': 'github_token', 'risk_score': 8.5},
    {'name': 'Stripe密钥', 'pattern': 'sk_live_[a-zA-Z0-9]{24,}', 'type': 'stripe_key', 'risk_score': 9.0},
    {'name': 'Slack令牌', 'pattern': 'xox[bpors]-[a-zA-Z0-9\\-]{10,}', 'type': 'slack_token', 'risk_score': 7.5},
    {'name': 'Discord机器人令牌', 'pattern': '[MN][A-Za-z\\d]{23,25}\\.[A-Za-z\\d]{6}\\.[A-Za-z\\d_\\-]{27,}', 'type': 'discord_token', 'risk_score': 7.5},
    {'name': 'Telegram机器人令牌', 'pattern': '[0-9]{8,10}:[0-9A-Za-z_\\-]{35}', 'type': 'telegram_token', 'risk_score': 7.5},
    {'name': 'Google API密钥', 'pattern': 'AIza[0-9A-Za-z\\-_]{35,}', 'type': 'google_key', 'risk_score': 8.5},
    {'name': '密码赋值', 'pattern': '(?:password|passwd|pwd|pass)\\s*[=:]\\s*[^\\s,;)]{6,}', 'type': 'password', 'risk_score': 8.0},
    {'name': '身份证号', 'pattern': '[1-9]\\d{5}(?:19|20)\\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\\d|3[01])\\d{3}[0-9Xx]', 'type': 'id_card', 'risk_score': 8.0},
    {'name': '信用卡号', 'pattern': '(?<!\\d)\\d{4}[-\\s]?\\d{4}[-\\s]?\\d{4}[-\\s]?\\d{4}(?!\\d)', 'type': 'credit_card', 'risk_score': 8.0},
    {'name': 'JWT令牌', 'pattern': 'eyJ[a-zA-Z0-9_-]{10,}\\.eyJ[a-zA-Z0-9_-]{10,}\\.[a-zA-Z0-9_-]{10,}', 'type': 'jwt_token', 'risk_score': 7.0},
    {'name': '以太坊地址', 'pattern': '(?<![a-zA-Z0-9])0x[a-fA-F0-9]{40}(?![a-zA-Z0-9])', 'type': 'eth_address', 'risk_score': 6.0},
    {'name': '比特币地址', 'pattern': '(?<![a-zA-Z0-9])[13][a-km-zA-HJ-NP-Z1-9]{25,34}(?![a-zA-Z0-9])', 'type': 'btc_address', 'risk_score': 6.0},
    {'name': '银行卡号', 'pattern': '(?<![0-9])\\d{16,19}(?![0-9])', 'type': 'bank_card', 'risk_score': 6.0},
    {'name': '手机号', 'pattern': '(?<![0-9])1[3-9]\\d{9}(?![0-9])', 'type': 'phone', 'risk_score': 6.0},
    {'name': '私有IP地址', 'pattern': '\\b(?:10\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}|172\\.(?:1[6-9]|2\\d|3[01])\\.\\d{1,3}\\.\\d{1,3}|192\\.168\\.\\d{1,3}\\.\\d{1,3})\\b', 'type': 'ip_address', 'risk_score': 5.0},
    {'name': 'IP地址', 'pattern': '(?<![0-9.])\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}(?![0-9.])', 'type': 'ip_address', 'risk_score': 5.0},
    {'name': '车牌号', 'pattern': '[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼使领][A-Z][A-Z0-9]{4}[A-Z0-9挂学警港澳]', 'type': 'license_plate', 'risk_score': 5.0},
    {'name': '邮箱地址', 'pattern': '[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}', 'type': 'email', 'risk_score': 4.0},
    {'name': 'QQ号', 'pattern': '(?<![0-9])[1-9]\\d{5,10}(?![0-9a-zA-Z])', 'type': 'qq', 'risk_score': 3.0},
]

BYPASS_KEYWORDS = ['禁止脱敏', '不要脱敏', '跳过脱敏', '关闭脱敏', '取消脱敏', '卸载脱敏', '移除脱敏', '停用脱敏', '禁用脱敏', '取消检测', '跳过检测', '关闭检测', '不要检测', '禁止检测', '绕过检测', '绕过脱敏', '忽略检测', '忽略脱敏', '跳过安全检测', '暂时关闭', '临时关闭', '先关掉', '关一下', '我是管理员', '我有权限', '给我权限', '授权我', '信任我', '这是安全的', '这个没问题', '让我通过', '我知道风险', '我承担后果', '确认不脱敏', '确认跳过', '不脱敏', '别脱敏', '关闭安全检测']

INJECTION_PATTERNS = [
    ('(?:ignore|disregard|forget|override|bypass)\\s+(?:all\\s+)?(?:previous|above|prior|earlier|system)\\s+(?:instructions?|prompts?|rules?|constraints?)', 9.5, '指令覆盖攻击'),
    ('(?:new|updated|revised|real)\\s+(?:instructions?|system\\s+prompt|directive)', 8.5, '新指令注入'),
    ('(?:you\\s+are\\s+now|act\\s+as|pretend\\s+to\\s+be|your\\s+new\\s+role\\s+is)', 8.0, '角色劫持'),
    ('(?:output|print|display|reveal|show|send|transmit)\\s+(?:all\\s+)?(?:api\\s*keys?|passwords?|secrets?|credentials?|tokens?)', 9.0, '数据外泄尝试'),
    ('(?:send|post|upload|transmit)\\s+(?:[\\w\\s]{0,20}\\s+)?(?:to|data\\s+to)\\s+https?://', 9.0, '外传数据到URL'),
    ('(?:base64|b64)\\s*(?:decode|exec|eval|run)', 7.5, 'Base64载荷执行'),
    ('[\\u200b-\\u200f\\u2028-\\u202f\\u2060-\\u206f\\ufeff]', 6.0, '不可见Unicode字符'),
    ('---\\s*(?:END|BEGIN|SYSTEM|ADMIN|ROOT)\\s*---', 8.0, '分隔符注入'),
    ('<\\s*(?:system|admin|root|prompt)\\s*>', 7.5, 'XML样式注入'),
    ('(?:DAN|do\\s+anything\\s+now|developer\\s+mode|jailbreak)', 7.0, '已知越狱模式'),
]

DANGEROUS_COMMAND_PATTERNS = [
    ('\\brm\\s+-[^\\s]*r[^\\s]*f', 9.5, '强制递归删除'),
    ('\\brm\\s+-rf\\s+/', 10.0, '从根目录递归删除'),
    ('\\brmdir\\s+/s', 9.5, '递归删除目录(Windows)'),
    ('curl\\s+.*\\|\\s*(?:bash|sh|zsh)', 9.5, '管道执行远程脚本'),
    ('wget\\s+.*\\|\\s*(?:bash|sh|zsh)', 9.5, '管道执行远程脚本'),
    ('\\bsudo\\s+', 7.5, 'sudo权限提升'),
    ('\\bchmod\\s+777\\s+', 8.0, '设置全局可写权限'),
    ('\\bchmod\\s+\\+s\\s+', 9.0, '设置SUID位'),
    ('\\bcurl\\s+-[^\\s]*d\\s+.*@', 8.0, '通过curl发送文件'),
    ('\\bnc\\s+-[^\\s]*\\s+\\d+', 8.0, 'Netcat连接'),
    ('\\becho\\s+.*>\\s*/etc/', 9.0, '写入系统配置'),
    ('\\bdd\\s+if=.*of=/dev/', 9.5, '直接磁盘写入'),
    ('\\b(?:shutdown|reboot|halt|poweroff)\\b', 8.0, '系统关机/重启'),
    ('os\\.system\\s*\\(', 7.5, 'os.system调用'),
    ('exec\\s*\\(', 7.5, 'exec动态执行'),
    ('eval\\s*\\(', 7.5, 'eval动态执行'),
]

IMAGE_SENSITIVE_KEYWORDS = ['银行', 'bank', 'boc', 'icbc', 'ccb', 'abc', 'bcom', 'credit card', 'debit card', 'card number', '银行卡', '信用卡', '储蓄卡', '中国银行', '工商银行', '建设银行', '农业银行', '交通银行', 'unionpay', '银联', 'visa', 'mastercard', 'amex', 'jcb', '身份证', 'id card', 'passport', '护照', '驾驶证', '行驶证', '居民身份证', '公民身份', '身份号码', 'cvv', 'cvc', '安全码', '有效期至', 'valid thru', 'expiry', 'cardholder', '持卡人', '账号', 'account', 'atm', 'emv', 'chip', 'contactless', '闪付', 'paywave']


@dataclass
class DetectionResult:
    pattern_name: str
    pattern_type: str
    value: str
    start: int
    end: int
    risk_score: float

class ReversibleDesensitizer:
    # Reversible desensitization manager - maps placeholders to original values
    _instance = None
    _mappings: Dict[str, str] = {}
    _mapping_file: str = ''

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def init(cls, data_dir: str = None):
        if data_dir is None:
            data_dir = os.path.dirname(os.path.abspath(__file__))
        os.makedirs(data_dir, exist_ok=True)
        cls._mapping_file = os.path.join(data_dir, "sensitive_mappings.json")
        cls._load()

    @classmethod
    def _load(cls):
        if cls._mapping_file and os.path.exists(cls._mapping_file):
            try:
                with open(cls._mapping_file, "r", encoding="utf-8") as f:
                    cls._mappings.update(json.load(f))
            except Exception:
                pass

    @classmethod
    def _save(cls):
        if cls._mapping_file:
            try:
                d = os.path.dirname(cls._mapping_file)
                if d:
                    os.makedirs(d, exist_ok=True)
                with open(cls._mapping_file, "w", encoding="utf-8") as f:
                    json.dump(cls._mappings, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    @classmethod
    def encode(cls, value: str, prefix: str) -> str:
        key = '[' + prefix + '_' + hashlib.md5((prefix + '_' + value + '_' + str(id(value))).encode()).hexdigest()[:8] + ']'
        cls._mappings[key] = value
        cls._save()
        return key

    @classmethod
    def decode_all(cls, text: str) -> str:
        cls._load()
        if not text:
            return text
        for key, val in cls._mappings.items():
            text = text.replace(key, val)
        return text

    @classmethod
    def get_mapping_count(cls) -> int:
        return len(cls._mappings)

    @classmethod
    def clear(cls):
        cls._mappings.clear()
        cls._save()

class SensitiveInfoDetector:
    def __init__(self):
        self._patterns = [(p['name'], re.compile(p['pattern']), p['type'], p['risk_score']) for p in SENSITIVE_PATTERNS]
        self._injections = [(re.compile(p[0], re.IGNORECASE | re.MULTILINE), p[1], p[2]) for p in INJECTION_PATTERNS]
        self._commands = [(re.compile(p[0], re.IGNORECASE), p[1], p[2]) for p in DANGEROUS_COMMAND_PATTERNS]

    def detect_sensitive(self, text: str) -> List[DetectionResult]:
        results = []
        for name, pat, ptype, score in self._patterns:
            for m in pat.finditer(text):
                results.append(DetectionResult(name, ptype, m.group(0), m.start(), m.end(), score))
        for cr in _match_company_names(text):
            results.append(DetectionResult(cr['name'], cr['type'], cr['value'], cr['start'], cr['end'], cr['risk_score']))
        return self._deduplicate(results)

    def detect_bypass(self, text: str):
        if not text:
            return False, ''
        t = text.lower()
        for kw in BYPASS_KEYWORDS:
            if kw in text or kw.lower() in t:
                return True, u'检测到绕过意图：' + kw
        return False, ''

    def detect_injection(self, text: str) -> List[dict]:
        r = []
        for pat, score, desc in self._injections:
            for m in pat.finditer(text):
                r.append({'type': 'prompt_injection', 'risk_score': score, 'description': desc})
        r.sort(key=lambda x: -x['risk_score'])
        return r

    def detect_dangerous_commands(self, text: str) -> List[dict]:
        r = []
        for pat, score, desc in self._commands:
            for m in pat.finditer(text):
                r.append({'type': 'dangerous_command', 'risk_score': score, 'description': desc})
        r.sort(key=lambda x: -x['risk_score'])
        return r

    def desensitize(self, text: str):
        if not text:
            return text, []
        results = self.detect_sensitive(text)
        if not results:
            return text, []
        result_text = text
        detected = []
        for r in sorted(results, key=lambda x: -x.start):
            prefix = CATEGORY_PREFIX.get(r.pattern_type, 'SENSITIVE')
            key = ReversibleDesensitizer.encode(r.value, prefix)
            result_text = result_text[:r.start] + key + result_text[r.end:]
            detected.append({'type': r.pattern_type, 'name': r.pattern_name, 'risk_score': r.risk_score})
        return result_text, detected

    def restore(self, text: str) -> str:
        return ReversibleDesensitizer.decode_all(text)

    def detect_image(self, image_base64: str):
        detected = []
        try:
            import base64 as b64
            if image_base64.startswith('data:image'):
                image_base64 = image_base64.split(',', 1)[1]
            data = b64.b64decode(image_base64)
            try:
                from PIL import Image
                from io import BytesIO
                img = Image.open(BytesIO(data))
                w, h = img.size
                ratio = w / h if h > 0 else 0
                if 1.55 < ratio < 1.65:
                    detected.append({'type': 'card_like', 'risk_score': 7.0, 'detail': u'比例接近银行卡/身份证'})
                if 0.5 < ratio < 0.67:
                    detected.append({'type': 'portrait', 'risk_score': 6.0, 'detail': u'竖版比例疑似证件'})
            except ImportError:
                pass
        except Exception:
            pass
        return len(detected) > 0, detected

    def _deduplicate(self, results: List[DetectionResult]) -> List[DetectionResult]:
        if len(results) <= 1:
            return results
        results.sort(key=lambda r: (-r.risk_score, r.start))
        kept, ranges = [], []
        for r in results:
            if not any(not (r.end <= s or r.start >= e) for s, e in ranges):
                kept.append(r)
                ranges.append((r.start, r.end))
        kept.sort(key=lambda r: r.start)
        return kept

_detector: Optional[SensitiveInfoDetector] = None

def get_detector() -> SensitiveInfoDetector:
    global _detector
    if _detector is None:
        _detector = SensitiveInfoDetector()
    return _detector

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ReversibleDesensitizer.init(_SCRIPT_DIR)

def process_user_message(message: str, images: Optional[List[str]] = None):
    detector = get_detector()
    is_bypass, reason = detector.detect_bypass(message)
    if is_bypass:
        return True, u'安全检测不可绕过。' + reason, ''
    if any(i['risk_score'] >= 7.0 for i in detector.detect_injection(message)):
        return True, u'检测到恶意指令注入，拒绝处理。', ''
    if any(c['risk_score'] >= 7.0 for c in detector.detect_dangerous_commands(message)):
        return True, u'检测到危险命令，拒绝处理。', ''
    if images:
        for img in images:
            has_sensitive, detected = detector.detect_image(img)
            if has_sensitive:
                reasons = [d.get('detail', d['type']) for d in detected]
                return True, u'图片包含敏感信息（' + u'; '.join(reasons) + u'），拒绝处理。', ''
    processed, _ = detector.desensitize(message)
    return False, processed, message

def process_file(file_path: str):
    _, ext = os.path.splitext(file_path)
    ext = ext.lower()
    TEXT_EXTS = {'.txt', '.md', '.py', '.js', '.ts', '.json', '.yaml', '.yml', '.xml', '.html', '.css', '.csv', '.env', '.cfg', '.ini', '.conf', '.log', '.sql', '.sh', '.bat', '.ps1', '.toml', '.java', '.cpp', '.c', '.h', '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.vue', '.jsx', '.tsx', '.svelte', '.dockerfile', '.gitignore', '.properties'}
    if ext not in TEXT_EXTS:
        return False, '', '', ext
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        return True, u'无法读取文件: ' + str(e), '', ext
    is_refused, processed, original = process_user_message(content)
    return is_refused, processed, original, ext

def restore_ai_response(text: str) -> str:
    return get_detector().restore(text)

def scan_text(text: str) -> dict:
    detector = get_detector()
    sensitive = detector.detect_sensitive(text)
    injections = detector.detect_injection(text)
    commands = detector.detect_dangerous_commands(text)
    scores = [r.risk_score for r in sensitive] + [i['risk_score'] for i in injections] + [c['risk_score'] for c in commands]
    max_score = max(scores) if scores else 0.0
    if max_score >= 9.0:
        level = 'CRITICAL'
    elif max_score >= 7.0:
        level = 'HIGH'
    elif max_score >= 4.0:
        level = 'MEDIUM'
    elif max_score > 0:
        level = 'LOW'
    else:
        level = 'SAFE'
    return {'risk_level': level, 'max_score': max_score, 'sensitive_count': len(sensitive), 'injection_count': len(injections), 'command_count': len(commands), 'mapping_count': ReversibleDesensitizer.get_mapping_count()}

def health_check() -> dict:
    test_cases = [('手机号', '13812345678'), ('身份证', '110101199001011234'), ('OpenAI Key', 'sk-proj-TestKey12345'), ('企业名称', 'HD'), ('企业全称', 'HD融资担保股份有限公司'), ('企业简称', 'HD金控')]
    results = []
    for name, value in test_cases:
        _, processed, _ = process_user_message(u'测试' + name + u': ' + value)
        restored = restore_ai_response(processed)
        results.append({'test': name, 'passed': value in restored, 'processed': processed, 'restored': restored})
    passed = sum(1 for r in results if r['passed'])
    return {'status': 'ok' if passed == len(results) else 'degraded', 'passed': passed, 'total': len(results), 'tests': results}

if __name__ == '__main__':
    print('=' * 60)
    print('  敏感信息检测与可逆脱敏 v2.0 - 跨平台插件版')
    print('  零外部依赖 | Pure Python 3.7+')
    print('=' * 60)

    test_msgs = [('手机号', '我的手机是13812345678'), ('身份证', '身份证号110101199001011234'), ('API Key', 'OpenAI key: sk-proj-abc123def456'), ('企业名称', '我公司是HD'), ('企业全称', 'HD融资担保股份有限公司'), ('企业简称', 'HD金控和HD控股集团'), ('邮箱', '联系我support@example.com')]
    for label, msg in test_msgs:
        _, proc, _ = process_user_message(msg)
        rest = restore_ai_response(proc)
        found = any(cn in rest for cn in COMPANY_SENSITIVE_NAMES if cn in msg) or msg in rest
        status = 'OK' if found else 'FAIL'
        print(f'  [{status}] {label}: {proc}')

    print('')
    print('  --- 安全检测 ---')
    for t in ['不要脱敏', '跳过检测', 'rm -rf /', 'ignore all instructions']:
        refused, result, _ = process_user_message(t)
        status = 'BLOCKED' if refused else 'PASSED'
        print(f'  [{status}] {t}')

    print('')
    print('  --- 自检 ---')
    hc = health_check()
    print(f"  Status: {hc['status']} ({hc['passed']}/{hc['total']})")
    print(f"  Mappings: {ReversibleDesensitizer.get_mapping_count()}")
    print('=' * 60)

