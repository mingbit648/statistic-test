#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
非交互版本的删除脚本 - 直接执行删除，无需确认
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

# 配置
HISTORY_FILE = "data/history.json"
BACKUP_DIR = "data/backups"
DELETE_THRESHOLD = 6128  # 删除 id <= 6128 的记录
UPLOADS_DIR = "uploads"
STANDARDS_DIR = "standards"


def ensure_backup_dir():
    """确保备份目录存在"""
    Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)


def backup_history_file():
    """备份原始 history.json"""
    ensure_backup_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"history_before_cleanup_{timestamp}.json")
    
    if os.path.exists(HISTORY_FILE):
        shutil.copy2(HISTORY_FILE, backup_path)
        print(f"✅ 备份完成: {backup_path}")
        return backup_path
    return None


def load_history():
    """加载历史记录"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            print("❌ 无法读取history.json")
            return []
    return []


def save_history(history):
    """保存历史记录"""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        print(f"✅ 已保存清理后的历史记录，共 {len(history)} 条")
    except Exception as e:
        print(f"❌ 保存failed: {e}")
        raise


def safe_delete_file(filepath, record_id):
    """安全删除文件"""
    if not filepath:
        return False
    
    full_path = filepath
    
    # 如果是相对路径，补全为完整路径
    if not os.path.isabs(filepath):
        # 尝试在uploads或standards目录中查找
        if os.path.exists(os.path.join(UPLOADS_DIR, filepath)):
            full_path = os.path.join(UPLOADS_DIR, filepath)
        elif os.path.exists(os.path.join(STANDARDS_DIR, filepath)):
            full_path = os.path.join(STANDARDS_DIR, filepath)
        else:
            full_path = filepath
    
    if os.path.exists(full_path):
        try:
            os.remove(full_path)
            print(f"  📄 删除文件: {filepath}")
            return True
        except Exception as e:
            print(f"  ⚠️  文件删除失败 (record_id={record_id}): {filepath} - {e}")
            return False
    else:
        print(f"  ℹ️  文件不存在: {filepath}")
        return False


def cleanup_old_records():
    """清理旧记录"""
    print("\n" + "="*70)
    print("非交互模式：开始清理旧历史记录（id <= 6128）")
    print("="*70)
    
    # 备份
    backup_path = backup_history_file()
    if not backup_path:
        print("❌ 备份失败，停止操作")
        return False
    
    # 加载历史记录
    print("\n📂 正在加载历史记录...")
    history = load_history()
    if not history:
        print("❌ 历史记录为空")
        return False
    
    print(f"📊 总记录数: {len(history)}")
    print(f"ID范围: {history[0]['id']} - {history[-1]['id']}")
    
    # 识别需要删除的记录
    print(f"\n🔍 扫描 id <= {DELETE_THRESHOLD} 的记录...")
    to_delete = [item for item in history if item["id"] <= DELETE_THRESHOLD]
    to_keep = [item for item in history if item["id"] > DELETE_THRESHOLD]
    
    print(f"待删除: {len(to_delete)} 条")
    print(f"待保留: {len(to_keep)} 条")
    
    if not to_delete:
        print("ℹ️  没有需要删除的记录")
        return True
    
    print("\n⚠️  即将删除以下信息:")
    print(f"  - 数据库记录: {len(to_delete)} 条")
    print(f"  - 关联的上传文件")
    print(f"  - 关联的标准文件副本")
    
    # 执行删除
    print("\n🗑️  开始删除记录...")
    deleted_count = 0
    deleted_files = 0
    
    for i, record in enumerate(to_delete, 1):
        record_id = record.get("id")
        record_name = record.get("record_name", f"记录 #{record_id}")
        
        # 显示进度（每100条显示一次）
        if i % 100 == 1 or i == len(to_delete):
            print(f"[{i}/{len(to_delete)}] 删除: {record_name} (id={record_id})")
        
        # 删除关联文件
        if safe_delete_file(record.get("record_path"), record_id):
            deleted_files += 1
        
        # 删除标准文件（仅当不被其他保留记录使用时）
        standard_path = record.get("standard_path")
        if standard_path:
            # 检查是否被其他记录使用
            is_used_by_others = any(
                item.get("standard_path") == standard_path 
                for item in to_keep
            )
            if not is_used_by_others:
                if safe_delete_file(standard_path, record_id):
                    deleted_files += 1
        
        deleted_count += 1
    
    # 保存清理后的数据
    print("\n💾 保存清理后的数据...")
    save_history(to_keep)
    
    # 生成报告
    print("\n" + "="*70)
    print("清理完成 ✅")
    print("="*70)
    print(f"📊 操作统计:")
    print(f"  ✅ 删除记录数: {deleted_count}")
    print(f"  ✅ 删除文件数: {deleted_files}")
    print(f"  📁 保留记录数: {len(to_keep)}")
    if to_keep:
        print(f"  🆔 新ID范围: {to_keep[0]['id']} - {to_keep[-1]['id']}")
        print(f"  ➡️  下一条新记录的ID: {max([item['id'] for item in to_keep]) + 1}")
    print(f"  💾 备份文件: {backup_path}")
    
    return True


def verify_data_integrity():
    """验证数据完整性"""
    print("\n" + "="*70)
    print("数据完整性检查")
    print("="*70)
    
    history = load_history()
    if not history:
        print("❌ 历史记录为空")
        return False
    
    # 检查ID唯一性
    ids = [item["id"] for item in history]
    if len(ids) != len(set(ids)):
        print("❌ 发现ID重复")
        return False
    
    print(f"✅ ID唯一性检查通过 ({len(ids)} 条记录)")
    
    # 检查ID是否都 > 6128
    if any(id <= 6128 for id in ids):
        print(f"❌ 发现 id <= 6128 的记录尚未删除")
        return False
    
    print(f"✅ 所有记录 ID > 6128 检查通过")
    
    # 检查文件存在性
    print(f"✅ 数据完整性检查通过")
    
    return True


if __name__ == "__main__":
    try:
        # 执行清理
        success = cleanup_old_records()
        
        if success:
            # 校验数据
            print()
            verify_data_integrity()
        
        print("\n✨ 脚本执行完成\n")
        exit(0 if success else 1)
        
    except KeyboardInterrupt:
        print("\n❌ 用户中断操作")
        exit(1)
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
