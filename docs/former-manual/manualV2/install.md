# 下载、运行及更新

## Windows

### 下载和运行

1.  在群文件`"Mower下载"`文件夹中获取最新全量包
2.  在英文路径下创建Mower工作文件夹
3.  将全量包内容解压至此
4.  运行`"mower.exe"`启动Mower

### 手动更新

1.  在群文件`"Mower下载"`文件夹中获取最新增量包
2.  将增量包内容解压至Mower工作文件夹，覆盖原有文件
3.  运行`"mower.exe"`启动Mower

### 自动更新

1.  从群文件`"Mower下载"`获取最新下载器
2.  解压并运行`"MowerDownload.exe"`，选择安装路径
3.  选择目标版本
4.  选择更新类型：
    +   仅更新新干员资源（保留当前版本）
    +   更新Mower代码（体验新功能）
    +   全量更新（干员资源+代码更新）
    +   替换新版本DLL（更新MAA调用文件）
5.  等待更新完成，关闭更新提示窗口

## MacOS、GNU/Linux

MacOS、GNU/Linux使用源码运行，本指北以MacOS示例

### 首次运行

1.  **配置环境**
    
    访问MAA项目地址：[https://github.com/MaaAssistantArknights/MaaAssistantArknights](https://github.com/MaaAssistantArknights/MaaAssistantArknights)
    
    安装mac版MAA，并下载Windows版MAA，复制其python文件夹到
    
    `/Applications/MAA.app/Contents/Resources`
    
    将`/Applications/MAA.app/Contents/Frameworks`里的内容复制到
    
    `/Applications/MAA.app/Contents/Resources`
    
    安装蓝叠模拟器Air版：[https://www.bluestacks.com/mac](https://www.bluestacks.com/mac)
    
    安装MuMu模拟器Mac版：[https://mumu.163.com/](https://mumu.163.com/)
    
    模拟器设置
    
    +   分辨率：
        
        `1920x1080`
        
    +   每英寸点数（DPI）：
        
        `280`
        
    +   启用Android调试(ADB)
    
    安装Mac软件包管理器和Mower运行依赖
    
    ```bash linenums="1"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    brew install git git-lfs python@3.12 android-platform-tools zbar
    ```
    
    
2.  **构建Mower**
    
    （假设你已设置好网络代理）在终端中执行以下命令：
    
    ```bash linenums="1"
    #创建mower工作目录
    cd
    mkdir ~/ark
    cd ~/ark
    #克隆mower源代码
    git lfs install
    git config --global lfs.concurrenttransfers 50
    git clone -c https://github.com/ArkMowers/arknights-mower.git --branch 2025.6.1
    cd arknights-mower
    #构建python虚拟环境并安装依赖
    python3.12 -m venv venv
    source venv/bin/activate
    pip install -r requirements.in
    cd ui
    npm install
    npm run build
    ```
    
    
3.  **运行Mower**
    
    通过终端启动：
    
    ```bash linenums="1"
    cd ~/ark/arknights-mower
    source venv/bin/activate
    python3 webview_ui.py
    ```
    
    
4.  **配置Mower**
    
      
    ADB路径：
    
    `adb`
    
    ADB连接地址：  
    
    `127.0.0.1:5555`
    
    模拟器类型：  
    
    `其它`
    
    启动游戏方式：  
    
    `使用adb命令启动`
    
    截图方案：  
    
    `DroidCast`
    
    MAA目录：  
    
    `**/Applications/MAA.app/Contents/Resources**`
    
    连接配置：  
    
    `General`
    
5.  **停止Mower**
    
    Mower运行时关闭终端
    

### 源码更新

（假设你已设置好网络代理）在终端中执行以下命令：

```bash linenums="1"
#进入mower工作目录
cd ~/ark/arknights-mower
#同步mower最新源代码
git fetch origin 2025.6.1 --progress
git switch -f 2025.6.1 --progress
git reset --hard origin/2025.6.1
#激活python虚拟环境并更新mower运行依赖
source venv/bin/activate
pip install -r requirements.in
cd ui
npm install
npm run build
```


## 多开

运行Mower文件夹中的'"多开管理器.exe"'

操作步骤：

1.  点击"添加实例"按钮
2.  通过铅笔图标重命名实例
3.  点击"..."设置数据保存路径
4.  启动实例并配置ADB路径和连接地址

!!! note "多开实例的ADB路径可在模拟器多开工具中查询"
