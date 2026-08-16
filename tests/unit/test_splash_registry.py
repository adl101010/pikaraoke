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
