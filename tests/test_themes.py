from app.gzh_adapter import THEMES


def test_all_six_builtin_themes_are_available():
    assert THEMES == {
        "石墨极简风": "theme-graphite-minimal.md",
        "摸鱼绿": "theme-moyu-green.md",
        "红白色系": "theme-red-white.md",
        "留白禅意风": "theme-zen-whitespace.md",
        "摸鱼票据风": "theme-moyu-ticket.md",
        "橄榄手记": "theme-olive-journal.md",
    }
