# 站点侧文件（Jekyll 版 · 推荐）

## 一、为什么从 Hexo 换到 Jekyll

你现在用的是 Hexo。两套都能实现，但**运维成本差很多**：

| 维度 | Hexo（现状） | **Jekyll（推荐）** |
|---|---|---|
| 构建 | 本地 `hexo g && hexo d`，**要 Node 环境** | **push 后 GitHub 自动构建，0 环境** |
| 换电脑/重装 | 重新搭 Node + npm install | **什么都不用装** |
| 移动端发文 | 基本不行（要环境） | **GitHub 网页端直接编辑 md** |
| 自定义 JSON | 写 JS 生成器（灵活） | **Liquid 模板输出**（够用，**不算插件**） |
| 插件限制 | 无限制 | GitHub Pages 白名单，**但 Liquid 不受限** |
| 主题 | 现用 Freeth | 需换主题（或不用主题） |

**结论：选 Jekyll。** 决定性因素是"GitHub 自动构建 + 手机上能发文"——
对一个要长期运营、随时可能发紧急公告的 App 官方站，这比"生成器更灵活"重要得多。
你的 Hexo 站目前只有一篇 Hello World，迁移成本约等于 0。

> Hexo 版文件仍保留在 `../site-hexo/`，如果你不想换可以直接用。

## 二、迁移步骤（约 10 分钟）

```bash
# 1) 备份现有 Hexo 源文件（feed/主题配置等）
# 2) 清空仓库，换成 Jekyll 结构
git clone https://github.com/eFreeLab/efreelab.github.io.git
cd efreelab.github.io

# 3) 把本目录内容拷进去
cp -r api _posts ./          # 若已有同名目录则合并

# 4) 最小 _config.yml（或在你现有配置上补）
```

`_config.yml` 最小可用配置：

```yaml
title: eFreeLab
description: 轩扫描 XuanScan 官方站
url: https://efreelab.github.io
baseurl: ""

# 关键：让 api/ 目录下的 .json 被当作模板处理（默认会被当静态文件，也能用）
# 但 Jekyll 对无 front-matter 的 json 会原样拷贝 —— 我们要的是"渲染"，
# 因此 feed.json / version.json 顶部已带 --- layout: none ---，会被正常渲染。
include: ["api"]

# 可选：生成站点地图与 RSS（白名单插件）
plugins:
  - jekyll-feed        # 生成 /feed.xml，用户可用 RSS 阅读器订阅
  - jekyll-sitemap

# 不想要主题的，可留空；Jekyll 无主题也能跑
theme: null
```

```bash
# 5) 推上去
git add . && git commit -m "feat: XuanScan API endpoints" && git push
```

推送后等 1–2 分钟，访问验证：

```
https://efreelab.github.io/api/v1/feed.json
https://efreelab.github.io/api/v1/version.json
https://efreelab.github.io/api/v1/config.json
https://efreelab.github.io/api/v1/diag.json
```

> ⚠️ **必须确认**：仓库 Settings → Pages → Source 选 **Deploy from a branch**，
> 分支选默认分支（**确认是 `master` 还是 `main`**），目录 `/ (root)`。
> 分支名决定 jsDelivr 加速路径里的 `@master` / `@main`。

## 三、日常用法：写文章 = 发公告

在 `_posts/` 新建 `YYYY-MM-DD-标题.md`，front-matter 带 `xscan` 即可：

```yaml
---
title: v0.2.0 新增自动边缘检测
date: 2026-09-25 10:00:00 +0800      # ← 时区别漏，否则排序可能错
tags: [XuanScan]
xscan:
  app: xuanscan                      # 必填，否则不进 feed
  type: bugfix                       # announce|bugfix|prerelease|release|notice|reply
  version: '0.2.0'
  minVersion: '0.1.0'                # 影响范围
  fixVersion: '0.2.0'                # 修复于
  severity: normal                   # low|normal|high|critical（critical 会弹窗）
  pinned: false                      # 消息中心置顶
  receipt: ''                        # 回复某条反馈时填回执码
  summary: 一句话摘要                 # 不填自动截取正文前 120 字
  action:
    type: update                     # none|update|dialog|open_url
    url: ''
---

正文……
```

**只有 `type: release`** 需要额外填下载渠道：

```yaml
xscan:
  type: release
  version: '0.2.0'
  minSupported: '0.1.0'
  channels:
    - name: 蓝奏云
      url: https://...
      note: 推荐，国内直连不限速
    - name: GitHub Releases
      url: https://...
      note: 海外备用
```

> 💡 GitHub 网页端可以直接新建/编辑 `_posts/` 里的 md，**手机上也能发公告**。

## 四、国内加速（jsDelivr 代理 GitHub 仓库）

```
https://cdn.jsdelivr.net/gh/eFreeLab/efreelab.github.io@master/api/v1/feed.json
https://fastly.jsdelivr.net/gh/eFreeLab/efreelab.github.io@master/api/v1/feed.json
```

App 侧三源并发探测、取最先成功者（配置见 `api/v1/config.json` 的 `endpoints`）。

> ⚠️ jsDelivr 有缓存（几分钟 ~ 24h）。紧急公告以 GitHub Pages 源为准。
> ⚠️ `@master` 请按实际默认分支改成 `@main`。

## 五、开启评论（giscus）

1. 仓库 **Settings → Features → 勾选 Discussions**
2. 打开 https://giscus.app/ ，填 `eFreeLab/efreelab.github.io`，选 Discussions
3. 复制生成的 `<script>` 标签
4. 在 `_layouts/post.html`（若无则新建）里放入该 script

```html
<!-- _layouts/post.html -->
<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{{ page.title }}</title></head>
<body>
  <article>
    <h1>{{ page.title }}</h1>
    {{ content }}
  </article>

  <!-- giscus 评论区（把你在 giscus.app 拿到的参数粘过来） -->
  <script src="https://giscus.app/client.js"
          data-repo="eFreeLab/efreelab.github.io"
          data-repo-id="R_xxxxxxxxxx"
          data-category="Announcements"
          data-category-id="DIC_xxxxxxxxxx"
          data-mapping="pathname"
          data-strict="0"
          data-reactions-enabled="1"
          data-emit-metadata="0"
          data-input-position="bottom"
          data-theme="light"
          data-lang="zh-CN"
          crossorigin="anonymous"
          async>
  </script>
</body></html>
```

## 六、运营动作速查

| 我要做什么 | 怎么做 |
|---|---|
| 发新版本 | 写 `type: release` 文章，填 `channels` |
| 预告新版本 | 写 `type: prerelease` |
| 公告 bug 已修复 | 写 `type: bugfix`，填 `fixVersion` |
| 回复某用户反馈 | 写 `type: reply`，`receipt` 填对方回执码 |
| 紧急通知 | 写 `severity: critical`，App 会弹窗 |
| **某机型有问题** | **改 `api/v1/diag.json` 的 `known_bad_device` 规则，填机型** —— 无需发版，全网生效 |
