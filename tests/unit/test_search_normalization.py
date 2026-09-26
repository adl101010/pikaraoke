"""Tests for search text normalization and matching.

Guests search for what they can say, not what the filename happens to
contain -- "dont stop believin" has to find "Don't Stop Believin'". These
tests pin both halves of that: the folding is generous enough to catch the
way people actually type, and still tight enough not to match everything.
"""

import pytest

from pikaraoke.lib.metadata_parser import (
    normalize_for_search,
    search_matches,
    searchable_song_text,
)

# --------------------------------------------------------------------------
# normalize_for_search: exact output
# --------------------------------------------------------------------------

APOSTROPHE_CASES = [
    ("Don't Stop Believin'", "dont stop believin"),
    ("Don\u2019t Stop", "dont stop"),
    ("Don\u2018t Stop", "dont stop"),
    ("Don\u02bct Stop", "dont stop"),
    ("Don\u02bet Stop", "dont stop"),
    ("Don\u0060t Stop", "dont stop"),
    ("Don\u00b4t Stop", "dont stop"),
    ("Don\u2032t Stop", "dont stop"),
    ("Sin\u00e9ad O'Connor", "sinead oconnor"),
    ("Guns N' Roses", "guns n roses"),
    ("Livin' on a Prayer", "livin on a prayer"),
    ("It's My Life", "its my life"),
    ("'Til I Hear It From You", "til i hear it from you"),
    ("Rock'n'Roll", "rocknroll"),
    ("O'Sullivan's", "osullivans"),
]

ACCENT_CASES = [
    ("Beyonc\u00e9", "beyonce"),
    ("Caf\u00e9", "cafe"),
    ("M\u00f6tley Cr\u00fce", "motley crue"),
    ("na\u00efve", "naive"),
    ("Bj\u00f6rk", "bjork"),
    ("Sin\u00e9ad", "sinead"),
    ("\u00fcn\u00efc\u00f6d\u00e9", "unicode"),
    ("Celine Di\u00f3n", "celine dion"),
    ("e\u0301", "e"),
    ("\u00e9", "e"),
    ("A\u030a", "a"),
    ("Jos\u00e9 Gonz\u00e1lez", "jose gonzalez"),
]

AMPERSAND_CASES = [
    ("Hall & Oates", "hall and oates"),
    ("Simon & Garfunkel", "simon and garfunkel"),
    ("&", "and"),
    ("Tom&Jerry", "tom and jerry"),
    ("Salt-N-Pepa & Friends", "salt n pepa and friends"),
]

PUNCTUATION_CASES = [
    ("AC/DC", "ac dc"),
    ("R.E.M.", "r e m"),
    ("Blink-182", "blink 182"),
    ("Song (Karaoke Version)", "song karaoke version"),
    ("Song [Official Video]", "song official video"),
    ("Mr. Brightside", "mr brightside"),
    ("Wham!", "wham"),
    ("P!nk", "p nk"),
    ("Ke$ha", "ke ha"),
    ("+44", "44"),
    ("100%", "100"),
    ("C++", "c"),
    ("tears_for_fears", "tears for fears"),
    ("Song: The Sequel", "song the sequel"),
    ("Who?", "who"),
    ("Hey; You", "hey you"),
    ("Song, Reprise", "song reprise"),
    ("A|B", "a b"),
    ("<Song>", "song"),
    ("Song @ Home", "song home"),
    ("#1 Hit", "1 hit"),
    ("Song~Two", "song two"),
    ("Song=Two", "song two"),
    ("Song*Two", "song two"),
    ("\u00bd Time", "1 2 time"),
]

CASE_AND_SPACE_CASES = [
    ("BOHEMIAN RHAPSODY", "bohemian rhapsody"),
    ("bohemian rhapsody", "bohemian rhapsody"),
    ("BoHeMiAn", "bohemian"),
    ("  spaced   out  ", "spaced out"),
    ("x  --  y", "x y"),
    ("Song\tTabbed", "song tabbed"),
    ("Song\nNewline", "song newline"),
    ("Song\r\nCRLF", "song crlf"),
    ("   ", ""),
    ("\t\n", ""),
]

EMPTY_AND_NOISE_CASES = [
    ("", ""),
    ("!!!", ""),
    ("---", ""),
    ("()", ""),
    ("...", ""),
    ("\u0301", ""),
    ("\U0001F600 Party", "party"),
    ("\U0001F3A4\U0001F3B5", ""),
]

NON_LATIN_CASES = [
    ("\u65e5\u672c\u8a9e", "\u65e5\u672c\u8a9e"),
    ("\u65e5\u672c\u8a9e\u30ab\u30e9\u30aa\u30b1", "\u65e5\u672c\u8a9e\u30ab\u30e9\u30aa\u30b1"),
    ("\u041f\u0440\u0438\u043c\u0435\u0440", "\u043f\u0440\u0438\u043c\u0435\u0440"),
    ("\u0410\u0411\u0412", "\u0430\u0431\u0432"),
    ("\ud55c\uad6d\uc5b4", "\ud55c\uad6d\uc5b4"),
    ("\u0e44\u0e17\u0e22", "\u0e44\u0e17\u0e22"),
    # German sharp s has no NFKD decomposition, so it survives as itself.
    ("Stra\u00dfe", "stra\u00dfe"),
    # Ligatures do decompose, which is what makes them matchable.
    ("\ufb01re", "fire"),
]

NUMERIC_CASES = [
    ("99 Problems", "99 problems"),
    ("1999", "1999"),
    ("Blink 182", "blink 182"),
    ("4 Non Blondes", "4 non blondes"),
]


@pytest.mark.parametrize(
    "raw,expected",
    APOSTROPHE_CASES
    + ACCENT_CASES
    + AMPERSAND_CASES
    + PUNCTUATION_CASES
    + CASE_AND_SPACE_CASES
    + EMPTY_AND_NOISE_CASES
    + NON_LATIN_CASES
    + NUMERIC_CASES,
)
def test_normalize_for_search(raw, expected):
    assert normalize_for_search(raw) == expected


# --------------------------------------------------------------------------
# normalize_for_search: invariants that must hold for anything
# --------------------------------------------------------------------------

AWKWARD_INPUTS = [
    "",
    "   ",
    "a",
    "Don't Stop Believin'",
    "\u65e5\u672c\u8a9e",
    "\U0001F600",
    "\x00\x01\x02",
    "a" * 5000,
    "!@#$%^&*()",
    "Mixed \u00e9 \u65e5 \U0001F600 123",
    "\u200bzero width",
    "tab\tand\nnewline",
]


@pytest.mark.parametrize("raw", AWKWARD_INPUTS)
def test_normalization_is_idempotent(raw):
    """Normalizing twice must equal normalizing once."""
    once = normalize_for_search(raw)
    assert normalize_for_search(once) == once


@pytest.mark.parametrize("raw", AWKWARD_INPUTS)
def test_normalized_output_is_tidy(raw):
    """No leading, trailing, or doubled whitespace, ever."""
    result = normalize_for_search(raw)
    assert result == result.strip()
    assert "  " not in result


@pytest.mark.parametrize("raw", AWKWARD_INPUTS)
def test_normalization_never_raises(raw):
    assert isinstance(normalize_for_search(raw), str)


# --------------------------------------------------------------------------
# search_matches: queries that must find their song
# --------------------------------------------------------------------------

SHOULD_MATCH = [
    # The case that started this: typed plainly, stored with punctuation.
    ("dont stop believin", "Don't Stop Believin'"),
    ("Dont Stop Believin", "Don't Stop Believin'"),
    ("DONT STOP", "Don't Stop Believin'"),
    ("don't stop", "Dont Stop Believin"),
    ("don\u2019t stop", "Don't Stop Believin'"),
    ("believin", "Don't Stop Believin'"),
    ("stop believin", "Don't Stop Believin'"),
    # Apostrophes in either direction.
    ("its my life", "It's My Life"),
    ("it's my life", "Its My Life"),
    ("livin on a prayer", "Livin' On A Prayer"),
    ("guns n roses", "Guns N' Roses"),
    ("guns n' roses", "Guns N Roses"),
    ("osullivan", "O'Sullivan"),
    ("o'sullivan", "OSullivan"),
    # Accents either way.
    ("beyonce", "Beyonc\u00e9 - Halo"),
    ("beyonc\u00e9", "Beyonce - Halo"),
    ("motley crue", "M\u00f6tley Cr\u00fce - Kickstart"),
    ("m\u00f6tley", "Motley Crue"),
    ("cafe", "Caf\u00e9 Del Mar"),
    ("bjork", "Bj\u00f6rk - Army Of Me"),
    ("jose gonzalez", "Jos\u00e9 Gonz\u00e1lez"),
    # Ampersands.
    ("hall and oates", "Hall & Oates"),
    ("hall & oates", "Hall and Oates"),
    ("simon and garfunkel", "Simon & Garfunkel"),
    ("simon garfunkel", "Simon Garfunkel"),
    # Separators of every kind.
    ("ac dc", "AC/DC - Thunderstruck"),
    ("ac/dc", "AC DC - Thunderstruck"),
    ("acdc", "AC/DC - Thunderstruck"),
    ("rock n roll", "Rock-N-Roll"),
    ("rocknroll", "Rock N Roll"),
    ("rock-n-roll", "Rock N Roll"),
    ("blink 182", "Blink-182"),
    ("blink182", "Blink-182"),
    ("blink-182", "Blink 182"),
    ("rem", "R.E.M. - Losing My Religion"),
    ("r e m", "R.E.M."),
    ("salt n pepa", "Salt-N-Pepa"),
    ("mr brightside", "Mr. Brightside"),
    ("mr. brightside", "Mr Brightside"),
    # Case insensitivity.
    ("BOHEMIAN", "bohemian rhapsody"),
    ("bohemian", "BOHEMIAN RHAPSODY"),
    ("BoHeMiAn RhApSoDy", "Bohemian Rhapsody"),
    ("wonderwall", "WONDERWALL"),
    # Partial and interior matches, which autocomplete has always allowed.
    ("rhapsody", "Bohemian Rhapsody"),
    ("hemian", "Bohemian Rhapsody"),
    ("journey", "Journey - Don't Stop Believin'"),
    ("sweet caroline", "Neil Diamond - Sweet Caroline"),
    ("caroline", "Sweet Caroline (Karaoke Version)"),
    # Bracketed noise in the stored name shouldn't block a clean query.
    ("sweet caroline", "Sweet Caroline [Official Karaoke]"),
    ("karaoke version", "Song (Karaoke Version)"),
    ("dancing queen", "ABBA - Dancing Queen (Karaoke)"),
    # Whitespace sloppiness.
    ("  dancing   queen  ", "Dancing Queen"),
    ("dancing\tqueen", "Dancing Queen"),
    # Symbols in the stored name.
    ("pnk", "P!nk - Raise Your Glass"),
    ("p nk", "P!nk"),
    # A symbol standing in for a letter isn't decoded, so Ke$ha is reached by
    # the parts around it rather than by spelling it out.
    ("ke ha", "Ke$ha - Tik Tok"),
    ("keha", "Ke$ha - Tik Tok"),
    ("tik tok", "Ke$ha - Tik Tok"),
    ("wham", "Wham! - Last Christmas"),
    ("99 problems", "99 Problems"),
    ("4 non blondes", "4 Non Blondes"),
    # Non-Latin scripts.
    ("\u65e5\u672c\u8a9e", "\u65e5\u672c\u8a9e\u30ab\u30e9\u30aa\u30b1"),
    (
        "\u043f\u0440\u0438\u043c\u0435\u0440",
        "\u041f\u0440\u0438\u043c\u0435\u0440 \u041f\u0435\u0441\u043d\u0438",
    ),
    ("\u0410\u0411\u0412", "\u0430\u0431\u0432\u0433\u0434"),
    ("\ud55c\uad6d\uc5b4", "\ud55c\uad6d\uc5b4 \ub178\ub798"),
    # Full-path style haystacks, since that is what autocomplete passes.
    ("believin", "/songs/Journey - Don't Stop Believin'"),
    ("journey", "C:/songs/Journey - Dont Stop"),
    ("disney", "/songs/Disney/Let It Go"),
    ("let it go", "/songs/Disney/Let It Go"),
]


@pytest.mark.parametrize("query,haystack", SHOULD_MATCH)
def test_search_matches_finds_song(query, haystack):
    assert search_matches(query, haystack) is True


# --------------------------------------------------------------------------
# search_matches: queries that must NOT match
#
# The normalization is deliberately generous, so this half matters more --
# a search that matches everything is as useless as one that matches nothing.
# --------------------------------------------------------------------------

SHOULD_NOT_MATCH = [
    ("bohemian rhapsody", "Dancing Queen"),
    ("journey", "ABBA - Dancing Queen"),
    ("beatles", "Rolling Stones - Angie"),
    ("wonderwall", "Champagne Supernova"),
    ("dancing queen", "Dancing"),
    ("sweet caroline", "Sweet Child O' Mine"),
    ("zzzzz", "Bohemian Rhapsody"),
    ("purple rain", "Purple Haze"),
    # An empty or punctuation-only query must never match anything.
    ("", "Bohemian Rhapsody"),
    ("   ", "Bohemian Rhapsody"),
    ("!!!", "Bohemian Rhapsody"),
    ("---", "Bohemian Rhapsody"),
    ("()", "Bohemian Rhapsody"),
    ("\u0301", "Bohemian Rhapsody"),
    ("", ""),
    ("!!!", ""),
    # A query longer than the text can't be inside it.
    ("bohemian rhapsody by queen", "Bohemian Rhapsody"),
    ("dancing queen live at wembley", "Dancing Queen"),
    # Real song, wrong library.
    ("thunderstruck", "Highway To Hell"),
    ("halo", "Single Ladies"),
    # Accent folding must not make unrelated words collide.
    ("beyonce", "Bon Jovi"),
    ("cafe", "Coffee"),
    # Despacing must not become a wildcard.
    ("acdc", "Academic Decathlon"),
    ("xyz", "AC/DC"),
    # Numbers stay meaningful.
    ("182", "Blink 183"),
    ("1999", "1998"),
    ("99 bottles", "99 Problems"),
    # Non-Latin scripts don't cross-match.
    ("\u65e5\u672c\u8a9e", "\u041f\u0440\u0438\u043c\u0435\u0440"),
    ("\u043f\u0440\u0438\u043c\u0435\u0440", "\u65e5\u672c\u8a9e"),
    ("\ud55c\uad6d\uc5b4", "\u65e5\u672c\u8a9e"),
    # The sharp s does not fold to "ss", so document that rather than pretend.
    ("strasse", "Stra\u00dfe"),
    # Symbols used as letters are not decoded: "$" is not an "s" and "!" is
    # not an "i". Spelling the name out therefore misses, which is a known
    # limit rather than a bug -- deciding "$" means "s" would also have to
    # decide what digits mean, and digits carry meaning in song titles.
    ("kesha", "Ke$ha - Tik Tok"),
    ("pink", "P!nk - Raise Your Glass"),
    ("asap", "A$AP Rocky"),
]


@pytest.mark.parametrize("query,haystack", SHOULD_NOT_MATCH)
def test_search_does_not_match(query, haystack):
    assert search_matches(query, haystack) is False


@pytest.mark.parametrize("query", ["", "   ", "\t", "!!!", "()", "\u0301", "\U0001F600"])
def test_contentless_query_never_matches(query):
    """A query that normalizes to nothing must not return the whole library."""
    assert search_matches(query, "Any Song At All") is False


# --------------------------------------------------------------------------
# searchable_song_text: the YouTube ID must not be searchable
# --------------------------------------------------------------------------

SEARCHABLE_TEXT_CASES = [
    ("Song---dQw4w9WgXcQ.mp4", "Song"),
    ("/songs/Song---dQw4w9WgXcQ.mp4", "/songs/Song"),
    ("Song [dQw4w9WgXcQ].mp4", "Song"),
    ("Song [dQw4w9WgXcQ].mkv", "Song"),
    ("Journey - Dont Stop---dQw4w9WgXcQ.mp4", "Journey - Dont Stop"),
    ("C:/songs/A - B---aB3_x9-Zq1K.mp4", "C:/songs/A - B"),
    # No ID at all: just the extension comes off.
    ("Ripped From CD.mp4", "Ripped From CD"),
    ("/songs/Manual Add.mkv", "/songs/Manual Add"),
    ("No Extension", "No Extension"),
    # ID-shaped but wrong length, so not an ID.
    ("Song---short.mp4", "Song---short"),
    ("Song---toolongtobeanid.mp4", "Song---toolongtobeanid"),
    ("Song [short].mp4", "Song [short]"),
    # A trailing duplicate marker means the suffix no longer anchors the end.
    ("Song---dQw4w9WgXcQ (1).mp4", "Song---dQw4w9WgXcQ (1)"),
    # Other extensions used by the library.
    ("Song---dQw4w9WgXcQ.zip", "Song"),
    ("Song---dQw4w9WgXcQ.cdg", "Song"),
    ("Song---dQw4w9WgXcQ.webm", "Song"),
]


@pytest.mark.parametrize("path,expected", SEARCHABLE_TEXT_CASES)
def test_searchable_song_text(path, expected):
    assert searchable_song_text(path) == expected


ID_QUERIES_THAT_MUST_MISS = [
    "dQw4w9WgXcQ",
    "dqw4w9wgxcq",
    "dQw4w9",
    "w9WgXcQ",
    "aB3_x9-Zq1K",
]


@pytest.mark.parametrize("query", ID_QUERIES_THAT_MUST_MISS)
def test_youtube_id_is_not_searchable(query):
    """Searching an ID fragment shouldn't surface a song by its ID.

    The ID is invisible in the UI, so a hit on it looks like a bug to whoever
    typed it.
    """
    path = "Bohemian Rhapsody---dQw4w9WgXcQ.mp4"
    assert search_matches(query, searchable_song_text(path)) is False


@pytest.mark.parametrize(
    "query",
    ["bohemian", "rhapsody", "bohemian rhapsody", "BOHEMIAN", "hemian"],
)
def test_title_still_matches_after_id_removal(query):
    """Stripping the ID must not cost us the real title match."""
    path = "Bohemian Rhapsody---dQw4w9WgXcQ.mp4"
    assert search_matches(query, searchable_song_text(path)) is True


@pytest.mark.parametrize("extension", [".mp4", ".mkv", ".webm", ".zip", ".cdg", ".avi"])
def test_extension_is_not_searchable(extension):
    """Typing a container name shouldn't return the entire library."""
    path = f"Bohemian Rhapsody---dQw4w9WgXcQ{extension}"
    assert search_matches(extension.lstrip("."), searchable_song_text(path)) is False
