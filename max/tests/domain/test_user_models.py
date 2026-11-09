from pymax.types.domain import User


def test_user_parses_bot_gender_int_and_web_app_url() -> None:
    """Bot accounts send ``gender`` as a numeric code and ``web_app`` as a URL
    string (observed for the "Алиса AI" bot); the profile must still parse."""
    payload = {
        "id": 6738397,
        "names": [{"name": "Алиса AI", "type": "NICK"}],
        "gender": 1,
        "webApp": "https://alice.yandex.ru/max_onboarding",
    }

    user = User.model_validate(payload)

    assert user.gender == 1
    assert user.web_app == "https://alice.yandex.ru/max_onboarding"


def test_user_parses_human_without_optional_fields() -> None:
    """Regular users come without ``gender`` and ``web_app``."""
    payload = {"id": 1, "names": [{"name": "Test User", "type": "NICK"}]}

    user = User.model_validate(payload)

    assert user.gender is None
    assert user.web_app is None


def test_user_still_accepts_dict_web_app() -> None:
    """The dict type for ``web_app`` is kept from the original PyMax schema
    (no real example of this format was seen, but we keep compatibility)."""
    user = User.model_validate({"id": 2, "webApp": {}})

    assert user.web_app == {}
