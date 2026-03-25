
# 文档

本项目文档使用 `Markdown` 格式编写，由 [MkDocs](https://www.mkdocs.org/) 构建，并使用 [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) 主题。

源码在 [doc-pages 分支](https://github.com/ArkMowers/arknights-mower/tree/doc-pages)，使用 [Publishing from a branch](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site#publishing-from-a-branch) 的方式自动部署到 GitHub Pages。

在本地预览与构建文档，需要安装 Python 3 环境。

## 获取源码

### fork主仓库到自己仓库

前往 Mower 在 Github 上的主仓库进行 fork ：

[`https://github.com/ArkMowers/arknights-mower/fork`](https://github.com/ArkMowers/arknights-mower/fork){ target="_blank" }

??? info "注意取消勾选`Copy the main branch only`"

    如果 fork 时只复制了 main 分支

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
    
    完成之后就可以前往[安装依赖](#_4)的步骤了

### 从自己的仓库克隆源码

```bash linenums="1"
git clone --single-branch --branch doc-pages https://github.com/你的用户名/arknights-mower.git
cd arknights-mower
```
## 安装依赖

```bash linenums="1"
pip install mkdocs-material
pip install mkdocs-git-revision-date-localized-plugin
pip install mkdocs-git-committers-plugin-2
pip install mkdocs-git-authors-plugin
```

## 编辑文档

文档虽然主要使用 `Markdown` 格式编写，但还可能涉及到对 `yaml` 文件的编辑。

建议使用 `Visual Studio Code` 等类似软件进行编辑。

查看 [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/){ target="blank" } 的官方文档可能会对编辑有很大帮助。

## 构建文档

```bash
mkdocs build
```

## 预览文档

```bash
mkdocs serve
```

## 提交更改到自己的仓库

在本地编辑完文档后通过构建并测试完成之后，可以先将更改推送到自己的仓库上：

```bash linenums="1"
git add .
git commit -m "[对提交的更改进行描述]"
git push -u origin doc-pages
```

!!! note "commit的描述内容建议参考 [“约定式提交”](https://www.conventionalcommits.org/zh-hans/v1.0.0-beta.4/#%e7%ba%a6%e5%ae%9a%e5%bc%8f%e6%8f%90%e4%ba%a4%e8%a7%84%e8%8c%83) 等规范进行编写"

> 由于 `mkdocs.yml` 中 `site_url` 填写的是主仓库的链接，若想要在自己的仓库中部署并预览网页，需要在 `Pages` 中选择 `Delopy form a branch`，并选择由 `GitHub Actions` 自动构建并生成的分支 `gh-pages`。 

## 创建Pull Requests

在自己的仓库中检查并测试无误，就可以创建对主仓库 `doc-pages` 分支的 `Pull Requests` 了。