/**
 * Host half of the cut-workbench dashboard bundle.
 * Scans the F:\agent workspace for batch/episode progress and serves it
 * as JSON through the webServer service; the Client half renders the panel.
 */
import fs from 'node:fs';
import path from 'node:path';

const ROOT = 'F:\\agent';

function safeListDir(dir, depth = 1) {
  try {
    return fs.readdirSync(dir, { withFileTypes: true }).map((e) => ({
      name: e.name,
      isDir: e.isDirectory(),
    }));
  } catch {
    return [];
  }
}

function exists(p) {
  try { fs.statSync(p); return true; } catch { return false; }
}

/** 批次目录下的视频条目（.mp4/.mov/.MP4/.MOV 文件） */
function listBatchVideos(batchDir) {
  return safeListDir(batchDir)
    .filter((e) => !e.isDir && /\.(mp4|mov)$/i.test(e.name))
    .map((e) => e.name.replace(/\.(mp4|mov)$/i, ''));
}

/** 单期七步进度推断 */
function episodeProgress(title, ctx) {
  const steps = [];
  // ① 打标：打标素材批次里存在去掉 _打标 后缀的同名视频，或已经是标题名
  const tagged = ctx.taggedVideos.some((v) => v === title || v === `${title}_打标`);
  steps.push({ key: 'tag', label: '打标', done: tagged });
  // ② 口播工程：kbcg 任务输出目录（edit-* 任务根下）存在包含该标题的交付目录
  const spoken = ctx.editOutputRoots.some((root) =>
    safeListDir(root).some((d) => d.isDir && d.name.includes(title)));
  steps.push({ key: 'edit', label: '口播工程', done: spoken });
  // ③ 重点词
  const hl = ctx.highlightDirs.some((d) => d.includes(title));
  steps.push({ key: 'hl', label: '重点词', done: hl });
  // ④ 音效
  const sfx = ctx.sfxDirs.some((d) => d.includes(title));
  steps.push({ key: 'sfx', label: '音效', done: sfx });
  // ⑤ 空镜回填（overlay 目录带 空镜版）
  const overlay = ctx.overlayDirs.some((d) => d.includes(title));
  steps.push({ key: 'overlay', label: '空镜回填', done: overlay });
  // ⑥ 封面 + 空镜（空镜根目录下有该标题目录，且含 封面.png）
  const shotDir = path.join(ctx.shotRoot, title);
  const cover = exists(path.join(shotDir, '封面.png'));
  const shots = safeListDir(shotDir).filter((e) => /^镜\d+\.mp4$/i.test(e.name)).length;
  steps.push({ key: 'shot', label: '封面/空镜', done: cover && shots > 0 });
  steps.push({ key: 'merge', label: '合并交付', done: false });
  return { steps, cover, shots };
}

function buildData() {
  const tagRoot = path.join(ROOT, '广济医疗-医生IP-打标素材');
  const shotRoot = path.join(ROOT, '广济医疗-医生IP-空镜');
  const thRoot = path.join(ROOT, 'talking-head-auot-cut');
  const tasksDir = path.join(thRoot, '任务');
  const outputRoot = path.join(thRoot, '输出');
  const recycleRoot = path.join(thRoot, '运行记录', '剪映草稿回收');

  const batches = safeListDir(tagRoot)
    .filter((e) => e.isDir)
    .map((b) => {
      const batchDir = path.join(tagRoot, b.name);
      const taggedVideos = listBatchVideos(batchDir);
      // 收集各包装目录名（批次级一次）
      const subjectRoots = safeListDir(outputRoot).filter((e) => e.isDir).map((e) => e.name);
      const highlightDirs = [];
      const sfxDirs = [];
      const overlayDirs = [];
      const editOutputRoots = [];
      for (const subject of subjectRoots) {
        const hlRoot = path.join(outputRoot, subject, 'spoken-video-highlights');
        for (const sub of safeListDir(hlRoot)) {
          if (!sub.isDir) continue;
          for (const d of safeListDir(path.join(hlRoot, sub.name))) {
            highlightDirs.push(d.name);
          }
        }
        const sfxRoot = path.join(outputRoot, subject, 'spoken-video-sfx');
        for (const sub of safeListDir(sfxRoot)) {
          if (!sub.isDir) continue;
          for (const d of safeListDir(path.join(sfxRoot, sub.name))) {
            sfxDirs.push(d.name);
          }
        }
        const ovRoot = path.join(outputRoot, subject, 'spoken-video-overlay');
        for (const sub of safeListDir(ovRoot)) {
          if (!sub.isDir) continue;
          for (const d of safeListDir(path.join(ovRoot, sub.name))) {
            overlayDirs.push(d.name);
          }
        }
        const kbcgRoot = path.join(outputRoot, subject, 'kbcg-pipeline-win');
        for (const t of safeListDir(kbcgRoot)) {
          if (t.isDir) editOutputRoots.push(path.join(kbcgRoot, t.name));
        }
      }
      // 每期以打标目录中的视频标题为键
      const episodes = taggedVideos.map((raw) => {
        const title = raw.replace(/_打标$/, '');
        const ctx = {
          taggedVideos,
          editOutputRoots,
          highlightDirs,
          sfxDirs,
          overlayDirs,
          shotRoot,
        };
        // 合并交付：最终草稿名 = 批次名；在回收目录之外无法直接读剪映草稿箱，这里只看回收目录是否留有中间稿
        const p = episodeProgress(title, ctx);
        // merge 判定：批次内所有期其他 6 步全 done 且不存在于回收目录中间稿
        const allDone = p.steps.slice(0, 6).every((s) => s.done);
        p.steps[6].done = allDone;
        return { title, ...p };
      });
      // 任务统计
      const tasks = safeListDir(tasksDir)
        .filter((e) => !e.isDir && /\.md$/.test(e.name))
        .map((e) => e.name);
      return { name: b.name, videos: taggedVideos.length, episodes, };
    });

  const shotsByTitle = {};
  for (const ep of safeListDir(shotRoot).filter((e) => e.isDir)) {
    const dir = path.join(shotRoot, ep.name);
    shotsByTitle[ep.name] = {
      cover: exists(path.join(dir, '封面.png')),
      shots: safeListDir(dir).filter((e) => /^镜\d+\.mp4$/i.test(e.name)).length,
    };
  }

  const recycled = safeListDir(recycleRoot).filter((e) => e.isDir).map((e) => e.name);
  const taskFiles = safeListDir(tasksDir).filter((e) => !e.isDir && /\.md$/.test(e.name)).length;
  const hlCount = safeListDir(tasksDir).filter((e) => /^hl-/.test(e.name)).length;
  const sfxCount = safeListDir(tasksDir).filter((e) => /^sfx-/.test(e.name)).length;

  return {
    generatedAt: new Date().toISOString(),
    root: ROOT,
    batches,
    shotsByTitle,
    stats: { taskFiles, hlCount, sfxCount, recycledBatches: recycled.length },
    recycled,
  };
}

export const inject = ['webServer'];

export function apply(ctx) {
  const webServer = ctx.get('webServer');
  if (webServer === undefined) throw new Error('webServer service unavailable');

  let disposer = () => {};
  try {
    disposer = webServer.register({
      kind: 'exact',
      path: '/api/cut-workbench/dashboard-v2',
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
