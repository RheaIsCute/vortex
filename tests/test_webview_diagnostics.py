import os

from webview_diagnostics import find_webview2_files, prepare_user_data_dir


def test_prepare_user_data_dir_writes_and_removes_probe(tmp_path):
    messages = []
    profile = tmp_path / "Vortex" / "WebView2"

    assert prepare_user_data_dir(str(profile), messages.append)
    assert profile.is_dir()
    assert list(profile.iterdir()) == []
    assert "writable: yes" in messages[-1]


def test_find_webview2_files_prefers_packaged_tree(tmp_path):
    webview = tmp_path / "webview" / "lib"
    native = webview / "runtimes" / "win-x64" / "native"
    native.mkdir(parents=True)
    for name in (
        "WebView2Loader.dll",
        "Microsoft.Web.WebView2.Core.dll",
        "Microsoft.Web.WebView2.WinForms.dll",
    ):
        target = native / name
        target.write_bytes(b"")

    found = find_webview2_files(str(tmp_path))
    assert all(value != "not found" for value in found.values())
    assert os.path.basename(found["WebView2Loader.dll"]) == "WebView2Loader.dll"
