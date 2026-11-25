# 登记与验收

看板刷新时读取每个打标批次目录下的 `交付清单.json`（UTF-8）。有原视频、没有清单的旧批次仍然显示，状态为“待登记”；升级本身不会改写文件或补签验收。负责交付的 Agent 在**业务批次目录**维护清单，不提交真实清单到 Git。批次名必须等于目录名，dst 是该目录中包含扩展名的实际文件名，subject + episode 在批次内唯一。不要从标题猜身份。

示例（文件路径相对于清单，也支持 Windows 绝对路径）：

```json
{
  "version": 1,
  "batch": "示例批次",
  "episodes": [{
    "subject": "示例主体",
    "episode": "01",
    "dst": "早餐建议_打标.MP4",
    "files": {
      "edit": "成果/01/口播/draft_content.json",
      "hl": "成果/01/重点词清单.json",
      "sfx": "成果/01/音效清单.json",
      "overlay": "成果/01/回填/draft_content.json",
      "cover": "成果/01/封面.png",
      "shots": ["成果/01/镜01.mp4"],
      "draft": "成果/01/最终版/draft_content.json"
    }
  }]
}
```

只登记实际返回且属于该期的路径，没做的阶段可以省略。中间步骤按非空文件判断。最终草稿需要是可解析的 draft_content.json，且至少有一个含片段的视频轨道；这只能证明已生成。播放验收后，在该期对象内加入 `"review": {"reviewer":"验收人","sha256":"验收时草稿文件的64位小写SHA256"}`。PowerShell 取值：`(Get-FileHash -LiteralPath $draftPath -Algorithm SHA256).Hash.ToLowerInvariant()`。同一个批次合并草稿只在确认确实包含该期后才登记到那一期；文件本身不能证明期数归属。草稿文件改动后旧验收自动失效，外部素材内容的变化不在该指纹范围内。

从仓库根运行 `node --test cut-workbench-dashboard/dashboard.test.js`。部署时 host 和 client 一起更新，重启插件并刷新页面（新接口为 dashboard-v3）。
