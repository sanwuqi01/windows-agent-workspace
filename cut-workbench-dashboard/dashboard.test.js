import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {buildData} from './index.js';

function setup(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(),'dash-'));
  t.after(() => fs.rmSync(root,{recursive:true, force:true}));
  const dst='早餐_打标.MP4';
  function batch(name,subject) {
    const dir=path.join(root,'广济医疗-医生IP-打标素材',name);
    fs.mkdirSync(dir,{recursive:true}); fs.writeFileSync(path.join(dir,dst),'video');
    const row={subject,episode:'01',dst,files:{draft:'draft_content.json'}};
    const save=(rows=[row]) => fs.writeFileSync(path.join(dir,'交付清单.json'),JSON.stringify({version:1,batch:name,episodes:rows}));
    const write=(file,data) => { const target=path.join(dir,file); fs.mkdirSync(path.dirname(target),{recursive:true}); fs.writeFileSync(target,data); };
    const ep=() => buildData(root).batches.find(b=>b.name===name).episodes[0];
    return {row,save,write,ep};
  }
  return batch;
}
const draft=JSON.stringify({tracks:[{type:'video',segments:[{}]}]});

test('两个主体同名视频绑定各自的批次，近似标题不算命中',t=>{
  const batch=setup(t), a=batch('A','主体甲'), b=batch('B','主体乙');
  a.save(); b.save(); a.write('draft_content.json',draft);
  assert.equal(a.ep().generated,true); assert.equal(b.ep().generated,false);
  a.row.dst='早餐_打标.mov'; a.save(); assert.equal(a.ep().note,'待登记'); assert.equal(a.ep().generated,false);
});

test('前六项齐全仍需真实草稿，生成和人工验收分开',t=>{
  const a=setup(t)('A','甲');
  for(const k of ['edit','hl','sfx','overlay','cover']){a.row.files[k]=k; a.write(k,'x');}
  a.write('成果/镜01.mp4','x'); a.row.files.shots=['成果/镜01.mp4']; a.save();
  assert.ok(a.ep().steps.slice(0,6).every(s=>s.done)); assert.equal(a.ep().generated,false);
  for (const text of ['','{','{"tracks":[]}']) { a.write('draft_content.json',text); assert.equal(a.ep().generated,false); }
  a.write('draft_content.json',draft); assert.equal(a.ep().generated,true); assert.equal(a.ep().reviewed,false);
  a.row.review={reviewer:'验收员',sha256:createHash('sha256').update(draft).digest('hex')}; a.save();
  assert.equal(a.ep().reviewed,true);
  a.write('draft_content.json',draft+' '); assert.equal(a.ep().reviewed,false);
});

test('旧批次、损坏清单、重复单期和文件冲突都不冒认交付',t=>{
  const a=setup(t)('A','甲'); a.write('draft_content.json',draft);
  assert.equal(a.ep().note,'待登记'); a.write('交付清单.json','{');
  assert.equal(a.ep().note,'清单无法读取');
  for(const other of [{...a.row,dst:'另一条.mov'},{...a.row,subject:'乙'}]){
    a.save([a.row,other]); assert.equal(a.ep().note,'清单身份冲突'); assert.equal(a.ep().generated,false);
  }
});
