#!/usr/bin/env node
// kuaizi-cdp skill: storyboard planner
//
// 设计原则（2026-11-11 修订）：
//   1. 先读输入字幕/文稿的完整文本，而不是只看少量关键词。
//   2. 用医疗词命中判断内容属性：
//      - 命中强医疗词（疾病/解剖/检查/治疗/生殖等）→ 3D 建模医学动画风格
//      - 只有医院/医生/诊室等场景词 → 温馨写实，不强行 3D
//   3. 医疗文本：从原文抽取含医疗词的原句/短语，逐句生成，不凭空编造。
//   4. 非医疗文本：抽取可视觉化的原句，走温馨写实。
//   5. 输出数组，可直接喂 `generate.mjs batch`；分析元数据另写 `.meta.json`。
//
// Usage:
//   node storyboard.mjs plan <字幕.txt|文稿.md|关键词.json> [-n 6] [--out plan.json]
//   node storyboard.mjs plan --text "完整字幕文本" -n 6 --out plan.json
//   node storyboard.mjs plan <完整文稿> --shots <DSH整稿计划.json> --out <筷子批次.json>
//   node storyboard.mjs rules

import fs from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';

// ---------- 强医疗词：命中即按医疗内容处理，走 3D 医学动画 ----------
const STRONG_MEDICAL_TERMS = [
  '无精子症', '无精子', '少精', '弱精', '畸形精子', '精子', '精液', '精液常规',
  '生育力', '生育力保护', '不孕', '不育', '男性不育', '女性不孕',
  '卵巢', '子宫', '子宫内膜', '输卵管', '盆腔', '盆底', '盆底肌', '漏尿',
  '激素', '性激素', 'AMH', '超声', 'B超', '附件超声', '超声探头',
  '胚胎', '胎儿', '孕囊', '妊娠', '怀孕', '备孕', '孕周', '孕妇', '产妇',
  '流产', '药流', '人流', '宫外孕', '宫内', '早产', '产检',
  '试管婴儿', '辅助生殖',
  '诊断', '治疗', '手术', '微创', '化疗', '放疗', '药物', '用药', '服药', '剂量',
  '感染', '炎症', '肿瘤', '癌', '病变', '畸形', '遗传', '基因', '染色体',
  '免疫', '内分泌', '月经', '排卵', '检查', '化验', '指标', '病理', '解剖', '细胞',
];

// ---------- 场景词：只说明是医院场景，不等于医疗内容；不能单独触发 3D ----------
const CONTEXT_TERMS = [
  '医院', '医生', '主任', '诊室', '门诊', '患者', '夫妻', '护士', '病房',
  '手术室', '报告', '处方', '病历', '挂号', '科室', '走廊', '授牌', '牌匾',
  '联盟', '成员单位', '生殖中心', '生殖医学', '男科', '妇科', '产科',
];

const VISUAL_WORDS = [
  '夫妻', '丈夫', '妻子', '医生', '主任', '护士', '孩子', '婴儿', '家庭',
  '诊室', '走廊', '医院', '实验室', '报告', '检查', '抽血', '超声',
  '握手', '低头', '微笑', '点头', '拥抱', '走出', '坐在', '拿起', '递给',
  '阳光', '窗', '晨光', '牌匾', '授牌', '试管', '显微镜',
];

function uniq(list) {
  return [...new Set(list)];
}

function hits(text, terms) {
  const found = terms.filter(term => text.includes(term)).sort((a, b) => b.length - a.length);
  const kept = [];
  for (const term of found) {
    if (!kept.some(k => k.includes(term))) kept.push(term);
  }
  return kept;
}

function cleanInputText(text) {
  return String(text || '')
    .replace(/\r/g, '\n')
    .replace(/^[ \t]*#{1,6}[ \t]*/gm, '')
    .replace(/[（(][^）)]{0,60}[）)]/g, '')
    .replace(/^[ \t]*[-*•]\s+/gm, '')
    .replace(/^[ \t]*\d+[.、)]\s*/gm, '')
    .replace(/[ \t]+/g, ' ')
    .trim();
}

function analyzeText(text) {
  const strong = uniq(hits(text, STRONG_MEDICAL_TERMS));
  const context = uniq(hits(text, CONTEXT_TERMS));
  return {
    medical_related: strong.length > 0 || context.length > 0,
    medical_content: strong.length > 0,
    style: strong.length > 0 ? 'medical3d' : 'warmReal',
    strong_hits: strong,
    context_hits: context,
    char_count: text.length,
  };
}

function splitSentences(text) {
  return text
    .replace(/\r/g, '\n')
    .split(/[。！？!?；;\n]+/)
    .map(s => s.replace(/\s+/g, ' ').trim())
    .map(s => s.replace(/^[，,、：:]+|[，,、：:]+$/g, '').trim())
    .filter(s => s.length >= 4);
}

function splitClauses(text) {
  return text
    .replace(/\r/g, '\n')
    .split(/[。！？!?；;\n，,、]+/)
    .map(s => s.replace(/\s+/g, ' ').trim())
    .filter(s => s.length >= 4);
}

function scoreSentence(sentence, analysis) {
  const strong = hits(sentence, STRONG_MEDICAL_TERMS);
  const context = hits(sentence, CONTEXT_TERMS);
  const visual = hits(sentence, VISUAL_WORDS);
  let score = strong.length * 5 + context.length * 1.5 + visual.length * 1;
  if (sentence.length < 8) score -= 2;
  if (sentence.length > 80) score -= 2;
  return { score, strong, context, visual };
}

function selectSentences(text, analysis, max) {
  const all = splitClauses(text);
  const scored = all.map((sentence, index) => ({
    sentence,
    index,
    ...scoreSentence(sentence, analysis),
  }));

  let pool = scored;
  if (analysis.medical_content) {
    pool = scored.filter(x => x.strong.length > 0);
    // 医疗内容很强但原句都被切碎时，用含场景词/动作的句子兜底
    if (!pool.length) pool = scored.filter(x => x.context.length > 0 || x.visual.length > 0);
  } else {
    pool = scored.filter(x => x.visual.length > 0);
  }
  if (!pool.length) pool = scored;

  pool.sort((a, b) => (b.score - a.score) || (a.index - b.index));
  const picked = [];
  const seen = new Set();
  for (const row of pool) {
    const key = row.sentence.replace(/[^\u3400-\u9fffA-Za-z0-9]/g, '');
    if (!key || seen.has(key)) continue;
    seen.add(key);
    picked.push(row);
    if (picked.length >= max) break;
  }
  picked.sort((a, b) => a.index - b.index);
  return picked;
}

// Automatic extraction supplies review candidates. DSH can provide its semantic
// summary and concrete visual anchor with --shots before a paid batch.
function buildPrompt(summary, style, anchor) {
  const subject = summary.trim().replace(/[。，、！？；：,.!?;:]+$/u, '');
  const ending = style === 'medical3d'
    ? '生成合适的3D医学科普动画，画面里不要出现任何文字。'
    : '生成合适的写实摄影空镜，画面里不要出现任何文字，画面里不要出现人物。';
  return `${subject}，${anchor}。${ending}`;
}

function loadReviewedShots(filename, sourceText) {
  const plan = JSON.parse(fs.readFileSync(filename, 'utf8').replace(/^\uFEFF/, ''));
  const digest = createHash('sha256').update(sourceText.trim()).digest('hex');
  if (plan.source_sha256 && plan.source_sha256 !== digest) throw new Error('整稿与 DSH 计划来源不一致');
  const rows = plan.kuaizi_shots;
  if (!Array.isArray(rows)) throw new Error('--shots 文件缺少 kuaizi_shots 数组');
  return rows.map((row, i) => {
    const { source_sentence, summary, anchor, style } = row ?? {};
    if (typeof source_sentence !== 'string' || !source_sentence.trim() || !sourceText.includes(source_sentence)) {
      throw new Error(`第 ${i + 1} 镜的原句没有逐字出现在输入文稿中`);
    }
    if (typeof summary !== 'string' || !summary.trim() || /[。！？!?；;\r\n]/u.test(summary.trim().replace(/[。！？!?]$/u, ''))) {
      throw new Error(`第 ${i + 1} 镜需要一句完整的压缩口播`);
    }
    if (typeof anchor !== 'string' || !anchor.trim() || [...anchor.trim()].length > 15 ||
        /[\p{P}\s]/u.test(anchor)) throw new Error(`第 ${i + 1} 镜需要 1–15 字的单个机制或物象锚点`);
    if (!['medical3d', 'warmReal'].includes(style)) throw new Error(`第 ${i + 1} 镜的风格无效`);
    return {
      name: `镜${String(i + 1).padStart(2, '0')}`, type: 'video',
      prompt: buildPrompt(summary, style, anchor.trim()), keyword: anchor.trim(),
      reason: 'DSH 按完整口播选镜', style, source_sentence,
    };
  });
}

function buildItemsFromSentences(rows, styleOverride) {
  return rows.map((row, i) => {
    const style = styleOverride || (row.strong.length > 0 ? 'medical3d' : 'warmReal');
    return {
      name: `镜${String(i + 1).padStart(2, '0')}`,
      type: 'video',
      prompt: buildPrompt(row.sentence, style, row.strong[0] || row.visual[0] || row.sentence.slice(0, 15)),
      keyword: (row.strong[0] || row.sentence.slice(0, 12)).trim(),
      reason: `原文命中：${(row.strong.length ? row.strong : row.visual).slice(0, 4).join('、') || '可视觉化场景'}`,
      style,
      source_sentence: row.sentence,
    };
  });
}

function buildItemsFromKeywords(selections, analysis, styleOverride) {
  return selections.map((sel, i) => {
    const sentence = `${sel.keyword || ''}${sel.reason ? '：' + sel.reason : ''}`.trim();
    const style = styleOverride || (analysis.medical_content ? 'medical3d' : 'warmReal');
    return {
      name: `镜${String(i + 1).padStart(2, '0')}`,
      type: 'video',
      prompt: buildPrompt(sentence || sel.keyword || '医学科普空镜', style, (sel.keyword || sentence || '医学科普').slice(0, 15)),
      keyword: sel.keyword || '',
      reason: sel.reason || '',
      style,
      source_sentence: sentence,
    };
  });
}

function readTextInput(inputPath, inlineText) {
  if (inlineText && inlineText.trim()) {
    return { text: inlineText.trim(), source: 'inline' };
  }
  if (!inputPath) throw new Error('缺少输入：传字幕/文稿路径，或用 --text 传完整文本');
  const ext = path.extname(inputPath).toLowerCase();
  if (ext === '.json') {
    const j = JSON.parse(fs.readFileSync(inputPath, 'utf8').replace(/^\uFEFF/, ''));
    if (typeof j.text === 'string') return { text: j.text, source: inputPath };
    if (typeof j.transcript === 'string') return { text: j.transcript, source: inputPath };
    if (typeof j.script === 'string') return { text: j.script, source: inputPath };
    if (Array.isArray(j.cards)) {
      return { text: j.cards.map(x => (typeof x === 'string' ? x : x.text || '')).filter(Boolean).join('\n'), source: inputPath };
    }
    if (Array.isArray(j.subtitles)) {
      return { text: j.subtitles.map(x => (typeof x === 'string' ? x : x.text || '')).filter(Boolean).join('\n'), source: inputPath };
    }
    if (Array.isArray(j.selections)) {
      return {
        text: j.selections.map(x => `${x.keyword || ''}${x.reason ? '：' + x.reason : ''}`).join('\n'),
        source: inputPath,
        selections: j.selections,
      };
    }
    throw new Error('JSON 里没有 text / transcript / script / cards / subtitles / selections');
  }
  return { text: fs.readFileSync(inputPath, 'utf8'), source: inputPath };
}

export function makePlan(inputPath, { max = 6, videoSecs = 5, text = '', style = 'auto', shotsFile = null } = {}) {
  const input = readTextInput(inputPath, text);
  const sourceText = input.text.replace(/\r\n?/g, '\n');
  input.text = cleanInputText(input.text);
  const analysis = analyzeText(input.text);
  const styleOverride = style === 'medical3d' ? 'medical3d' : style === 'warmReal' ? 'warmReal' : null;

  let items;
  if (shotsFile) {
    items = loadReviewedShots(shotsFile, sourceText);
  } else if (input.selections && input.selections.length) {
    items = buildItemsFromKeywords(input.selections, analysis, styleOverride);
  } else {
    const rows = selectSentences(input.text, analysis, max);
    if (!rows.length) throw new Error('输入文本里没有可用的句子');
    items = buildItemsFromSentences(rows, styleOverride);
  }

  const meta = {
    schema: 'kuaizi-cdp/storyboard-plan@2',
    source: input.source,
    video: { resolution: '720p', aspect_ratio: '9:16', duration_sec: videoSecs },
    analysis,
    style_override: styleOverride || 'auto',
    selection: shotsFile ? 'reviewed-shots' : 'automatic-candidates',
    item_count: items.length,
  };
  return { items, meta };
}

// CLI
if (process.argv[1] && process.argv[1].endsWith('storyboard.mjs')) {
  const [cmd, ...rest] = process.argv.slice(2);
  if (cmd === 'rules') {
    console.log(`先读整期文稿，选择具体的医疗机制或无人物场景。
医疗：<原句压成一句>，<≤15字机制锚点>。生成合适的3D医学科普动画，画面里不要出现任何文字。
写实空景：改用写实摄影空镜并要求画面里不要出现人物。
把逐字原句、压缩句、锚点和风格放进 kuaizi_shots；plan 文稿 --shots 文件 --out 计划.json。
普通 plan 提供候选，提交前按原稿审阅。新主题先试一条、抽帧确认，再按现有流程放量。`);
  } else if (cmd === 'plan') {
    const args = [...rest];
    let input = null;
    let max = 6;
    let out = null;
    let shotsFile = null;
    let videoSecs = 5;
    let text = '';
    let style = 'auto';

    for (let i = 0; i < args.length; i++) {
      const a = args[i];
      if (a === '-n' || a === '--n' || a === '--max') max = parseInt(args[++i], 10);
      else if (a === '--shots') {
        shotsFile = args[++i];
        if (!shotsFile || shotsFile.startsWith('--')) { console.error('--shots 缺少文件路径'); process.exit(1); }
      }
      else if (a === '--out') out = args[++i];
      else if (a === '--video-secs') videoSecs = parseInt(args[++i], 10);
      else if (a === '--text') text = args[++i] || '';
      else if (a === '--style') style = args[++i] || 'auto';
      else if (!a.startsWith('-') && !input) input = a;
    }
    if (!input && !text) {
      console.error('usage: node storyboard.mjs plan <字幕.txt|文稿.md|关键词.json> [-n 6] [--text "..."] [--out plan.json]');
      process.exit(1);
    }
    if (!Number.isFinite(max) || max < 1) max = 6;
    if (max > 12) max = 12;

    try {
      const { items, meta } = makePlan(input, { max, videoSecs, text, style, shotsFile });
      const outFile = out || (input ? input.replace(/\.(json|txt|md)$/i, '') + '.storyboard-plan.json' : 'storyboard-plan.json');
      fs.writeFileSync(outFile, JSON.stringify(items, null, 2), 'utf8');
      fs.writeFileSync(outFile.replace(/\.json$/i, '') + '.meta.json', JSON.stringify(meta, null, 2), 'utf8');
      console.log('PLAN WRITTEN', outFile);
      console.log(`style=${meta.analysis.style} medical=${meta.analysis.medical_content} items=${items.length}`);
      if (meta.analysis.strong_hits.length) console.log('medical_hits:', meta.analysis.strong_hits.slice(0, 12).join('、'));
      for (const it of items) console.log(`  [${it.style}] ${it.keyword} → ${it.source_sentence.slice(0, 40)}`);
      console.log('\n[next] 人工审阅后: node generate.mjs batch ' + outFile);
    } catch (e) {
      console.error('ERR', e.message);
      process.exit(1);
    }
  } else {
    console.log('usage: storyboard.mjs plan <input> [-n 6] [--text "..."] [--out plan.json] | rules');
  }
}
