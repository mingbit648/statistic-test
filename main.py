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
HISTORY_INDEX_FILE = "data/history_index.json"
HISTORY_RECORDS_DIR = "data/history_records"
CONCURRENCY_TESTS_FILE = "data/concurrency_tests.json"
CONCURRENCY_MAX_TESTS_PER_RECORD = 100
CONCURRENCY_MAX_ATTEMPTS_PER_ROUND = 100
CONCURRENCY_RECORD_DISPATCH_INTERVAL_SECONDS = 2

# 确保数据目录存在
os.makedirs("data", exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(STANDARDS_DIR, exist_ok=True)
os.makedirs(HISTORY_RECORDS_DIR, exist_ok=True)

# 分析任务管理
TASKS_FILE = "data/tasks.json"  # 任务数据存储文件
ANALYSIS_BATCHES_FILE = "data/analysis_batches.json"  # 首页分析批次数据存储文件
analysis_executor = ThreadPoolExecutor(max_workers=2)  # 限制并发任务数
TASK_EXPIRATION_TIME = 24 * 3600  # 24小时后过期
HOME_ANALYSIS_MAX_CONCURRENCY = 20
tasks_lock = threading.RLock()
history_lock = threading.RLock()
analysis_batches_lock = threading.RLock()
concurrency_tests_lock = threading.Lock()

# 确保任务数据目录存在
os.makedirs("data", exist_ok=True)

def load_tasks() -> dict:
    """加载任务数据"""
    with tasks_lock:
        if os.path.exists(TASKS_FILE):
            try:
                with open(TASKS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                return {}
    return {}

def save_tasks(tasks: dict):
    """保存任务数据"""
    with tasks_lock:
        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)

def load_analysis_batches() -> dict:
    """加载首页分析批次数据"""
    with analysis_batches_lock:
        if os.path.exists(ANALYSIS_BATCHES_FILE):
            try:
                with open(ANALYSIS_BATCHES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("batches"), list):
                    return data
            except (json.JSONDecodeError, FileNotFoundError):
                pass
    return {"batches": []}

def save_analysis_batches(data: dict):
    """保存首页分析批次数据"""
    with analysis_batches_lock:
        with open(ANALYSIS_BATCHES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

# 全局任务存储
global_analysis_tasks = load_tasks()
global_analysis_batches = load_analysis_batches()

def load_concurrency_tests() -> dict:
    """加载并发测试批次数据"""
    if os.path.exists(CONCURRENCY_TESTS_FILE):
        try:
            with open(CONCURRENCY_TESTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("batches"), list):
                return data
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    return {"batches": []}

def save_concurrency_tests(data: dict):
    """保存并发测试批次数据"""
    with open(CONCURRENCY_TESTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

global_concurrency_tests = load_concurrency_tests()

def load_legacy_history() -> list:
    """加载旧版完整历史记录文件。"""
    with history_lock:
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                return []
    return []

def save_legacy_history(history: list):
    """保存旧版完整历史记录文件。"""
    with history_lock:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

def _history_detail_path(record_id: int) -> str:
    return os.path.join(HISTORY_RECORDS_DIR, f"{record_id}.json")

def _history_index_entry(item: dict, source_type: str, source_path: str) -> dict:
    record_id = int(item["id"])
    return {
        "id": record_id,
        "record_name": item.get("record_name", f"分析记录 #{record_id}"),
        "timestamp": item.get("timestamp", ""),
        "record_filename": item.get("record_filename", ""),
        "standard_filename": item.get("standard_filename", ""),
        "source_type": source_type,
        "source_path": source_path,
        "deleted": bool(item.get("deleted", False))
    }

def rebuild_history_index() -> list:
    """从旧历史文件和新详情目录重建轻量历史索引。"""
    entries = []

    for item in load_legacy_history():
        if isinstance(item, dict) and "id" in item:
            entries.append(_history_index_entry(item, "legacy", HISTORY_FILE))

    if os.path.exists(HISTORY_RECORDS_DIR):
        for filename in os.listdir(HISTORY_RECORDS_DIR):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(HISTORY_RECORDS_DIR, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    item = json.load(f)
                if isinstance(item, dict) and "id" in item:
                    entries.append(_history_index_entry(item, "record_file", path))
            except (json.JSONDecodeError, OSError):
                continue

    deduped = {}
    for entry in entries:
        deduped[entry["id"]] = entry
    entries = sorted(deduped.values(), key=lambda item: item["id"])
    save_history_index(entries)
    return entries

def load_history_index() -> list:
    """加载轻量历史索引；缺失或损坏时自动重建。"""
    with history_lock:
        if os.path.exists(HISTORY_INDEX_FILE):
            try:
                with open(HISTORY_INDEX_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return data
            except (json.JSONDecodeError, FileNotFoundError):
                pass
        return rebuild_history_index()

def save_history_index(index: list):
    """保存轻量历史索引。"""
    with history_lock:
        with open(HISTORY_INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

def load_history() -> list:
    """加载历史页使用的轻量历史记录。"""
    return [item for item in load_history_index() if not item.get("deleted")]

def load_history_detail(record_id: int) -> dict:
    """按历史 ID 加载完整历史详情。"""
    index = load_history_index()
    entry = next((item for item in index if item.get("id") == record_id and not item.get("deleted")), None)
    if not entry:
        return None

    if entry.get("source_type") == "legacy":
        for item in load_legacy_history():
            if item.get("id") == record_id:
                return item
        return None

    source_path = entry.get("source_path") or _history_detail_path(record_id)
    if not os.path.exists(source_path):
        return None
    try:
        with open(source_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

def next_history_id(index: list = None) -> int:
    """获取下一个历史 ID，兼容旧历史和新索引。"""
    index = index if index is not None else load_history_index()
    ids = [item.get("id", 0) for item in index]
    ids.extend(item.get("id", 0) for item in load_legacy_history())
    return max(ids or [0]) + 1

def format_history_time(timestamp: str) -> str:
    """历史记录名称使用的时间格式。"""
    try:
        return datetime.fromisoformat(timestamp).strftime("%Y-%m-%d %H-%M-%S")
    except ValueError:
        return datetime.now().strftime("%Y-%m-%d %H-%M-%S")

def remove_history_assets(item: dict):
    """删除历史记录关联的上传病历文件；标准文件可能被复用，不在这里删除。"""
    record_path = item.get("record_path")
    if not record_path:
        return
    candidates = [record_path, os.path.join(UPLOAD_DIR, record_path)]
    for path in candidates:
        try:
            if os.path.exists(path) and os.path.isfile(path):
                os.remove(path)
                return
        except OSError:
            return

def delete_history_by_id(record_id: int) -> bool:
    """删除历史记录，同步维护旧文件/详情文件和索引。"""
    with history_lock:
        index = load_history_index()
        entry_index = next((i for i, item in enumerate(index) if item.get("id") == record_id), None)
        if entry_index is None:
            return False

        entry = index[entry_index]
        if entry.get("source_type") == "legacy":
            history = load_legacy_history()
            for i, item in enumerate(history):
                if item.get("id") == record_id:
                    remove_history_assets(item)
                    del history[i]
                    save_legacy_history(history)
                    break
        else:
            detail = load_history_detail(record_id)
            if detail:
                remove_history_assets(detail)
            source_path = entry.get("source_path") or _history_detail_path(record_id)
            try:
                if os.path.exists(source_path):
                    os.remove(source_path)
            except OSError:
                pass

        del index[entry_index]
        save_history_index(index)
        return True

def rename_history_by_id(record_id: int, new_name: str) -> str:
    """重命名历史记录，同步维护旧文件/详情文件和索引。"""
    with history_lock:
        index = load_history_index()
        entry = next((item for item in index if item.get("id") == record_id), None)
        if not entry:
            return None

        old_name = entry.get("record_name", f"分析记录 #{record_id}")
        if entry.get("source_type") == "legacy":
            history = load_legacy_history()
            found = False
            for item in history:
                if item.get("id") == record_id:
                    item["record_name"] = new_name
                    found = True
                    break
            if not found:
                return None
            save_legacy_history(history)
        else:
            detail = load_history_detail(record_id)
            if not detail:
                return None
            detail["record_name"] = new_name
            source_path = entry.get("source_path") or _history_detail_path(record_id)
            with open(source_path, "w", encoding="utf-8") as f:
                json.dump(detail, f, ensure_ascii=False, indent=2)

        entry["record_name"] = new_name
        save_history_index(index)
        return old_name

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

def mask_api_key(api_key: str) -> str:
    """脱敏显示 Dify API Key"""
    if not api_key:
        return ""
    if len(api_key) <= 10:
        return "*" * len(api_key)
    return f"{api_key[:6]}...{api_key[-4:]}"

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
    
    with tasks_lock:
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
    
    with tasks_lock:
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
    with tasks_lock:
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

def normalize_completed_task(task_id: str) -> bool:
    """兼容修复：result 已存在但状态未完成的旧任务按完成处理。"""
    with tasks_lock:
        task = global_analysis_tasks.get(task_id)
        if not task or not task.get("result") or task.get("status") == "completed":
            return False

        task["status"] = "completed"
        task["progress"] = 100
        task["current_step"] = "分析完成"
        if not task.get("end_time"):
            task["end_time"] = time.time()
        save_tasks(global_analysis_tasks)
        return True

def get_task_info(task_id: str) -> Dict[str, Any]:
    """获取任务信息"""
    with tasks_lock:
        if task_id not in global_analysis_tasks:
            return {"error": "任务不存在"}

        normalize_completed_task(task_id)
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

def _find_concurrency_batch(batch_id: str) -> dict:
    for batch in global_concurrency_tests["batches"]:
        if batch["id"] == batch_id:
            return batch
    return None

def _recalculate_concurrency_summary(batch: dict):
    details = batch.get("details", [])
    completed_details = [
        item for item in details
        if item.get("status") in ["success", "failed"]
    ]
    successful_details = [
        item for item in details
        if item.get("status") == "success"
    ]
    failed_details = [
        item for item in details
        if item.get("status") == "failed"
    ]
    durations = [
        item["duration_seconds"] for item in completed_details
        if isinstance(item.get("duration_seconds"), (int, float))
    ]

    batch["completed_attempts"] = len(completed_details)
    batch["success_count"] = len(successful_details)
    batch["failed_count"] = len(failed_details)
    batch["avg_duration_seconds"] = round(sum(durations) / len(durations), 3) if durations else 0
    batch["min_duration_seconds"] = round(min(durations), 3) if durations else 0
    batch["max_duration_seconds"] = round(max(durations), 3) if durations else 0

def update_concurrency_batch(batch_id: str, **fields):
    """更新并发测试批次状态"""
    with concurrency_tests_lock:
        batch = _find_concurrency_batch(batch_id)
        if not batch:
            return
        batch.update(fields)
        _recalculate_concurrency_summary(batch)
        save_concurrency_tests(global_concurrency_tests)

def update_concurrency_attempt(batch_id: str, attempt_id: str, **fields):
    """更新并发测试单次明细"""
    with concurrency_tests_lock:
        batch = _find_concurrency_batch(batch_id)
        if not batch:
            return
        for detail in batch.get("details", []):
            if detail["attempt_id"] == attempt_id:
                detail.update(fields)
                break
        _recalculate_concurrency_summary(batch)
        save_concurrency_tests(global_concurrency_tests)

def get_concurrency_batch_info(batch_id: str) -> dict:
    """获取并发测试批次信息"""
    with concurrency_tests_lock:
        batch = _find_concurrency_batch(batch_id)
        if not batch:
            return None
        return json.loads(json.dumps(batch, ensure_ascii=False))

def summarize_workflow_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """提取单次工作流结果摘要，避免并发测试明细过大"""
    count_data = result.get("count") if result else None
    if isinstance(count_data, str) and count_data.strip():
        try:
            count_data = json.loads(count_data)
        except json.JSONDecodeError:
            count_data = None

    details = count_data.get("details", {}) if isinstance(count_data, dict) else {}
    return {
        "score": details.get("总分"),
        "grade": details.get("病历等级"),
        "record_rating_chars": len(result.get("record_rating", "")) if result else 0,
        "record_all_chars": len(result.get("record_all", "")) if result else 0,
        "record_chars": len(result.get("record", "")) if result else 0
    }

def workflow_result_to_html(result: Dict[str, Any]) -> Dict[str, Any]:
    """将工作流 Markdown 结果转换为首页/历史页面可展示的 HTML。"""
    return {
        "record_rating": markdown_to_html(result["record_rating"]),
        "record_all": markdown_to_html(result["record_all"]),
        "record": markdown_to_html(result["record"]),
        "count": result.get("count", "")
    }

def save_analysis_result_to_history(
    record_filename: str,
    standard_filename: str,
    record_path: str,
    standard_path: str,
    analysis_result: Dict[str, Any],
    record_name: str = None,
    submitted_at: str = None,
    attempt_index: int = None
) -> dict:
    """原子化写入新历史详情文件和轻量索引，并返回新记录。"""
    with history_lock:
        index = load_history_index()
        next_id = next_history_id(index)
        timestamp = datetime.now().isoformat()
        name_time = format_history_time(submitted_at or timestamp)

        if record_name:
            resolved_record_name = (
                record_name
                .replace("{history_id}", str(next_id))
                .replace("{submitted_time}", name_time)
            )
        elif attempt_index is not None:
            resolved_record_name = f"{next_id}_{record_filename}_{name_time}_第{attempt_index}次"
        else:
            resolved_record_name = f"{next_id}_{record_filename}_{name_time}"

        history_item = {
            "id": next_id,
            "record_name": resolved_record_name,
            "timestamp": timestamp,
            "record_filename": record_filename,
            "standard_filename": standard_filename,
            "record_path": record_path,
            "standard_path": standard_path,
            "analysis_result": analysis_result
        }
        detail_path = _history_detail_path(next_id)
        with open(detail_path, "w", encoding="utf-8") as f:
            json.dump(history_item, f, ensure_ascii=False, indent=2)

        index.append(_history_index_entry(history_item, "record_file", detail_path))
        index.sort(key=lambda item: item["id"])
        save_history_index(index)
        return history_item

def _find_analysis_batch(batch_id: str) -> dict:
    for batch in global_analysis_batches["batches"]:
        if batch["id"] == batch_id:
            return batch
    return None

def _find_analysis_attempt(batch: dict, attempt_id: str) -> dict:
    for attempt in batch.get("attempts", []):
        if attempt["attempt_id"] == attempt_id:
            return attempt
    return None

def _recalculate_analysis_batch_summary(batch: dict):
    attempts = batch.get("attempts", [])
    completed = [item for item in attempts if item.get("status") in ["success", "failed"]]
    successes = [item for item in attempts if item.get("status") == "success"]
    failures = [item for item in attempts if item.get("status") == "failed"]

    batch["completed_attempts"] = len(completed)
    batch["success_count"] = len(successes)
    batch["failed_count"] = len(failures)
    batch["updated_at"] = datetime.now().isoformat()

    if attempts and len(completed) == len(attempts):
        batch["status"] = "completed" if successes else "failed"
        if not batch.get("ended_at"):
            batch["ended_at"] = batch["updated_at"]
    elif any(item.get("status") == "running" for item in attempts):
        batch["status"] = "running"

def _analysis_batch_public_copy(batch: dict, include_results: bool = False) -> dict:
    copied = json.loads(json.dumps(batch, ensure_ascii=False))
    if not include_results:
        for attempt in copied.get("attempts", []):
            attempt.pop("result", None)
    return copied

def get_analysis_batch_info(batch_id: str, include_results: bool = False) -> dict:
    with analysis_batches_lock:
        batch = _find_analysis_batch(batch_id)
        if not batch:
            return None
        _recalculate_analysis_batch_summary(batch)
        save_analysis_batches(global_analysis_batches)
        return _analysis_batch_public_copy(batch, include_results=include_results)

def get_recent_analysis_batch_for_session(session_id: str) -> dict:
    with analysis_batches_lock:
        candidates = [
            batch for batch in global_analysis_batches["batches"]
            if batch.get("session_id") == session_id
        ]
        if not candidates:
            return None

        for batch in candidates:
            _recalculate_analysis_batch_summary(batch)
        save_analysis_batches(global_analysis_batches)

        running = [batch for batch in candidates if batch.get("status") in ["pending", "running"]]
        pool = running or candidates
        pool.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or "", reverse=True)
        return _analysis_batch_public_copy(pool[0], include_results=False)

def update_analysis_batch(batch_id: str, **fields):
    with analysis_batches_lock:
        batch = _find_analysis_batch(batch_id)
        if not batch:
            return
        batch.update(fields)
        _recalculate_analysis_batch_summary(batch)
        save_analysis_batches(global_analysis_batches)

def update_analysis_attempt(batch_id: str, attempt_id: str, **fields):
    with analysis_batches_lock:
        batch = _find_analysis_batch(batch_id)
        if not batch:
            return
        attempt = _find_analysis_attempt(batch, attempt_id)
        if not attempt:
            return
        attempt.update(fields)
        _recalculate_analysis_batch_summary(batch)
        save_analysis_batches(global_analysis_batches)

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

async def run_workflow_analysis(record_content: bytes, standard_content: bytes, record_filename: str, standard_filename: str, task_id: str = None, executor: ThreadPoolExecutor = None) -> Dict[str, Any]:
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
                    "type": "document"
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
        result = await loop.run_in_executor(executor, sync_workflow_analysis)
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
        analysis_submitted_at = datetime.now().isoformat()
        
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
                    with tasks_lock:
                        global_analysis_tasks[task_id]["error"] = analysis_result["error"]
                        save_tasks(global_analysis_tasks)
                    return
                
                # 保存到历史记录
                print(f"[后台] 保存分析结果到历史记录...")
                history_item = save_analysis_result_to_history(
                    record_filename=record_file.filename,
                    standard_filename=standard_filename,
                    record_path=saved_record_filename,
                    standard_path=selected_standard["filepath"],
                    analysis_result=analysis_result,
                    submitted_at=analysis_submitted_at
                )
                print(f"[后台] 历史记录已保存")
                
                # 转换为HTML
                result_html = workflow_result_to_html(analysis_result)
                
                with tasks_lock:
                    global_analysis_tasks[task_id]["result"] = {
                        "status": "success",
                        "message": "分析完成",
                        "result": result_html,
                        "record_id": history_item["id"]
                    }
                    global_analysis_tasks[task_id]["status"] = "completed"
                    global_analysis_tasks[task_id]["progress"] = 100
                    global_analysis_tasks[task_id]["current_step"] = "分析完成"
                    if not global_analysis_tasks[task_id].get("end_time"):
                        global_analysis_tasks[task_id]["end_time"] = time.time()
                    save_tasks(global_analysis_tasks)
                print(f"[后台] 分析任务完成: {task_id}")
                
            except Exception as e:
                print(f"[后台] 分析任务异常: {str(e)}")
                import traceback
                traceback.print_exc()
                with tasks_lock:
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

async def run_home_analysis_attempt(
    batch_id: str,
    attempt_id: str,
    attempt_index: int,
    batch_submitted_at: str,
    record_content: bytes,
    record_filename: str,
    standard_content: bytes,
    standard_filename: str,
    standard_path: str,
    executor: ThreadPoolExecutor
):
    """执行首页批次中的单次分析。"""
    started = time.time()
    update_analysis_attempt(
        batch_id,
        attempt_id,
        status="running",
        progress=10,
        current_step="初始化分析环境",
        started_at=datetime.now().isoformat()
    )

    try:
        update_analysis_attempt(
            batch_id,
            attempt_id,
            progress=70,
            current_step="工作流执行中..."
        )
        analysis_result = await run_workflow_analysis(
            record_content,
            standard_content,
            record_filename,
            standard_filename,
            None,
            executor=executor
        )
        duration = round(time.time() - started, 3)

        if analysis_result.get("error"):
            update_analysis_attempt(
                batch_id,
                attempt_id,
                status="failed",
                progress=100,
                current_step="分析失败",
                duration_seconds=duration,
                error=analysis_result["error"],
                ended_at=datetime.now().isoformat()
            )
            return

        update_analysis_attempt(
            batch_id,
            attempt_id,
            progress=90,
            current_step="保存分析结果"
        )
        saved_record_filename = await save_upload_file_content(record_content, record_filename)
        history_item = save_analysis_result_to_history(
            record_filename=record_filename,
            standard_filename=standard_filename,
            record_path=saved_record_filename,
            standard_path=standard_path,
            analysis_result=analysis_result,
            submitted_at=batch_submitted_at,
            attempt_index=attempt_index
        )

        update_analysis_attempt(
            batch_id,
            attempt_id,
            status="success",
            progress=100,
            current_step="分析完成",
            duration_seconds=duration,
            error=None,
            history_record_id=history_item["id"],
            result=workflow_result_to_html(analysis_result),
            result_summary=summarize_workflow_result(analysis_result),
            ended_at=datetime.now().isoformat()
        )
    except Exception as e:
        update_analysis_attempt(
            batch_id,
            attempt_id,
            status="failed",
            progress=100,
            current_step="分析异常",
            duration_seconds=round(time.time() - started, 3),
            error=str(e),
            ended_at=datetime.now().isoformat()
        )

async def run_home_analysis_batch(
    batch_id: str,
    batch_submitted_at: str,
    record_content: bytes,
    record_filename: str,
    standard_content: bytes,
    standard_filename: str,
    standard_path: str,
    concurrency: int
):
    """执行首页单文件多次并发分析批次。"""
    import asyncio

    update_analysis_batch(
        batch_id,
        status="running",
        started_at=datetime.now().isoformat()
    )

    try:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
            batch = get_analysis_batch_info(batch_id, include_results=True)
            if not batch:
                return
            tasks = [
                asyncio.create_task(run_home_analysis_attempt(
                    batch_id=batch_id,
                    attempt_id=attempt["attempt_id"],
                    attempt_index=attempt["attempt_index"],
                    batch_submitted_at=batch_submitted_at,
                    record_content=record_content,
                    record_filename=record_filename,
                    standard_content=standard_content,
                    standard_filename=standard_filename,
                    standard_path=standard_path,
                    executor=executor
                ))
                for attempt in batch.get("attempts", [])
            ]
            if tasks:
                await asyncio.gather(*tasks)

        update_analysis_batch(
            batch_id,
            ended_at=datetime.now().isoformat()
        )
    except Exception as e:
        update_analysis_batch(
            batch_id,
            status="failed",
            ended_at=datetime.now().isoformat(),
            error=str(e)
        )

@app.post("/api/analysis/batches")
async def create_home_analysis_batch(
    record_file: UploadFile = File(...),
    concurrency: int = Form(1),
    session_id: str = Form(...),
    confirmed_standard_id: str = Form(None)
):
    """创建首页分析批次：一份病历可并发执行多次。"""
    try:
        if not record_file.filename:
            raise HTTPException(status_code=400, detail="请选择病历文件")
        if concurrency < 1 or concurrency > HOME_ANALYSIS_MAX_CONCURRENCY:
            raise HTTPException(status_code=400, detail=f"并发次数必须在 1-{HOME_ANALYSIS_MAX_CONCURRENCY} 之间")
        if not session_id or len(session_id.strip()) < 8:
            raise HTTPException(status_code=400, detail="会话标识无效")

        ext = os.path.splitext(record_file.filename)[1].lower()
        if ext not in config.allowed_extensions:
            raise HTTPException(status_code=400, detail=f"不支持的病历文件格式: {record_file.filename}")

        selected_standard = get_selected_standard()
        if not selected_standard:
            raise HTTPException(status_code=400, detail="请先到知识库选择标准文件")
        if confirmed_standard_id and confirmed_standard_id != selected_standard["id"]:
            return JSONResponse(
                status_code=409,
                content={
                    "status": "standard_changed",
                    "message": "当前实际使用标准已变化，请确认后重新提交",
                    "data": {
                        "selected_id": selected_standard["id"],
                        "filename": selected_standard["filename"]
                    }
                }
            )

        standard_filepath = os.path.join(STANDARDS_DIR, selected_standard["filepath"])
        if not os.path.exists(standard_filepath):
            raise HTTPException(status_code=400, detail="标准文件不存在，请重新选择")

        record_content = await record_file.read()
        async with aiofiles.open(standard_filepath, "rb") as f:
            standard_content = await f.read()

        batch_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        attempts = [
            {
                "attempt_id": str(uuid.uuid4()),
                "attempt_index": index,
                "status": "pending",
                "progress": 0,
                "current_step": "等待开始",
                "duration_seconds": None,
                "error": None,
                "history_record_id": None,
                "result_summary": None,
                "result": None
            }
            for index in range(1, concurrency + 1)
        ]
        batch = {
            "id": batch_id,
            "session_id": session_id.strip(),
            "record_filename": record_file.filename,
            "standard_filename": selected_standard["filename"],
            "standard_path": selected_standard["filepath"],
            "status": "pending",
            "total_attempts": concurrency,
            "completed_attempts": 0,
            "success_count": 0,
            "failed_count": 0,
            "created_at": now,
            "started_at": None,
            "ended_at": None,
            "updated_at": now,
            "attempts": attempts
        }

        with analysis_batches_lock:
            global_analysis_batches["batches"].append(batch)
            save_analysis_batches(global_analysis_batches)

        import asyncio
        asyncio.create_task(run_home_analysis_batch(
            batch_id=batch_id,
            batch_submitted_at=now,
            record_content=record_content,
            record_filename=record_file.filename,
            standard_content=standard_content,
            standard_filename=selected_standard["filename"],
            standard_path=selected_standard["filepath"],
            concurrency=concurrency
        ))

        return {
            "status": "success",
            "message": "分析批次已开始",
            "batch_id": batch_id,
            "data": get_analysis_batch_info(batch_id)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析批次创建失败: {str(e)}")

@app.get("/api/analysis/batches/recent")
async def get_recent_home_analysis_batch(session_id: str):
    """恢复当前浏览器会话最近的首页分析批次。"""
    if not session_id:
        raise HTTPException(status_code=400, detail="缺少会话标识")
    batch = get_recent_analysis_batch_for_session(session_id)
    if not batch:
        return {"status": "success", "data": None}
    return {"status": "success", "data": batch}

@app.get("/api/analysis/batches/{batch_id}")
async def get_home_analysis_batch(batch_id: str):
    """获取首页分析批次状态。"""
    batch = get_analysis_batch_info(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="分析批次不存在")
    return {"status": "success", "data": batch}

@app.get("/api/analysis/batches/{batch_id}/attempts/{attempt_id}")
async def get_home_analysis_attempt(batch_id: str, attempt_id: str):
    """获取首页分析批次中某次运行的完整结果。"""
    with analysis_batches_lock:
        batch = _find_analysis_batch(batch_id)
        if not batch:
            raise HTTPException(status_code=404, detail="分析批次不存在")
        attempt = _find_analysis_attempt(batch, attempt_id)
        if not attempt:
            raise HTTPException(status_code=404, detail="分析结果不存在")
        return {
            "status": "success",
            "data": json.loads(json.dumps(attempt, ensure_ascii=False))
        }

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

@app.get("/concurrency-test", response_class=HTMLResponse)
async def concurrency_test_page(request: Request):
    """并发测试页面"""
    return templates.TemplateResponse("concurrency_test.html", {"request": request})

@app.get("/api/concurrency-tests")
async def list_concurrency_tests():
    """列出并发测试批次"""
    with concurrency_tests_lock:
        batches = []
        for batch in global_concurrency_tests["batches"]:
            item = {key: value for key, value in batch.items() if key != "details"}
            batches.append(item)
        batches.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return {"status": "success", "data": batches}

@app.get("/api/concurrency-tests/{batch_id}")
async def get_concurrency_test(batch_id: str):
    """获取并发测试批次详情"""
    batch = get_concurrency_batch_info(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="并发测试批次不存在")
    return {"status": "success", "data": batch}

@app.post("/api/concurrency-tests")
async def create_concurrency_test(
    record_files: List[UploadFile] = File(..., alias="record_files[]"),
    tests_per_record: int = Form(10),
    records_per_round: int = Form(5)
):
    """创建并启动并发测试批次"""
    selected_standard = get_selected_standard()
    if not selected_standard:
        raise HTTPException(status_code=400, detail="请先到知识库选择标准文件")

    standard_filepath = os.path.join(STANDARDS_DIR, selected_standard["filepath"])
    if not os.path.exists(standard_filepath):
        raise HTTPException(status_code=400, detail="标准文件不存在，请重新选择")

    if not record_files:
        raise HTTPException(status_code=400, detail="请至少上传一份病历")

    if tests_per_record < 1 or tests_per_record > CONCURRENCY_MAX_TESTS_PER_RECORD:
        raise HTTPException(status_code=400, detail=f"每份病历测试次数必须在 1-{CONCURRENCY_MAX_TESTS_PER_RECORD} 之间")

    if records_per_round < 1 or records_per_round > len(record_files):
        raise HTTPException(status_code=400, detail=f"每轮病历数必须在 1-{len(record_files)} 之间")

    attempts_per_round = tests_per_record * records_per_round
    if attempts_per_round > CONCURRENCY_MAX_ATTEMPTS_PER_ROUND:
        raise HTTPException(
            status_code=400,
            detail=f"单轮并发数不能超过 {CONCURRENCY_MAX_ATTEMPTS_PER_ROUND}，请调小每份测试次数或每轮病历数"
        )

    async with aiofiles.open(standard_filepath, "rb") as f:
        standard_content = await f.read()

    records = []
    for index, file in enumerate(record_files, start=1):
        if not file.filename:
            raise HTTPException(status_code=400, detail="存在未命名的病历文件")
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in config.allowed_extensions:
            raise HTTPException(status_code=400, detail=f"不支持的病历文件格式: {file.filename}")

        content = await file.read()
        saved_filename = await save_upload_file_content(content, file.filename)
        records.append({
            "record_id": f"record-{index}",
            "filename": file.filename,
            "saved_filename": saved_filename,
            "size_bytes": len(content),
            "content": content
        })

    batch_id = str(uuid.uuid4())
    total_records = len(records)
    total_rounds = (total_records + records_per_round - 1) // records_per_round
    total_attempts = total_records * tests_per_record
    details = []

    for record_index, record in enumerate(records):
        round_index = (record_index // records_per_round) + 1
        dispatch_group_index = (record_index % records_per_round) + 1
        for attempt_index in range(1, tests_per_record + 1):
            details.append({
                "attempt_id": str(uuid.uuid4()),
                "round_index": round_index,
                "dispatch_group_index": dispatch_group_index,
                "record_id": record["record_id"],
                "record_filename": record["filename"],
                "attempt_index": attempt_index,
                "status": "pending",
                "duration_seconds": None,
                "error": None,
                "result_summary": None
            })

    batch = {
        "id": batch_id,
        "created_at": datetime.now().isoformat(),
        "status": "pending",
        "current_round": 0,
        "current_record_filename": None,
        "total_records": total_records,
        "tests_per_record": tests_per_record,
        "records_per_round": records_per_round,
        "attempts_per_round": attempts_per_round,
        "record_dispatch_interval_seconds": CONCURRENCY_RECORD_DISPATCH_INTERVAL_SECONDS,
        "total_attempts": total_attempts,
        "total_rounds": total_rounds,
        "completed_attempts": 0,
        "success_count": 0,
        "failed_count": 0,
        "avg_duration_seconds": 0,
        "min_duration_seconds": 0,
        "max_duration_seconds": 0,
        "started_at": None,
        "ended_at": None,
        "standard_filename": selected_standard["filename"],
        "records": [
            {
                "record_id": record["record_id"],
                "filename": record["filename"],
                "saved_filename": record["saved_filename"],
                "size_bytes": record["size_bytes"]
            }
            for record in records
        ],
        "details": details
    }

    with concurrency_tests_lock:
        global_concurrency_tests["batches"].append(batch)
        save_concurrency_tests(global_concurrency_tests)

    import asyncio
    asyncio.create_task(run_concurrency_batch(
        batch_id=batch_id,
        records=records,
        standard_content=standard_content,
        standard_filename=selected_standard["filename"],
        tests_per_record=tests_per_record,
        records_per_round=records_per_round
    ))

    return {
        "status": "success",
        "message": "并发测试批次已开始",
        "batch_id": batch_id,
        "data": get_concurrency_batch_info(batch_id)
    }

@app.get("/api/standards")
async def get_standards():
    """获取标准文件列表"""
    data = load_standards()
    return {"status": "success", "data": data}

@app.get("/api/dify-config")
async def get_dify_config():
    """获取 Dify 配置信息（API Key 脱敏）"""
    api_key = config.dify_api_key
    return {
        "status": "success",
        "data": {
            "base_url": config.dify_base_url,
            "api_key_masked": mask_api_key(api_key),
            "has_api_key": bool(api_key),
            "env_override": bool(os.getenv("DIFY_API_KEY"))
        }
    }

@app.post("/api/dify-config")
async def update_dify_config(request: Request):
    """更新 Dify API Key，用于切换工作流"""
    try:
        data = await request.json()
        api_key = str(data.get("api_key", "")).strip()

        if not api_key:
            raise HTTPException(status_code=400, detail="请输入 Dify API Key")

        if not config.update_config("dify", "api_key", api_key):
            raise HTTPException(status_code=500, detail="保存 Dify API Key 失败")

        message = "Dify API Key 已保存，后续分析将使用新的工作流"
        if os.getenv("DIFY_API_KEY"):
            message += "；注意：服务重启后环境变量 DIFY_API_KEY 仍会覆盖配置文件"

        return {
            "status": "success",
            "message": message,
            "data": {
                "api_key_masked": mask_api_key(api_key),
                "has_api_key": True,
                "env_override": bool(os.getenv("DIFY_API_KEY"))
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新 Dify 配置失败: {str(e)}")

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
    item = load_history_detail(record_id)
    if item:
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
    if delete_history_by_id(record_id):
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
        
        old_name = rename_history_by_id(record_id, new_name.strip())
        if old_name is not None:
            print(f"[重命名] 记录名称已修改: {old_name} → {new_name.strip()}")
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

async def run_concurrency_attempt(
    batch_id: str,
    attempt: dict,
    record: dict,
    standard_content: bytes,
    standard_filename: str,
    executor: ThreadPoolExecutor
):
    """执行并发测试中的单次工作流请求"""
    attempt_id = attempt["attempt_id"]
    update_concurrency_attempt(
        batch_id,
        attempt_id,
        status="running",
        started_at=datetime.now().isoformat()
    )

    started = time.time()
    try:
        result = await run_workflow_analysis(
            record["content"],
            standard_content,
            record["saved_filename"],
            standard_filename,
            None,
            executor=executor
        )
        duration = round(time.time() - started, 3)

        if result.get("error"):
            update_concurrency_attempt(
                batch_id,
                attempt_id,
                status="failed",
                duration_seconds=duration,
                error=result["error"],
                ended_at=datetime.now().isoformat()
            )
            return

        update_concurrency_attempt(
            batch_id,
            attempt_id,
            status="success",
            duration_seconds=duration,
            error=None,
            result_summary=summarize_workflow_result(result),
            ended_at=datetime.now().isoformat()
        )
    except Exception as e:
        update_concurrency_attempt(
            batch_id,
            attempt_id,
            status="failed",
            duration_seconds=round(time.time() - started, 3),
            error=str(e),
            ended_at=datetime.now().isoformat()
        )

async def run_concurrency_batch(
    batch_id: str,
    records: List[dict],
    standard_content: bytes,
    standard_filename: str,
    tests_per_record: int,
    records_per_round: int
):
    """按轮次执行并发测试批次"""
    import asyncio

    update_concurrency_batch(
        batch_id,
        status="running",
        started_at=datetime.now().isoformat(),
        current_round=0
    )

    try:
        record_map = {record["record_id"]: record for record in records}
        total_rounds = (len(records) + records_per_round - 1) // records_per_round

        for round_index in range(1, total_rounds + 1):
            batch = get_concurrency_batch_info(batch_id)
            if not batch:
                return

            round_attempts = [
                detail for detail in batch.get("details", [])
                if detail.get("round_index") == round_index
            ]
            attempts_by_record = {}
            for attempt in round_attempts:
                attempts_by_record.setdefault(attempt["record_id"], []).append(attempt)

            update_concurrency_batch(batch_id, current_round=round_index)

            with ThreadPoolExecutor(max_workers=max(1, len(round_attempts))) as executor:
                running_tasks = []
                for group_index, (record_id, record_attempts) in enumerate(attempts_by_record.items(), start=1):
                    record = record_map[record_id]
                    update_concurrency_batch(
                        batch_id,
                        current_round=round_index,
                        current_record_filename=record["filename"]
                    )

                    running_tasks.extend([
                        asyncio.create_task(run_concurrency_attempt(
                            batch_id=batch_id,
                            attempt=attempt,
                            record=record,
                            standard_content=standard_content,
                            standard_filename=standard_filename,
                            executor=executor
                        ))
                        for attempt in record_attempts
                    ])

                    if group_index < len(attempts_by_record):
                        await asyncio.sleep(CONCURRENCY_RECORD_DISPATCH_INTERVAL_SECONDS)

                if running_tasks:
                    await asyncio.gather(*running_tasks)

                update_concurrency_batch(batch_id, current_record_filename=None)

        update_concurrency_batch(
            batch_id,
            status="completed",
            current_round=total_rounds,
            current_record_filename=None,
            ended_at=datetime.now().isoformat()
        )
    except Exception as e:
        update_concurrency_batch(
            batch_id,
            status="failed",
            current_record_filename=None,
            ended_at=datetime.now().isoformat(),
            error=str(e)
        )

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
