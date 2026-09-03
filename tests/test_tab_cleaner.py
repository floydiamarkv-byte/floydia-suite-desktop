"""Tests de tab_cleaner.py: allowlist anti-symlink y skip de Service Worker."""
import os

import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("psutil")

from modules import tab_cleaner as tc  # noqa: E402

BITWARDEN = "nngceckbapebfimnlniiiahkandclblb"


def test_allowlist_realpath_closes_symlink_bypass(tmp_path):
    secret_dir = tmp_path / "Extensions" / BITWARDEN
    secret_dir.mkdir(parents=True)
    link = tmp_path / "cache_evil"
    os.symlink(secret_dir, link)
    assert tc.is_path_strictly_protected(str(link)) is True


def test_service_worker_not_protected_in_clean_profile(tmp_path):
    p = str(tmp_path / "Service Worker" / "CacheStorage" / "abc")
    assert tc.is_path_strictly_protected(p) is False


def test_profile_has_protected_extension():
    import tempfile
    td = tempfile.mkdtemp()
    assert tc.profile_has_protected_extension(td) is False
    os.makedirs(os.path.join(td, "Extensions", BITWARDEN), exist_ok=True)
    assert tc.profile_has_protected_extension(td) is True