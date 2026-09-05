/**
 * mail_server.js — Olivia Lin 离线「写信」mock 后端
 *
 * 游戏前端的写信/收信功能全部走 REST：
 *   POST /letter/send         {content, material:{stampId}}  -> {letterId}
 *   GET  /letter/list?pageSize=  -> {list:[...], remainingToday, total}
 *   GET  /letter/detail?letterId= -> 单封信 + 回信
 *   GET  /letter/unread_count -> {count}
 *   POST /letter/resend       {letterId} -> {shareId?}
 *   POST /letter/share        {letterId} -> {shareId}
 *
 * 真实后端已下线，这里由本机 Node 接管。autoplay.js 会把游戏内所有
 * /letter/* 请求劫持到 http://127.0.0.1:8787。
 *
 * Olivia 的回信：根据来信内容做轻量个性化（摘取关键词）+ 一组温柔人设模板。
 *
 * 运行：node mail_server.js   （已用托管 node，无第三方依赖）
 */
const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = 8787;
const DATA_FILE = path.join(__dirname, 'mail_data.json');

// ---- 持久化 ----
let store = { letters: [] };
try { store = JSON.parse(fs.readFileSync(DATA_FILE, 'utf8')); } catch (e) { /* 首次运行 */ }
function save() { fs.writeFileSync(DATA_FILE, JSON.stringify(store, null, 2)); }

// ---- Olivia 人设回信模板 ----
// 变量：{kw} 从来信中提取的关键词；{len} 来信字数
const REPLY_TEMPLATES = [
  '收到你的信啦，{kw}。我抱着膝盖在窗边读了一遍又一遍——能被你这样惦记着，真好。',
  '关于「{kw}」……其实我也有过同样的念头呢。夜深的时候，琴键比任何人都诚实。',
  '你的字句我都收下了。{kw} 这种心情，我懂的。下次练习时，我会为你多弹一小段。',
  '读着读着就笑了。{kw}——你总是能把最普通的事说得这么温柔。',
  '谢谢你还愿意写信给我。{kw} 的事，别太为难自己，好吗？我在这儿呢。',
  '今天练琴的时候一直想着你的话。{kw}，嗯，我记下了。要一直好好的呀。'
];
const KEYWORDS = ['钢琴', '曲子', '想你', '练习', '夜晚', '歌', '心情', '梦', '寂寞', '星星', '雨', '旋律', '你'];

function pickReply(text) {
  const t = (text || '').trim();
  let kw = '';
  for (const k of KEYWORDS) { if (t.includes(k)) { kw = k; break; } }
  if (!kw) {
    const m = t.match(/[一-龥]{2,4}/);   // 抓前几个连续汉字当关键词
    kw = m ? m[0] : '那些话';
  }
  const tpl = REPLY_TEMPLATES[Math.abs(hash(t)) % REPLY_TEMPLATES.length];
  return tpl.replace('{kw}', kw);
}
function hash(s) { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return h; }

function nowSec() { return Math.floor(Date.now() / 1000); }

function makeLetterId() { return 'loc_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }

// ---- 请求体解析 ----
function readBody(req) {
  return new Promise((resolve) => {
    let buf = '';
    req.on('data', (c) => (buf += c));
    req.on('end', () => {
      try { resolve(buf ? JSON.parse(buf) : {}); } catch (e) { resolve({}); }
    });
  });
}

function send(res, code, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(code, {
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
    'Access-Control-Allow-Headers': '*'
  });
  res.end(body);
}

const server = http.createServer(async (req, res) => {
  if (req.method === 'OPTIONS') { return send(res, 204, {}); }
  const url = new URL(req.url, `http://127.0.0.1:${PORT}`);
  const p = url.pathname;
  console.log(`[mail] ${req.method} ${p}`);

  try {
    if (p === '/letter/send' && req.method === 'POST') {
      const b = await readBody(req);
      const content = (b.content || '').toString();
      const stampId = (b.material && b.material.stampId) || (b.stampId) || 's1';
      const id = makeLetterId();
      const letter = {
        letterId: id,
        isRead: 1,
        letterStatus: 'REPLIED',
        auditStatus: 'PASS',
        summary: content.slice(0, 20),
        createdAt: nowSec(),
        replyType: 'TEXT',
        repliedAt: nowSec() + 1,
        replyText: pickReply(content),
        replyVideoUrl: '',
        content
      };
      store.letters.unshift(letter);
      save();
      return send(res, 200, { letterId: id });
    }

    if (p === '/letter/list' && req.method === 'GET') {
      const list = store.letters.map((e) => ({
        letterId: e.letterId,
        isRead: e.isRead,
        letterStatus: e.letterStatus,
        auditStatus: e.auditStatus,
        summary: e.summary,
        createdAt: e.createdAt,
        replyType: e.replyType,
        repliedAt: e.repliedAt,
        replyText: e.replyText,
        replyVideoUrl: e.replyVideoUrl || undefined
      }));
      return send(res, 200, { list, remainingToday: 99, total: list.length });
    }

    if (p === '/letter/detail' && req.method === 'GET') {
      const id = url.searchParams.get('letterId');
      const e = store.letters.find((x) => x.letterId === id);
      if (!e) return send(res, 200, { letterId: id, letterStatus: 'NONE', auditStatus: 'PASS', summary: '', createdAt: nowSec(), replyType: 'NONE' });
      return send(res, 200, {
        letterId: e.letterId, isRead: 1, letterStatus: e.letterStatus, auditStatus: e.auditStatus,
        summary: e.summary, createdAt: e.createdAt, replyType: e.replyType, repliedAt: e.repliedAt,
        replyText: e.replyText, replyVideoUrl: e.replyVideoUrl || undefined, content: e.content
      });
    }

    if (p === '/letter/unread_count' && req.method === 'GET') {
      return send(res, 200, { count: 0 });
    }

    if (p === '/letter/resend' && req.method === 'POST') {
      return send(res, 200, { shareId: 'loc_share_' + nowSec() });
    }

    if (p === '/letter/share' && req.method === 'POST') {
      return send(res, 200, { shareId: 'loc_share_' + nowSec() });
    }

    // 兜底
    return send(res, 200, {});
  } catch (e) {
    console.error('[mail] error', e);
    return send(res, 500, { message: 'mock server error' });
  }
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[mail] Olivia 离线信箱已启动 → http://127.0.0.1:${PORT}`);
  console.log(`[mail] 已存信件: ${store.letters.length} 封`);
});
