from unittest.mock import patch

from backend import updater


class _Response:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


def test_release_api_detects_update_when_manifest_mirrors_are_stale():
    release = {
        "tag_name": "v5.5.34",
        "body": "release notes",
        "assets": [{
            "name": "VortexSetup.exe",
            "browser_download_url": "https://github.com/RheaIsCute/vortex/releases/download/v5.5.34/VortexSetup.exe",
        }],
    }
    stale = '{"version":"5.5.33","download_url":"https://example.invalid/VortexSetup.exe"}'

    with patch.object(updater.requests, "get", side_effect=[
        _Response(200, release),
        _Response(200, text=stale),
        _Response(200, text=stale),
    ]):
        with patch.object(updater, "APP_VERSION", "5.5.33"):
            found = updater.check_for_update()

    assert found["version"] == "5.5.34"
    assert found["url"].endswith("/v5.5.34/VortexSetup.exe")


def test_current_release_is_not_an_update():
    release = {
        "tag_name": "v5.5.34",
        "assets": [{
            "name": "VortexSetup.exe",
            "browser_download_url": "https://example.invalid/VortexSetup.exe",
        }],
    }
    with patch.object(updater.requests, "get", return_value=_Response(200, release)):
        with patch.object(updater, "APP_VERSION", "5.5.34"):
            assert updater.check_for_update() is None
