# 🎵 olivia-autoplay

[中文](#中文) | [English](#english)

---

<a id="中文"></a>
## 中文

**Olivia 自动连播增强插件** —— 为 Steam 上的节奏音乐游戏《Olivia》注入一个浮动面板，实现全曲库自动连播、队列管理、手动切歌跟随等功能。

> ⚠️ **本项目为逆向研究 / 个人学习产物，与游戏官方无关。** 请勿将本仓库或其产物用于任何商业用途。

### 功能特性

- **自动连播** —— 全曲库顺序 / 随机 / 单曲循环三种模式，歌曲自然播完自动切下一首
- **手动切歌跟随** —— 在游戏内手动切歌时，插件队列与列表高亮自动跟随到当前曲目（不在队列中的歌会自动加入）
- **浮动控制面板** —— 实时显示当前曲目、队列进度、播放模式；可折叠；快捷键 `Ctrl+Alt+O` 显示/隐藏
- **完整曲目列表** —— 可滚动队列列表，点击任意一首即播，当前曲目高亮并自动滚动到可见
- **曲库动态补扫** —— 自动发现懒加载的歌单（独奏 / 弹唱 / 伴奏），数据到达后自动建队
- **零侵入设计** —— 不修改游戏任何官方逻辑，只读官方状态、只调官方 API，全部异常兜底

### 工作原理

游戏前端（`feapp.dat`）是一个 ZIP 打包的 Vue 单页应用。本工具：

1. 从原始 `feapp.dat` 备份重建补丁包，把 `src/autoplay.js` 注入为 `assets/autoplay.js`，并在 `index.html` 中插入脚本引用
2. 注入脚本随游戏启动自动加载，通过 Pinia store 只读取曲库与播放状态、通过官方 `cefViewQuery` 桥接下发播放指令

### 安装

**前置要求**：Python 3.8+，Steam 版 Olivia（脚本默认按 Steam 路径定位，可通过环境变量 `OLIVIA_APP_DIR` 覆盖）。

```bash
git clone https://github.com/vega0707/olivia-autoplay.git
cd olivia-autoplay/tools

# 1. 查看状态（首次运行会自动生成原始备份）
python olivia_patch.py status

# 2. 构建补丁包（自动收集本地缓存曲目清单）
python olivia_patch.py build

# 3. 安装（需先完全关闭 Olivia，会自动备份当前现场）
python olivia_patch.py install

# 回滚
python olivia_patch.py restore
```

自定义游戏目录：

```bash
set OLIVIA_APP_DIR=C:\你的\Olivia\安装目录
python olivia_patch.py build && python olivia_patch.py install
```

### 使用

1. 启动游戏，窗口内会出现「♪ 自动连播」浮动面板
2. 等面板显示队列曲目数（曲库懒加载，通常几秒内就绪）
3. 点击「**开始连播**」—— 插件**不会**自动开播，一切等你确认
4. 面板按钮：开始/停止、下一首；下拉框切换曲目范围与播放模式
5. `Ctrl+Alt+O` 隐藏/显示面板

### 目录结构

```
olivia-autoplay/
├── src/
│   └── autoplay.js            # 注入脚本主体（面板 + 队列控制器）
├── tools/
│   ├── olivia_patch.py        # build / install / restore 补丁工具
│   └── olivia_webplayer_patch.py  # webplayer.dat 诊断探针（可选，排查播放问题时用）
├── LICENSE
└── README.md
```

### 免责声明

- 本项目**不分发**游戏本体的任何原始资源；补丁工具基于用户本机的原始文件备份工作
- 仅供个人学习、研究与娱乐使用（PolyForm Noncommercial 授权）
- 使用本插件产生的任何游戏账号风险由使用者自行承担
- 如需回滚，`python olivia_patch.py restore` 可完整还原原始文件

---

<a id="english"></a>
## English

**Auto-play enhancement plugin for Olivia (Steam)** — injects a floating panel into the game's front-end for full-library continuous playback, queue management, and manual song-switch following.

> ⚠️ **This is a reverse-engineering / personal-study project, not affiliated with the game's developers.** Do not use this repository or its artifacts for any commercial purpose.

### Features

- **Continuous playback** — repeat / shuffle / single modes; automatically advances when a song ends
- **Manual-switch following** — when you switch songs in the game UI, the queue and list highlight follow the currently playing song (out-of-queue songs are adopted into the queue)
- **Floating control panel** — live current song, queue position, and play mode; collapsible; `Ctrl+Alt+O` to toggle
- **Full track list** — scrollable queue with click-to-play, current track highlighted and auto-scrolled into view
- **Dynamic library re-scan** — auto-discovers lazily-registered playlists (solo / play-sing / instrumental) and builds the queue once data arrives
- **Non-invasive design** — never modifies official game logic; reads official state and calls official APIs only, with full exception guarding

### How it works

The game front-end (`feapp.dat`) is a ZIP-packaged Vue SPA. This tool:

1. Rebuilds a patched archive from the original `feapp.dat` backup, injecting `src/autoplay.js` as `assets/autoplay.js` plus a script tag in `index.html`
2. The injected script auto-loads at game start; it reads library/playback state via Pinia stores and sends playback commands through the official `cefViewQuery` bridge

### Installation

**Requirements**: Python 3.8+, Olivia (Steam). The Steam path is located by default and can be overridden via the `OLIVIA_APP_DIR` environment variable.

```bash
git clone https://github.com/vega0707/olivia-autoplay.git
cd olivia-autoplay/tools

# 1. Check status (creates the original backup on first run)
python olivia_patch.py status

# 2. Build the patched archive (collects your local cached-track list)
python olivia_patch.py build

# 3. Install (close Olivia first; the current file is backed up automatically)
python olivia_patch.py install

# Rollback
python olivia_patch.py restore
```

Custom game directory:

```bash
set OLIVIA_APP_DIR=C:\your\Olivia\install\dir
python olivia_patch.py build && python olivia_patch.py install
```

### Usage

1. Launch the game — a "♪ 自动连播" floating panel appears
2. Wait until the panel shows the queue count (libraries load lazily; usually ready within seconds)
3. Click "**开始连播**" (start) — the plugin **never** auto-starts playback
4. Panel controls: start/stop, next track; dropdowns for track range and play mode
5. `Ctrl+Alt+O` to hide/show the panel

### Disclaimer

- This project **does not distribute** any original game assets; the patch tool works from backups of your own local files
- For personal study, research, and entertainment only (PolyForm Noncommercial license)
- Any account risk arising from using this plugin is on the user
- `python olivia_patch.py restore` fully restores the original file

---

## License / 许可

[PolyForm Noncommercial 1.0.0](./LICENSE) — free for noncommercial use; commercial use requires separate permission from the author.

PolyForm Noncommercial 1.0.0 —— 非商业用途免费使用；商业使用需另行获得作者授权。
