# 教程 00 - 环境准备（小白版）

> 从零开始搭建开发环境，不需要任何编程基础

---

## 你需要准备什么

1. 一台电脑（Windows/Mac/Linux 都可以）
2. 稳定的网络（需要下载工具和访问API）
3. 一个 LLM API Key（MiniMax 或 OpenAI，下面会教你怎么获取）

---

## Step 1: 安装 Python

Python 是本项目的主力语言，推荐版本 3.10+。

### Mac
```bash
# 安装 Homebrew（Mac的包管理器）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 安装 Python
brew install python@3.11

# 验证
python3 --version
```

### Windows
1. 打开 https://www.python.org/downloads/
2. 下载最新版 Python
3. 安装时**勾选 "Add Python to PATH"**
4. 打开命令提示符，输入 `python --version` 验证

### Linux
```bash
sudo apt update
sudo apt install python3.11 python3.11-venv python3-pip
```

---

## Step 2: 安装 Docker（推荐）

Docker 可以让你一键启动所有服务。

### Mac
下载 Docker Desktop: https://www.docker.com/products/docker-desktop/

### Windows
下载 Docker Desktop: https://www.docker.com/products/docker-desktop/
（需要开启 WSL2）

### Linux
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

验证：
```bash
docker --version
docker-compose --version
```

---

## Step 3: 安装 IDE

推荐 **VS Code**（免费、强大、插件丰富）：

1. 下载: https://code.visualstudio.com/
2. 安装推荐插件:
   - Python
   - Java Extension Pack（如果写Java版）
   - Go（如果写Go版）
   - Docker

---

## Step 4: 获取 LLM API Key

### 方案一: MiniMax（推荐国内用户）

1. 注册: https://platform.minimaxi.com/
2. 创建应用，获取 API Key 和 Group ID
3. 免费额度足够学习使用

### 方案二: OpenAI

1. 注册: https://platform.openai.com/
2. 创建 API Key
3. 需要绑定信用卡

---

## Step 5: 克隆项目

```bash
# 克隆仓库
git clone https://github.com/bcefghj/multi-agent-meeting-assistant.git
cd multi-agent-meeting-assistant

# 配置环境变量
cp .env.example .env
# 用文本编辑器打开 .env，填入你的 API Key
```

---

## Step 6: 验证环境

```bash
cd python
python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m src.main
```

看到 `Starting Meeting Assistant Server` 就说明环境搭建成功了！

访问 http://localhost:8000/docs 可以看到API文档。

---

## 常见问题

**Q: pip install 很慢怎么办？**
```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**Q: 没有 GPU 可以运行吗？**
可以！在 `.env` 中设置 `WHISPER_DEVICE=cpu`。

**Q: 安装时报错怎么办？**
大多数情况是网络问题，多试几次或使用国内镜像。

---

下一篇: [01 - 理解Agent](01-understanding-agents.md)
