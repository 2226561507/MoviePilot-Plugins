import importlib.util
import sys
from enum import Enum
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).parents[3]
PLUGIN = ROOT / "plugins.v3/userdownloadpath/__init__.py"


class FakeEventManager:
    def __init__(self):
        self.registered = []

    def register(self, event_type):
        self.registered.append(event_type)
        return lambda func: func


class FakeLogger:
    def __init__(self):
        self.infos = []
        self.warnings = []
        self.errors = []

    def info(self, message):
        self.infos.append(message)

    def warning(self, message):
        self.warnings.append(message)

    def error(self, message):
        self.errors.append(message)


@pytest.fixture
def runtime(monkeypatch):
    for name in ("app", "app.sdk", "app.schemas"):
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)

    events = FakeEventManager()
    logs = FakeLogger()
    monkeypatch.setitem(sys.modules, "app.sdk.plugin", SimpleNamespace(_PluginBase=type("Base", (), {})))
    monkeypatch.setitem(sys.modules, "app.sdk.events",
                        SimpleNamespace(Event=object, eventmanager=events))
    monkeypatch.setitem(sys.modules, "app.sdk.logging", SimpleNamespace(logger=logs))
    monkeypatch.setitem(sys.modules, "app.schemas.types",
                        SimpleNamespace(ChainEventType=SimpleNamespace(ResourceDownload="resource.download")))

    spec = importlib.util.spec_from_file_location("userdownloadpath_v3", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module, events, logs


class MediaType(Enum):
    MOVIE = "电影"


def download_event(options, media=None):
    return SimpleNamespace(event_data=SimpleNamespace(
        options=options,
        context=SimpleNamespace(media_info=media) if media is not None else None,
    ))


def test_parses_simple_extended_and_windows_paths(runtime):
    module, _, _ = runtime
    plugin = module.UserDownloadPath()
    plugin.init_plugin({"user_paths_text": "\n".join([
        "admin=/downloads/admin",
        "user1=/downloads/user1:1:1",
        "user2=/downloads/user2:1:0",
        r"win=C:\downloads\win:0:1",
        "123=/downloads/userid123",
    ])})

    assert plugin._user_paths["admin"] == {
        "path": "/downloads/admin",
        "enable_type_folder": True,
        "enable_category_folder": True,
    }
    assert plugin._user_paths["user1"]["enable_category_folder"] is True
    assert plugin._user_paths["user2"]["enable_category_folder"] is False
    assert plugin._user_paths["win"]["path"] == "C:\\downloads\\win"
    assert plugin._user_paths["win"]["enable_type_folder"] is False
    assert plugin._user_paths["win"]["enable_category_folder"] is True
    assert "123" in plugin._user_paths


def test_sets_user_download_path_with_categorized_folders(runtime, tmp_path):
    module, _, _ = runtime
    user_dir = tmp_path / "alice"
    user_dir.mkdir()
    plugin = module.UserDownloadPath()
    plugin.init_plugin({"enabled": True, "user_paths_text": f"alice={user_dir}:1:1"})

    media = SimpleNamespace(type=MediaType.MOVIE, category="动漫")
    event = download_event({"username": "alice", "userid": 7, "save_path": None}, media)
    assert plugin.intercept_download(event) is event

    assert event.event_data.options["save_path"] == str(user_dir / "电影" / "动漫")


def test_matches_user_id_and_accepts_plain_string_media_type(runtime, tmp_path):
    module, _, _ = runtime
    user_dir = tmp_path / "uid42"
    user_dir.mkdir()
    plugin = module.UserDownloadPath()
    plugin.init_plugin({"enabled": True, "user_paths_text": f"42={user_dir}:0:0"})

    event = download_event({"username": "someone", "userid": 42}, SimpleNamespace(type="电视剧", category="纪录片"))
    plugin.intercept_download(event)
    assert event.event_data.options["save_path"] == str(user_dir)


def test_explicit_save_path_is_not_overwritten(runtime, tmp_path):
    module, _, _ = runtime
    user_dir = tmp_path / "alice"
    user_dir.mkdir()
    plugin = module.UserDownloadPath()
    plugin.init_plugin({"enabled": True, "user_paths_text": f"alice={user_dir}"})

    event = download_event({"username": "alice", "save_path": "/custom/path"})
    plugin.intercept_download(event)
    assert event.event_data.options["save_path"] == "/custom/path"


def test_unknown_user_and_unusable_path_keep_default_download(runtime, tmp_path):
    module, _, logs = runtime
    user_dir = tmp_path / "alice"
    user_dir.mkdir()
    plugin = module.UserDownloadPath()
    plugin.init_plugin({"enabled": True, "user_paths_text": f"alice={user_dir}\nmissing={tmp_path / 'absent'}"})

    unknown = download_event({"username": "bob"})
    plugin.intercept_download(unknown)
    assert "save_path" not in unknown.event_data.options

    missing = download_event({"username": "missing"})
    plugin.intercept_download(missing)
    assert "save_path" not in missing.event_data.options
    assert any("missing" in message for message in logs.errors)


def test_v3_contract_registration_forms_and_reload(runtime, tmp_path):
    module, events, _ = runtime
    plugin = module.UserDownloadPath()

    assert events.registered == ["resource.download"]
    assert plugin.get_api() == []
    assert plugin.get_service() == []
    assert plugin.stop_service() is None

    form, defaults = plugin.get_form()
    assert form[0]["component"] == "VForm"
    assert set(defaults) == {
        "enabled", "enable_logging", "enable_type_folder",
        "enable_category_folder", "user_paths_text",
    }
    assert plugin.get_page()

    user_dir = tmp_path / "alice"
    user_dir.mkdir()
    plugin.init_plugin({"enabled": True, "user_paths_text": f"alice={user_dir}"})
    assert plugin.get_state() is True
    plugin.init_plugin({})
    assert plugin.get_state() is False
    assert plugin._user_paths == {}
