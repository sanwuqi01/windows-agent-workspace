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
//   node storyboard.mjs rules

import fs from 'node:fs';
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

const MEDICAL_STYLE = '3D 建模医学动画风格，柔和的医学科普渲染，半透明解剖演示质感，洁净的浅蓝米白配色，圆润低多边形建模，专业不冰冷';
const WARM_STYLE = '温馨写实摄影质感，柔和自然光，浅景深，中国现代家庭生活场景，治愈氛围';
const HARD_CONSTRAINTS = '画面人物必须是中国人黄皮肤面孔，不得出现欧美或其他外国人面孔；符合中国大陆内容发布规范；无文字，无logo，无水印';

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

function sentenceTopic(sentence, maxLen = 60) {
  return sentence.length > maxLen ? sentence.slice(0, maxLen) : sentence;
}

function buildPrompt(sentence, style, keyword = '') {
  const topic = keyword || sentenceTopic(sentence);
  const medical = style === 'medical3d';
  if (medical) {
    return `${MEDICAL_STYLE}。9:16竖屏科普空镜，主题【${topic}】；原文语境【${sentenceTopic(sentence)}】。只表现这句原文中的医疗概念，不添加原文没有的疾病、治疗或疗效；画面干净专业，柔和洁净光照，不出现真实文字标注。${HARD_CONSTRAINTS}。`;
  }
  return `温馨写实摄影质感。9:16竖屏空镜，主题【${sentenceTopic(sentence)}】。${WARM_STYLE}。画面只表现原文中的场景与动作，不添加原文没有的信息；${HARD_CONSTRAINTS}。`;
}

function buildItemsFromSentences(rows, analysis, styleOverride) {
  return rows.map((row, i) => {
    const style = styleOverride || (row.strong.length > 0 ? 'medical3d' : analysis.style);
    return {
      name: `镜${String(i + 1).padStart(2, '0')}`,
      type: 'video',
      prompt: buildPrompt(row.sentence, style, row.strong[0] || ''),
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
      prompt: buildPrompt(sentence || sel.keyword || '医学科普空镜', style, sel.keyword || ''),
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
    const j = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
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

export function makePlan(inputPath, { max = 6, videoSecs = 5, text = '', style = 'auto' } = {}) {
  const input = readTextInput(inputPath, text);
  input.text = cleanInputText(input.text);
  const analysis = analyzeText(input.text);
  const styleOverride = style === 'medical3d' ? 'medical3d' : style === 'warmReal' ? 'warmReal' : null;

  let items;
  if (input.selections && input.selections.length) {
    items = buildItemsFromKeywords(input.selections, analysis, styleOverride);
  } else {
    const rows = selectSentences(input.text, analysis, max);
    if (!rows.length) throw new Error('输入文本里没有可用的句子');
    items = buildItemsFromSentences(rows, analysis, styleOverride);
  }

  const meta = {
    schema: 'kuaizi-cdp/storyboard-plan@2',
    source: input.source,
    video: { resolution: '720p', aspect_ratio: '9:16', duration_sec: videoSecs },
    analysis,
    style_override: styleOverride || 'auto',
    item_count: items.length,
  };
  return { items, meta };
}

// CLI
if (process.argv[1] && process.argv[1].endsWith('storyboard.mjs')) {
  const [cmd, ...rest] = process.argv.slice(2);
  if (cmd === 'rules') {
    console.log(`空镜生成规范（2026-11-11 修订）
=====================================
1) 先读完整字幕/文稿，不只看关键词。
2) 医疗内容判定：命中强医疗词（无精子症/精子/精液/生育力/卵巢/子宫/激素/超声/胚胎/诊断/治疗/手术等）
   → 3D 建模医学动画风格：${MEDICAL_STYLE}
3) 只有“医院/医生/诊室/患者/报告”等场景词、没有强医疗词
   → 温馨写实：${WARM_STYLE}
4) 医疗文本从原文抽取含医疗词的原句/短语生成，不凭空编造疾病或疗效。
5) 硬约束：${HARD_CONSTRAINTS}
6) 输出为数组，可直接 generate.mjs batch；分析元数据写 .meta.json。
7) 默认取 6 条；可用 -n 控制；agent 必须人工审阅后再 batch。`);
  } else if (cmd === 'plan') {
    const args = [...rest];
    let input = null;
    let max = 6;
    let out = null;
    let videoSecs = 5;
    let text = '';
    let style = 'auto';

    for (let i = 0; i < args.length; i++) {
      const a = args[i];
      if (a === '-n' || a === '--n' || a === '--max') max = parseInt(args[++i], 10);
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
      const { items, meta } = makePlan(input, { max, videoSecs, text, style });
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
