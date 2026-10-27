"""Discography Analyzer."""

from importlib.metadata import PackageNotFoundError, version

try:  # Installed package or the PyInstaller bundle.
    __version__ = version("discography-analyzer")
except PackageNotFoundError:  # Running from a source checkout.
    __version__ = "1.15.0"

