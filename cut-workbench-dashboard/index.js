/**
 * Host half of the cut-workbench dashboard bundle.
 * Scans the F:\agent workspace for batch/episode progress and serves it
 * as JSON through the webServer service; the Client half renders the panel.
 */
import fs from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';

const ROOT = 'F:\\agent';

function list(dir, optional = false) {
  try { return fs.readdirSync(dir, { withFileTypes: true }); }
  catch (e) { if (optional && e.code === 'ENOENT') return []; throw e; }
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
}

// 文件名含扩展名，逐字匹配。主体和单期编号由交付者登记，不从标题推测。
function loadLedger(dir, batch) {
  let data;
  try { data = readJson(path.join(dir, '交付清单.json')); }
  catch (e) { return { note: e.code === 'ENOENT' ? '待登记' : '清单无法读取' }; }
  if (data?.version !== 1 || data.batch !== batch || !Array.isArray(data.episodes))
    return { note: '清单格式或批次不符' };
  const entries = new Map(), ids = new Set(), conflicts = new Set();
  for (const row of data.episodes) {
    if (!row || ![row.subject, row.episode, row.dst].every(v => typeof v === 'string' && v.trim()))
      return { note: '清单缺少单期身份' };
    const id = JSON.stringify([row.subject, row.episode]);
    if (ids.has(id)) conflicts.add(id);
    ids.add(id);
    entries.set(row.dst, entries.has(row.dst) ? null : { row, id });
  }
  return { entries, conflicts };
}

function filePath(ref, dir) {
  return typeof ref === 'string' && ref.trim() ? path.resolve(dir, ref) : null;
}
function nonempty(ref, dir) {
  const file = filePath(ref, dir);
  if (!file) return false;
  try { const stat = fs.statSync(file); return stat.isFile() && stat.size > 0; }
  catch { return false; }
}
function draftDigest(ref, dir, cache) {
  const file = filePath(ref, dir);
  if (!file || path.basename(file) !== 'draft_content.json') return null;
  if (!cache.has(file)) {
    let digest = null;
    try {
      const bytes = fs.readFileSync(file);
      const draft = JSON.parse(bytes.toString('utf8').replace(/^\uFEFF/, ''));
      if (draft.tracks?.some(t => t.type === 'video' && Array.isArray(t.segments) && t.segments.length))
        digest = createHash('sha256').update(bytes).digest('hex');
    } catch { /* 未生成、写入中或不可读：不计交付 */ }
    cache.set(file, digest);
  }
  return cache.get(file);
}
const labels = { edit: '口播工程', hl: '重点词', sfx: '音效', overlay: '空镜回填' };
export function buildData(root = ROOT) {
  const tagRoot = path.join(root, '广济医疗-医生IP-打标素材');
  const th = path.join(root, 'talking-head-auot-cut');
  const tasks = list(path.join(th, '任务'), true).filter(e => e.isFile() && /\.md$/i.test(e.name));
  const recycled = list(path.join(th, '运行记录', '剪映草稿回收'), true).filter(e => e.isDirectory()).map(e => e.name);
  const cache = new Map();
  const batches = list(tagRoot).filter(e => e.isDirectory()).map(({name}) => {
    const dir = path.join(tagRoot, name), ledger = loadLedger(dir, name);
    const episodes = list(dir).filter(e => e.isFile() && /\.(mov|mp4)$/i.test(e.name)).map(({name: dst}) => {
      const match = ledger.entries?.get(dst);
      const conflict = match === null || ledger.conflicts?.has(match?.id);
      const row = !conflict && match?.row;
      const note = conflict ? '清单身份冲突' : row ? '' : ledger.note || '待登记';
      const files = row?.files || {};
      const shotFiles = Array.isArray(files.shots) ? files.shots : [];
      const shots = new Set(shotFiles.filter(f => nonempty(f, dir)).map(f => filePath(f, dir))).size;
      const cover = nonempty(files.cover, dir);
      const digest = draftDigest(files.draft, dir, cache);
      const reviewed = !!digest && row.review?.sha256 === digest && typeof row.review?.reviewer === 'string' && !!row.review.reviewer.trim();
      const delivery = reviewed ? '已验收' : digest ? '已生成·待验收' : note || '无有效草稿';
      const steps = [{key:'tag', label:'打标素材', done:true},
        ...Object.entries(labels).map(([key,label]) => ({key,label,done:nonempty(files[key], dir)})),
        {key:'shot', label:'封面/空镜', done:cover && shots > 0},
        {key:'merge', label:'最终草稿', done:!!digest, status:delivery}];
      return {dst, title:dst.replace(/\.(mov|mp4)$/i,'').replace(/_打标$/,''), subject:row?.subject,
        episode:row?.episode, note, steps, shots, cover, generated:!!digest, reviewed};
    });
    return {name, videos:episodes.length, episodes};
  });
  return {generatedAt:new Date().toISOString(), root, batches, recycled, stats:{taskFiles:tasks.length,
    hlCount:tasks.filter(e => e.name.startsWith('hl-')).length, sfxCount:tasks.filter(e => e.name.startsWith('sfx-')).length,
    recycledBatches:recycled.length}};
}

export const inject = ['webServer'];

export function apply(ctx) {
  const webServer = ctx.get('webServer');
  if (webServer === undefined) throw new Error('webServer service unavailable');

  let disposer = () => {};
  try {
    disposer = webServer.register({
      kind: 'exact',
      path: '/api/cut-workbench/dashboard-v3',
      handler(req, res) {
        try {
          const data = buildData();
          res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
          res.end(JSON.stringify(data));
        } catch (error) {
          res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
          res.end(JSON.stringify({ error: String(error?.message ?? error) }));
        }
      },
    });
  } catch (error) {
    // A prior fiber's route may still be mounted after an HMR reload on this
    // Harness build; that instance keeps serving the same handler, so treat a
    // duplicate-route rejection as non-fatal.
    if (!String(error?.message ?? '').includes('duplicate exact route')) throw error;
  }
  return disposer;
}
