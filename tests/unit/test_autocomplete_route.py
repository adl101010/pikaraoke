"""Tests for the library autocomplete endpoint.

This is the dropdown a guest sees while typing, and the only place the local
library surfaces during a search -- so a miss here sends them to YouTube to
download something we already have.
"""

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import werkzeug
from flask import Flask

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from pikaraoke.routes.search import search_bp

LIBRARY = [
    "/songs/Journey - Don't Stop Believin'---dQw4w9WgXcQ.mp4",
    "/songs/ABBA - Dancing Queen---aB3_x9-Zq1K.mp4",
    "/songs/AC-DC - Thunderstruck---cD5_y8-Wp2L.mp4",
    "/songs/Beyoncé - Halo---eF6_z7-Vq3M.mp4",
    "/songs/Hall & Oates - Maneater---gH7_a6-Ur4N.mp4",
    "/songs/Blink-182 - All The Small Things---iJ8_b5-Ts5O.mp4",
    "/songs/Ripped From CD.mp4",
]


@pytest.fixture
def client():
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(search_bp)
    app.extensions["babel"] = MagicMock()
    return app.test_client()


def _ask(client, query):
    k = MagicMock()
    k.song_manager.songs = LIBRARY
    k.song_manager.display_name_from_path.side_effect = lambda p, *a: p.split("/")[-1]
    with patch("pikaraoke.routes.search.get_karaoke_instance", return_value=k):
        response = client.get("/autocomplete", query_string={"q": query})
    assert response.status_code == 200
    return response.get_json()


class TestAutocompleteFindsSongs:
    @pytest.mark.parametrize(
        "query",
        [
            "dont stop believin",
            "Dont Stop",
            "don't stop",
            "DONT STOP",
            "believin",
            "journey",
            "  journey  ",
        ],
    )
    def test_finds_the_apostrophe_song(self, client, query):
        """The case that prompted all this: typed plainly, stored with punctuation."""
        paths = [item["path"] for item in _ask(client, query)]
        assert any("Believin" in path for path in paths)

    @pytest.mark.parametrize("query", ["beyonce", "Beyoncé", "halo"])
    def test_finds_across_accents(self, client, query):
        """The stored name carries the accent; the typed one usually will not."""
        paths = [item["path"] for item in _ask(client, query)]
        assert any("Halo" in path for path in paths)

    @pytest.mark.parametrize("query", ["hall and oates", "hall & oates", "maneater"])
    def test_finds_across_ampersands(self, client, query):
        paths = [item["path"] for item in _ask(client, query)]
        assert any("Maneater" in path for path in paths)

    @pytest.mark.parametrize("query", ["blink 182", "blink182", "blink-182"])
    def test_finds_across_hyphens(self, client, query):
        paths = [item["path"] for item in _ask(client, query)]
        assert any("Blink-182" in path for path in paths)

    @pytest.mark.parametrize("query", ["ac dc", "acdc", "ac-dc", "thunderstruck"])
    def test_finds_across_separators(self, client, query):
        paths = [item["path"] for item in _ask(client, query)]
        assert any("AC-DC" in path for path in paths)

    def test_returns_the_shape_the_dropdown_expects(self, client):
        results = _ask(client, "dancing queen")
        assert len(results) == 1
        assert set(results[0]) == {"path", "fileName", "type"}
        assert results[0]["type"] == "autocomplete"

    def test_finds_a_manually_added_song_with_no_id(self, client):
        paths = [item["path"] for item in _ask(client, "ripped from cd")]
        assert paths == ["/songs/Ripped From CD.mp4"]


class TestAutocompleteStaysQuiet:
    @pytest.mark.parametrize("query", ["zzzzz", "nonexistent song", "bohemian rhapsody"])
    def test_no_results_for_songs_we_lack(self, client, query):
        assert _ask(client, query) == []

    @pytest.mark.parametrize("query", ["!!!", "   ", "---", "()"])
    def test_a_contentless_query_returns_nothing(self, client, query):
        """It must not dump the whole library into the dropdown."""
        assert _ask(client, query) == []

    @pytest.mark.parametrize("query", ["dQw4w9WgXcQ", "aB3_x9-Zq1K", "dQw4w9"])
    def test_youtube_ids_are_not_searchable(self, client, query):
        """The ID is invisible in the UI, so matching it looks like a bug."""
        assert _ask(client, query) == []

    @pytest.mark.parametrize("query", ["mp4", ".mp4"])
    def test_the_extension_is_not_searchable(self, client, query):
        assert _ask(client, query) == []

    def test_songs_directory_still_matches(self, client):
        """Path components stay searchable, as they were before normalization."""
        assert len(_ask(client, "songs")) == len(LIBRARY)


class TestQueriesSurviveTheUrl:
    """Characters that break an unencoded query string still have to work."""

    @pytest.mark.parametrize(
        "query,expected_fragment",
        [
            ("hall & oates", "Maneater"),
            ("hall and oates", "Maneater"),
            ("ac-dc", "Thunderstruck"),
            ("ac/dc", "Thunderstruck"),
            ("blink-182", "Blink-182"),
        ],
    )
    def test_awkward_characters_match(self, client, query, expected_fragment):
        paths = [item["path"] for item in _ask(client, query)]
        assert any(expected_fragment in path for path in paths)

    @pytest.mark.parametrize("query", ["a&b", "a#b", "a+b", "a?b", "a=b", "a%b", "100%"])
    def test_url_metacharacters_are_handled(self, client, query):
        """These must come back cleanly rather than erroring or leaking params.

        Not asserting emptiness: a two-letter query legitimately matches plenty
        once punctuation is folded away. The contract here is only that the
        endpoint answers.
        """
        assert isinstance(_ask(client, query), list)


class TestTemplateKeepsTheServerAsTheMatcher:
    """Guards the client half of punctuation-insensitive search.

    Selectize scores options against the raw label, so it rated
    "dont stop believin" against "Don't Stop Believin'" as zero and hid the
    result the server had just found. Removing any of these three lines makes
    the server-side normalization invisible to guests, with no test failing
    anywhere else and nothing in the log to show for it.
    """

    @pytest.fixture
    def search_template(self):
        path = Path(__file__).resolve().parents[2] / "pikaraoke" / "templates" / "search.html"
        return path.read_text(encoding="utf-8")

    def test_a_custom_score_disables_client_side_filtering(self, search_template):
        assert re.search(r"score:\s*function", search_template)

    def test_the_query_is_url_encoded(self, search_template):
        """An unencoded "&" ends the query string and truncates the search."""
        assert re.search(r"autocomplete[^\n]*encodeURIComponent\(query\)", search_template)

    def test_stale_options_are_cleared_before_each_load(self, search_template):
        """With filtering off, old results would otherwise linger in the list."""
        assert "clearOptions()" in search_template
