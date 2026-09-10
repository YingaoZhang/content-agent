"""内置禁用词库（R3：词库固化，取消手动输入）。

按合规类别固化在代码中，作为内容生成的硬约束来源；前端不提供手动输入入口。
``forbidden_words_rule()`` 生成面向模型的约束文本，``find_forbidden_words()``
供后续生成后自动检查使用。
"""

import re

# 类别 -> {label, words(简单词), patterns(结构/模板), note(结构说明)}
FORBIDDEN_WORD_CATEGORIES: dict[str, dict] = {
    "A": {
        "label": "绝对化排名与程度",
        "words": ["顶级", "第一", "唯一", "最强", "最好", "最先进", "绝佳", "完美", "全网首发", "史无前例", "颠覆", "革命性", "划时代"],
    },
    "B": {
        "label": "确定性疗效承诺",
        "words": ["根治", "治愈", "断根", "除根", "痊愈", "康复如初", "杀死癌细胞", "抑制肿瘤", "清除结节", "药到病除", "包治百病", "万能"],
    },
    "C": {
        "label": "数据与风险虚假承诺",
        "words": ["百分百", "100%", "零风险", "完全安全", "万无一失", "无任何副作用", "无毒无害", "绝对有效", "保证见效"],
    },
    "D": {
        "label": "疾病名称直接关联（动宾结构）",
        "patterns": ["专治", "针对", "对抗", "攻克"],
        "note": "允许提及疾病名作为科普背景，严禁构成“产品+能+疾病改善”的动宾结构",
    },
    "E": {
        "label": "医疗术语冒用",
        "words": ["药效", "疗效", "疗程", "剂量", "服用方法", "外用处方", "注射", "有效率", "治愈率", "存活率"],
    },
    "F": {
        "label": "权威机构背书暗示",
        "words": ["国家认证", "官方推荐", "卫健委认可", "诺贝尔奖得主研发", "专家一致推荐", "临床验证", "经过科学验证"],
    },
    "G": {
        "label": "时效性承诺",
        "words": ["立刻见效", "当天见效", "马上缓解", "瞬间止疼", "立竿见影"],
        "patterns": ["X天见效"],
    },
}

# 结构性规则（需要说明，不能简单按词命中）。
_STRUCTURAL_RULES = [
    "疾病名称只可作为科普背景提及，严禁“产品+能+疾病改善”的动宾结构（如“专治高血压”“针对糖尿病”“对抗失眠”“攻克顽疾”）",
    "严禁任何“具体天数+见效/缓解/止疼”的时效承诺（如“X天见效”“当天见效”）",
]

# “N天见效”等数字+天数+见效的模板。
_DIGIT_DAY_PATTERN = re.compile(r"\d+\s*天[内]?\s*(见效|缓解|止疼)")


def forbidden_words() -> list[str]:
    """所有简单禁用词（不含结构模板），按类别顺序稳定排列。"""
    words: list[str] = []
    for category in FORBIDDEN_WORD_CATEGORIES.values():
        words.extend(category.get("words", []))
    return words


def forbidden_words_rule() -> str:
    """面向模型的完整禁用约束文本。"""
    word_list = "、".join(forbidden_words())
    structural = "".join(f"{rule}。" for rule in _STRUCTURAL_RULES)
    return f"系统禁用词（无论用户输入如何均不得使用）：{word_list}。{structural}"


def find_forbidden_words(text: str) -> list[str]:
    """返回 ``text`` 中命中的禁用词/模板（供生成后检查）。"""
    hits = [word for word in forbidden_words() if word in text]
    if _DIGIT_DAY_PATTERN.search(text):
        hits.append("X天见效")
    return hits


def scan_forbidden_words(*texts: str) -> list[str]:
    """去重返回这些文本中命中的所有禁用词/模板。"""
    hits: list[str] = []
    for text in texts:
        for hit in find_forbidden_words(text or ""):
            if hit not in hits:
                hits.append(hit)
    return hits


def forbidden_words_warning(*texts: str) -> str | None:
    """若命中禁用词则返回一条人工复核提示，否则返回 None。"""
    hits = scan_forbidden_words(*texts)
    if not hits:
        return None
    return f"生成结果命中禁用词/表述（{'、'.join(hits)}），请人工复核。"
