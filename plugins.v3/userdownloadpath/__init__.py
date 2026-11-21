"""MoviePilot V3 plugin: per-user download directories."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.types import ChainEventType
from app.sdk.events import Event, eventmanager
from app.sdk.logging import logger
from app.sdk.plugin import _PluginBase


class UserDownloadPath(_PluginBase):
    """Route downloads to a directory configured for the requesting user."""

    plugin_name = "用户目录配置"
    plugin_desc = "为不同用户设置不同的下载目录"
    plugin_icon = "https://raw.githubusercontent.com/DzAvril/MoviePilot-Plugins/main/icons/userdownloadpath.png"
    plugin_version = "2.0.0"
    plugin_author = "DzAvril"
    author_url = "https://github.com/DzAvril"
    plugin_config_prefix = "userdownloadpath"
    plugin_order = 1
    auth_level = 1

    _enabled = False
    _enable_logging = False
    _enable_type_folder = True
    _enable_category_folder = True
    _user_paths: Dict[str, Dict[str, Any]] = {}

    def init_plugin(self, config: Optional[dict] = None) -> None:
        """Reload all state on every call; V3 may re-instantiate on hot reload."""
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._enable_logging = bool(config.get("enable_logging", False))
        self._enable_type_folder = bool(config.get("enable_type_folder", True))
        self._enable_category_folder = bool(config.get("enable_category_folder", True))
        self._user_paths = self._parse_user_paths(config.get("user_paths_text", ""))
        if self._enabled:
            self._validate_config()

    def get_state(self) -> bool:
        return self._enabled

    def _log(self, message: str) -> None:
        if self._enable_logging:
            logger.info(f"[用户目录配置] {message}")

    def _parse_user_paths(self, user_paths_text: str) -> Dict[str, Dict[str, Any]]:
        """Parse ``user=path[:type_folder:category_folder]`` lines.

        Flags are read from the right so Windows drive letters keep their colon.
        """
        user_paths: Dict[str, Dict[str, Any]] = {}
        for line in (user_paths_text or "").strip().splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            user, _, config_part = line.partition("=")
            user, config_part = user.strip(), config_part.strip()
            if not user or not config_part:
                continue

            parts = [part.strip() for part in config_part.split(":")]
            path = config_part
            enable_type = self._enable_type_folder
            enable_category = self._enable_category_folder
            if (len(parts) >= 3 and parts[-1] in ("0", "1") and parts[-2] in ("0", "1")):
                enable_type, enable_category = bool(int(parts[-2])), bool(int(parts[-1]))
                path = ":".join(parts[:-2]).strip()
            elif len(parts) >= 2 and parts[-1] in ("0", "1"):
                enable_type = bool(int(parts[-1]))
                path = ":".join(parts[:-1]).strip()
            if not path:
                continue

            user_paths[user] = {
                "path": path,
                "enable_type_folder": enable_type,
                "enable_category_folder": enable_category,
            }
            self._log(f"配置用户路径: {user} -> {path} "
                      f"(按类型分类:{enable_type}, 按类别分类:{enable_category})")
        return user_paths

    @staticmethod
    def _path_is_usable(path: Any) -> bool:
        try:
            candidate = Path(str(path))
            return candidate.exists() and candidate.is_dir()
        except (OSError, TypeError, ValueError):
            return False

    def _validate_config(self) -> None:
        for username, config in self._user_paths.items():
            if not self._path_is_usable(config["path"]):
                logger.warning(f"[用户目录配置] 用户 {username} 的下载路径不存在或不是目录: {config['path']}")

    @staticmethod
    def _media_part(value: Any) -> str:
        if value is None:
            return ""
        raw = getattr(value, "value", value)
        return str(raw).strip() if raw is not None else ""

    def _build_categorized_path(self, base_path: str, media_info: Any,
                                enable_type_folder: bool,
                                enable_category_folder: bool) -> str:
        """Append media type and category folders using the user's own flags."""
        if not media_info:
            return base_path
        try:
            target = Path(base_path)
            if enable_type_folder:
                media_type = self._media_part(getattr(media_info, "type", None))
                if media_type:
                    target = target / media_type
            if enable_category_folder:
                category = self._media_part(getattr(media_info, "category", None))
                if category:
                    target = target / category
            return str(target)
        except (OSError, TypeError, ValueError) as error:
            logger.warning(f"[用户目录配置] 构建分类路径失败，使用原路径: {error}")
            return base_path

    def _get_user_config(self, username: Any, userid: Any) -> Optional[Dict[str, Any]]:
        if username and str(username) in self._user_paths:
            config = self._user_paths[str(username)]
            self._log(f"通过用户名匹配到配置: {username} -> {config}")
            return config
        if userid and str(userid) in self._user_paths:
            config = self._user_paths[str(userid)]
            self._log(f"通过用户ID匹配到配置: {userid} -> {config}")
            return config
        return None

    @eventmanager.register(ChainEventType.ResourceDownload)
    def intercept_download(self, event: Event) -> Event:
        """Set ``options.save_path`` before the downloader submission."""
        if not self._enabled or not event or not event.event_data:
            return event
        data = event.event_data
        options = getattr(data, "options", None)
        if options is None:
            options = {}
            data.options = options
        if not isinstance(options, dict):
            return event

        current_save_path = options.get("save_path")
        username, userid = options.get("username"), options.get("userid")
        self._log(f"拦截下载请求 - 用户: {username}, ID: {userid}, 当前路径: {current_save_path}")
        if current_save_path:
            self._log(f"已有自定义路径，跳过处理: {current_save_path}")
            return event

        user_config = self._get_user_config(username, userid)
        if not user_config:
            self._log("未找到用户专用路径，使用系统默认路径")
            return event

        base_path = user_config["path"]
        if not self._path_is_usable(base_path):
            logger.error(f"[用户目录配置] 用户 {username or userid} 的路径不存在或不是目录: {base_path}")
            return event

        context = getattr(data, "context", None)
        media_info = getattr(context, "media_info", None) if context else None
        final_path = self._build_categorized_path(
            base_path, media_info,
            user_config["enable_type_folder"], user_config["enable_category_folder"],
        )
        options["save_path"] = final_path
        self._log(f"设置用户专用路径: {base_path} -> {final_path}")
        return event

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VSwitch", "props": {"model": "enabled", "label": "启用插件"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VSwitch", "props": {"model": "enable_logging", "label": "启用详细日志"}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VSwitch", "props": {"model": "enable_type_folder", "label": "按类型分类"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VSwitch", "props": {"model": "enable_category_folder", "label": "按类别分类"}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VTextarea", "props": {
                                    "model": "user_paths_text",
                                    "label": "用户路径配置",
                                    "placeholder": "用户名=路径 或 用户名=路径:按类型分类:按类别分类\n"
                                                   "admin=/downloads/admin\n"
                                                   "user1=/downloads/user1:1:1\n"
                                                   "user2=/downloads/user2:1:0\n"
                                                   "user3=/downloads/user3:0:0\n"
                                                   "123=/downloads/userid123",
                                    "rows": 10,
                                    "hint": "用户名优先于用户ID；Windows 路径可直接写 C:\\downloads\\user",
                                    "persistentHint": True,
                                }}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VAlert", "props": {
                                    "type": "info", "variant": "tonal",
                                    "text": "使用说明：\n"
                                            "1. 插件拦截资源下载事件，按用户身份设置下载目录\n"
                                            "2. 优先匹配用户名，其次匹配用户ID\n"
                                            "3. 扩展格式中 1 表示启用、0 表示禁用对应分类子目录\n"
                                            "4. 用户专属开关优先于插件默认开关\n"
                                            "5. 用户已指定下载目录时不覆盖\n"
                                            "6. V3 要求目录位于「设定-目录」已配置的下载目录内，且路径实际存在且可写",
                                }}]},
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "enable_logging": False,
            "enable_type_folder": True,
            "enable_category_folder": True,
            "user_paths_text": "",
        }

    def get_page(self) -> Optional[List[dict]]:
        return [{"component": "VAlert", "props": {
            "type": "info", "variant": "tonal",
            "text": "按用户名或用户ID分配下载目录；在插件配置中维护用户路径映射。",
        }}]

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        return []

    def stop_service(self) -> None:
        return None
