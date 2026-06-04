from comment import _find_existing_bumpkin_comment_id


def test_find_existing_bumpkin_comment_by_marker() -> None:
    comments = [
        {"id": 10, "body": "random comment"},
        {
            "id": 11,
            "body": "<!-- bumpkin:recommendation -->\n🤖 Bumpkin Recommendation\n...",
        },
    ]
    assert _find_existing_bumpkin_comment_id(comments) == 11


def test_find_existing_bumpkin_comment_by_legacy_title() -> None:
    comments = [
        {"id": 21, "body": "🤖 Bumpkin Recommendation\n\nRecommendation : 🟡 MINOR"},
    ]
    assert _find_existing_bumpkin_comment_id(comments) == 21


def test_find_existing_returns_latest_matching_comment() -> None:
    comments = [
        {"id": 31, "body": "🤖 Bumpkin Recommendation\nOld"},
        {"id": 32, "body": "normal"},
        {
            "id": 33,
            "body": "<!-- bumpkin:recommendation -->\n🤖 Bumpkin Recommendation\nNew",
        },
    ]
    assert _find_existing_bumpkin_comment_id(comments) == 33


def test_find_existing_returns_none_when_no_match() -> None:
    comments = [
        {"id": 41, "body": "hello"},
        {"id": 42, "body": "world"},
    ]
    assert _find_existing_bumpkin_comment_id(comments) is None
