"""Unit tests for SplashRegistry (splash screen master election)."""

import pytest

from pikaraoke.lib.splash_registry import MASTER_STALE_SECONDS, SplashRegistry


@pytest.fixture
def registry():
    return SplashRegistry(stale_after=30.0)


class TestElection:
    def test_first_screen_becomes_master(self, registry):
        assert registry.register("tv1", now=0) == "master"
        assert registry.master == "tv1"

    def test_second_screen_becomes_slave(self, registry):
        registry.register("tv1", now=0)
        assert registry.register("tv2", now=1) == "slave"
        assert registry.master == "tv1"

    def test_a_live_master_keeps_the_role(self, registry):
        registry.register("tv1", now=0)
        registry.touch("tv1", now=100)
        assert registry.register("tv2", now=101) == "slave"
        assert registry.master == "tv1"

    def test_registering_twice_is_idempotent(self, registry):
        assert registry.register("tv1", now=0) == "master"
        assert registry.register("tv1", now=1) == "master"
        assert registry.connections == {"tv1"}


class TestZombieMaster:
    """The bug this exists for: a screen that vanished without a clean close
    isn't reaped for ~45s, and until then new screens were all made slaves."""

    def test_a_silent_master_is_replaced_by_a_new_screen(self, registry):
        registry.register("dead-tv", now=0)

        # Long enough that it can't still be there.
        assert registry.register("tv2", now=31) == "master"
        assert registry.master == "tv2"

    def test_takeover_waits_out_a_brief_hiccup(self, registry):
        """A short blip must not cost the role -- handover mid-song is worse."""
        registry.register("tv1", now=0)

        assert registry.register("tv2", now=29) == "slave"
        assert registry.master == "tv1"

    def test_activity_refreshes_the_master(self, registry):
        registry.register("tv1", now=0)
        registry.touch("tv1", now=25)  # position report keeps it alive

        assert registry.register("tv2", now=50) == "slave"
        assert registry.master == "tv1"

    def test_touch_ignores_unknown_screens(self, registry):
        registry.touch("never-registered", now=5)
        assert registry.connections == set()


class TestDisconnect:
    def test_removing_a_slave_leaves_the_master_alone(self, registry):
        registry.register("tv1", now=0)
        registry.register("tv2", now=1)

        assert registry.remove("tv2", now=2) is None
        assert registry.master == "tv1"

    def test_removing_the_master_promotes_a_survivor(self, registry):
        registry.register("tv1", now=0)
        registry.register("tv2", now=1)

        assert registry.remove("tv1", now=2) == "tv2"
        assert registry.master == "tv2"

    def test_promotes_the_most_recently_heard_from(self, registry):
        registry.register("tv1", now=0)
        registry.register("quiet", now=1)
        registry.register("chatty", now=2)
        registry.touch("chatty", now=10)

        assert registry.remove("tv1", now=11) == "chatty"

    def test_last_screen_leaving_clears_the_master(self, registry):
        registry.register("tv1", now=0)

        assert registry.remove("tv1", now=1) is None
        assert registry.master is None
        assert registry.connections == set()

    def test_removing_an_unknown_screen_is_harmless(self, registry):
        registry.register("tv1", now=0)
        assert registry.remove("ghost", now=1) is None
        assert registry.master == "tv1"

    def test_a_fresh_screen_after_everyone_left_is_master(self, registry):
        registry.register("tv1", now=0)
        registry.remove("tv1", now=1)
        assert registry.register("tv2", now=2) == "master"


class TestIsMaster:
    def test_only_the_master_reports(self, registry):
        registry.register("tv1", now=0)
        registry.register("tv2", now=1)

        assert registry.is_master("tv1") is True
        assert registry.is_master("tv2") is False

    def test_unknown_screens_are_not_master(self, registry):
        registry.register("tv1", now=0)
        assert registry.is_master("stale-tab") is False

    def test_nothing_is_master_when_empty(self, registry):
        assert registry.is_master("anything") is False


def test_default_stale_window_is_generous():
    """Short windows would demote a healthy master on a network blip."""
    assert MASTER_STALE_SECONDS >= 30.0
    assert SplashRegistry().register("tv1") == "master"


class TestPinnedMaster:
    """An admin can pin a device so it reclaims the role across reconnects."""

    def test_pinned_device_takes_over_on_register(self, registry):
        registry.register("tv1", device_id="dev-tv1", now=0)
        registry.pin_device("dev-tv2")

        assert registry.register("tv2", device_id="dev-tv2", now=1) == "master"
        assert registry.master == "tv2"

    def test_pinned_device_wins_even_against_a_healthy_master(self, registry):
        registry.register("tv1", device_id="dev-tv1", now=0)
        registry.touch("tv1", now=10)
        registry.pin_device("dev-tv2")

        assert registry.register("tv2", device_id="dev-tv2", now=11) == "master"

    def test_pinned_device_reclaims_after_a_reconnect(self, registry):
        """The reconnect-as-slave-against-its-own-corpse case."""
        registry.register("old-sid", device_id="dev-tv1", now=0)
        registry.pin_device("dev-tv1")

        # Same TV returns on a new socket while the old one hasn't been reaped.
        assert registry.register("new-sid", device_id="dev-tv1", now=5) == "master"
        assert registry.master == "new-sid"

    def test_pinning_a_connected_device_promotes_it_immediately(self, registry):
        registry.register("tv1", device_id="dev-tv1", now=0)
        registry.register("tv2", device_id="dev-tv2", now=1)

        assert registry.pin_device("dev-tv2") == "tv2"
        assert registry.master == "tv2"

    def test_pinning_an_absent_device_waits_for_it(self, registry):
        registry.register("tv1", device_id="dev-tv1", now=0)

        assert registry.pin_device("dev-tv-elsewhere") is None
        assert registry.master == "tv1"  # unchanged until it shows up

    def test_pin_survives_the_pinned_screen_disconnecting(self, registry):
        registry.register("tv1", device_id="dev-tv1", now=0)
        registry.register("tv2", device_id="dev-tv2", now=1)
        registry.pin_device("dev-tv1")

        registry.remove("tv1", now=2)
        assert registry.master == "tv2"  # someone must lead meanwhile

        # ...and the pinned screen takes it back when it returns.
        assert registry.register("tv1-again", device_id="dev-tv1", now=3) == "master"

    def test_pinned_device_outranks_recency_on_promotion(self, registry):
        registry.register("tv1", device_id="dev-tv1", now=0)
        registry.register("pinned", device_id="dev-pinned", now=1)
        registry.register("chatty", device_id="dev-chatty", now=2)
        registry.touch("chatty", now=10)
        registry.pin_device("dev-pinned")
        registry._master = "tv1"  # pretend tv1 still leads

        assert registry.remove("tv1", now=11) == "pinned"

    def test_clearing_the_pin_returns_to_normal_election(self, registry):
        registry.register("tv1", device_id="dev-tv1", now=0)
        registry.pin_device("dev-tv1")
        registry.pin_device("")

        assert registry.pinned_device == ""
        assert registry.register("tv2", device_id="dev-tv2", now=1) == "slave"


class TestStaleMasterWatchdog:
    """Demotes a quiet master, but only when someone can actually replace it."""

    def test_promotes_a_survivor_when_the_master_goes_quiet(self, registry):
        registry.register("tv1", device_id="a", now=0)
        registry.register("tv2", device_id="b", now=1)

        assert registry.demote_stale_master(now=40) == "tv2"
        assert registry.master == "tv2"

    def test_does_nothing_for_a_lone_screen(self, registry):
        """Stripping the only screen of the role would leave nobody to end songs."""
        registry.register("tv1", device_id="a", now=0)

        assert registry.demote_stale_master(now=999) is None
        assert registry.master == "tv1"

    def test_does_nothing_while_the_master_is_healthy(self, registry):
        registry.register("tv1", device_id="a", now=0)
        registry.register("tv2", device_id="b", now=1)
        registry.touch("tv1", now=39)

        assert registry.demote_stale_master(now=40) is None
        assert registry.master == "tv1"

    def test_does_nothing_when_there_is_no_master(self, registry):
        assert registry.demote_stale_master(now=100) is None


class TestScreens:
    def test_reports_identity_for_the_admin_page(self, registry):
        registry.register("tv1", device_id="dev-1", ip_address="10.0.0.5", now=0)

        screen = registry.screens()[0]
        assert screen.sid == "tv1"
        assert screen.device_id == "dev-1"
        assert screen.ip_address == "10.0.0.5"

    def test_ordered_by_connection_time(self, registry):
        registry.register("second", now=5)
        registry.register("first", now=1)

        assert [s.sid for s in registry.screens()] == ["first", "second"]


class TestNoPinBehavesLikeBefore:
    """The default path must be identical to pre-pin behaviour."""

    def test_first_screen_leads_and_others_follow(self, registry):
        assert registry.register("tv1", device_id="a", now=0) == "master"
        assert registry.register("tv2", device_id="b", now=1) == "slave"
        assert registry.register("tv3", device_id="c", now=2) == "slave"
        assert registry.pinned_device == ""

    def test_single_screen_reconnect_is_unaffected_without_a_pin(self, registry):
        registry.register("old", device_id="a", now=0)
        # No pin: the returning socket still waits out the stale window.
        assert registry.register("new", device_id="a", now=5) == "slave"
