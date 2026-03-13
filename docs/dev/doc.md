
# 文档

本项目文档由 [MkDocs](https://www.mkdocs.org/) 构建，并使用 [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) 主题，源码在 [doc-pages 分支](https://github.com/ArkMowers/arknights-mower/tree/doc-pages)，使用 [Publishing from a branch](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site#publishing-from-a-branch) 的方式自动部署到 GitHub Pages。

在本地预览与构建文档，需要安装 Python 3 环境。

## 安装依赖

```bash
pip install mkdocs-material
pip install mkdocs-git-revision-date-localized-plugin
pip install mkdocs-git-committers-plugin-2
pip install mkdocs-git-authors-plugin
```

## 预览文档

```bash
mkdocs serve
```

## 构建文档

```bash
mkdocs build
```




