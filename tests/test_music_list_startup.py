"""起動時の更新確認 (アプリ本体と曲リスト) のテスト

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.makedirs(os.path.join(ROOT, "log"), exist_ok=True)

from src import startup_check  # noqa: E402
from src.music_list_fetch import MusicList  # noqa: E402
from src.startup_check import StartupUpdateCheck  # noqa: E402
from src.updater import ReleaseInfo  # noqa: E402


def _release(tag="991231.1") -> ReleaseInfo:
    return mock.Mock(spec=ReleaseInfo, tag=tag, notes="", size=0, page_url="https://example.com")


def _list(serial: int | None) -> MusicList:
    return MusicList([{"title": "a"}], serial, None, "https://example.com/x.json")


def _run(app_mode="notify", release=None, music_list=None, serial=5, frozen=True,
         skip_until_next=False, notified="", apply_result=(1, 1), answer=True):
    """確認結果がそろったときの動作を、ネットワークなしで確認する。"""
    config = SimpleNamespace(
        update_check_mode=app_mode, music_list_serial=serial, music_list_url="https://example.com/x.json",
        update_skip_until_next=skip_until_next, update_notified_tag=notified, save_config=mock.Mock(),
    )
    manager = mock.Mock()
    manager.apply_music_list.return_value = apply_result
    parent = mock.Mock()   # manager と updater の呼び出し順を見るための親
    parent.attach_mock(manager, "manager")
    updater, changed = mock.Mock(), mock.Mock()
    parent.attach_mock(updater, "updater")
    check = StartupUpdateCheck(None, config, manager, updater, changed)
    check._waiting = {"app", "music"}
    with mock.patch.object(startup_check, "confirm_update", return_value=answer) as confirm, \
            mock.patch.object(startup_check, "get_app_version", return_value="261001.0"), \
            mock.patch.object(startup_check, "is_frozen", return_value=frozen), \
            mock.patch.object(startup_check.QMessageBox, "warning") as warning:
        check._on_release(release, "" if release else "error")
        check._on_music_list(music_list, "" if music_list else "error")
    return SimpleNamespace(
        config=config, manager=manager, updater=updater, changed=changed, warning=warning, confirm=confirm,
        calls=parent.mock_calls,
    )


class MusicListTest(unittest.TestCase):
    def test_newer_list_is_applied_without_asking(self):
        r = _run(app_mode="off", music_list=_list(6))
        r.manager.apply_music_list.assert_called_once()
        r.confirm.assert_not_called()
        self.assertEqual(r.config.music_list_serial, 6)

    def test_same_or_older_serial_is_ignored(self):
        for serial in (5, 4, None):
            r = _run(music_list=_list(serial))
            r.manager.apply_music_list.assert_not_called()
            self.assertEqual(r.config.music_list_serial, 5)

    def test_fetch_error_is_silent(self):
        r = _run(music_list=None)
        r.manager.apply_music_list.assert_not_called()
        r.warning.assert_not_called()

    def test_apply_failure_keeps_serial_and_warns(self):
        failing = mock.Mock()
        failing.apply_music_list.side_effect = ValueError("bad")
        config = SimpleNamespace(music_list_serial=5, save_config=mock.Mock())
        self.assertIsNone(startup_check.apply_music_list_quietly(failing, config, _list(6)))
        self.assertEqual(config.music_list_serial, 5)
        with mock.patch.object(startup_check, "apply_music_list_quietly", return_value=None):
            r = _run(music_list=_list(6))
        r.warning.assert_called_once()

    def test_data_changed_called_only_when_relinked(self):
        r = _run(music_list=_list(6), apply_result=(1, 0))
        r.changed.assert_not_called()
        r = _run(music_list=_list(6), apply_result=(1, 2))
        r.changed.assert_called_once()

    def test_list_is_applied_even_if_app_update_is_declined(self):
        r = _run(release=_release(), music_list=_list(6), answer=False)
        r.manager.apply_music_list.assert_called_once()
        r.updater.apply_release.assert_not_called()


class AppUpdateTest(unittest.TestCase):
    def test_notify_asks_and_applies_on_yes(self):
        r = _run(release=_release())
        r.confirm.assert_called_once()
        r.updater.apply_release.assert_called_once()

    def test_notify_declined(self):
        r = _run(release=_release(), answer=False)
        r.updater.apply_release.assert_not_called()

    def test_auto_applies_without_asking(self):
        r = _run(app_mode="auto", release=_release())
        r.confirm.assert_not_called()
        r.updater.apply_release.assert_called_once()

    def test_auto_asks_instead_when_not_frozen(self):
        r = _run(app_mode="auto", release=_release(), frozen=False, answer=False)
        r.confirm.assert_called_once()
        r.updater.apply_release.assert_not_called()

    def test_old_version_is_ignored(self):
        r = _run(release=_release("261001.0"))
        r.confirm.assert_not_called()
        r.updater.apply_release.assert_not_called()

    def test_notified_version_is_skipped_when_configured(self):
        r = _run(release=_release("261100.0"), skip_until_next=True, notified="261100.0")
        r.confirm.assert_not_called()

    def test_notified_tag_is_recorded(self):
        r = _run(release=_release("261100.0"))
        self.assertEqual(r.config.update_notified_tag, "261100.0")

    def test_music_list_is_applied_before_app_update(self):
        r = _run(app_mode="auto", release=_release(), music_list=_list(6))
        names = [c[0] for c in r.calls]
        self.assertLess(names.index("manager.apply_music_list"), names.index("updater.apply_release"))

    def test_app_check_off_does_not_start_app_thread(self):
        config = SimpleNamespace(update_check_mode="off", music_list_url="u", music_list_serial=0)
        check = StartupUpdateCheck(None, config, mock.Mock(), mock.Mock())
        with mock.patch.object(startup_check, "CheckThread") as app_thread, \
                mock.patch.object(startup_check, "FetchThread") as music_thread:
            check.start()
        app_thread.assert_not_called()
        music_thread.assert_called_once()


if __name__ == "__main__":
    unittest.main()
