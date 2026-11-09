from __future__ import annotations

import asyncio
from random import Random

import pytest

from pymax.telemetry.navigation import (
    NavigationPlanner,
    RouteProfile,
    Screen,
    ScreenTransition,
)
from pymax.telemetry.payloads import TelemetryPayloadBuilder
from pymax.telemetry.service import TelemetryService
from pymax.types.domain import Chat, Profile
from tests.conftest import FakeApp, chat_payload, profile_payload


class ControlledRng:
    def __init__(self) -> None:
        self.random_values: list[float] = []
        self.uniform_values: list[float] = []
        self.randint_values: list[int] = []

    def random(self) -> float:
        return self.random_values.pop(0)

    def uniform(self, left: float, right: float) -> float:
        if self.uniform_values:
            return self.uniform_values.pop(0)
        return left

    def randint(self, left: int, right: int) -> int:
        if self.randint_values:
            return self.randint_values.pop(0)
        return left

    def choice(self, items):
        return tuple(items)[0]


def test_route_profile_pause_and_navigation_planner_history() -> None:
    rng = ControlledRng()
    profile = RouteProfile(
        steps=1,
        min_pause=1,
        max_pause=2,
        long_pause_chance=0.5,
        min_long_pause=10,
        max_long_pause=20,
        back_chance=0.5,
    )
    rng.random_values = [0.4, 0.6]
    rng.uniform_values = [15, 1.5]

    assert profile.pause(rng) == 15
    assert profile.pause(rng) == 1.5

    planner = NavigationPlanner(Random(1))
    assert planner.current_screen == Screen.BACKGROUND
    next_screen = planner.next_screen(profile)
    assert next_screen in {Screen.CHATS, Screen.SETTINGS}
    assert planner.history
    planner.reset_to_background()
    assert planner.current_screen == Screen.BACKGROUND
    assert planner.history == []


def test_navigation_weighted_choice_falls_back_to_last_transition() -> None:
    rng = ControlledRng()
    rng.randint_values = [100]
    planner = NavigationPlanner(rng)

    assert (
        planner._weighted_choice(
            (
                ScreenTransition(screen=Screen.CHATS, weight=1),
                ScreenTransition(screen=Screen.SETTINGS, weight=1),
            )
        )
        == Screen.SETTINGS
    )


def test_telemetry_payload_builder_creates_real_event_payloads() -> None:
    builder = TelemetryPayloadBuilder(Random(1))

    login = builder.login(user_id=10, session_id=20)
    nav = builder.navigation(
        user_id=10,
        session_id=20,
        screen_from=int(Screen.BACKGROUND),
        screen_to=int(Screen.CHATS),
        prev_time=1,
        action_id=2,
        extra_params={"source_id": 3},
    )
    open_chat = builder.open_chat(10, 20)
    open_chats = builder.open_chats(10, 20)
    payload = builder.to_payload([login, nav, open_chat, open_chats])

    assert login.event == "login"
    assert nav.params["screen_to"] == int(Screen.CHATS)
    assert open_chat.event == "open_chat_to_render"
    assert open_chats.event == "open_chats_to_render"
    assert len(payload["events"]) == 4


@pytest.mark.asyncio
async def test_telemetry_service_start_stop_send_and_source_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FakeApp()
    app.me = Profile.model_validate(profile_payload(9))
    app.chats = [Chat.model_validate(chat_payload(100, "DIALOG"))]
    service = TelemetryService(app)

    async def fake_run():
        await asyncio.Event().wait()

    monkeypatch.setattr(service, "_run", fake_run)

    assert service._ready is True
    assert service._source_params(Screen.CHATS)["tab_config"] == 2
    assert service._source_params(Screen.CHAT) == {
        "source_type": 1,
        "source_id": 100,
    }

    await service._send_events([service._payloads.login(9, 7)])
    assert app.calls[-1].payload["events"][0]["event"] == "login"

    service.start()
    assert service._task is not None
    await service.stop()
    assert service._task is None


def test_telemetry_service_ready_and_user_id_guards() -> None:
    app = FakeApp()
    service = TelemetryService(app)

    assert service._ready is False
    with pytest.raises(RuntimeError, match="authenticated profile"):
        _ = service._user_id
