# 病历分析系统

基于FastAPI的Web应用，用于展示和分析病历信息，支持Markdown渲染和历史记录管理。

## 功能特性

- 📋 **病历信息展示** - 清晰展示病历内容
- 📊 **病历等级分析** - 自动评分和等级评定
- 🌐 **全国性分析问题** - 标准化问题检测
- 🚀 **并发分析** - 同一份病历支持并发多次分析，对比结果稳定性
- 📚 **历史记录管理** - 保存和查看分析历史
- 🎨 **美观界面** - 响应式设计，支持Markdown渲染

## 快速开始

### 方法1：使用批处理文件（推荐）

双击运行 `start.bat` 文件，系统将自动：
- 检查Python环境
- 创建虚拟环境
- 安装依赖包
- 启动Web服务器

### 方法2：使用PowerShell

在项目目录下运行：
```powershell
.\start.ps1
```

### 方法3：手动启动

1. 创建虚拟环境：
```bash
python -m venv venv
```

2. 激活虚拟环境：
```bash
# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

3. 安装依赖：
```bash
pip install -r requirements.txt
```

4. 初始化 data 目录（首次运行需创建数据目录）：
```bash
python -c "import os; os.makedirs('data', exist_ok=True); os.makedirs('data/history_records', exist_ok=True)"
```

5. 启动应用：
```bash
python main.py
```

## 访问应用

启动成功后，在浏览器中访问：
- **主页面**: http://localhost:8889
- **历史记录**: http://localhost:8889/history
- **并发测试**: http://localhost:8889/concurrency-test
- **知识库**: http://localhost:8889/standards

## 项目结构

```
statistic-test2/
├── main.py                     # FastAPI主应用
├── run_workflow.py             # Dify工作流调用脚本
├── cleanup_old_records.py      # 清理历史记录脚本
├── cleanup_old_records_auto.py # 自动清理历史记录脚本
├── requirements.txt            # Python依赖
├── .gitignore                  # Git忽略规则
├── config/
│   ├── config.py               # 配置加载模块
│   └── config.json             # 运行时配置（端口、Dify API Key等）
├── templates/                  # HTML模板
│   ├── index.html              # 主页面（含并发分析）
│   ├── history.html            # 历史记录页面
│   ├── standards.html          # 知识库管理页面
│   └── concurrency_test.html   # 并发测试页面
├── static/
│   └── style.css               # 自定义样式
├── uploads/                    # 上传的病历文件（运行时生成，不纳入版本控制）
├── data/                       # 数据存储目录（运行时生成，不纳入版本控制）
│   ├── history.json            # 旧版历史记录文件
│   ├── history_index.json      # 历史记录索引
│   ├── history_records/        # 历史记录详情（每次分析的完整结果）
│   ├── analysis_batches.json   # 首页并发分析批次数据
│   ├── concurrency_tests.json  # 并发测试数据
│   ├── standards.json          # 知识库标准文件元数据
│   └── tasks.json              # 分析任务数据
├── standards/                  # 知识库标准文件（txt格式）
├── docs/                       # 文档
└── README.md                   # 本文件
```

## data 目录说明

`data/` 目录存放运行过程中产生的数据文件，**不纳入 Git 版本控制**。克隆项目后首次运行前需手动创建：

```bash
mkdir -p data/history_records
```

各文件说明：

| 文件/目录 | 用途 | 生成方式 |
|-----------|------|----------|
| `history.json` | 历史记录（旧版完整存储） | 系统自动生成 |
| `history_index.json` | 历史记录索引（轻量级列表） | 系统自动生成 |
| `history_records/` | 历史记录详情（按 ID 分文件存储） | 每次分析结果写入一个 `.json` 文件 |
| `analysis_batches.json` | 首页并发分析批次数据 | 每次首页并发分析生成 |
| `concurrency_tests.json` | 并发测试数据 | 通过并发测试页面生成 |
| `standards.json` | 知识库中已上传的标准文件列表 | 通过知识库页面上传/删除标准时更新 |
| `tasks.json` | 正在进行的分析任务状态 | 系统自动生成 |

首次启动后，系统会自动创建 `data/` 目录，无需手动干预。如需重置数据，删除 `data/` 目录即可。

## API接口

### 病历分析
- **POST** `/api/analyze` - 提交单次病历分析
- **POST** `/api/analysis/batches` - 创建并发分析批次
- **GET** `/api/analysis/batches/{batch_id}` - 查询批次进度
- **GET** `/api/analysis/batches` - 获取批次列表

### 历史记录
- **GET** `/api/history` - 获取历史记录列表
- **DELETE** `/api/history/{record_id}` - 删除单条记录
- **POST** `/api/history/clear` - 清空历史记录

### 配置
- **GET** `/api/config/dify-key` - 获取当前 Dify API Key（掩码显示）
- **POST** `/api/config/dify-key` - 更新 Dify API Key

### 并发测试
- **POST** `/api/concurrency/batches` - 创建并发测试批次
- **GET** `/api/concurrency/batches` - 获取并发测试批次列表

## 技术栈

- **后端**: FastAPI, Python
- **前端**: Bootstrap 5, JavaScript
- **模板**: Jinja2
- **样式**: CSS3, Font Awesome
- **数据存储**: JSON文件

## 注意事项

1. 确保系统已安装Python 3.7或更高版本
2. 首次运行会自动创建虚拟环境和安装依赖
3. `data/` 和 `uploads/` 目录被 Git 忽略，不会提交到远程仓库，多环境部署需各自生成
4. 应用默认运行在端口8889，如需修改请编辑 `config/config.json`
5. Dify API Key 可在运行后通过首页界面动态配置

## 开发说明

如需修改前端样式，请编辑：
- `templates/index.html` - 主页面模板
- `templates/history.html` - 历史记录模板
- `templates/standards.html` - 知识库模板
- `templates/concurrency_test.html` - 并发测试模板
- `static/style.css` - 自定义样式

后端逻辑修改请编辑 `main.py` 文件。
