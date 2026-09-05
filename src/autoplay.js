/* =========================================================================
 * Olivia AutoPlay —— BSide: Olivia Lin 自动连播增强
 *
 * 设计原则：
 *   1. 零侵入：不修改官方任何既有逻辑，只读官方 store 状态、只调官方 API
 *   2. 只读 + 受控写入：播放动作全部走官方 playSong()，视频解码/时段/机位
 *      选择仍由应用决定，本脚本只负责「播谁、什么时候播下一首」
 *   3. 全程 try/catch 包裹，任何异常都不允许影响宿主页面
 *
 * 依赖的官方能力（经逆向确认存在于 feapp.dat 中）：
 *   - pinia store：可通过 app 实例从 #app.__vue_app__ 取得
 *   - 播放 store：playSong / handlePlayNext / isPlaying / playMode / playlist
 *   - 曲库 store：studioSolo / studioPlaySing / studioInstrumental 的 songList
 * ========================================================================= */
(function () {
    'use strict';

    var TAG = '[OliviaAutoPlay]';
    var TICK_MS = 600;          // 状态轮询间隔
    var END_GRACE_MS = 1500;    // 停止后视为自然结束的宽限
    var TIMING_SLACK_MS = 1200; // 时长预估的容错

    var MODE = { REPEAT: 'repeat', SHUFFLE: 'shuffle', SINGLE: 'single' };
    var MODE_LABEL = { repeat: '顺序', shuffle: '随机', single: '单曲' };

    /*__CACHE_DIRS__*/   // ← build 时替换为 window.__OLIVIA_CACHE_DIRS=[...]（本地缓存曲目清单）

    // 从缓存目录名解析可读曲名：PlaySing_Da_Capo_Ziyun_original → Da Capo
    function parseCacheName(dir) {
        var parts = dir.split('_');
        var out = [];
        for (var i = 1; i < parts.length; i++) {
            var p = parts[i];
            if (!p || p === 'original' || p === 'Ziyun' || p === 'cover' ||
                /^(TOD|NI|WI|L|v\d+)$/i.test(p)) continue;
            out.push(p);
        }
        return out.join(' ') || dir;
    }

    // ---------------------------------------------------------------------
    // v17：直连原生桥接取离线曲库（不依赖 pinia store）
    // 真机日志确认：原生 getOfflineSongList 返回 ~1.1MB 完整曲库元数据
    // （id/nameKey/videoUrl/videoByTodView），离线可用，响应 ~100ms。
    // pinia store 是惰性创建的 —— 应用没用过它就不在 pinia._s 里，
    // 所以直接走 window.cefViewQuery 桥接（与官方 We() 同一协议）。
    // ---------------------------------------------------------------------
    var offlineData = { songs: [], fetching: false, since: 0 };   // 桥接取回的完整元数据曲目
    window.__oliviaOffline = offlineData;               // 调试句柄

    // ---------------------------------------------------------------------
    // v21：播放器事件直接观测（ToyPianistClient webPlayerControl）。
    // 官方 store 的进度更新（case"timeupdate": d.value=B.currentTime）
    // 是无条件的 —— 谁发起播放无所谓，只要播放器真播，事件就会回流。
    // 这里绕过 store 直接监听：pos=最近 position，maxPos=本次播放最大
    // position（真播判据），ended=自然结束计数（比 30s 看门狗更快的
    // 切歌触发器）。
    // ---------------------------------------------------------------------
    var liveStats = { pos: -1, posTs: 0, maxPos: -1, ended: 0, events: 0 };
    window.__oliviaLive = liveStats;

    // 读取 Vue Router（模块级：控制器与 UI 都要用）
    function getRouter() {
        try {
            var el = document.getElementById('app');
            var vueApp = el && el.__vue_app__;
            return (vueApp && vueApp.config.globalProperties.$router) || null;
        } catch (e) { return null; }
    }

    // v20：play 指令 source 改写。真机日志中唯一的成功播放（官方手动
    // 点击）source=songlist；我们经 store playSong 发出的全部是
    // source=playlist 且从未真播。载荷其余字段已逐字节对比无差异，
    // source 是最后一个可变因素 —— 在桥接层改写后实测。
    (function rewritePlaySource() {
        function hook() {
            try {
                if (typeof window.cefViewQuery !== 'function' ||
                    window.cefViewQuery.__apHooked) {
                    if (!window.cefViewQuery) setTimeout(hook, 500);
                    return;
                }
                var orig = window.cefViewQuery;
                var wrapped = function (q) {
                    try {
                        var req = JSON.parse(q.request);
                        if (req && req.action === 'sendWebPlayerControlCmd' &&
                            req.data && req.data.cmd === 'play' &&
                            req.data.song && req.data.song.source === 'playlist') {
                            req.data.song.source = 'songlist';
                            q.request = JSON.stringify(req);
                        }
                    } catch (e) { }
                    return orig.call(window, q);
                };
                wrapped.__apHooked = true;
                window.cefViewQuery = wrapped;
                log('cefViewQuery play source 改写钩子已装');
            } catch (e) { }
        }
        hook();
    })();

    // 官方 y1() 的等价实现（逆向自 main-31595bd3.js）：
    //   ys  —— 深度 snake_case→camelCase（video_by_tod_view→videoByTodView）
    //   xs  —— 递归收割目录树中所有「形如歌曲」的对象
    //           （v1 判据：id 为 string/number 且 name/nameKey 为 string）
    //   h1  —— 按 styleType-id 去重
    // 目录顶层没有 songs 字段（只有 env/apiBase/fetchedAt/performanceModes），
    // 歌曲嵌套在 performanceModes→子分组→songs 深处，必须递归收割。
    function camelDeep(e) {
        var k, nk, out, i;
        if (Array.isArray(e)) {
            out = [];
            for (i = 0; i < e.length; i++) out.push(camelDeep(e[i]));
            return out;
        }
        if (e && typeof e === 'object') {
            out = {};
            for (k in e) {
                if (Object.prototype.hasOwnProperty.call(e, k)) {
                    nk = k.replace(/_([a-z0-9])/g, function (m, l) {
                        return l.toUpperCase();
                    });
                    out[nk] = camelDeep(e[k]);
                }
            }
            return out;
        }
        return e;
    }

    function isSongLike(e) {
        return !!e && typeof e === 'object' && !Array.isArray(e) &&
            (typeof e.id === 'number' || typeof e.id === 'string') &&
            typeof e.name === 'string' && typeof e.nameKey === 'string';
    }

    function harvestSongs(e, depth) {
        var out = [], i, k;
        depth = depth || 0;
        if (depth > 8) return out;
        if (isSongLike(e)) return [e];
        if (Array.isArray(e)) {
            for (i = 0; i < e.length; i++) out = out.concat(harvestSongs(e[i], depth + 1));
            return out;
        }
        if (e && typeof e === 'object') {
            for (k in e) {
                if (Object.prototype.hasOwnProperty.call(e, k)) {
                    out = out.concat(harvestSongs(e[k], depth + 1));
                }
            }
        }
        return out;
    }

    function dedupSongs(list) {
        var seen = {}, out = [], i, key;
        for (i = 0; i < list.length; i++) {
            key = ((list[i] && list[i].styleType) || '') + '-' +
                (list[i] && list[i].id);
            if (seen[key]) continue;
            seen[key] = 1;
            out.push(list[i]);
        }
        return out;
    }

    function fetchOfflineViaBridge() {
        return new Promise(function (resolve) {
            try {
                if (typeof window.cefViewQuery !== 'function') return resolve(null);
                window.cefViewQuery({
                    request: JSON.stringify({ action: 'getOfflineSongList', data: {} }),
                    onSuccess: function (a) {
                        try {
                            // 响应形态：{"data":"<JSON 字符串>"}，逐层解包
                            var obj = a ? JSON.parse(a) : null;
                            if (obj && typeof obj.data === 'string') {
                                obj = JSON.parse(obj.data);
                            }
                            while (obj && obj.data && typeof obj.data === 'object') {
                                obj = obj.data;
                            }
                            obj = camelDeep(obj);
                            // 官方 y1 等价：深度收割形如歌曲的对象
                            resolve({ songs: dedupSongs(harvestSongs(obj)) });
                        } catch (e) { resolve(null); }
                    },
                    onFailure: function () { resolve(null); }
                });
            } catch (e) { resolve(null); }
        });
    }

    function ensureOfflineData() {
        if (offlineData.songs.length) return;
        // 挂起超时保护：原生对异常查询可能不回调（早期 action not found
        // 阶段），12 秒后允许重试，避免 fetching 永久卡死
        if (offlineData.fetching && Date.now() - offlineData.since < 12000) return;
        offlineData.fetching = true;
        offlineData.since = Date.now();
        fetchOfflineViaBridge().then(function (obj) {
            offlineData.fetching = false;
            try {
                if (obj && Array.isArray(obj.songs) && obj.songs.length) {
                    offlineData.songs = obj.songs;
                    log('原生离线曲库已取回 ' + obj.songs.length + ' 首（cefViewQuery 直连）');
                }
            } catch (e) { }
        });
    }
    ensureOfflineData();   // 脚本一载入就取（早期可能被原生拒绝，靠 5s 重试兜底）

    // 面板样式（等待面板与主控面板共用，保证视觉一致）
    var PANEL_CSS = [
        'position:fixed', 'right:16px', 'bottom:16px', 'z-index:2147483000',
        'font:13px/1.5 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif',
        'color:#e8eaed', 'background:rgba(24,26,31,.92)',
        'border:1px solid rgba(255,255,255,.12)', 'border-radius:12px',
        'box-shadow:0 8px 28px rgba(0,0,0,.35)', 'backdrop-filter:blur(8px)',
        'width:280px', 'user-select:none', 'overflow:hidden'
    ].join(';');
    var PANEL_HEAD_CSS = 'display:flex;align-items:center;justify-content:space-between;' +
        'padding:9px 12px;background:rgba(255,255,255,.05)';
    // 按钮基础样式（主控面板与等待面板共用）
    var BTN_CSS = 'padding:6px 4px;font-size:12px;border-radius:7px;cursor:pointer;' +
        'border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.07);' +
        'color:#e8eaed;font-family:inherit;';

    function log() {
        try { console.log(TAG, [].slice.call(arguments).join(' ')); } catch (e) { }
    }
    function warn() {
        try { console.warn(TAG, [].slice.call(arguments).join(' ')); } catch (e) { }
    }

    // ---------------------------------------------------------------------
    // 1. 拿到 pinia（等待 Vue 应用挂载完成）
    // ---------------------------------------------------------------------
    // 多路径探测 pinia：不同挂载方式下 __vue_app__ / __vueParentComponent
    // 的出现时机不同，这里穷举常见入口，任一条命中即可
    function tryGetPinia() {
        var el = document.querySelector('#app');
        if (!el) return null;

        // 路径 1：Vue3 在挂载容器上写入的 __vue_app__
        try {
            var app = el.__vue_app__;
            var gp = app && app.config && app.config.globalProperties;
            if (gp && gp.$pinia) return gp.$pinia;
            if (app && app._context && app._context.config &&
                app._context.config.globalProperties &&
                app._context.config.globalProperties.$pinia) {
                return app._context.config.globalProperties.$pinia;
            }
        } catch (e) { }

        // 路径 2：根组件实例反查 appContext
        try {
            var comp = el.__vueParentComponent;
            var ac = comp && comp.appContext && comp.appContext.config;
            if (ac && ac.globalProperties && ac.globalProperties.$pinia) {
                return ac.globalProperties.$pinia;
            }
        } catch (e) { }

        // 路径 3：遍历已渲染的子节点（仅在启动阶段，最多扫 300 个）
        try {
            var nodes = el.querySelectorAll('*');
            var limit = Math.min(nodes.length, 300);
            for (var i = 0; i < limit; i++) {
                var c = nodes[i].__vueParentComponent;
                var g = c && c.appContext && c.appContext.config &&
                    c.appContext.config.globalProperties;
                if (g && g.$pinia) return g.$pinia;
            }
        } catch (e) { }

        return null;
    }

    function waitPinia(timeoutMs) {
        return new Promise(function (resolve) {
            var deadline = Date.now() + (timeoutMs || 60000);
            var timer = setInterval(function () {
                var pinia = null;
                try { pinia = tryGetPinia(); } catch (e) { }
                if (pinia) { clearInterval(timer); resolve(pinia); }
                else if (Date.now() > deadline) { clearInterval(timer); resolve(null); }
            }, 250);
        });
    }

    // ---------------------------------------------------------------------
    // 2. 定位播放 store 与曲库 store
    // ---------------------------------------------------------------------
    // 播放 store 的识别：不依赖单一字段名（可能被压缩改名），改为按
    // 「播放相关能力」打分，取最高分者。避免版本微调后整个功能失效。
    var PLAYER_HINTS = [
        ['playSong', 'fn', 4],
        ['playMode', 'any', 3],
        ['setPlaylist', 'fn', 2],
        ['handlePlayNext', 'fn', 2],
        ['handlePlayPrev', 'fn', 1],
        ['handleChangePlayMode', 'fn', 1],
        ['stopCurrentSong', 'fn', 1],
        ['isPlaying', 'any', 1],
        ['currentSong', 'any', 1],
        ['playlist', 'any', 1],
        ['nowPlayingDuration', 'any', 1]
    ];

    function scorePlayerStore(s) {
        var score = 0, hit = [];
        for (var i = 0; i < PLAYER_HINTS.length; i++) {
            var key = PLAYER_HINTS[i][0], kind = PLAYER_HINTS[i][1], w = PLAYER_HINTS[i][2];
            try {
                var v = s[key];
                var ok = (kind === 'fn') ? (typeof v === 'function') : (v !== undefined);
                if (ok) { score += w; hit.push(key); }
            } catch (e) { }
        }
        return { score: score, hit: hit };
    }

    // 曲库识别：优先 songList，其次常见的同义字段
    var CATALOG_KEYS = ['songList', 'songs', 'list', 'items'];

    // 曲库显示名（沿用官方语言包里「独奏歌单/弹唱歌单/伴奏歌单」的叫法）
    var CATALOG_LABEL = {
        studioSolo: '独奏歌单',
        studioPlaySing: '弹唱歌单',
        studioInstrumental: '伴奏歌单',
        song: '全部曲库',
        playlist: '我的歌单',
        localPerformance: '本地演奏',
        offlineCatalog: '离线曲库',
        performance: '演奏记录'
    };

    // 对外诊断通道：QCefView 的 titleChanged 会同步到 Qt 窗口标题，
    // 外部用 GetWindowText 即可读取，无需 DevTools。
    var diagState = { phase: 'boot', detail: '' };
    function setDiag(phase, detail) {
        diagState.phase = phase;
        diagState.detail = detail || '';
        try { document.title = '[AP]' + phase + (detail ? '|' + detail : ''); } catch (e) { }
    }
    setInterval(function () {
        try { setDiag(diagState.phase, diagState.detail); } catch (e) { }
    }, 5000);

    function pickCatalogArray(s) {
        for (var i = 0; i < CATALOG_KEYS.length; i++) {
            try {
                var v = s[CATALOG_KEYS[i]];
                // 字段存在即收录，空数组也收（真机诊断确认曲库懒加载，
                // 初始 songList=[]；收下来等 30s 自愈建队列即可）。
                if (v && Array.isArray(v)) {
                    return { key: CATALOG_KEYS[i], list: v };
                }
            } catch (e) { }
        }
        return null;
    }

    // 可播性抽样：仅作排序用的软信号（rate 高的真曲库排前面），
    // 不再据此剔除 —— 剔除交给 buildQueue 里的逐首过滤。
    function sampleAvailRate(player, list) {
        if (!player || typeof player.isSongAvailable !== 'function') return -1;
        var n = Math.min(3, list.length), ok = 0;
        for (var i = 0; i < n; i++) {
            try { if (player.isSongAvailable(list[i])) ok++; } catch (e) { }
        }
        return n ? ok / n : 0;
    }

    // v22.4：全局持有 pinia 引用，供面板在运行期重新扫描曲库
    // （官方歌单 store 是懒注册的，伴奏歌单等用户打开过页面才存在）。
    var gPinia = null;

    function locateStores(pinia) {
        var all = {}, player = null;
        var bestScore = 0, bestId = null, bestHit = [];
        try {
            pinia._s.forEach(function (store, id) { all[id] = store; });
        } catch (e) {
            warn('遍历 pinia._s 失败', e && e.message);
        }
        // 第一轮：先定播放 store（曲库验证要用它的 isSongAvailable）
        Object.keys(all).forEach(function (id) {
            var s = all[id];
            if (!s) return;
            try {
                // 必须真的能播歌，才够格当「播放 store」
                if (typeof s.playSong === 'function') {
                    var r = scorePlayerStore(s);
                    if (r.score > bestScore) {
                        bestScore = r.score; bestId = id; bestHit = r.hit; player = s;
                    }
                }
            } catch (e) { }
        });
        if (player) {
            log('播放 store = ' + bestId + '（得分 ' + bestScore + '：' + bestHit.join(',') + '）');
            // v22.3：掐断自动 seek(0) 死循环的唯一发送源。
            // 根因（frida 调用栈 + 逆向证实）：feapp 某进度条组件每 ~2.2s
            // 调 handleSeekTo(0)（其 duration ref 未初始化 → Math.min(0,E)=0），
            // 经 Ct → query {action:'sendWebPlayerControlCmd', data:{cmd:'timeupdate',
            // position:0}} 发出；native 侧 NutGui ContainerBridge 转发给
            // NutStudioUI LiteUIController 分发器，后者把 "timeupdate" 命令
            // 映射到 Player.seek(position)（vt+0x48）→ WebPlayerClient::seek(0)
            // → webplayer 视频被反复拉回 0。此处覆写 store 方法（组件均经
            // store 属性访问调用）即可让该 query 不再发出。
            try {
                player.handleSeekTo = function (p) {
                    log('已拦截 handleSeekTo(' + p + ')（v22.3 seek 循环修复）');
                };
                log('已拦截 store.handleSeekTo（v22.3）');
            } catch (e) { warn('拦截 handleSeekTo 失败', e && e.message); }
        }

        // 第二轮：收集曲库。字段存在即收录，空数组也收 ——
        // 官方 songList 由 fetchSongList() 分页懒加载，初始为空。
        var catalogs = [];
        Object.keys(all).forEach(function (id) {
            var s = all[id];
            if (!s) return;
            try {
                var cat = pickCatalogArray(s);
                if (!cat) return;
                catalogs.push({
                    id: id, store: s, key: cat.key,
                    label: CATALOG_LABEL[id] || id,
                    rate: sampleAvailRate(player, cat.list),
                    count: cat.list.length
                });
            } catch (e) { }
        });
        // 主动预加载：官方只在进入曲库页面时才 fetchSongList，
        // 这里直接调官方方法把曲库拉下来（分页工厂 Mt 的 fetchList）
        catalogs.forEach(function (c) {
            try {
                if (typeof c.store.fetchSongList === 'function') {
                    c.store.fetchSongList();
                    log('已触发 ' + c.id + '.fetchSongList() 预加载曲库');
                }
            } catch (e) { }
        });
        // 排序：可播率高的在前，其次曲数多的在前 —— 真曲库天然沉不到底
        catalogs.sort(function (a, b) {
            if (a.rate < 0 && b.rate < 0) return b.count - a.count;
            if (a.rate < 0) return 1;
            if (b.rate < 0) return -1;
            if (b.rate !== a.rate) return b.rate - a.rate;
            return b.count - a.count;
        });
        // 本地下载清单 store：官方 isSongAvailable 的数据源
        var downloads = all['songDownload'] || null;
        if (!downloads) {
            Object.keys(all).forEach(function (id) {
                if (!downloads && all[id] && all[id].downloadMap) downloads = all[id];
            });
        }
        if (downloads) {
            var dn = 0;
            try {
                downloads.downloadMap.forEach(function (v) {
                    if (v && v.state === 'completed') dn++;
                });
            } catch (e) { }
            log('下载清单 store 已就绪，本地可播 ' + dn + ' 首');
        }
        // 离线曲库 store：原生 getOfflineSongList 桥接返回完整曲库元数据
        // （id/nameKey/videoUrl/videoByTodView 齐全），离线可用 —— 这是
        // 官方 App 自己的离线数据源（真机日志确认原生响应 ~1.1MB JSON）。
        // 识别签名：songs 数组 + load/getSongsByStyle/markUnavailable 方法。
        var offline = null, offlineId = null;
        if (all['offlineCatalog']) { offline = all['offlineCatalog']; offlineId = 'offlineCatalog'; }
        if (!offline) {
            Object.keys(all).forEach(function (id) {
                if (offline) return;
                var s = all[id];
                try {
                    if (s && Array.isArray(s.songs) &&
                        typeof s.load === 'function' &&
                        typeof s.getSongsByStyle === 'function' &&
                        typeof s.markUnavailable === 'function') {
                        offline = s; offlineId = id;
                    }
                } catch (e) { }
            });
        }
        if (offline) {
            try {
                // load() 幂等（官方内部已去重），原生响应快（日志 ~100ms）
                if (!offline.loaded && typeof offline.load === 'function') offline.load();
            } catch (e) { }
            var on_ = 0;
            try { on_ = (offline.songs || []).length; } catch (e) { }
            log('离线曲库 store = ' + offlineId + '，' + on_ + ' 首完整元数据');
        }
        return {
            all: all, player: player, playerId: bestId,
            catalogs: catalogs, downloads: downloads,
            offline: offline, offlineId: offlineId
        };
    }

    // ---------------------------------------------------------------------
    // 3. 控制器：队列 / 模式 / 自动续播
    // ---------------------------------------------------------------------
    function createController(player, catalogs, downloads, offline, offlineId) {
        var state = {
            autoOn: false,
            mode: MODE.REPEAT,
            source: 'auto',        // 曲目来源（曲库 store id 或 'playlist'）
            queue: [],             // 可播放曲目数组
            index: -1,             // 当前在队列中的位置
            playingSince: 0,       // 本首开始播放的时间戳
            expectEndAt: 0,        // 预计结束时间戳
            stopSince: 0,          // 检测到停止的时间戳
            lastPlaying: false,
            lastSongKey: null,
            busy: false
        };

        function songKey(s) {
            if (!s) return null;
            // songId 在前：官方曲目对象实测只带 songId
            return s.songId || s.itemId || s.id || s.nameKey || s.name || null;
        }

        function songName(s) {
            if (!s) return '—';
            return s.name || s.title || s.songName || s.musicName ||
                s.nameKey || (s.songId ? '#' + s.songId : null) ||
                s.itemId || s.id || '未命名';
        }

        // 收集可播放曲目
        function buildQueue() {
            var list = [];
            if (state.source === 'playlist') {
                try { list = Array.prototype.slice.call(player.playlist || []); } catch (e) { }
            } else {
                var target = state.source;
                for (var i = 0; i < catalogs.length; i++) {
                    if (target === 'auto' || catalogs[i].id === target) {
                        try {
                            var arr = catalogs[i].store[catalogs[i].key] || [];
                            list = list.concat(Array.prototype.slice.call(arr));
                        } catch (e) { }
                    }
                }
                // ── 离线曲库优先（v16）─────────────────────────────
                // 原生 getOfflineSongList 返回完整元数据曲目。真机日志证实：
                // 携带 videoByTodView/videoUrl 的曲目原生能真播放（进度推进），
                // 而空元数据构造对象原生收下却不播（songPlayEnd end_progress=0）。
                // 原生按 nameKey 定位缓存目录（nameKey === 缓存目录名，实测一致），
                // 因此只保留 nameKey 命中缓存目录清单的曲目 —— 离线下其余必播不出。
                var ocSongs = [];
                try {
                    var wantOffline = (state.source === 'auto') ||
                        (offline && state.source === offlineId);
                    // 数据源优先级：桥接直取（最快、不依赖 store 创建时机）
                    // > offlineCatalog store > 无
                    var ocSrc = offlineData.songs.length ? offlineData.songs :
                        (offline && Array.isArray(offline.songs) ?
                            offline.songs : null);
                    if (wantOffline && ocSrc && ocSrc.length) {
                        var dirsMap = {};
                        var dirsArr = window.__OLIVIA_CACHE_DIRS || [];
                        for (var xi = 0; xi < dirsArr.length; xi++) dirsMap[dirsArr[xi]] = 1;
                        for (var oi = 0; oi < ocSrc.length; oi++) {
                            var osong = ocSrc[oi];
                            if (!osong) continue;
                            var nk = osong.nameKey || osong.songNameKey;
                            if (!nk || !dirsMap[nk]) continue;
                            var it = {
                                itemType: (osong.itemType === 2 || osong.itemType === 3)
                                    ? osong.itemType : 3,
                                id: osong.id,
                                songId: osong.songId != null ? osong.songId : osong.id,
                                itemId: osong.itemId != null ? osong.itemId : String(osong.id),
                                name: osong.name || parseCacheName(nk),
                                nameKey: nk,
                                videoUrl: osong.videoUrl,
                                videoByTodView: osong.videoByTodView,
                                coverUrl: osong.coverUrl || osong.iconUrl,
                                performanceType: osong.performanceType
                            };
                            // 给官方 isSongAvailable 兜底：仅对已确认在缓存里的
                            // 曲目补 completed 条目。Map 的数字键与字符串键不同，
                            // 官方 l(B) 用原始 id 查、我们补 String(id)，两种都补
                            try {
                                if (downloads && downloads.downloadMap &&
                                    typeof downloads.downloadMap.set === 'function') {
                                    var zids = [it.songId, it.id,
                                        String(it.songId), String(it.id)];
                                    for (var zi = 0; zi < zids.length; zi++) {
                                        var zid = zids[zi];
                                        if (zid === undefined || zid === null) continue;
                                        var den = downloads.downloadMap.get(zid);
                                        if (!den || den.state !== 'completed') {
                                            downloads.downloadMap.set(zid,
                                                { state: 'completed', progress: 100 });
                                        }
                                    }
                                }
                            } catch (e) { }
                            ocSongs.push(it);
                        }
                        if (ocSongs.length) {
                            list = ocSongs;   // 完整元数据可用 → 杂项/空壳全弃用
                            log('离线曲库命中本地缓存 ' + ocSongs.length + ' 首（完整元数据）');
                        }
                    }
                } catch (e) { warn('离线曲库建队失败', e && e.message); }

                // 本地缓存曲目兜底：官方按曲目标识（nameKey）定位缓存目录，
                // 缓存目录名即该标识。离线曲库不可用时（老版本/加载失败），
                // 直接用目录名构造曲目对象；同时向 downloadMap 补
                // 「已下载」条目，让官方 isSongAvailable 判定通过。
                if (!ocSongs.length) {
                    // 桥接数据还没回来 → 现在取（异步，下轮 buildQueue 生效）
                    try { ensureOfflineData(); } catch (e) { }
                }
                if (!ocSongs.length &&
                    downloads && downloads.downloadMap &&
                    typeof downloads.downloadMap.set === 'function') {
                    try {
                        var dirs = window.__OLIVIA_CACHE_DIRS || [];
                        for (var di = 0; di < dirs.length; di++) {
                            var dir = dirs[di];
                            var entry = downloads.downloadMap.get(dir);
                            if (!entry || entry.state !== 'completed') {
                                downloads.downloadMap.set(dir, {
                                    state: 'completed', progress: 100
                                });
                            }
                            list.push({
                                itemType: 3,            // pt.UGC_SONG
                                id: dir, songId: dir, itemId: dir,
                                name: parseCacheName(dir),
                                nameKey: dir
                            });
                        }
                        if (dirs.length) {
                            log('已并入本地缓存曲目 ' + dirs.length + ' 首');
                        }
                    } catch (e) { }
                }
            }
            // 过滤出可播放的（本地已缓存 / 可在线）
            var ok = [];
            for (var j = 0; j < list.length; j++) {
                var s = list[j];
                if (!s) continue;
                var available = true;
                try {
                    if (typeof player.isSongAvailable === 'function') {
                        available = !!player.isSongAvailable(s);
                    }
                } catch (e) {
                    // 查询本身抛错 → 视为不可播，宁可跳过也不硬播
                    available = false;
                }
                if (available) ok.push(s);
            }
            // 官方可播判定全军覆没时的保险：我们的清单本来就只含本地
            // 缓存曲目（离线曲库按缓存目录过滤 / 目录名直接来自缓存），
            // 判定失灵（downloadMap 未同步 / Map 键型不符）时直接放行，
            // 否则整队被吞、队列永远为空
            if (!ok.length && list.length) {
                ok = list;
                log('官方可播过滤通过 0 首，直接采用原始清单 ' + list.length + ' 首');
            }
            // 去重
            var seen = {}, uniq = [];
            for (var k = 0; k < ok.length; k++) {
                var key = songKey(ok[k]);
                if (key == null || seen[key]) continue;
                seen[key] = 1;
                uniq.push(ok[k]);
            }
            state.queue = uniq;
            log('队列已建立：' + uniq.length + ' 首（' + state.source + '）');
        }

        function currentSong() {
            try { return player.currentSong || player.nowPlaying || null; } catch (e) { return null; }
        }

        function syncIndexToCurrent() {
            var cur = currentSong();
            var key = songKey(cur);
            if (key == null) return;
            for (var i = 0; i < state.queue.length; i++) {
                if (songKey(state.queue[i]) === key) { state.index = i; return; }
            }
        }

        // v22.4：跟随「外部切歌」—— 用户用官方 UI 切到一首不在我们
        // 队列里的歌（例如官方播放列表里的其它曲目）时，把它插入当前
        // 位置之后并把索引指向它，后续连播从这首继续。
        function adoptCurrent() {
            var cur = currentSong();
            var key = songKey(cur);
            if (key == null) return false;
            for (var i = 0; i < state.queue.length; i++) {
                if (songKey(state.queue[i]) === key) { state.index = i; return true; }
            }
            try {
                var at = state.index >= 0 ? state.index + 1 : 0;
                state.queue.splice(at, 0, cur);
                state.index = at;
                log('已把当前曲目加入队列：' + songName(cur));
                return true;
            } catch (e) { return false; }
        }

        function pickNextIndex() {
            var n = state.queue.length;
            if (n === 0) return -1;
            if (state.mode === MODE.SINGLE) return state.index >= 0 ? state.index : 0;
            if (state.mode === MODE.SHUFFLE) {
                if (n === 1) return 0;
                var r = state.index;
                var guard = 0;
                while (r === state.index && guard++ < 50) {
                    r = Math.floor(Math.random() * n);
                }
                return r;
            }
            return (state.index + 1) % n;   // repeat：顺序循环
        }

        // v21b：eventTrack 遥测（ToyPianistClient.invoke）。官方 songlist
        // 播放的完整序列 = songPlayEnd(上一首) → play → songPlayStart。
        // 同一轮内官方点击成功而我们 6s ended 的剩余差异只剩这些遥测，
        // 逐一补齐以排除。
        function makeUUID() {
            try { if (window.crypto && typeof window.crypto.randomUUID === 'function')
                return window.crypto.randomUUID(); } catch (e) { }
            return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,
                function (c) {
                    var r = Math.random() * 16 | 0;
                    return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
                });
        }
        var lastSongEventId = null;
        var lastPlaySentAt = 0;   // v22：最近一次 direct play 发出时刻（忽略交叉淡切期的陈旧 ended）
        function emitEventTrack(actionName, p) {
            try {
                window.ToyPianistClient.invoke('eventTrack', {
                    actionName: actionName,
                    params: JSON.stringify(p)
                });
            } catch (e) { }
        }
        function songPlayEndTrack(song, reason) {
            emitEventTrack('songPlayEnd', {
                log_time: Date.now(), aid: '', uid: '10000',
                event_id: lastSongEventId || makeUUID(),
                source: 'songlist',
                name: song ? (song.name || '') : '',
                name_key: song ? (song.nameKey || '') : '',
                style_type: song ? (song.styleType || '') : '',
                performance_type: song ? String(song.performanceType || '') : '',
                end_progress: Math.floor(Number(
                    (typeof player !== 'undefined' && player.songProgress) || 0)),
                end_reason: reason || 'natural_end'
            });
            lastSongEventId = null;
        }

        // v21：直接经 cefViewQuery 发送 play（source=songlist）。背景：
        // 官方 playSong 的 playlist 分支硬编码 source:"playlist"，真机上
        // 载荷逐字段与成功案例一致却从未真播；唯一成功播放（官方曲库页
        // 手动点击）走 songlist 分支，source:"songlist" 是载荷里仅存的
        // 差异。此处完全复刻官方 songlist 分支的载荷
        // （{id,name,coverUrl,videoUrl,videoByTodView,nameKey,
        //   performanceType,source:"songlist",eventId}，duration 不进载荷）。
        function nativePlayDirect(song) {
            try {
                var payload = {
                    id: String(song.songId || song.id || song.itemId || ''),
                    name: song.name || '',
                    coverUrl: song.coverUrl || song.iconUrl || '',
                    videoUrl: song.videoUrl || '',
                    videoByTodView: song.videoByTodView || undefined,
                    nameKey: song.nameKey || '',
                    performanceType: song.performanceType != null ?
                        String(song.performanceType) : '',
                    source: 'songlist',
                    eventId: makeUUID()
                };
                window.cefViewQuery({
                    request: JSON.stringify({
                        action: 'sendWebPlayerControlCmd',
                        data: { cmd: 'play', song: payload }
                    }),
                    onSuccess: function (a) {
                        log('直接 play 送达（songlist id=' + payload.id + '）resp=' +
                            String(a == null ? 'null' : a).slice(0, 60));
                    },
                    onFailure: function (a) {
                        warn('直接 play 被原生拒绝',
                            String(a == null ? '' : a).slice(0, 80));
                    }
                });
                // v21b：复刻官方 songPlayStart 遥测（play 后 ~266ms 到达原生）
                var dur = 0;
                try {
                    var v0 = song.videoByTodView && song.videoByTodView[0];
                    dur = Number(v0 && v0.duration) || 0;
                } catch (e) { }
                lastSongEventId = payload.eventId;
                lastPlaySentAt = Date.now();
                emitEventTrack('songPlayStart', {
                    log_time: Date.now(), aid: '', uid: '10000',
                    event_id: payload.eventId, source: 'songlist',
                    name: song.name || '', name_key: song.nameKey || '',
                    style_type: song.styleType || '',
                    performance_type: String(song.performanceType || ''),
                    song_length: dur
                });
                // v21c 诊断实验（url-only play）已移除：真机日志证实其必触发
                // "no video TOD view item found, skip play"，仅作路径探针用，
                // 结论已取得（所有 play 均进 onPlayerPlay）。
                return true;
            } catch (e) {
                warn('nativePlayDirect 异常', e && e.message);
                return false;
            }
        }

        // v21：镜像官方 songlist 播放分支的状态写入（f=当前曲/h=来源/
        // m=播放中/u=null），让面板与官方内部逻辑认为正在播放。
        // 纯状态同步，失败不影响播放本身。direct 模式下刻意不调
        // setPlaylist —— 官方 ended 处理会从 playlist 里挑歌改走官方
        // 路径（source=playlist）与直接播放打架。
        function syncPlayerSonglistState(song) {
            try {
                var dur = 0;
                try {
                    var v0 = song.videoByTodView && song.videoByTodView[0];
                    dur = Number(v0 && v0.duration) || 0;
                } catch (e) { }
                var f = {
                    id: String(song.songId || song.id || ''),
                    name: song.name || '',
                    coverUrl: song.coverUrl || song.iconUrl || '',
                    duration: dur,
                    videoUrl: song.videoUrl || '',
                    videoByTodView: song.videoByTodView,
                    nameKey: song.nameKey || '',
                    performanceType: String(song.performanceType || ''),
                    source: 'songlist',
                    eventId: makeUUID()
                };
                var touched = [];
                try { player.f = f; touched.push('f'); } catch (e) { }
                try { player.u = null; touched.push('u'); } catch (e) { }
                try { if ('h' in player) { player.h = 'songlist'; touched.push('h'); } } catch (e) { }
                try { player.m = true; touched.push('m'); } catch (e) { }
                // v22.1：镜像 isPlaying=true —— webplayer 探针证实，不置位
                // 时官方 store 的内部播放时钟停在 0，其同步逻辑每 ~2.2s
                // 把视频 seek 回 0（webplayer 收到无限 cmd:seek offset:0），
                // 歌曲视频永远在开头 2 秒循环。官方点击路径 isPlaying=true
                // 时钟走表、无 seek。测试桩 isPlaying 为 getter-only，写入
                // 抛 TypeError 被 catch，行为不变。
                try { player.isPlaying = true; touched.push('isPlaying'); } catch (e) { }
                if (touched.length) log('store 状态镜像：' + touched.join('/'));
            } catch (e) { }
        }

        function playIndex(i) {
            if (i < 0 || i >= state.queue.length) return false;
            var song = state.queue[i];
            try {
                state.index = i;
                state.playingSince = Date.now();
                state.expectEndAt = 0;
                state.stopSince = 0;
                state.lastPlaying = true;
                state.lastSongKey = songKey(song);
                // v21：cefViewQuery 可用 → 直接发 songlist play（首选）；
                // 不可用才回落官方 playSong（source=playlist 旧路径）。
                if (typeof window.cefViewQuery === 'function' &&
                    typeof window.ToyPianistClient === 'object') {
                    // 复刻官方 w("switch_library")：结束上一首的播放会话
                    if (lastSongEventId) songPlayEndTrack(song, 'switch_library');
                    // v22.2：优先走官方 store 自带的 songlist 播放方法 ——
                    // 它在内部完成 f 构建、h='songlist'、m.value=true（isPlaying
                    // 置位！）、songPlayStart 遥测。webplayer 探针证实：仅手工
                    // 直发载荷时 m 无法置位（isPlaying 是闭包 ref 的只读暴露），
                    // 官方同步逻辑每 ~2.2s 把视频 seek 回 0，歌曲永远在开头循环。
                    if (typeof player.playSonglistItem === 'function') {
                        try {
                            player.playSonglistItem(song);
                            try { lastSongEventId = player.currentEventId || null; }
                            catch (e) { }
                            log('播放[o] [' + (i + 1) + '/' + state.queue.length + '] ' +
                                songName(song) + '（store songlist 路径）');
                        } catch (e) {
                            warn('playSonglistItem 异常，回落直发', e && e.message);
                            nativePlayDirect(song);
                            syncPlayerSonglistState(song);
                            log('播放[d] [' + (i + 1) + '/' + state.queue.length + '] ' +
                                songName(song));
                        }
                    } else {
                        nativePlayDirect(song);
                        syncPlayerSonglistState(song);
                        log('播放[d] [' + (i + 1) + '/' + state.queue.length + '] ' +
                            songName(song));
                    }
                    // v22：direct 模式节奏修正 —— 真机日志证实 play 已真实
                    // 起播（timeupdate 0→1→2 实时爬升），旧逻辑因 store
                    // isPlaying 恒 false 而每 ~2s 误判"播放结束"杀掉视频。
                    // 以 videoByTodView 的真实时长设定预计结束时刻：
                    //  - 起播准备期（canplaythrough + 双 video 交叉淡切需
                    //    3-4s）内不判终（tick 兜底由看门狗 30s 承担）；
                    //  - 自然终止以 ended 事件为准（live listener）。
                    var dv = 0;
                    try {
                        dv = Number(song.videoByTodView &&
                            song.videoByTodView[0] &&
                            song.videoByTodView[0].duration) || 0;
                    } catch (e) { }
                    state.expectEndAt = dv > 0 ?
                        Date.now() + (dv + 8) * 1000 : 0;
                    // 每首重置真播观测与看门狗基线（进度/事件按曲独立）
                    liveStats.pos = -1;
                    liveStats.posTs = 0;
                    liveStats.maxPos = -1;
                    wd.maxPg = -1;
                    wd.maxLive = -1;
                    wd.lastAdvance = Date.now();
                    return true;
                }
                // 让官方播放列表与我们的队列保持一致，便于官方内部逻辑协同
                if (typeof player.setPlaylist === 'function') {
                    try { player.setPlaylist(state.queue); } catch (e) { }
                }
                player.playSong(song);
                log('播放 [' + (i + 1) + '/' + state.queue.length + '] ' + songName(song));
                return true;
            } catch (e) {
                warn('playSong 失败', e && e.message);
                return false;
            }
        }

        function playNext() {
            if (state.busy) return;
            state.busy = true;
            try {
                syncIndexToCurrent();
                var next = pickNextIndex();
                if (next < 0) { log('队列为空，停止'); return; }
                playIndex(next);
            } finally {
                setTimeout(function () { state.busy = false; }, 800);
            }
        }

        // v21：自注册 webPlayerControl 事件监听 —— 与官方 store 同一事件
        // 源（ToyPianistClient.addEventListener），回调直接收到原生传来的
        // 事件对象（官方包装层只做 OTEL 日志，不改形状）。ended → 立即
        // 切歌；timeupdate → 跟踪真实 position（真播的最直接判据）。
        (function installLiveListener() {
            try {
                var tpc = window.ToyPianistClient;
                if (!tpc || typeof tpc.addEventListener !== 'function') {
                    setTimeout(installLiveListener, 1000);
                    return;
                }
                if (tpc.__apLiveHooked) return;
                tpc.__apLiveHooked = true;
                tpc.addEventListener('webPlayerControl', function (ev) {
                    try {
                        liveStats.events++;
                        if (!ev || typeof ev !== 'object') return;
                        var pos = Number(ev.currentTime !== undefined ?
                            ev.currentTime : ev.position);
                        if (ev.event === 'timeupdate' || ev.cmd === 'timeupdate') {
                            if (!isNaN(pos)) {
                                liveStats.pos = pos;
                                liveStats.posTs = Date.now();
                                if (pos > liveStats.maxPos) liveStats.maxPos = pos;
                            }
                        } else if (ev.event === 'ended' || ev.cmd === 'ended') {
                            liveStats.ended++;
                            // v22：play 后 2s 内的 ended 必为交叉淡切期
                            // 旧 video 元素的残留（真曲最短也有 ~80s），
                            // 忽略之，否则会把刚起播的视频误杀。
                            if (lastPlaySentAt &&
                                Date.now() - lastPlaySentAt < 2000) {
                                log('忽略 play 后 2s 内的陈旧 ended 事件');
                                return;
                            }
                            log('收到播放器 ended 事件，切下一首');
                            try {
                                if (lastSongEventId) {
                                    songPlayEndTrack(currentSong(), 'natural_end');
                                }
                            } catch (e) { }
                            liveStats.pos = -1;
                            liveStats.maxPos = -1;
                            playNext();
                        }
                    } catch (e) { }
                });
                log('webPlayerControl 事件监听已注册');
            } catch (e) { }
        })();

        // v18：舞台页导航。真机日志对比：官方点击播放（songlist 页，舞台
        // 视图可见）原生立刻真播（position 持续推进）；我们程序化 playSong
        // 后原生处于"播放中"但 position 恒 0，且壁纸视频继续循环 ——
        // 舞台视图不可见时原生不让出视频面。开播前先把路由导航到舞台页。
        function navToStage(r) {
            if (!r) return false;
            try {
                var cur = r.currentRoute && r.currentRoute.value;
                var curName = cur && cur.name;
                if (curName === 'studio' || curName === 'studio-lite') return true;
                if (typeof r.hasRoute === 'function') {
                    if (r.hasRoute('studio-lite')) {
                        r.push({ name: 'studio-lite' });
                        log('已导航到舞台页 studio-lite');
                        return true;
                    }
                    if (r.hasRoute('studio')) {
                        r.push({ name: 'studio' });
                        log('已导航到舞台页 studio');
                        return true;
                    }
                }
            } catch (e) { }
            return false;
        }

        function start() {
            navToStage(getRouter());
            var prevQueue = state.queue;
            buildQueue();
            if (!state.queue.length) {
                // 重建失败（官方过滤失灵等）→ 保留原队列，不清空
                if (prevQueue.length) {
                    state.queue = prevQueue;
                    log('重建队列为空，保留原队列（' + prevQueue.length + ' 首）');
                } else {
                    warn('没有可播放曲目，无法开始');
                    return false;
                }
            }
            state.autoOn = true;
            // 若当前正在播放，就接上它；否则从队列头开始
            var cur = currentSong();
            var isPlaying = false;
            try { isPlaying = !!player.isPlaying; } catch (e) { }
            syncIndexToCurrent();
            // 旧索引失效防护：队列可能刚被重建，残留 index 指向的曲目
            // 已不是当前播放的那首 → 归零，避免 playIndex 越界静默失败
            if (state.index >= 0) {
                var qk = songKey(state.queue[state.index]);
                if (qk !== songKey(cur)) state.index = -1;
            }
            if (isPlaying && state.index >= 0) {
                state.playingSince = Date.now();
                log('接管当前播放：' + songName(cur));
            } else {
                playIndex(state.index >= 0 ? state.index : 0);
            }
            return true;
        }

        function stop() {
            state.autoOn = false;
            state.stopSince = 0;
            state.playingSince = 0;
            state.lastPlaying = false;
            // 手动停止后，本次会话内不再自动开播（重启应用会恢复）
            try { sessionStorage.setItem('ap_manual_stop', '1'); } catch (e) { }
            try {
                if (typeof player.stopCurrentSong === 'function') {
                    player.stopCurrentSong('autoplay_off');
                } else if (typeof player.handleTogglePlay === 'function') {
                    player.handleTogglePlay();
                }
            } catch (e) { }
            log('已停止自动播放');
        }

        // 每轮心跳：识别「自然播放结束」并续播
        // v22：direct 模式下 store isPlaying 不反映真实播放（官方仅由
        // resume/pause 事件置位，而我们的 play 不触发）——真播判据改用
        // liveStats（webPlayerControl timeupdate 实时事件）：
        //   maxPos>=3 → 进度爬过壁纸循环区（0-2），必为真实视频；
        //   posTs 15s 内新鲜 → 事件仍在流动（视频未停）。
        // v21c 真机日志：play 已真实起播（0→1→2 实时爬升）但旧逻辑因
        // isPlaying=false 每 ~2s 误判结束杀视频 —— 本版修复节奏。
        function tick() {
            if (!state.autoOn) return;
            var isPlaying = false;
            try { isPlaying = !!player.isPlaying; } catch (e) { }
            var livePlaying = liveStats.maxPos >= 3 && liveStats.posTs &&
                (Date.now() - liveStats.posTs < 15000);
            var cur = currentSong();
            var key = songKey(cur);

            // 曲目发生了切换（可能是官方自己续播的）→ 同步索引
            if (key && key !== state.lastSongKey) {
                syncIndexToCurrent();
                state.lastSongKey = key;
                state.playingSince = Date.now();
                state.expectEndAt = 0;
                state.stopSince = 0;
                return;
            }

            if (isPlaying || livePlaying) {
                state.stopSince = 0;
                state.lastPlaying = true;
                // v22：超过预计结束时刻仍未收到 ended（事件丢失）→ 兜底
                if (state.expectEndAt &&
                    Date.now() > state.expectEndAt + TIMING_SLACK_MS) {
                    log('超过预计结束时间仍未收到 ended，切换下一首');
                    state.expectEndAt = 0;
                    playNext();
                }
                return;
            }

            // 未在播放（store 与 live 均无播放证据）：
            // v22 起播宽限窗 —— canplaythrough + 交叉淡切需 3-4s，
            // 已知时长（direct 载荷）的曲目在 play 后 10s 内不判终；
            // 管线真故障由看门狗（30s 停滞）兜底切换。
            if (state.expectEndAt && lastPlaySentAt &&
                Date.now() - lastPlaySentAt < 10000) return;

            // 本曲曾真实起播（maxPos>=3）但事件已静默：ended 丢失的
            // 情况 —— 撑到预计结束时刻后切换。
            if (liveStats.maxPos >= 3) {
                if (state.expectEndAt && Date.now() < state.expectEndAt) return;
                log('播放器事件静默且已超过预计结束时间，切换下一首');
                state.expectEndAt = 0;
                playNext();
                return;
            }

            // —— 旧路径：从未观测到真播（回落模式 / 无时长信息）——
            // 这里不能只依赖 lastPlaying 采样——若曲目极短、或停止发生在
            // 两次采样之间，就永远采不到「播放中」，续播会静默失效。
            if (state.lastPlaying || state.playingSince) {
                if (!state.stopSince) state.stopSince = Date.now();
            }
            if (state.stopSince) {
                var waited = Date.now() - state.stopSince;
                var timedOut = state.expectEndAt &&
                    Date.now() > state.expectEndAt + TIMING_SLACK_MS;
                if (waited >= END_GRACE_MS || timedOut) {
                    log('检测到播放结束，准备下一首（等待 ' + waited + 'ms）');
                    state.stopSince = 0;
                    state.expectEndAt = 0;
                    playNext();
                }
            }
            state.lastPlaying = isPlaying;
        }

        setInterval(function () {
            try { tick(); } catch (e) { warn('tick 异常', e && e.message); }
        }, TICK_MS);

        // v19：播放看门狗 —— 真机日志显示：App 冷启动 15s 内发出的 play
        // 被原生接受（songPlayStart 上报、无任何错误）但 live player
        // position 恒 0、壁纸循环未停；唯一成功的官方播放发生在启动
        // 11 分钟后。说明原生媒体管线就绪时间远晚于页面就绪。
        // 每 10s 检查进度推进，停滞超 30s 自动换下一首重试。
        // v21：双证据 —— store 进度（pg）或直接观测的播放器 position
        // （liveStats）任一在推进即视为正常播放。
        var wd = { maxPg: -1, maxLive: -1, lastAdvance: 0 };
        setInterval(function () {
            try {
                if (!state.autoOn || !state.queue.length) return;
                var pg = 0, lv = -1;
                try { pg = Number(player.songProgress) || 0; } catch (e) { }
                try { lv = Number(liveStats.pos) || 0; } catch (e) { }
                var now = Date.now();
                if (pg > wd.maxPg + 0.5 || lv > wd.maxLive + 0.5) {
                    // 进度在推进 → 一切正常
                    wd.maxPg = Math.max(wd.maxPg, pg);
                    wd.maxLive = Math.max(wd.maxLive, lv);
                    wd.lastAdvance = now;
                    return;
                }
                if (!wd.lastAdvance) { wd.lastAdvance = now; return; }
                if (now - wd.lastAdvance > 30000) {
                    log('播放进度停滞超过 30s（pg=' + pg + ' lv=' + lv +
                        '），重试下一首');
                    wd.maxPg = -1;
                    wd.maxLive = -1;
                    wd.lastAdvance = now;
                    playNext();
                }
            } catch (e) { }
        }, 10000);

        return {
            state: state,
            catalogs: catalogs,
            buildQueue: buildQueue,
            start: start,
            stop: stop,
            playNext: playNext,
            songName: songName,
            currentSong: currentSong,
            songKey: songKey,
            syncIndexToCurrent: syncIndexToCurrent,
            adoptCurrent: adoptCurrent,
            playIndex: playIndex,
            setMode: function (m) { state.mode = m; },
            setSource: function (s) { state.source = s; buildQueue(); }
        };
    }

    // ---------------------------------------------------------------------
    // 4. 浮层 UI（原生 DOM，挂在 body 下，不受 Vue 重渲染影响）
    // ---------------------------------------------------------------------
    function buildUI(ctl, catalogs, offlineStore) {
        // 先建一次队列，让面板一出现就能显示真实曲数，便于确认识别是否成功
        try { ctl.buildQueue(); } catch (e) { warn('初次建队列失败', e && e.message); }

        var wrap = document.createElement('div');
        wrap.id = 'olivia-autoplay';
        wrap.style.cssText = PANEL_CSS;

        var head = document.createElement('div');
        head.style.cssText = PANEL_HEAD_CSS + 'cursor:pointer;';
        var title = document.createElement('span');
        title.textContent = '♪ 自动连播';
        title.style.cssText = 'font-weight:600;font-size:13px';
        var fold = document.createElement('span');
        fold.textContent = '－';
        fold.style.cssText = 'opacity:.6;font-size:14px;line-height:1';
        head.appendChild(title);
        head.appendChild(fold);

        var body = document.createElement('div');
        body.style.cssText = 'padding:10px 12px 12px;display:flex;flex-direction:column;gap:9px';

        // 状态行
        var status = document.createElement('div');
        status.style.cssText = 'font-size:11.5px;color:#9aa0a6;line-height:1.45;word-break:break-all;min-height:32px';

        // 按钮通用样式
        function mkBtn(label, primary) {
            var b = document.createElement('button');
            b.textContent = label;
            b.style.cssText = 'flex:1;padding:6px 4px;font-size:12px;border-radius:7px;cursor:pointer;' +
                'border:1px solid rgba(255,255,255,.14);' +
                'background:' + (primary ? 'rgba(64,140,255,.9)' : 'rgba(255,255,255,.07)') + ';' +
                'color:#e8eaed;font-family:inherit;transition:background .15s';
            b.onmouseenter = function () { b.style.background = primary ? 'rgba(80,155,255,1)' : 'rgba(255,255,255,.14)'; };
            b.onmouseleave = function () { b.style.background = primary ? 'rgba(64,140,255,.9)' : 'rgba(255,255,255,.07)'; };
            return b;
        }

        // 模式选择
        var modeRow = document.createElement('div');
        modeRow.style.cssText = 'display:flex;gap:6px';
        var modeBtns = {};
        [MODE.REPEAT, MODE.SHUFFLE, MODE.SINGLE].forEach(function (m) {
            var b = mkBtn(MODE_LABEL[m], false);
            b.onclick = function () {
                ctl.setMode(m);
                try { if (ctl.state.queue.length) { } } catch (e) { }
                // 同步给官方 store，保持内外一致
                try { if (window.__oliviaPlayer) window.__oliviaPlayer.playMode = m; } catch (e) { }
                refreshMode();
            };
            modeBtns[m] = b;
            modeRow.appendChild(b);
        });

        function refreshMode() {
            Object.keys(modeBtns).forEach(function (m) {
                var on = ctl.state.mode === m;
                modeBtns[m].style.background = on ? 'rgba(64,140,255,.22)' : 'rgba(255,255,255,.07)';
                modeBtns[m].style.borderColor = on ? 'rgba(90,160,255,.75)' : 'rgba(255,255,255,.14)';
                modeBtns[m].style.color = on ? '#9dc4ff' : '#e8eaed';
            });
        }

        // 主控制行
        var mainRow = document.createElement('div');
        mainRow.style.cssText = 'display:flex;gap:6px';
        var btnStart = mkBtn('开始连播', true);
        var btnNext = mkBtn('下一首', false);
        mainRow.appendChild(btnStart);
        mainRow.appendChild(btnNext);

        btnStart.onclick = function () {
            if (ctl.state.autoOn) { ctl.stop(); }
            else {
                try { sessionStorage.removeItem('ap_manual_stop'); } catch (e) { }
                ctl.start();
            }
            refresh();
        };
        btnNext.onclick = function () {
            if (!ctl.state.autoOn) {
                try { sessionStorage.removeItem('ap_manual_stop'); } catch (e) { }
                ctl.start();
            }
            else { ctl.playNext(); }
            refresh();
        };

        // 曲目来源
        var sel = document.createElement('select');
        sel.style.cssText = 'width:100%;padding:5px 6px;font-size:12px;border-radius:7px;' +
            'background:rgba(255,255,255,.07);color:#e8eaed;border:1px solid rgba(255,255,255,.14);' +
            'font-family:inherit;outline:none';
        var optAuto = document.createElement('option');
        optAuto.value = 'auto';
        optAuto.textContent = '曲目范围：全部曲库';
        sel.appendChild(optAuto);
        // 下拉直接用 locateStores 排好的顺序（可播率优先，其次曲数）
        catalogs.forEach(function (c) {
            var o = document.createElement('option');
            o.value = c.id;
            o.textContent = '曲目范围：' + (c.label || c.id) + '（' + c.count + ' 首）';
            sel.appendChild(o);
        });
        var optPl = document.createElement('option');
        optPl.value = 'playlist';
        optPl.textContent = '曲目范围：当前播放列表';
        sel.appendChild(optPl);
        sel.onchange = function () { ctl.setSource(sel.value); refresh(); };

        // 提示
        var tip = document.createElement('div');
        tip.style.cssText = 'font-size:10.5px;color:#6f757c;line-height:1.4';
        tip.textContent = 'Ctrl+Alt+O 显示/隐藏 · 点击列表曲目可直接播放 · ' +
            '已识别 ' + catalogs.length + ' 个曲库';

        // v22.4：曲目列表 —— 可滚动、点击即播、当前曲目高亮并自动滚动到可见。
        // 这是此前面板缺失的部分（此前只能「盲播」，看不到队列内容）。
        var listBox = document.createElement('div');
        listBox.style.cssText = 'max-height:190px;overflow-y:auto;margin-top:8px;' +
            'border:1px solid rgba(255,255,255,.10);border-radius:8px;' +
            'background:rgba(0,0,0,.18)';
        var listRows = [];
        var listRenderedKey = '';

        function songMeta(s) {
            if (!s) return '';
            return s.composer || s.artist || s.singer || s.album || '';
        }

        function renderList() {
            var q = ctl.state.queue;
            var sig = q.length + ':' + ctl.state.index + ':' +
                (ctl.currentSong() ? ctl.songKey(ctl.currentSong()) : '') + ':' +
                (q.length ? ctl.songKey(q[0]) + '>' + ctl.songKey(q[q.length - 1]) : '');
            if (sig === listRenderedKey) return;
            listRenderedKey = sig;
            listBox.innerHTML = '';
            listRows = [];
            if (!q.length) {
                var empty = document.createElement('div');
                empty.style.cssText = 'padding:10px;font-size:11.5px;color:#6f757c';
                empty.textContent = '队列为空';
                listBox.appendChild(empty);
                return;
            }
            for (var i = 0; i < q.length; i++) {
                (function (idx) {
                    var row = document.createElement('div');
                    var on = idx === ctl.state.index;
                    var meta = songMeta(q[idx]);
                    row.style.cssText = 'display:flex;align-items:center;gap:6px;' +
                        'padding:5px 8px;cursor:pointer;font-size:12px;line-height:1.35;' +
                        (on ? 'background:rgba(64,140,255,.22);color:#dbe9ff;' :
                            'color:#c9cdd4;') +
                        (idx ? 'border-top:1px solid rgba(255,255,255,.06);' : '');
                    var num = document.createElement('span');
                    num.style.cssText = 'flex:0 0 26px;text-align:right;color:' +
                        (on ? '#9dc4ff' : '#5f6570') + ';font-size:11px';
                    num.textContent = String(idx + 1);
                    var txt = document.createElement('div');
                    txt.style.cssText = 'flex:1 1 auto;overflow:hidden';
                    var nm = document.createElement('div');
                    nm.textContent = ctl.songName(q[idx]);
                    nm.style.cssText = 'white-space:nowrap;overflow:hidden;' +
                        'text-overflow:ellipsis';
                    txt.appendChild(nm);
                    if (meta) {
                        var mt = document.createElement('div');
                        mt.textContent = meta;
                        mt.style.cssText = 'white-space:nowrap;overflow:hidden;' +
                            'text-overflow:ellipsis;font-size:10.5px;color:#6f757c';
                        txt.appendChild(mt);
                    }
                    row.appendChild(num);
                    row.appendChild(txt);
                    row.onclick = function () {
                        try {
                            if (!ctl.state.autoOn) {
                                try { sessionStorage.removeItem('ap_manual_stop'); } catch (e) { }
                                ctl.start();
                            }
                            ctl.playIndex(idx);
                            refresh();
                        } catch (e) { warn('点击曲目失败', e && e.message); }
                    };
                    listBox.appendChild(row);
                    listRows[idx] = row;
                })(i);
            }
            // 当前曲目滚动到可见位置
            try {
                if (ctl.state.index >= 0 && listRows[ctl.state.index]) {
                    var r = listRows[ctl.state.index];
                    var top = r.offsetTop - listBox.clientHeight / 2 + r.clientHeight / 2;
                    listBox.scrollTop = Math.max(0, top);
                }
            } catch (e) { }
        }

        body.appendChild(status);
        body.appendChild(modeRow);
        body.appendChild(mainRow);
        body.appendChild(sel);
        body.appendChild(listBox);
        body.appendChild(tip);

        wrap.appendChild(head);
        wrap.appendChild(body);

        head.onclick = function () {
            var hidden = body.style.display === 'none';
            body.style.display = hidden ? 'flex' : 'none';
            fold.textContent = hidden ? '－' : '＋';
        };

        document.body.appendChild(wrap);

        // 快捷键
        document.addEventListener('keydown', function (e) {
            if (e.ctrlKey && e.altKey && (e.key === 'o' || e.key === 'O')) {
                wrap.style.display = wrap.style.display === 'none' ? 'block' : 'none';
                e.preventDefault();
            }
        });

        function refresh() {
            var q = ctl.state.queue;
            var cur = ctl.currentSong();
            var pos = ctl.state.index >= 0 ? (ctl.state.index + 1) : 0;
            if (!q.length) {
                // 离线/未登录时曲库元数据拉不到，直接告诉用户怎么办
                var us = null;
                try { us = window.__oliviaStores && window.__oliviaStores['user']; } catch (e) { }
                if (us && us.isOfflineMode && !us.username) {
                    status.innerHTML =
                        '<div style="color:#ffb4a2;font-size:12.5px;margin-bottom:2px">离线模式 · 未登录</div>' +
                        '<div>请在应用内登录账号并关闭离线模式，曲库加载后自动就绪</div>';
                } else {
                    status.innerHTML =
                        '<div style="color:#ffb4a2;font-size:12.5px;margin-bottom:2px">未找到可播放曲目</div>' +
                        '<div>已识别 ' + catalogs.length + ' 个曲库，请先在应用内打开一次歌单</div>';
                }
            } else {
                status.innerHTML =
                    '<div style="color:#e8eaed;font-size:12.5px;margin-bottom:2px">' +
                    (ctl.state.autoOn
                        ? (cur ? ctl.songName(cur) : '准备中…')
                        : (cur ? '当前：' + ctl.songName(cur) +
                            '（未连播）' : '未开启 · 点「开始连播」')) +
                    '</div>' +
                    '<div>队列 ' + pos + '/' + q.length +
                    ' · ' + MODE_LABEL[ctl.state.mode] +
                    (ctl.state.autoOn ? ' · <span style="color:#7ee2a8">连播中</span>' : '') +
                    '</div>';
            }
            btnStart.textContent = ctl.state.autoOn ? '停止' : '开始连播';
            btnStart.style.background = ctl.state.autoOn ? 'rgba(220,80,90,.9)' : 'rgba(64,140,255,.9)';
            refreshMode();
            try { renderList(); } catch (e) { }
        }

        // v22.4：跟随外部（官方 UI）切歌 —— 与是否开启连播无关。
        // 用户在应用里手动切歌 / 点别的曲目时，队列索引与列表高亮自动
        // 跟到当前播放的那一首；若这首不在队列里则就地加入队列。
        var lastFollowKey = null;
        setInterval(function () {
            try {
                var cur = ctl.currentSong();
                if (!cur) return;
                var k = ctl.songKey(cur);
                if (!k || k === lastFollowKey) return;
                lastFollowKey = k;
                var before = ctl.state.index;
                if (!ctl.adoptCurrent() || ctl.state.index < 0) return;
                if (ctl.state.index !== before) {
                    log('已跟随手动切歌：' + ctl.songName(cur) +
                        '（队列位置 ' + (ctl.state.index + 1) + '/' +
                        ctl.state.queue.length + '）');
                    listRenderedKey = '';   // 强制重绘列表以更新高亮
                    try { renderList(); } catch (e) { }
                }
            } catch (e) { }
        }, 1000);

        ctl.refresh = refresh;
        refresh();
        setInterval(function () { try { refresh(); } catch (e) { } }, 1000);

        // v22.4：曲库动态补扫 —— 官方歌单 store 懒注册（伴奏歌单要用户
        // 打开过对应页面才出现），这里每 6s 重新扫一次 pinia，把新出现
        // 的曲库追加进下拉并更新提示里的曲库数。
        function rebuildCatalogOptions() {
            var keep = ctl.state.source;
            sel.innerHTML = '';
            var oa = document.createElement('option');
            oa.value = 'auto';
            oa.textContent = '曲目范围：全部曲库（' + ctl.state.queue.length + ' 首）';
            sel.appendChild(oa);
            catalogs.forEach(function (c) {
                var o = document.createElement('option');
                o.value = c.id;
                var n = 0;
                try { n = (c.store[c.key] || []).length; } catch (e) { }
                o.textContent = '曲目范围：' + (c.label || c.id) + '（' + n + ' 首）';
                sel.appendChild(o);
            });
            var op = document.createElement('option');
            op.value = 'playlist';
            op.textContent = '曲目范围：当前播放列表';
            sel.appendChild(op);
            sel.value = keep;
        }

        setInterval(function () {
            try {
                if (!gPinia) return;
                var f = locateStores(gPinia);
                var added = 0;
                f.catalogs.forEach(function (c) {
                    var exist = catalogs.some(function (x) { return x.id === c.id; });
                    if (!exist) {
                        catalogs.push(c);
                        log('发现新曲库：' + c.id + '（' + (c.label || '') + '，' +
                            ((c.store[c.key] || []).length) + ' 首）');
                        added++;
                    }
                });
                if (added) rebuildCatalogOptions();
            } catch (e) { }
        }, 6000);
        // 曲库就绪自愈：曲库是懒加载的，这里定期检查 —— 队列空时
        // 重触发官方 fetchSongList 并重建队列，数据一到就自动填上。
        // 若直接调 API 仍拉不到（登录态/时机问题），则借用 Vue 路由把
        // 应用导航到曲库页面，让页面组件自己的 onMounted 去加载，
        // 数据到达后自动跳回原页面。
        var NAV_ROUTES = ['solo-list', 'playsing-list', 'instrumental-list'];
        var nav = { tries: 0, fromName: null, waitingSince: 0 };

        setInterval(function () {
            try {
                if (ctl.state.autoOn) return;

                // ① v22.4：不再自动开播 —— 一律等用户点「开始连播」。
                // 队列就绪即停止轮询尝试，面板按钮会提示可开始。
                if (ctl.state.queue.length) return;

                // ② 队列空 → 尝试拉取曲库数据
                var total = 0;
                catalogs.forEach(function (c) {
                    try { total += (c.store[c.key] || []).length; } catch (e) { }
                });

                if (total > 0) {
                    // 数据到了：回到原页面并建队列
                    if (nav.fromName) {
                        var back = nav.fromName;
                        var r0 = getRouter();
                        if (r0) { try { r0.push({ name: back }); } catch (e) { } }
                        nav.fromName = null;
                        log('曲库数据已到达，已跳回 ' + back);
                    }
                    ctl.buildQueue();
                } else {
                    // 无数据：先直接调官方加载方法
                    catalogs.forEach(function (c) {
                        try {
                            if (typeof c.store.fetchSongList === 'function' &&
                                !(c.store[c.key] || []).length) {
                                c.store.fetchSongList();
                            }
                        } catch (e) { }
                    });
                    // 离线曲库加载（幂等，原生 getOfflineSongList 桥接）
                    try {
                        if (offlineStore && !(offlineStore.songs || []).length &&
                            typeof offlineStore.load === 'function') {
                            offlineStore.load();
                        }
                    } catch (e) { }
                    ctl.buildQueue();
                }

                // ③ 仍无数据 → 自动导航到曲库页（每 15s 一个候选，循环尝试）

                // 仍无数据 → 自动导航到曲库页（每 15s 一个候选，循环尝试）
                var r = getRouter();
                if (!r) return;
                if (nav.fromName && !nav.waitingSince) nav.waitingSince = Date.now();
                // 若正在曲库页等待且未超时（45s），先不给它换页
                if (nav.fromName && Date.now() - nav.waitingSince < 45000) return;
                if (nav.fromName && Date.now() - nav.waitingSince >= 45000) {
                    nav.tries++; nav.fromName = null; nav.waitingSince = 0;
                }
                var cur = (r.currentRoute && r.currentRoute.value) ? r.currentRoute.value.name : null;
                var target = NAV_ROUTES[nav.tries % NAV_ROUTES.length];
                if (cur === target) return;
                if (!nav.fromName) nav.fromName = cur || 'home';
                try {
                    r.push({ name: target });
                    nav.waitingSince = Date.now();
                    log('自动导航到 ' + target + ' 以加载曲库');
                } catch (e) { }
            } catch (e) { }
        }, 15000);
        return wrap;
    }

    // ---------------------------------------------------------------------
    // 5. 等待面板：脚本一加载就出现，便于确认注入是否生效
    // ---------------------------------------------------------------------
    function buildWaitingUI() {
        var wrap = document.createElement('div');
        wrap.id = 'olivia-autoplay-wait';
        wrap.style.cssText = PANEL_CSS;

        var head = document.createElement('div');
        head.style.cssText = PANEL_HEAD_CSS;
        var t = document.createElement('span');
        t.textContent = '♪ 自动连播';
        t.style.cssText = 'font-weight:600;font-size:13px';
        head.appendChild(t);

        var body = document.createElement('div');
        body.style.cssText = 'padding:10px 12px 12px';
        var msg = document.createElement('div');
        msg.style.cssText = 'font-size:11.5px;color:#9aa0a6;line-height:1.5';
        msg.textContent = '等待应用就绪…';
        body.appendChild(msg);

        // 诊断区（失败时才显示）：把扫到的 store 直接列出来，
        // 省去开 DevTools 才能排查的麻烦
        var detail = document.createElement('div');
        detail.style.cssText = 'display:none;margin-top:8px;max-height:150px;overflow:auto;' +
            'background:rgba(0,0,0,.28);border-radius:6px;padding:7px 8px;' +
            'font:11px/1.45 Consolas,Monaco,monospace;color:#8ab4f8;white-space:pre-wrap;' +
            'word-break:break-all;user-select:text';
        body.appendChild(detail);

        var copyBtn = document.createElement('button');
        copyBtn.textContent = '复制诊断信息';
        copyBtn.style.cssText = BTN_CSS + 'display:none;width:100%;margin-top:8px';
        copyBtn.onclick = function () {
            try {
                navigator.clipboard.writeText(detail.textContent);
                copyBtn.textContent = '已复制 ✓';
                setTimeout(function () { copyBtn.textContent = '复制诊断信息'; }, 1500);
            } catch (e) {
                try { window.prompt('复制以下内容', detail.textContent); } catch (e2) { }
            }
        };
        body.appendChild(copyBtn);

        wrap.appendChild(head);
        wrap.appendChild(body);
        document.body.appendChild(wrap);

        return {
            setMessage: function (text) { try { msg.textContent = text; } catch (e) { } },
            showDetail: function (text) {
                try {
                    detail.textContent = text;
                    detail.style.display = 'block';
                    copyBtn.style.display = 'block';
                } catch (e) { }
            },
            destroy: function () { try { wrap.parentNode.removeChild(wrap); } catch (e) { } }
        };
    }

    // ---------------------------------------------------------------------
    // 6. 启动
    // ---------------------------------------------------------------------
    log('脚本已载入，等待应用就绪…');
    setDiag('waiting');
    var waitUI = buildWaitingUI();

    waitPinia(90000).then(function (pinia) {
        if (!pinia) {
            setDiag('fail', 'no-pinia');
            waitUI.setMessage('未能读取应用状态（超时 90 秒）。请重启应用后重试。');
            warn('未能获取 pinia，自动连播不可用');
            return;
        }
        gPinia = pinia;
        var found = locateStores(pinia);
        setDiag('stores', 'n=' + Object.keys(found.all).length +
            ' cat=' + found.catalogs.length);
        // 深度诊断：把每个 store 的字段名与数组长度 dump 出来，
        // 外部从内存即可读取（title 通道不通到窗口标题，但字符串会留在内存）
        // v22.4：把 pinia 全貌直接打进 Olivia 日志（分条输出，便于外部
        // 查阅哪些 store 是曲库、字段叫什么、各有多少首），用于确认
        // 「三个官方歌单」是否都被识别到。
        try {
            Object.keys(found.all).forEach(function (id) {
                var s = found.all[id];
                if (!s) return;
                var lens = [];
                ['songList', 'songs', 'list', 'items', 'playlist'].forEach(function (k) {
                    try {
                        if (s[k] && Array.isArray(s[k])) lens.push(k + '=' + s[k].length);
                    } catch (e) { }
                });
                var cat = pickCatalogArray(s);
                log('store[' + id + '] ' + (cat ? '曲库:' + cat.key + '(' + cat.list.length + ')'
                    : '—') + ' ' + lens.join(','));
            });
        } catch (e) { }
        if (!found.player) {
            setDiag('fail', 'no-player');
            waitUI.setMessage('未找到播放模块。应用版本可能已变化。');
            // 把扫到的 store 与它们的能力列出来，便于定位匹配条件为何落空
            var lines = ['已扫描 ' + Object.keys(found.all).length + ' 个 store：'];
            Object.keys(found.all).forEach(function (id) {
                var s = found.all[id];
                if (!s) return;
                var r = scorePlayerStore(s);
                var cat = pickCatalogArray(s);
                lines.push('- ' + id + '  [播放分 ' + r.score + ']' +
                    (cat ? '  [曲库 ' + cat.key + ' × ' + cat.list.length + ']' : ''));
            });
            waitUI.showDetail(lines.join('\n'));
            warn('未找到播放 store；已扫描 store：' + Object.keys(found.all).join(','));
            return;
        }

        window.__oliviaPlayer = found.player;
        window.__oliviaStores = found.all;
        window.__oliviaDiag = function () {
            return {
                playerId: found.playerId,
                catalogs: found.catalogs.map(function (c) {
                    return { id: c.id, key: c.key, count: (c.store[c.key] || []).length };
                }),
                allStoreIds: Object.keys(found.all)
            };
        };
        log('已定位播放 store = ' + found.playerId + '；曲库 store：' +
            found.catalogs.map(function (c) { return c.id + '(' + c.key + ')'; }).join(', '));

        var ctl = createController(found.player, found.catalogs, found.downloads,
            found.offline, found.offlineId);
        window.__oliviaAutoPlay = ctl;      // 便于在控制台调试
        waitUI.destroy();
        buildUI(ctl, found.catalogs, found.offline);
        // 面板就绪后周期把各曲库实时条数与队列数写进诊断串
        setInterval(function () {
            try {
                var cs = found.catalogs.map(function (c) {
                    var n = -1;
                    try { n = (c.store[c.key] || []).length; } catch (e) { }
                    return c.id + '=' + n;
                }).join(',');
                try {
                    var us = found.all['user'];
                    if (us) cs += ' user=' + (us.username || 'null') +
                        ' off=' + us.isOfflineMode;
                } catch (e) { }
                try {
                    var us2 = found.all['user'];
                    if (us2) {
                        cs += ' am=' + (us2.appMode !== undefined ? us2.appMode : '?') +
                            ' gl=' + (us2.gloabalLoading !== undefined ?
                                us2.gloabalLoading : '?');
                    }
                } catch (e) { }
                // 离线曲库实时条数（v16/v17 队列首选数据源）
                try {
                    var ocN = offlineData.songs.length;
                    if (!ocN && found.offline) {
                        ocN = (found.offline.songs || []).length;
                    }
                    cs += ' oc=' + ocN;
                } catch (e) { }
                try {
                    var r = getRouter();
                    var rt = (r && r.currentRoute && r.currentRoute.value) || {};
                    cs += ' rt=' + (rt.name || rt.path || '?');
                } catch (e) { cs += ' rt=!'; }
                var curSong = '-';
                try {
                    var c2 = ctl.currentSong();
                    if (c2) curSong = ctl.songName(c2);
                } catch (e) { }
                // 播放进度：真播放时 pg 会持续增长
                var pg = -1, dur = -1;
                try { pg = Number(window.__oliviaPlayer.songProgress) || 0; } catch (e) { }
                try { dur = Number(window.__oliviaPlayer.nowPlayingDuration) || 0; } catch (e) { }
                // v21：直接观测的播放器 position 与事件计数
                try {
                    cs += ' lv=' + liveStats.pos + '/' + liveStats.maxPos +
                        ' ev=' + liveStats.events;
                } catch (e) { }
                setDiag(ctl.state.autoOn ? 'on' : 'ready',
                    cs + ' q=' + ctl.state.queue.length + ' cur=' + curSong +
                    ' pg=' + pg.toFixed(1) + ' dur=' + dur.toFixed(0));
            } catch (e) { }
            // v17：桥接取数重试 —— 启动极早期调用会被原生拒绝
            // （真机日志：ContainerBridge "Query action not found"，
            // Studio 控制器晚于页面就绪），必须持续重试直到成功
            try {
                if (!offlineData.songs.length && !offlineData.fetching) {
                    ensureOfflineData();
                }
            } catch (e) { }
            // v17：元数据队列接管 —— 桥接数据到达后，把仍在跑的
            // 缓存目录兜底队列替换成完整元数据队列（兜底队列原生
            // 从不真播，pg 恒 0，重建/重启无感）。仅在原生确实
            // 没有播放进度时才动手，避免打断真实播放。
            try {
                if (ctl.state.source === 'auto' &&
                    offlineData.songs.length && ctl.state.queue.length &&
                    ctl.state.queue[0] &&
                    ctl.state.queue[0].videoByTodView === undefined) {
                    var pgNow = -1;
                    try { pgNow = Number(window.__oliviaPlayer.songProgress) || 0; } catch (e) { }
                    if (pgNow < 0.5) {
                        ctl.buildQueue();
                        if (ctl.state.autoOn) ctl.start();
                        log('离线曲库元数据已接管队列（' +
                            ctl.state.queue.length + ' 首）');
                    }
                }
            } catch (e) { }
        }, 5000);
        log('自动连播面板已就绪');
    }).catch(function (e) {
        setDiag('fail', (e && e.message) ? String(e.message).slice(0, 40) : 'unknown');
        waitUI.setMessage('初始化失败：' + (e && e.message ? e.message : e));
        try { waitUI.showDetail((e && e.stack) ? e.stack : String(e)); } catch (e2) { }
        warn('初始化失败', e && e.message);
    });

})();
