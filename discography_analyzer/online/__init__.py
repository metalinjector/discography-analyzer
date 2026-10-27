"""Tags and covers from online catalogues for albums whose tags are incomplete.

The package is self-contained: :mod:`.http` talks to the services,
:mod:`.apple`, :mod:`.deezer`, :mod:`.musicbrainz` and :mod:`.discogs` turn
their answers into :class:`.release.Release` objects, :mod:`.album` reads the
local folders, :mod:`.matching` decides which release is the local album,
:mod:`.lookup` runs the search and :mod:`.tagging` fills only the tags that
are empty. :mod:`.panel` is the utility in the «Утилиты» window; nothing else
in the program depends on this package.
"""
