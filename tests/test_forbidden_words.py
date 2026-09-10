from app.forbidden_words import (
    FORBIDDEN_WORD_CATEGORIES,
    find_forbidden_words,
    forbidden_words,
    forbidden_words_rule,
    forbidden_words_warning,
    scan_forbidden_words,
)


def test_all_seven_categories_are_present():
    assert set(FORBIDDEN_WORD_CATEGORIES) == {"A", "B", "C", "D", "E", "F", "G"}


def test_forbidden_words_cover_each_category():
    words = forbidden_words()
    for expected in ["顶级", "根治", "百分百", "100%", "药效", "国家认证", "立刻见效"]:
        assert expected in words


def test_rule_text_describes_words_and_structural_rules():
    rule = forbidden_words_rule()
    assert "系统禁用词" in rule
    assert "顶级" in rule
    assert "专治高血压" in rule
    assert "X天见效" in rule


def test_find_forbidden_words_detects_plain_and_digit_day_patterns():
    assert "根治" in find_forbidden_words("本产品可以根治失眠")
    assert "X天见效" in find_forbidden_words("使用后 3 天见效")
    assert "X天见效" in find_forbidden_words("7天内见效")
    assert find_forbidden_words("这是一段正常的科普内容") == []


def test_scan_forbidden_words_dedups_across_texts():
    hits = scan_forbidden_words("根治失眠", "还能根治焦虑", "顶级原料")
    assert hits == ["根治", "顶级"]


def test_forbidden_words_warning_only_when_hit():
    assert forbidden_words_warning("正常的科普介绍") is None
    warning = forbidden_words_warning("标题", "本产品可以根治失眠")
    assert warning is not None
    assert "根治" in warning
    assert "人工复核" in warning
