# 文档

本项目文档使用 :fontawesome-brands-markdown:{ .lg .middle } `Markdown` 编写，由 [MkDocs](https://www.mkdocs.org/){ target="blank" } 构建，并使用 [Zensical](https://zensical.org/){ target="blank" } 主题。

文档源码位于仓库的 [doc-pages 分支](https://github.com/ArkMowers/arknights-mower/tree/doc-pages)，使用 [Publishing from a branch](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site#publishing-from-a-branch){ target="blank" } 的方式自动部署到 GitHub Pages。

在本地预览与构建文档，需要安装 Python 3 环境。

---

## 环境配置（Windows）

### 获取源码

前往 Mower 在 Github 上的仓库进行 Fork ：

[`https://github.com/ArkMowers/arknights-mower`](https://github.com/ArkMowers/arknights-mower/){ target="\_blank" }

??? info "注意取消勾选`Copy the main branch only`"

    如果 Fork 时只复制了 main 分支

    1. 先 `clone` 自己的仓库
    ```bash linenums="1"
    git clone https://github.com/你的用户名/arknights-mower.git
    cd arknights-mower
    ```

    2. 添加主仓库为 `upstream`
    ```bash
    git remote add upstream https://github.com/ArkMowers/arknights-mower.git
    ```

    3. 拉取 `doc-pages` 分支并从 `main` 切换到 `doc-pages` 分支
    ```bash
    git fetch upstream doc-pages
    git checkout -b doc-pages upstream/doc-pages
    ```

    完成之后就可以前往[安装依赖](#install)的步骤了

```bash title="从自己的仓库克隆源码" linenums="1"
git clone --single-branch --branch doc-pages https://github.com/你的用户名/arknights-mower.git
cd arknights-mower
```
!!! info "如果你之前 Fork 过怎么办？ 先正常克隆源码，然后详见→ [同步 Fork ](#SyncFork){ data-preview }"

### 创建并激活虚拟环境

```bash linenums="1"
python -m venv venv
.\venv\Scripts\activate

```

### 安装依赖 {:#install}

```bash linenums="1"
pip install -r requirements.txt
```

至此，环境配置的步骤就完成了。

---

## 编辑文档

文档虽然主要使用 `Markdown` 格式编写，但还可能涉及到对 `yaml` 文件的编辑。

建议使用 `Visual Studio Code` 等类似软件进行编辑。

查看 [Zensical](https://zensical.org/){ target="blank" } 的官方文档可能会对编辑有很大帮助。

### 构建文档

```bash linenums="1"
zensical build
```

### 预览文档

```bash linenums="1"
zensical serve
```

等待一会，Zensical会启动一个本地开发服务器，默认监听`localhost:8000`

此时使用浏览器访问

[`http://localhost:8000/`](http://localhost:8000){ target="blank" }

就可以看到文档站页面了

修改文档、配置或静态资源后，页面会自动重新加载

!!! note "你也可以使用zensical serve -a <IP:PORT> 来指定监听地址和端口"

### 文档的文件结构

为了让大家更快上手，这里给出了简化的树状文件结构：

```text title="文件结构" linenums="1" hl_lines="8"
docs/
├── assets/                 # 静态资源
│   ├── img/
│   ├── logo/
│   └── snippets/           # 文档片段、可复用内容             
├── dev/                    # 开发文档（维护&贡献）
│   ├── develop/
│   ├── document/           # 当前位置
│   └── feedback/
├── former-manual/          # 旧版手册
│   ├── manualV1/
│   ├── manualV2/
│   └── README.md
├── manual/                 # Mower入门一条龙
├── stylesheets/            # 自定义css/js
site/                       # Zensical 构建输出目录（自动生成，无需提交）
README.md                   # 仓库说明
requirements.txt            # 依赖
zensical.toml               # 文档站点配置文件
```

---

## 提交更改

### 提交更改到自己的仓库

在本地编辑完文档后通过构建并测试完成之后，先将更改推送到自己的仓库上：

```bash linenums="1"
git add .
git commit -m "[对提交的更改进行描述]"
git push -u origin doc-pages
```

!!! note "commit的描述内容建议参考 [“约定式提交”](https://www.conventionalcommits.org/zh-hans/v1.0.0-beta.4/#%e7%ba%a6%e5%ae%9a%e5%bc%8f%e6%8f%90%e4%ba%a4%e8%a7%84%e8%8c%83) 规范进行编写"

> 若想要在自己的仓库中部署并预览网页，需要在 `Pages` 中选择 `Deploy form a branch`，并选择由 `GitHub Actions` 自动构建并生成的分支 `gh-pages`。

### 创建Pull Requests

在自己的仓库中检查并测试无误，就可以创建对主仓库 `doc-pages` 分支的 `Pull Requests` 了。

接下来就可以等待 ArkMowers 的成员审核了~

!!! note "如果审核完成之前发现有需要修改的地方，更改完再次提交到自己的仓库即可，后续的修改都会自动进入到这个 Pull Requests 中，不用重新创建 Pull Requests"

### 同步 Fork {:#SyncFork}

如果遇到了主仓库和 Fork 仓库需要同步的情况，例如：

- 你正在本地修改文档或者已经推送到 Fork 仓库，但是有其他人的修改被合并到主仓库了，你需要同步这些更改到你本地/仓库。

- 很久以前 Fork 过主仓库，需要同步主仓库的更改之后才能进行文档的维护。

这里在下方提供两种方式来处理冲突，可以根据自己的情况来选择

在进行任何同步操作前，确保你已经关联了主仓库（upstream）。如果之前没配置过，请在项目根目录执行：

```bash linenums="1"
git remote add upstream https://github.com/ArkMowers/arknights-mower.git
```

#### 获取更新后合并

!!! note "适用于正在开发时的情况"

1. 获取更新并进行合并

```bash linenums="1" 
git fetch upstream
git merge upstream/doc-pages
```

2. 处理合并产生的冲突

如果合并时提示 `CONFLICT` ，需要先用 Visual Studio Code 打开项目文件夹进行处理。

冲突处理完毕之后可以选择直接在VS Code中提交更改，或：

```bash linenums="1"
git add .
git commit -m "chore: 同步主仓库的更新并处理了冲突"
```

3. 推送到自己的仓库

```bash linenums="1"
git push origin doc-pages
```

#### 强制同步

!!! warning "该操作将会放弃之前所做的更改"

```bash linenums="1"
git fetch upstream
git reset --hard upstream/doc-pages
git push -f origin doc-pages
```