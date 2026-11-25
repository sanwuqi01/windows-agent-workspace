# Windows Agent 工作区源码

维护 Win 11 视频工作区的通用模块。仓库按生产目录保留相对路径，首次导入使用 2026-11-19 读取的工作文件；生产根仓库当时的 HEAD 为 `419aa56`，其中未包含全部运行中的源码。此仓库不继承它的提交历史，也不是整机备份。

| 路径 | 职责与使用条件 |
|---|---|
| [medical-motion/](medical-motion/README.md) | DSH 将一段医疗口播写成代码动效，调用 Win 11 现有 OpenMotion 输出可编辑 HTML 和剪映用无声 MP4。 |
| `chapter-progress-bar/` | DSH 从打标文案提炼五段，工具检查章节、按最终字幕对时，生成可放到剪映轨道上的 MP4。带合成示例和测试。 |
| `cut-workbench-dashboard/` | DSH 工作台插件，按[批次交付清单](cut-workbench-dashboard/README.md)核对单期产物，分别展示草稿已生成和人工已验收。 |
| `kuaizi-empty-shot/` | 独立的分镜计划生成器 storyboard.mjs；调用平台的生成、下载与浏览器登录适配器保留在生产机；[现有 Edge 素材中心选页修复](kuaizi-empty-shot/edge-routing/README.md)可只读核对或重建。 |
| `talking-head-auot-cut/` | 口播工作台本地启动入口。依赖生产机已部署的 personal-workbench 核心、模块及本机配置；导入时读取的核心版本为 09076e833427a26d2adb9ad74914bc8b0421dcaf。 |
| `tools/dsh-worker.cmd` | 在已配置的 Windows 主机上通过 stdin 传入任务，配合同目录的 PowerShell 包装器使用。模型配置 worker.patch.yml 和凭据由主机提供。 |

## 章节条验证

Windows 需要 Python 3.12、Pillow、ffmpeg、ffprobe 和样式指定的中文字体。在模块目录运行：

```bat
python -m unittest discover -s tests
run.cmd demo --out-dir outputs/demo16s
```

示例配置在 examples/demo16s 下，改色号后可以用同一份已对时的章节重新渲染。demo 通过只表明生成文件成功，实际剪映导入、布局和切换点需在目标主机检查。

## 迭代和上线

1. 从 main 建功能分支，改对应模块；PR 中写清输入、测试和会替换的文件。
2. 在独立检出目录用示例验收。依赖本机配置的模块，沿用已有部署；不要把模型、凭据、浏览器资料、真实文案、任务或交付物提交进来。
3. 合并后记录提交号。生产任务结束后，先比对拟替换文件与当前运行版本，保留本机改动和上版副本，只更新本次确认的模块。仓库没有自动部署，禁止在运行目录直接覆盖或强制拉取。
