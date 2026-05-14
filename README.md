# 病历分析系统

基于FastAPI的Web应用，用于展示和分析病历信息，支持Markdown渲染和历史记录管理。

## 功能特性

- 📋 **病历信息展示** - 清晰展示病历内容
- 📊 **病历等级分析** - 自动评分和等级评定
- 🌐 **全国性分析问题** - 标准化问题检测
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

4. 启动应用：
```bash
python main.py
```

## 访问应用

启动成功后，在浏览器中访问：
- **主页面**: http://localhost:8000
- **历史记录**: http://localhost:8000/history

## 项目结构

```
medical_record_control4.0/
├── main.py                 # FastAPI主应用
├── requirements.txt        # Python依赖
├── start.bat              # Windows启动脚本
├── start.ps1              # PowerShell启动脚本
├── templates/             # HTML模板
│   ├── index.html         # 主页面
│   └── history.html       # 历史记录页面
├── static/                # 静态文件
│   └── style.css          # 自定义样式
└── data/                  # 数据存储
    └── history.json       # 历史记录文件
```

## API接口

### 保存分析结果
- **POST** `/api/save_result`
- 参数：`record`, `record_rating`, `record_all`

### 获取历史记录
- **GET** `/api/history/{record_id}`

## 技术栈

- **后端**: FastAPI, Python
- **前端**: Bootstrap 5, JavaScript
- **模板**: Jinja2
- **样式**: CSS3, Font Awesome
- **数据存储**: JSON文件

## 注意事项

1. 确保系统已安装Python 3.7或更高版本
2. 首次运行会自动创建虚拟环境和安装依赖
3. 历史记录保存在 `data/history.json` 文件中
4. 应用默认运行在端口8000，如需修改请编辑 `main.py`

## 开发说明

如需修改前端样式，请编辑：
- `templates/index.html` - 主页面模板
- `templates/history.html` - 历史记录模板
- `static/style.css` - 自定义样式

后端逻辑修改请编辑 `main.py` 文件。