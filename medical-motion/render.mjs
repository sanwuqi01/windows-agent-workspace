import { execFileSync } from 'node:child_process';
import { access, copyFile, mkdir, mkdtemp, readFile, rename, rm } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { existsSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

async function main([input, target, seconds, ...extra]) {
  if (!input || !target || extra.length) throw new Error('用法：render.cmd 镜头.html 新输出目录');
  const html = path.resolve(input);
  await access(html);
  const state = JSON.parse(await readFile(path.join(process.env.LOCALAPPDATA, 'openmotion', 'install.json'), 'utf8'));
  const appModule = name => import(pathToFileURL(path.join(state.appRoot, name)).href);
  const native = await appModule('scripts/npm-runtime.mjs');
  const alternatives = {
    HYPERFRAMES_BROWSER_PATH: [process.env['ProgramFiles(x86)'], 'Microsoft/Edge/Application/msedge.exe'],
    HYPERFRAMES_FFMPEG_PATH: [os.homedir(), 'ffmpeg-dl/bin/ffmpeg.exe'],
    HYPERFRAMES_FFPROBE_PATH: [os.homedir(), 'ffmpeg-dl/bin/ffprobe.exe'],
  };
  const overrides = { ...process.env };
  await native.configureNativeEnvironment(state.appRoot);
  for (const [key, [base, relative]] of Object.entries(alternatives)) {
    if (process.env[key] && existsSync(process.env[key])) continue;
    const fallback = base && path.join(base, relative);
    if (overrides[key] || !fallback || !existsSync(fallback)) throw new Error('缺少可执行文件，请设置 ' + key);
    process.env[key] = fallback;
  }
  process.env.PATH = [path.dirname(process.env.HYPERFRAMES_FFMPEG_PATH),
    path.dirname(process.env.HYPERFRAMES_FFPROBE_PATH), process.env.PATH].join(path.delimiter);
  const { runHyperframes, snapshotExportExpectation } = await appModule('hyperframes.ts');
  const output = path.resolve(target);
  await mkdir(path.dirname(output), { recursive: true });
  // An interrupted render can reuse its saved project, but a finished movie is immutable.
  if (existsSync(output)) {
    if (!existsSync(path.join(output, 'project', 'index.html')) || existsSync(path.join(output, 'motion.mp4')))
      throw new Error('输出目录已存在，且不是可续渲染的失败镜头');
  } else {
    await mkdir(output);
  }
  const lock = path.join(output, '.render-lock');
  await mkdir(lock);
  let stage;
  try {
    stage = await mkdtemp(path.join(output, '.render-'));
    const project = path.join(output, 'project');
    await mkdir(path.join(project, 'assets'), { recursive: true });
    if (html !== path.join(project, 'index.html')) await copyFile(html, path.join(project, 'index.html'));
    await copyFile(path.join(state.appRoot, 'node_modules/gsap/dist/gsap.min.js'), path.join(project, 'assets/gsap.min.js'));
    const expected = await snapshotExportExpectation(state.appRoot, project);
    if (seconds && (expected.duration !== Number(seconds) || expected.width !== 1080 ||
        expected.height !== 1920 || expected.fps !== 30)) throw new Error('DSH 输出规格与要求不符');
    const movie = path.join(stage, 'motion.mp4');
    const result = await runHyperframes(state.appRoot, project, ['render', '.', '--output', movie, '--fps', String(expected.fps), '--workers', '1', '--strict'], 600000);
    if (result.code) throw new Error((result.stderr + '\n' + result.stdout).slice(-3000));
    const probe = JSON.parse(execFileSync(process.env.HYPERFRAMES_FFPROBE_PATH,
      ['-v', 'error', '-show_streams', '-show_format', '-of', 'json', movie], { encoding: 'utf8' }));
    const video = probe.streams.find(stream => stream.codec_type === 'video');
    const duration = Number(video?.duration);
    const [frames, secondsPerRate] = (video?.avg_frame_rate ?? '').split('/').map(Number);
    const fps = frames / secondsPerRate;
    if (video?.codec_name !== 'h264' || video.width !== expected.width || video.height !== expected.height ||
        !Number.isFinite(fps) || Math.abs(fps - expected.fps) > 0.001 ||
        !Number.isFinite(duration) || Math.abs(duration - expected.duration) > 1 / expected.fps ||
        probe.streams.some(stream => stream.codec_type === 'audio')) {
      throw new Error('输出规格与无声动效镜头不符：' + JSON.stringify(video));
    }
    await rename(movie, path.join(output, 'motion.mp4'));
    console.log(path.join(output, 'motion.mp4'));
  } finally {
    if (stage) await rm(stage, { force: true, recursive: true, maxRetries: 6, retryDelay: 400 }).catch(error => console.error(error.message));
    await rm(lock, { force: true, recursive: true });
  }
}
main(process.argv.slice(2)).catch(error => { console.error(error.message); process.exitCode = 1; });
