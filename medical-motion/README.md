# 医疗口播代码动效

从已定稿的 UTF-8 口播文案里取一个适合用图形解释的片段，例如一次时间变化或一组步骤。DSH 为这段话编写 HTML、SVG/CSS 和 GSAP 时间线，Win 11 本机的 OpenMotion 将它渲染成一条全画幅无声 MP4，可作为剪映中的插入镜头。默认竖屏 1080×1920、30 fps、6 秒。

在本模块目录运行。每次给一个新的输出目录。

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
