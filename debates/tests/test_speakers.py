import pytest

from debates.speakers import parse_label, strip_honorific


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Mr. Jo Smith", "Jo Smith"),
        ("Right Hon. Jo Smith", "Jo Smith"),
        ("Hon. Jo Smith", "Jo Smith"),
        ("Mme Jo Smith", "Jo Smith"),
        ("L'hon. Jo Smith", "Jo Smith"),
        ("Jo Smith", "Jo Smith"),  # 45th Parliament labels often drop Mr./Ms.
        ("  Ms.   Jo   Smith ", "Jo Smith"),
    ],
)
def test_strip_honorific(raw, expected):
    assert strip_honorific(raw) == expected


def test_member_with_riding_and_party():
    label = parse_label("Mr. Jo Smith (North—South Valley, CPC)", "2")
    assert (label.name, label.riding, label.party, label.role) == (
        "Jo Smith",
        "North—South Valley",
        "CPC",
        "",
    )
    assert label.is_full and not label.is_chair


def test_minister_role_with_nested_parentheses():
    label = parse_label("Hon. Jo Smith (Secretary of State (Sport), Lib.)", "5")
    assert label.name == "Jo Smith"
    assert label.role == "Secretary of State (Sport)"
    assert label.party == "Lib."
    assert label.riding == ""


def test_chair_with_named_occupant():
    label = parse_label("The Assistant Deputy Speaker (Mrs. Jo Smith)", "92")
    assert label.is_chair
    assert label.role == "The Assistant Deputy Speaker"
    assert label.name == "Jo Smith"
    assert label.party == ""


def test_chair_without_name():
    label = parse_label("The Deputy Speaker", "22")
    assert label.is_chair and label.name == "" and label.role == "The Deputy Speaker"


def test_short_label_has_no_party():
    label = parse_label("Jo Smith", "2")
    assert label.name == "Jo Smith" and not label.is_full


def test_trailing_colon_and_spaces_are_ignored():
    label = parse_label("Mr. Jo Smith (Westside, NDP) : ", "2")
    assert label.party == "NDP" and label.riding == "Westside"


def test_unknown_party_token_is_still_read():
    assert parse_label("Jo Smith (Westside, XYZ)", "2").party == "XYZ"


def test_comma_inside_role_without_party():
    label = parse_label("Hon. Jo Smith (Minister of Health, and of Sport)", "4")
    # "and of Sport" is not a party token, so the whole text stays the role
    assert label.party == ""
    assert label.role == "Minister of Health, and of Sport"
