# MediaDownloader

一个基于 Python、Playwright 和 Microsoft Edge 的小红书图片批量下载工具。

程序会根据关键词搜索笔记，自动滚动收集指定数量的搜索结果，逐篇打开并保存图文笔记中的图片。已经处理过的笔记会通过 `metadata.json` 自动跳过；视频或未检测到正文图片的笔记会记录 metadata，但不会下载视频。运行结束后，所有已下载图片还会额外复制到一个 `汇总` 文件夹中，方便统一查看。

> 本项目主要作为个人学习和自用工具。请仅下载和使用你有权访问、保存和使用的内容，并遵守相关平台规则及内容权利人的要求。

## 功能

- 输入搜索关键词
- 自定义处理笔记数量
- 自动滚动搜索结果页
- 固定本次搜索结果顺序后逐篇处理
- 下载图文笔记中的正文图片
- 多图笔记批量保存
- 视频 / 无正文图片笔记记录为已处理
- 通过 `metadata.json` 跳过已处理笔记
- 自定义图片保存目录
- 自动生成 `汇总` 文件夹
- 使用独立的 Edge 登录数据目录，首次登录后可复用登录状态

## 运行环境

本项目目前在以下环境中测试通过：

- Windows 10 / 11 64-bit
- Python 3.11（开发时使用 Python 3.11.16）
- Microsoft Edge
- `httpx 0.28.1`
- `playwright 1.63.0`

程序通过 Playwright 控制本机已经安装的 Microsoft Edge，因此需要系统中安装 Edge。

## 安装

### 方式一：Conda（推荐）

```powershell
conda create -n media_downloader python=3.11
conda activate media_downloader
pip install -r requirements.txt
```

也可以直接使用仓库中的环境文件：

```powershell
conda env create -f environment.yml
conda activate media_downloader
```

### 方式二：普通 Python 虚拟环境

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## 运行

```powershell
python main.py
```

程序会依次要求：

1. 输入搜索关键词；
2. 输入要处理的笔记数量；
3. 选择图片保存目录；
4. 第一次运行时，在自动打开的 Edge 中登录自己的小红书账号。

登录状态会保存在当前 Windows 用户的：

```text
%LOCALAPPDATA%\MediaDownloader\browser_data
```

该目录不在项目仓库中，也不应提交到 GitHub。

## 输出结构

假设选择 `D:\xhs_images` 作为保存目录：

```text
D:\xhs_images\
├── <note_id_1>\
│   ├── 01.webp
│   ├── 02.webp
│   └── metadata.json
├── <note_id_2>\
│   ├── 01.webp
│   └── metadata.json
└── 汇总\
    ├── <note_id_1>_01.webp
    ├── <note_id_1>_02.webp
    └── <note_id_2>_01.webp
```

如果下一次仍选择同一个保存目录，存在 `metadata.json` 的笔记会被跳过。

## 打包 Windows 可执行程序

先安装 PyInstaller：

```powershell
pip install pyinstaller
```

然后在项目根目录执行：

```powershell
pyinstaller --noconfirm --clean --onedir --console --name MediaDownloader --collect-all playwright main.py
```

生成结果位于：

```text
dist\MediaDownloader\
```

发布时应将整个 `MediaDownloader` 文件夹压缩成 ZIP，而不是只单独发送 `MediaDownloader.exe`。

仓库中也保留了 `MediaDownloader.spec`，可用于后续调整 PyInstaller 打包配置。

## GitHub Release 建议

源码建议保留在仓库中，而 `build/` 和 `dist/` 不提交到 Git。需要给普通用户下载的 Windows 成品，可以把 `dist\MediaDownloader` 压缩成 ZIP 后上传到 GitHub 的 **Releases**。

这样仓库保持干净，同时普通用户不需要安装 Python。

## 项目结构

```text
MediaDownloader/
├── main.py
├── requirements.txt
├── environment.yml
├── MediaDownloader.spec
├── .gitignore
├── README.md
└── src/
    ├── __init__.py
    └── xhs.py
```

## 注意

- 不要把浏览器登录数据目录上传到 GitHub。
- 不要提交下载后的图片、`output/`、`build/` 或 `dist/`。
- 搜索结果由网站本身决定，不同时间运行的结果和顺序可能不同。
- 网站页面结构变化后，页面定位逻辑可能需要相应调整。
