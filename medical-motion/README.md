# 医疗口播代码动效

DSH 阅读整期已定稿 UTF-8 口播正文，按语义挑选确实适合代码动效的段落，可为零个。每镜保留可定位的连续原文、字符区间和具体视觉说明，再编写 HTML、SVG/CSS 和 GSAP 时间线，Win 11 本机的 OpenMotion 将其渲染为全画幅无声 MP4，供剪映插入。默认竖屏 1080×1920、30 fps。

## 整稿入口

在本模块目录运行。`outputs` 为 Git 忽略的工作区产物目录；真实文案放在仓库外。

```bat
plan.cmd C:\work\final-script.txt outputs\episode-01
plan.cmd C:\work\final-script.txt outputs\episode-02 --plan-only --mixed
plan.cmd C:\work\final-script.txt outputs\episode-02 --resume
```

首次运行保存 `storyboard.json`，并在默认模式下依次生成 `code-01\motion.mp4` 等镜头。`--plan-only` 仅规划，`--resume` 使用既有计划继续；逐镜跳过方案未变的已完成 MP4，重用已生成 HTML，失败的渲染可在原目录重试。每镜的 `code-XX.request.json` 记录原文、位置、视觉说明与时长；若这些字段改动，旧 HTML/MP4 不再复用，应开新输出目录。正文改动后也需重新规划。空的 `code_shots` 是有效结果，不会生成 MP4。

`storyboard.json` 固定含 `schema_version: 1`、`source_sha256`、`mixed`、`code_shots`、`kuaizi_shots`。代码镜头项为 `{id, source_quote, start, end, visual_brief, seconds}`；筷子候选项为 `{source_sentence, summary, anchor, style, start, end}`。`start` 和 `end` 是从去掉整稿首尾空白后的正文计算的 Python 字符偏移，`end` 不包含在区间中。所有引文必须唯一定位，镜头区间互不重叠。`--mixed` 只让 DSH 额外规划适合 3D 医疗或温暖写实画面的 AI 空镜候选，可为零条；不会调用筷子或渲染 AI 空镜。`summary` 是忠实压缩句，末尾标点自动去除，小数点保留；`anchor` 是 1–15 字、不含标点的单一可视机制或物象，`style` 仅 `medical3d` / `warmReal`。

逐镜检查计划、屏幕文字、图形关系和原文，再按最终口播的起止点放入剪映工程。3D AI 空镜继续沿用原有筷子生产流程。

## 单镜入口

原有单镜入口仍可单独使用，每次给一个新的输出目录。

```bat
generate.cmd examples\excerpt.txt outputs\visit-01 --seconds 6
```

产物为 `outputs\visit-01\motion.mp4`，可编辑源码为同目录的 `project\index.html`。医生口播继续使用原音轨。核对屏幕文字、图形关系与原文，按最终口播的起止点把 MP4 放进口播工程。模型用词需逐镜核对。

修改 HTML 后可直接重渲染，也可让桌面 DSH 按示例自己写 HTML 后执行此入口：

```bat
render.cmd outputs\visit-01\project\index.html outputs\visit-02
render.cmd examples\visit-notes.html outputs\sample
```

镜头使用单文件 HTML，图形和样式内联，动画脚本引用 `assets/gsap.min.js`，渲染时从插件复制；根节点声明画幅、时长及帧率，暂停的 GSAP 时间线注册到同名 `window.__timelines` 键。渲染过程中会执行 HyperFrames 严格检查。若因 HTML 报错中止，已写入的 project 可修改后渲染到另一目录。

## 与生产机的连接

2026-11-25 在 Win 11 的 DSH desktop profile 查到 `dsh-plugin-openmotion-local@0.2.1`，其 Cordis 配置通过 stdio 启动 `openmotion` MCP 并加载配套技能。安装记录指向上游提交 `34df9b1`，内置 HyperFrames 0.9.7。这里调用该版本的本地渲染接口。生成阶段使用仓库的 DSH headless worker 及其主机模型配置，两阶段通过 HTML 交接。无需安装 Opus 或配置图像、视频生成服务。[上游源码](https://github.com/nexu-io/openmotion/tree/34df9b1aeae201c127ce2f7a1db3f42deed486aa)

代码生成需要 Python 3、相邻的 `tools\dsh-worker.ps1` 及已配置的 DSH worker。独立验证目录可用 `DSH_WORKER_PS1` 指向主机现有脚本。渲染入口使用 DSH 的 Node 和 `%LOCALAPPDATA%\openmotion\install.json` 所指安装。浏览器及 FFmpeg/FFprobe 优先取插件运行环境，缺失时查本机 Edge 和 `%USERPROFILE%\ffmpeg-dl\bin`。其他布局可显式设置 `HYPERFRAMES_BROWSER_PATH`、`HYPERFRAMES_FFMPEG_PATH` 和 `HYPERFRAMES_FFPROBE_PATH`。
