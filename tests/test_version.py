import re
import unittest
from pathlib import Path
from types import SimpleNamespace

import discography_analyzer
from discography_analyzer.audit_dialog import AuditFixDialog

PROJECT = Path(__file__).resolve().parents[1]


class VersionTests(unittest.TestCase):
    def test_package_version_matches_pyproject(self) -> None:
        # __init__ reads the installed metadata and falls back to the source
        # constant; a stale literal (1.7.0 next to 1.9.0) must not come back.
        # tomllib needs Python 3.11 and CI runs 3.10, so read the line itself.
        pyproject = (PROJECT / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
        self.assertIsNotNone(match)
        declared = match.group(1)
        self.assertEqual(discography_analyzer.__version__, declared)
        self.assertRegex(discography_analyzer.__version__, r"^\d+\.\d+\.\d+$")


class AuditDialogBackupTests(unittest.TestCase):
    def test_the_shared_backup_preference_is_shown_and_remembered(self) -> None:
        dialog = AuditFixDialog.__new__(AuditFixDialog)
        dialog.backup_enabled_var = SimpleNamespace(get=lambda: False)
        dialog.backup_button = SimpleNamespace(configure=lambda **kwargs: None)
        remembered: list[bool] = []
        dialog.on_backup_changed = remembered.append

        dialog._backup_state_changed()

        self.assertEqual(remembered, [False])


if __name__ == "__main__":
    unittest.main()
