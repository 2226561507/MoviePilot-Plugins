# 用户目录配置 2.0（V3）

适用于 MoviePilot 3.1.6 及以上的 V3 版本。V1/V2 实现保留在 `plugins.v2/userdownloadpath/`，本目录为独立的 V3 实现。

插件在资源下载事件提交下载器之前，按发起下载的用户设置独立的下载目录，并可按媒体类型和类别建立子目录。

## 配置

在插件配置页填写「用户路径配置」，每行一条：

```text
用户名=路径
用户名=路径:按类型分类:按类别分类
```

- 匹配顺序：先按用户名，再按用户 ID；用户名优先。
- 分类开关：`1` 启用，`0` 禁用；行内开关优先于插件顶部的默认开关。
- 路径需要是 MoviePilot 容器内实际存在的目录，并且位于「设定 - 目录」已配置的下载目录之内（根目录本身或其子目录）。V3 主程序会在下载提交前再次校验，未配置的外置路径会被主程序拒绝。
- Windows 路径可直接写 `C:\downloads\user`，末段只有 `0/1` 时才会被识别为分类开关。
- 用户已经指定自定义下载目录时，插件不会覆盖。

示例：

```text
admin=/downloads/admin
user1=/downloads/user1:1:1
user2=/downloads/user2:1:0
123=/downloads/userid123
```

## 与原 V2 实现的差异

- 改用 V3 稳定入口：`app.sdk.plugin`、`app.sdk.events`、`app.sdk.logging`；事件类型仍使用 `app.schemas.types.ChainEventType`。
- 版本号按发布门禁要求从 `1.1` 跃迁到 `2.0.0`，并登记到 `package.v3.json`。
- 强制实现 V3 生命周期契约：`get_api()` 返回空列表，`init_plugin()` 每次重复加载都重建状态，`stop_service()` 可安全重复调用。
- 保留原有的用户路径解析、用户名/ID 匹配、类型/类别子目录及不覆盖自定义路径等行为。
- 新增 Windows 盘符路径兼容（旧版使用 `:` 拆分会截断盘符）。
- 媒体类型兼容枚举与普通字符串，避免 V3 媒体模型差异导致路径构建失败。

## 验证

```sh
python -m compileall -q plugins.v3/userdownloadpath
python -m pytest -q tests/v3/userdownloadpath
python .github/scripts/check_plugin_versions.py package.v3.json
```
