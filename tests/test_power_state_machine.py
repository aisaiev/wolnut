"""Drives cli.main() through UPS status sequences taken from a real outage."""

import logging

import pytest

from wolnut import cli
from wolnut.config import ClientConfig, NutConfig, WakeOnConfig, WolnutConfig

OL = {"ups.status": "OL", "battery.charge": "100"}
OB = {"ups.status": "OB", "battery.charge": "90"}
UPSC_FAILED = {}
TICK_SECONDS = 10


class EndOfSequence(Exception):
    pass


@pytest.fixture
def run(mocker, tmp_path, caplog):
    """Returns run(steps, restore_delay) -> send_wol mock.

    Each step is (ups_status, client_online); one step is one main-loop pass.
    """

    def _run(steps, restore_delay=0, timeout=600, force_wol=True):
        config = WolnutConfig(
            nut=NutConfig(ups="ups@localhost"),
            clients=[
                ClientConfig(
                    name="srv",
                    host="192.0.2.1",
                    mac="DE:AD:BE:EF:00:01",
                    force_wol=force_wol,
                )
            ],
            poll_interval=TICK_SECONDS,
            wake_on=WakeOnConfig(
                restore_delay_sec=restore_delay,
                min_battery_percent=30,
                client_timeout_sec=timeout,
                reattempt_delay=30,
            ),
            log_level="INFO",
            status_file=str(tmp_path / "state.json"),
        )
        mocker.patch.object(cli, "load_config", return_value=config)

        # main() reads the status once at startup before entering its loop.
        statuses = iter([OL] + [status for status, _ in steps])
        online = iter([online for _, online in steps])
        clock = {"now": 1_000_000.0}

        def next_online(_host):
            try:
                return next(online)
            except StopIteration:
                raise EndOfSequence

        def tick(_seconds):
            clock["now"] += TICK_SECONDS

        def next_status(_ups):
            try:
                return next(statuses)
            except StopIteration:
                raise EndOfSequence

        mocker.patch.object(cli, "get_ups_status", side_effect=next_status)
        mocker.patch.object(cli, "is_client_online", side_effect=next_online)
        mocker.patch.object(cli.time, "sleep", side_effect=tick)
        mocker.patch.object(cli.time, "time", side_effect=lambda: clock["now"])
        send_wol = mocker.patch.object(cli, "send_wol_packet", return_value=True)

        caplog.set_level(logging.INFO, logger="wolnut")
        with pytest.raises(EndOfSequence):
            cli.main("unused.yaml", str(tmp_path / "state.json"))
        return send_wol

    return _run


def test_upsc_failure_on_battery_is_not_power_restoration(run, caplog):
    send_wol = run(
        [(OB, False), (UPSC_FAILED, False), (UPSC_FAILED, False), (OB, False)]
    )

    send_wol.assert_not_called()
    assert "Power restored" not in caplog.text


def test_upsc_failure_while_online_is_not_power_loss_or_restoration(run, caplog):
    send_wol = run([(OL, False), (UPSC_FAILED, False), (OL, False)])

    send_wol.assert_not_called()
    assert "Power restored" not in caplog.text
    assert "switched to battery" not in caplog.text


def test_power_restored_during_upsc_failure_still_wakes_client(run):
    send_wol = run([(OB, False), (UPSC_FAILED, False), (OL, False)])

    send_wol.assert_called_once_with("DE:AD:BE:EF:00:01")


def test_power_lost_again_during_restore_delay_cancels_wake(run):
    send_wol = run(
        [(OB, False), (OL, False), (OB, False), (OB, False), (OB, False)],
        restore_delay=15,
    )

    send_wol.assert_not_called()


def test_restore_delay_restarts_after_repeated_power_loss(run):
    send_wol = run(
        [(OB, False), (OL, False), (OB, False), (OB, False), (OL, False)],
        restore_delay=15,
    )
    send_wol.assert_not_called()


def test_repeated_power_loss_remembers_client_was_online(run, caplog):
    send_wol = run(
        [(OB, True), (OL, False), (OB, False), (OL, False), (OL, False), (OL, False)],
        restore_delay=15,
        force_wol=False,
    )

    send_wol.assert_called_once()
    assert "was not online before power loss" not in caplog.text


def test_client_seen_online_in_earlier_event_does_not_time_out_later(run, caplog):
    run(
        [
            (OB, True),
            (OL, True),  # restoration completes; client recorded as up
            (OB, True),  # next outage starts with no plain OL pass in between
            (OL, False),  # WOL sent
            (OL, True),  # client is back
            (OL, True),
        ],
        timeout=5,
    )

    assert caplog.text.count("all clients are back online") == 2
    assert "failed to come back online" not in caplog.text
