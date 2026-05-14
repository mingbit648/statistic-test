#!/usr/bin/env python3
"""
Dify 工作流执行脚本 - 完整流程
步骤：
1. 获取应用参数 (get_params.py 的功能)
2. 根据参数准备输入
3. 上传文件
4. 执行工作流
"""

import requests
import json
import os
import sys
from typing import Dict, Any, Optional

# 配置
BASE_URL = os.getenv("DIFY_BASE_URL", "http://localhost/v1")
API_KEY = os.getenv("DIFY_API_KEY", "")
USER_ID = "test-user-001"

class DifyClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        # 确保API密钥格式正确（如果未包含Bearer前缀则添加）
        if not api_key.startswith("Bearer "):
            self.api_key = f"Bearer {api_key}"
        self.headers = {
            "Authorization": self.api_key,
            "Content-Type": "application/json"
        }
    
    def get_info(self) -> Dict[str, Any]:
        """获取应用基本信息"""
        try:
            response = requests.get(f"{self.base_url}/info", headers=self.headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"✗ 获取应用信息失败: {e}")
            return {}
    
    def get_parameters(self) -> Dict[str, Any]:
        """获取应用参数配置"""
        try:
            response = requests.get(f"{self.base_url}/parameters", headers=self.headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"✗ 获取参数失败: {e}")
            return {}
    
    def upload_file(self, file_path: str, file_type: str, user: str) -> Optional[str]:
        """上传文件"""
        try:
            if not os.path.exists(file_path):
                print(f"✗ 文件不存在: {file_path}")
                return None
            
            print(f"  上传: {os.path.basename(file_path)} (类型: {file_type})")
            
            # 根据文件扩展名设置正确的 MIME 类型
            ext = os.path.splitext(file_path)[1].lower()
            mime_type_map = {
                '.xml': 'application/xml',
                '.md': 'text/markdown',
                '.txt': 'text/plain',
                '.pdf': 'application/pdf',
                '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                '.csv': 'text/csv',
            }
            mime_type = mime_type_map.get(ext, 'application/octet-stream')
            
            with open(file_path, 'rb') as f:
                files = {'file': (os.path.basename(file_path), f, mime_type)}
                data = {'user': user, 'type': file_type}
                upload_headers = {"Authorization": self.api_key}
                
                response = requests.post(
                    f"{self.base_url}/files/upload",
                    headers=upload_headers,
                    files=files,
                    data=data
                )
                response.raise_for_status()
                file_id = response.json().get('id')
                print(f"  ✓ 上传成功: {file_id}")
                return file_id
        except Exception as e:
            print(f"✗ 上传失败: {e}")
            return None
    
    def run_workflow(self, inputs: Dict[str, Any], user: str) -> Dict[str, Any]:
        """执行工作流"""
        try:
            # 检查是否是应用ID格式（以"app-"开头）
            if self.api_key.startswith("app-"):
                # 使用应用模式，需要app_id参数
                payload = {
                    "inputs": inputs,
                    "response_mode": "blocking",
                    "user": user,
                    "app_id": self.api_key  # 如果是应用ID，直接使用
                }
                endpoint = f"{self.base_url}/workflows/run"
            else:
                # 使用API密钥模式
                payload = {
                    "inputs": inputs,
                    "response_mode": "blocking",
                    "user": user
                }
                endpoint = f"{self.base_url}/workflows/run"
            
            print(f"  请求端点: {endpoint}")
            print(f"  请求参数: {json.dumps(payload, ensure_ascii=False, indent=2)}")
            
            response = requests.post(
                endpoint,
                headers=self.headers,
                json=payload,
                timeout=2000  # 超时时间约16分钟，适应长时间工作流执行
            )
            
            if response.status_code != 200:
                print(f"  API 响应: {response.status_code}")
                print(f"  响应内容: {response.text}")
            
            response.raise_for_status()
            
            result = response.json()
            print(f"  ✓ 工作流执行成功")
            return result
            
        except requests.exceptions.RequestException as e:
            error_msg = f"网络请求失败: {e}"
            print(f"✗ {error_msg}")
            return {"error": error_msg}
        except Exception as e:
            error_msg = f"执行工作流失败: {e}"
            print(f"✗ {error_msg}")
            return {"error": error_msg}

def print_section(title: str):
    """打印分隔符"""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")

def print_parameters(params: Dict[str, Any]):
    """打印参数信息"""
    print("\n【用户输入表单】")
    for item in params.get('user_input_form', []):
        for key, config in item.items():
            label = config.get('label', key)
            required = "必填" if config.get('required') else "可选"
            print(f"  • {label} ({key}): {required}")
    
    print("\n【文件上传配置】")
    file_upload = params.get('file_upload', {})
    for file_type, config in file_upload.items():
        if isinstance(config, dict) and config.get('enabled'):
            print(f"  • {file_type}: 启用 (限制: {config.get('number_limits', 3)} 个)")

def main():
    print_section("Dify 工作流执行 - 完整流程")
    
    client = DifyClient(BASE_URL, API_KEY)
    
    # 步骤 1: 获取应用信息
    print("\n[步骤 1] 获取应用信息...")
    info = client.get_info()
    if not info:
        print("✗ 无法连接到 Dify 服务")
        sys.exit(1)
    
    print(f"✓ 应用: {info.get('name')}")
    print(f"  描述: {info.get('description')}")
    print(f"  模式: {info.get('mode')}")
    
    # 步骤 2: 获取应用参数
    print("\n[步骤 2] 获取应用参数...")
    params = client.get_parameters()
    if not params:
        print("✗ 无法获取参数")
        sys.exit(1)
    
    print("✓ 参数获取成功")
    print_parameters(params)
    
    # 步骤 3: 准备文件
    print("\n[步骤 3] 准备测试文件...")
    
    # 创建测试 XML 文件
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<medical_record>
    <patient_id>P001</patient_id>
    <chief_complaint>头痛</chief_complaint>
    <history_of_present_illness>患者因头痛就诊，持续 3 天</history_of_present_illness>
</medical_record>"""
    
    # 创建测试标准文件
    standard_content = """# 医疗记录质控标准

## 必填项
1. 主诉 (Chief Complaint)
2. 现病史 (History of Present Illness)
3. 既往史 (Past Medical History)

## 检查项
- 是否包含患者 ID
- 是否包含时间戳
- 是否包含医生签名"""
    
    xml_file = "test_record.xml"
    standard_file = "test_standard.md"
    
    with open(xml_file, 'w', encoding='utf-8') as f:
        f.write(xml_content)
    with open(standard_file, 'w', encoding='utf-8') as f:
        f.write(standard_content)
    
    print(f"✓ 创建文件: {xml_file}, {standard_file}")
    
    # 步骤 4: 上传文件
    print("\n[步骤 4] 上传文件...")
    # 根据工作流配置：recoder 需要 .xml 文件，类型为 custom
    record_id = client.upload_file(xml_file, "custom", USER_ID)
    # stand 需要 document 类型
    standard_id = client.upload_file(standard_file, "document", USER_ID)
    
    if not record_id or not standard_id:
        print("✗ 文件上传失败")
        sys.exit(1)
    
    # 步骤 5: 执行工作流
    print("\n[步骤 5] 执行工作流...")
    
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
    
    result = client.run_workflow(inputs, USER_ID)
    
    # 步骤 6: 显示结果
    print("\n[步骤 6] 执行结果...")
    
    if "error" in result:
        print(f"✗ 执行失败: {result['error']}")
        sys.exit(1)
    
    data = result.get('data', {})
    print(f"✓ 执行成功!")
    print(f"  Workflow Run ID: {result.get('workflow_run_id')}")
    print(f"  状态: {data.get('status')}")
    print(f"  耗时: {data.get('elapsed_time', 0):.2f}s")
    print(f"  Token 数: {data.get('total_tokens', 0)}")
    
    outputs = data.get('outputs', {})
    if outputs:
        print(f"\n【输出结果】")
        print(json.dumps(outputs, ensure_ascii=False, indent=2))
    
    print_section("执行完成")

if __name__ == "__main__":
    main()
