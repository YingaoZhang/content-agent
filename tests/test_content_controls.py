from app.schemas.content import Audience, ContentRequest
from app.channels.xiaohongshu import xiaohongshu_constraints
from app.workflow import writing_constraints


def test_content_controls_use_optional_lengths_and_system_forbidden_words():
    request = ContentRequest(
        topic="测试主题",
        primary_audience=Audience.CONSUMER,
        objective="验证内容控制",
        key_points="作用机制与使用边界",
    )

    article_rules = writing_constraints(request)
    note_rules = xiaohongshu_constraints(request)
    assert request.target_length is None
    assert request.caption_length is None
    assert "不设固定字数" in article_rules
    assert "不设固定字数" in note_rules
    assert "系统禁用词" in article_rules
    assert "顶级" in article_rules
    assert "夸大" not in article_rules
    assert "语气：亲切、易懂、避免术语堆砌" in article_rules
    assert "文章结构：场景-困扰-解决方式-行动" in article_rules
    assert "笔记语气：亲切、易懂、避免术语堆砌" in note_rules
    assert "内容结构：场景-困扰-解决方式-行动" in note_rules


def test_audience_controls_drive_tone_and_structure_in_rules():
    request = ContentRequest(
        topic="测试主题",
        primary_audience=Audience.RD_FORMULATOR,
        objective="验证画像绑定",
    )

    article_rules = writing_constraints(request)
    note_rules = xiaohongshu_constraints(request)
    assert "语气：严谨、专业、克制" in article_rules
    assert "文章结构：问题-机制-方案-实践" in article_rules
    assert "笔记语气：严谨、专业、克制" in note_rules
    assert "内容结构：问题-机制-方案-实践" in note_rules


def test_content_controls_accept_manual_target_lengths_and_key_points():
    request = ContentRequest(
        topic="测试主题",
        primary_audience=Audience.CONSUMER,
        objective="验证手动字数",
        key_points="机制和边界",
        target_length=3200,
        caption_length=420,
    )

    assert "约 3200 个中文字符" in writing_constraints(request)
    assert "约 420 个中文字符" in xiaohongshu_constraints(request)
    assert "机制和边界" in request.key_points
