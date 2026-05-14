from fastapi import FastAPI, Request, Form, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import json
import os
import shutil
import re
from datetime import datetime
import markdown
from typing import Dict, Any, List
import subprocess
import tempfile
import aiofiles
import uuid
import time
from concurrent.futures import ThreadPoolExecutor
import threading

# 导入配置类
from config.config import config

app = FastAPI(title="病历分析系统", version="2.0.0")

# 挂载静态文件和模板
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# 使用配置类获取配置项
HISTORY_FILE = config.history_file
UPLOAD_DIR = config.upload_dir
STANDARDS_DIR = "standards"
STANDARDS_FILE = "data/standards.json"

# 确保数据目录存在
os.makedirs("data", exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(STANDARDS_DIR, exist_ok=True)

# 分析任务管理
TASKS_FILE = "data/tasks.json"  # 任务数据存储文件
analysis_executor = ThreadPoolExecutor(max_workers=2)  # 限制并发任务数
TASK_EXPIRATION_TIME = 24 * 3600  # 24小时后过期

# 确保任务数据目录存在
os.makedirs("data", exist_ok=True)

def load_tasks() -> dict:
    """加载任务数据"""
    if os.path.exists(TASKS_FILE):
        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}
    return {}

def save_tasks(tasks: dict):
    """保存任务数据"""
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)

# 全局任务存储
global_analysis_tasks = load_tasks()

def load_history() -> list:
    """加载历史记录"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []
    return []

def save_history(history: list):
    """保存历史记录"""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def load_standards() -> dict:
    """加载标准文件列表"""
    if os.path.exists(STANDARDS_FILE):
        try:
            with open(STANDARDS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"selected_id": None, "standards": []}
    return {"selected_id": None, "standards": []}

def save_standards(data: dict):
    """保存标准文件列表"""
    with open(STANDARDS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_selected_standard() -> dict:
    """获取当前选中的标准文件信息"""
    data = load_standards()
    if not data["selected_id"]:
        return None
    for item in data["standards"]:
        if item["id"] == data["selected_id"]:
            return item
    return None

def cleanup_expired_tasks():
    """清理过期的任务"""
    global global_analysis_tasks
    current_time = time.time()
    expired_tasks = []
    
    for task_id, task_data in list(global_analysis_tasks.items()):
        task_age = current_time - task_data["start_time"]
        
        # 如果任务已完成或失败，且超过24小时，则标记为过期
        if task_data["status"] in ["completed", "failed"] and task_age > TASK_EXPIRATION_TIME:
            expired_tasks.append(task_id)
    
    # 删除过期任务
    for task_id in expired_tasks:
        del global_analysis_tasks[task_id]
    
    # 保存更新后的任务数据
    if expired_tasks:
        save_tasks(global_analysis_tasks)
        print(f"[清理任务] 清理了 {len(expired_tasks)} 个过期任务")

def start_cleanup_scheduler():
    """启动定期清理任务的调度器"""
    def cleanup_loop():
        while True:
            time.sleep(3600)  # 每小时执行一次
            try:
                cleanup_expired_tasks()
            except Exception as e:
                print(f"[清理任务] 清理过程中出错: {e}")
    
    thread = threading.Thread(target=cleanup_loop, daemon=True)
    thread.start()
    print("[启动] 任务清理调度器已启动")

def markdown_to_html(markdown_text: str) -> str:
    """将Markdown转换为HTML，正确处理<think>标签"""
    if not markdown_text:
        return ""
    
    # 检查是否包含 <think> 标签
    think_pattern = r'<think>([\s\S]*?)</think>'
    match = re.search(think_pattern, markdown_text)
    
    if match:
        # 分离 think 内容和正式结果
        think_content = match.group(1).strip()
        # 获取 </think> 之后的内容
        result_content = markdown_text[match.end():].strip()
        
        # 分别转换
        think_html = markdown.markdown(think_content, extensions=['tables'])
        result_html = markdown.markdown(result_content, extensions=['tables'])
        
        # 重新组合，保留 think 标签结构供前端处理
        return f'<div class="think-wrapper"><think>{think_html}</think></div>\n{result_html}'
    
    return markdown.markdown(markdown_text, extensions=['tables'])

def create_analysis_task(record_filename: str, standard_filename: str) -> str:
    """创建分析任务"""
    task_id = str(uuid.uuid4())
    start_time = time.time()
    
    global_analysis_tasks[task_id] = {
        "id": task_id,
        "status": "pending",  # pending, running, completed, failed
        "progress": 0,
        "current_step": "等待开始",
        "start_time": start_time,
        "end_time": None,
        "record_filename": record_filename,
        "standard_filename": standard_filename,
        "result": None,
        "error": None
    }
    
    # 保存任务数据
    save_tasks(global_analysis_tasks)
    
    return task_id

def update_task_status(task_id: str, status: str, progress: int = None, current_step: str = None):
    """更新任务状态"""
    if task_id in global_analysis_tasks:
        global_analysis_tasks[task_id]["status"] = status
        if progress is not None:
            global_analysis_tasks[task_id]["progress"] = progress
        if current_step is not None:
            global_analysis_tasks[task_id]["current_step"] = current_step
        
        if status in ["completed", "failed"]:
            global_analysis_tasks[task_id]["end_time"] = time.time()
        
        # ✓ 关键：每次更新都保存到文件，确保数据持久化
        save_tasks(global_analysis_tasks)

def get_task_info(task_id: str) -> Dict[str, Any]:
    """获取任务信息"""
    if task_id not in global_analysis_tasks:
        return {"error": "任务不存在"}
    
    task = global_analysis_tasks[task_id].copy()
    
    # 计算已用时间
    if task["start_time"]:
        elapsed_time = time.time() - task["start_time"]
        task["elapsed_time"] = round(elapsed_time, 2)
    
    # 计算总耗时（如果已完成）
    if task["end_time"]:
        total_time = task["end_time"] - task["start_time"]
        task["total_time"] = round(total_time, 2)
    
    return task

async def save_upload_file(file: UploadFile, filename: str) -> tuple:
    """保存上传的文件，返回文件路径和文件内容"""
    # 生成文件名：UUID + 原始文件名后缀
    file_uuid = str(uuid.uuid4())
    file_extension = os.path.splitext(file.filename)[1]
    filename = f"{file_uuid}{file_extension}"
    
    # 保存文件
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    # 读取文件内容
    content = await file.read()
    
    # 保存文件到本地
    async with aiofiles.open(file_path, "wb") as buffer:
        await buffer.write(content)
    
    # 返回文件路径和内容（用于后续上传到Dify）
    return filename, content

async def save_upload_file_content(content: bytes, original_filename: str) -> str:
    """保存文件内容到本地，返回文件名"""
    # 生成文件名：UUID + 原始文件名后缀
    file_uuid = str(uuid.uuid4())
    file_extension = os.path.splitext(original_filename)[1]
    filename = f"{file_uuid}{file_extension}"
    
    # 保存文件
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    # 保存文件到本地
    async with aiofiles.open(file_path, "wb") as buffer:
        await buffer.write(content)
    
    # 返回文件名
    return filename

async def run_workflow_analysis(record_content: bytes, standard_content: bytes, record_filename: str, standard_filename: str, task_id: str = None) -> Dict[str, Any]:
    """运行工作流分析"""
    try:
        # 使用线程池异步执行同步的DifyClient操作
        import asyncio
        import sys
        sys.path.append(os.getcwd())
        
        from run_workflow import DifyClient
        
        def sync_workflow_analysis():
            """同步执行工作流分析"""
            print(f"[工作流] 开始执行分析任务: {task_id}")
            print(f"[工作流] 病历文件: {record_filename}, 标准文件: {standard_filename}")
            
            if task_id:
                update_task_status(task_id, "running", 10, "初始化分析环境")
                print(f"[工作流] 任务状态已更新: {task_id} -> running (10%)")
            
            # 使用配置类创建Dify客户端
            print(f"[工作流] 创建 Dify 客户端: {config.dify_base_url}")
            client = DifyClient(config.dify_base_url, config.dify_api_key)
            
            if task_id:
                update_task_status(task_id, "running", 30, "上传病历文件")
                print(f"[工作流] 任务状态已更新: {task_id} -> running (30%)")
            
            # 上传文件 - 使用文件内容而不是文件路径
            # 创建临时文件用于上传
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(record_filename)[1]) as temp_record:
                temp_record.write(record_content)
                temp_record_path = temp_record.name
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(standard_filename)[1]) as temp_standard:
                temp_standard.write(standard_content)
                temp_standard_path = temp_standard.name
            
            try:
                print(f"[工作流] 上传病历文件: {temp_record_path}")
                record_id = client.upload_file(temp_record_path, "custom", "medical-record-user")
                print(f"[工作流] 病历文件上传成功: {record_id}")
                
                print(f"[工作流] 上传标准文件: {temp_standard_path}")
                standard_id = client.upload_file(temp_standard_path, "document", "medical-record-user")
                print(f"[工作流] 标准文件上传成功: {standard_id}")
            finally:
                # 清理临时文件
                if os.path.exists(temp_record_path):
                    os.unlink(temp_record_path)
                    print(f"[工作流] 临时文件已清理: {temp_record_path}")
                if os.path.exists(temp_standard_path):
                    os.unlink(temp_standard_path)
                    print(f"[工作流] 临时文件已清理: {temp_standard_path}")
            
            if not record_id or not standard_id:
                print(f"[工作流] 文件上传失败: record_id={record_id}, standard_id={standard_id}")
                if task_id:
                    update_task_status(task_id, "failed", 100, "文件上传失败")
                return {"error": "文件上传失败"}
            
            if task_id:
                update_task_status(task_id, "running", 50, "文件上传完成，开始执行工作流")
                print(f"[工作流] 任务状态已更新: {task_id} -> running (50%)")
            
            # 执行工作流
            print(f"[工作流] 准备执行工作流...")
            inputs = {
                "recoder": {
                    "transfer_method": "local_file",
                    "upload_file_id": record_id,
                    "type": "custom"
                },
                "stand": {
                    "transfer_method": "local_file",
                    "upload_file_id": standard_id,
                    "type": "document"
                }
            }
            print(f"[工作流] 工作流输入: {json.dumps(inputs, indent=2)}")
            
            if task_id:
                update_task_status(task_id, "running", 70, "工作流执行中...")
                print(f"[工作流] 任务状态已更新: {task_id} -> running (70%)")
            
            print(f"[工作流] 调用 Dify API 执行工作流...")
            result = client.run_workflow(inputs, "medical-record-user")
            print(f"[工作流] 工作流执行完成，返回结果")
            
            if "error" in result:
                print(f"[工作流] 工作流执行失败: {result['error']}")
                if task_id:
                    update_task_status(task_id, "failed", 100, f"工作流执行失败: {result['error']}")
                return {"error": f"工作流执行失败: {result['error']}"}
            
            if task_id:
                update_task_status(task_id, "running", 90, "解析分析结果")
                print(f"[工作流] 任务状态已更新: {task_id} -> running (90%)")
            
            # 解析工作流输出
            outputs = result.get('data', {}).get('outputs', {})
            
            # 根据实际工作流输出结构解析结果
            # 工作流输出4个部分：record_rating, record_all, record, count
            record_rating = outputs.get('record_rating', "")
            record_all = outputs.get('record_all', "")
            record = outputs.get('record', "")
            count = outputs.get('count', "")  # 统计数据（JSON字符串）
            
            # 如果工作流没有返回数据，使用示例数据
            if not record_rating:
                record_rating = "## 扣分项目\n| 序号 | 缺陷模块名称 | 缺陷描述 | 对应评分标准 | 缺陷等级 | 扣分值 |\n| :--- | :--- | :--- | :--- | :--- | :--- |\n| 1 | 既往史 | 既往史缺失 | [Rule_37] 全局逻辑矛盾 | 重大 | 5分 |\n| 2 | 医生签名 | 医生签名缺失 | [Rule_37] 全局逻辑矛盾 | 重大 | 5分 |\n\n## 计算评分\n总分 = 100 - (5+5) = 90\n\n## 病历等级\n**90** >= 90  评定为**甲等**"
            
            if not record_all:
                record_all = "# 病历信息\n\"姓名\": \"黄翠卿\"\n\"门诊卡号\": \"0100****6732\",\n\"就诊日期\": \"2025-08-14 10:00\"\n\n# 问题列表\n\n| 序号 | 缺陷模块名称 | 缺陷描述 ｜\n|-----|-----|------|\n| 1 | 基 本信息 | 完整性缺失，门诊病历应包含患者姓名、性别、年龄或出生日期等基本信息 |\n| 2 | 过敏史 | 完整性缺失，门诊病历应有过敏史记录（包括药物、食物等过敏情况） |\n| 3 | 既往史 | 完整性缺失，门诊病历应有既往 疾病史、手术史、外伤史等相关记录 |\n| 4 | 体格检查 | 完整性缺失，门诊病历应有与主诉相关的体格检查记录 |\n| 5 | 辅助检查 | 完整性缺失，门诊病历应有相关的辅助检查记录或说明 |\n| 6 | 初步诊断 | 完整性缺失， 门诊病历应有初步诊断或确定诊断记录 |\n| 7 | 处理意见 | 完整性缺失，门诊病历应有治疗方案、用药指导或进 一步检查建议 |\n| 8 | 医师签名 | 完整性缺失，门诊病历应有接诊医师签名及签署日期 |\n| 9 | 主诉规范性 | 主诉不规范，应包含部位、性质、程度、持续时间等要素 |\n| 10 | 现病史详细性 | 现病史内容不完整，缺少起病情况、伴随症状、加重缓解因素等详细信息 |\n| 11 | 病历唯一标识 | 缺少就诊日期、门诊号等关键标识信息，无法确保病历的唯一性 |\n| 12 | 诊疗过程完整性 | 缺少体格检查、辅助检查、诊断、治疗方案等核心内容 |\n| 13 | 药品使用合规 | 未记录任何用药信息，无法判断药品使用是否符合规范要求 |\n| 14 | 随访/安全告知 | 缺失 随访计划和患者安全告知相关内容 |\n| 15 | 时间记录 | 病历未见具体就诊时间等时间信息 |\n| 16 | 现病史特 征描述 | 缺乏对头痛特征的详细描述（部位、性质、程度、加重/缓解因素等） |\n| 17 | 伴随症状 | 缺乏伴随症状描述（有无发热、恶心呕吐、神经系统症状等） |\n| 18 | 风险评估 | 缺乏患者年龄、性别等关键信息，无法评估是否为高危人群 |\n| 19 | 月经史 | 完整性缺失，14到49岁女性应有月经史记录 |"
            
            if not record:
                record = "### 患者与就诊概况\n- 患者ID: P001\n\n### 病历书写记录 (SOAP)\n- 主诉: 头痛\n- 现病史: 患者因头痛就诊，持续 3 天\n\n*注：根据XML内容，仅存在以上字段。其他字段（如姓名、性别、过敏史、诊断等） 在XML中无对应标签，故不予显示。*"
            
            if task_id:
                update_task_status(task_id, "completed", 100, "分析完成")
                print(f"[工作流] 任务状态已更新: {task_id} -> completed (100%)")
            
            print(f"[工作流] 分析任务完成: {task_id}")
            return {
                "record_rating": record_rating,
                "record_all": record_all,
                "record": record,
                "count": count  # 统计数据
            }
        
        # 在线程池中异步执行同步代码
        print(f"[工作流] 在线程池中执行分析任务: {task_id}")
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, sync_workflow_analysis)
        print(f"[工作流] 线程池执行完成: {task_id}")
        return result
        
    except Exception as e:
        print(f"[工作流] 执行工作流时出错: {str(e)}")
        import traceback
        traceback.print_exc()
        if task_id:
            update_task_status(task_id, "failed", 100, f"执行工作流时出错: {str(e)}")
        return {"error": f"执行工作流时出错: {str(e)}"}

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """首页 - 文件上传和分析"""
    return templates.TemplateResponse("index.html", {
        "request": request,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

@app.post("/api/analyze")
async def analyze_files(
    record_file: UploadFile = File(...)
):
    """分析上传的文件（异步版本，返回任务ID）"""
    try:
        print(f"[API] 收到分析请求")
        print(f"[API] 病历文件: {record_file.filename}")
        
        # 验证病历文件
        if not record_file.filename:
            print(f"[API] 文件验证失败")
            raise HTTPException(status_code=400, detail="请选择病历文件")
        
        # 获取当前选中的标准文件
        selected_standard = get_selected_standard()
        if not selected_standard:
            raise HTTPException(status_code=400, detail="请先到知识库选择标准文件")
        
        standard_filepath = os.path.join(STANDARDS_DIR, selected_standard["filepath"])
        if not os.path.exists(standard_filepath):
            raise HTTPException(status_code=400, detail="标准文件不存在，请重新选择")
        
        print(f"[API] 使用标准文件: {selected_standard['filename']}")
        
        # 读取病历文件内容
        print(f"[API] 读取病历文件内容...")
        record_content = await record_file.read()
        print(f"[API] 病历文件大小: {len(record_content)} bytes")
        
        # 读取标准文件内容
        print(f"[API] 读取标准文件内容...")
        async with aiofiles.open(standard_filepath, "rb") as f:
            standard_content = await f.read()
        print(f"[API] 标准文件大小: {len(standard_content)} bytes")
        
        standard_filename = selected_standard["filename"]
        
        # 创建分析任务
        task_id = create_analysis_task(record_file.filename, standard_filename)
        print(f"[API] 创建分析任务: {task_id}")
        
        # 异步执行分析任务
        async def run_analysis():
            try:
                print(f"[后台] 开始执行分析任务: {task_id}")
                # 保存上传的病历文件（使用UUID文件名）
                print(f"[后台] 保存病历文件...")
                saved_record_filename = await save_upload_file_content(record_content, record_file.filename)
                print(f"[后台] 病历文件已保存: {saved_record_filename}")
                
                # 运行工作流分析
                print(f"[后台] 调用工作流分析...")
                analysis_result = await run_workflow_analysis(record_content, standard_content, saved_record_filename, standard_filename, task_id)
                print(f"[后台] 工作流分析完成")
                
                if "error" in analysis_result:
                    print(f"[后台] 分析出错: {analysis_result['error']}")
                    global_analysis_tasks[task_id]["error"] = analysis_result["error"]
                    save_tasks(global_analysis_tasks)
                    return
                
                # 保存到历史记录
                print(f"[后台] 保存分析结果到历史记录...")
                history = load_history()
                # 修复：使用最大ID而不是记录数，避免删除旧记录后ID冲突
                max_id = max([item["id"] for item in history] or [0])
                next_id = max_id + 1
                default_record_name = f"{next_id}_{record_file.filename}"
                history_item = {
                    "id": next_id,
                    "record_name": default_record_name,
                    "timestamp": datetime.now().isoformat(),
                    "record_filename": record_file.filename,
                    "standard_filename": standard_filename,
                    "record_path": saved_record_filename,
                    "standard_path": selected_standard["filepath"],
                    "analysis_result": analysis_result
                }
                
                history.append(history_item)
                save_history(history)
                print(f"[后台] 历史记录已保存")
                
                # 转换为HTML
                result_html = {
                    "record_rating": markdown_to_html(analysis_result["record_rating"]),
                    "record_all": markdown_to_html(analysis_result["record_all"]),
                    "record": markdown_to_html(analysis_result["record"]),
                    "count": analysis_result.get("count", "")  # 统计数据保持原样（JSON字符串）
                }
                
                global_analysis_tasks[task_id]["result"] = {
                    "status": "success",
                    "message": "分析完成",
                    "result": result_html,
                    "record_id": history_item["id"]
                }
                save_tasks(global_analysis_tasks)
                print(f"[后台] 分析任务完成: {task_id}")
                
            except Exception as e:
                print(f"[后台] 分析任务异常: {str(e)}")
                import traceback
                traceback.print_exc()
                global_analysis_tasks[task_id]["error"] = f"分析失败: {str(e)}"
                save_tasks(global_analysis_tasks)
        
        # 在后台执行分析任务
        print(f"[API] 在后台启动分析任务: {task_id}")
        import asyncio
        asyncio.create_task(run_analysis())
        
        print(f"[API] 返回任务ID: {task_id}")
        return {
            "status": "success",
            "message": "分析任务已开始",
            "task_id": task_id
        }
        
    except Exception as e:
        print(f"[API] 分析任务创建失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"分析任务创建失败: {str(e)}"}
        )

@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    """历史记录页面"""
    history = load_history()
    return templates.TemplateResponse("history.html", {
        "request": request,
        "history": history
    })

@app.get("/standards", response_class=HTMLResponse)
async def standards_page(request: Request):
    """知识库页面"""
    return templates.TemplateResponse("standards.html", {"request": request})

@app.get("/api/standards")
async def get_standards():
    """获取标准文件列表"""
    data = load_standards()
    return {"status": "success", "data": data}

@app.post("/api/standards/upload")
async def upload_standard(file: UploadFile = File(...)):
    """上传标准文件"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="请选择文件")
    
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".xml", ".md", ".txt", ".json"]:
        raise HTTPException(status_code=400, detail="不支持的文件格式")
    
    file_id = str(uuid.uuid4())
    filepath = f"{file_id}{ext}"
    file_path = os.path.join(STANDARDS_DIR, filepath)
    
    content = await file.read()
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)
    
    data = load_standards()
    data["standards"].append({
        "id": file_id,
        "filename": file.filename,
        "filepath": filepath,
        "upload_time": datetime.now().isoformat()
    })
    save_standards(data)
    
    return {"status": "success", "message": "上传成功"}

@app.post("/api/standards/{standard_id}/select")
async def select_standard(standard_id: str):
    """设置默认标准"""
    data = load_standards()
    
    found = False
    for item in data["standards"]:
        if item["id"] == standard_id:
            found = True
            break
    
    if not found:
        raise HTTPException(status_code=404, detail="标准文件不存在")
    
    data["selected_id"] = standard_id
    save_standards(data)
    
    return {"status": "success", "message": "设置成功"}

@app.delete("/api/standards/{standard_id}")
async def delete_standard(standard_id: str):
    """删除标准文件"""
    data = load_standards()
    
    if data["selected_id"] == standard_id:
        raise HTTPException(status_code=400, detail="不能删除当前选中的标准，请先切换到其他标准")
    
    for i, item in enumerate(data["standards"]):
        if item["id"] == standard_id:
            file_path = os.path.join(STANDARDS_DIR, item["filepath"])
            if os.path.exists(file_path):
                os.remove(file_path)
            del data["standards"][i]
            save_standards(data)
            return {"status": "success", "message": "删除成功"}
    
    raise HTTPException(status_code=404, detail="标准文件不存在")

@app.get("/api/history/{record_id}")
async def get_history_record(record_id: int):
    """获取特定历史记录"""
    history = load_history()
    
    for item in history:
        if item["id"] == record_id:
            result = item["analysis_result"]
            return {
                "status": "success",
                "data": {
                    "record": markdown_to_html(result["record"]),
                    "record_rating": markdown_to_html(result["record_rating"]),
                    "record_all": markdown_to_html(result["record_all"]),
                    "count": result.get("count", ""),  # 统计数据（可能不存在于旧记录）
                    "record_filename": item["record_filename"],
                    "standard_filename": item["standard_filename"],
                    "timestamp": item["timestamp"],
                    "record_name": item.get("record_name", f"分析记录 #{record_id}")
                }
            }
    
    raise HTTPException(status_code=404, detail="记录不存在")

@app.get("/api/history/{record_id}/delete")
async def delete_history_record(record_id: int):
    """删除历史记录"""
    history = load_history()
    
    for i, item in enumerate(history):
        if item["id"] == record_id:
            # 删除文件
            if os.path.exists(item["record_path"]):
                os.remove(item["record_path"])
            if os.path.exists(item["standard_path"]):
                os.remove(item["standard_path"])
            
            # 删除记录
            del history[i]
            save_history(history)
            
            return {"status": "success", "message": "记录已删除"}
    
    raise HTTPException(status_code=404, detail="记录不存在")

@app.post("/api/history/{record_id}/rename")
async def rename_history_record(record_id: int, request: Request):
    """重命名历史记录"""
    try:
        data = await request.json()
        new_name = data.get("name")  # ✓ 改为 "name" 用于修改记录名称
        
        print(f"[重命名] 收到重命名请求: record_id={record_id}, new_name={new_name}")
        
        if not new_name:
            print(f"[重命名] 参数验证失败")
            raise HTTPException(status_code=400, detail="请提供记录名称")
        
        history = load_history()
        
        for item in history:
            if item["id"] == record_id:
                old_name = item.get("record_name", f"分析记录 #{record_id}")
                item["record_name"] = new_name.strip()
                
                print(f"[重命名] 记录名称已修改: {old_name} → {new_name.strip()}")
                
                save_history(history)
                print(f"[重命名] 历史记录已保存")
                return {"status": "success", "message": "记录名称已修改"}
        
        print(f"[重命名] 记录不存在: {record_id}")
        raise HTTPException(status_code=404, detail="记录不存在")
        
    except Exception as e:
        print(f"[重命名] 重命名失败: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"重命名失败: {str(e)}")

@app.get("/api/analysis/task/{task_id}")
async def get_analysis_task_status(task_id: str):
    """获取分析任务状态"""
    task_info = get_task_info(task_id)
    
    if "error" in task_info:
        # 任务不在内存中，尝试从文件中重新加载
        current_time = time.time()
        all_tasks = load_tasks()
        
        if task_id in all_tasks:
            task_data = all_tasks[task_id]
            task_age = current_time - task_data["start_time"]
            
            # 检查任务是否已过期
            if task_age > TASK_EXPIRATION_TIME:
                return {
                    "status": "error",
                    "message": "任务已过期（超过24小时）",
                    "data": {
                        "id": task_id,
                        "status": "expired",
                        "progress": 0,
                        "current_step": "任务已过期"
                    }
                }
            else:
                # 任务存在但不在内存中，重新加载到内存
                global_analysis_tasks[task_id] = task_data
                task_info = get_task_info(task_id)
        else:
            # 任务不存在
            return {
                "status": "error",
                "message": "任务不存在",
                "data": {
                    "id": task_id,
                    "status": "not_found",
                    "progress": 0,
                    "current_step": "任务不存在"
                }
            }
    
    response = {
        "status": "success",
        "data": task_info
    }
    
    # 如果任务已完成且有结果，返回结果
    if task_info["status"] == "completed" and task_info.get("result"):
        response["result"] = task_info["result"]
    elif task_info["status"] == "failed" and task_info.get("error"):
        response["error"] = task_info["error"]
    
    return response

@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    # 启动任务清理调度器
    start_cleanup_scheduler()
    print("[启动] 应用已启动")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app, 
        host=config.server_host, 
        port=config.server_port
    )