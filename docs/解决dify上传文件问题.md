# Dify 工作流执行 - 问题排查与解决方案

## 概述

本文档记录了在执行 Dify 工作流时遇到的问题、调试过程和最终解决方案。

## 执行流程总结

```
获取参数 → 上传文件 → 执行工作流 → 获取结果
```

## 问题 1: 文件上传失败 - 415 UNSUPPORTED MEDIA TYPE

### 症状
```
✗ 上传失败: 415 Client Error: UNSUPPORTED MEDIA TYPE for url: http://localhost/v1/files/upload
```

### 原因分析
- 初始代码没有指定正确的 MIME 类型
- `.md` 文件被识别为 `text/plain` 而不是 `text/markdown`
- Dify 服务器对 MIME 类型的验证很严格

### 解决方案
在上传文件时，根据文件扩展名设置正确的 MIME 类型：

```python
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

files = {'file': (os.path.basename(file_path), f, mime_type)}
```

### 验证
```bash
✓ 上传成功: 30eed613-5abe-44f1-ad10-854362f1f4fd
```

---

## 问题 2: 工作流执行失败 - 400 invalid_param

### 症状
```
✗ 执行工作流失败: 400 Client Error: BAD REQUEST for url: http://localhost/v1/workflows/run
响应: {"code":"invalid_param","message":"recoder in input form must be a file","status":400}
```

### 原因分析
- 初始代码使用了列表格式的输入：`"recoder": [{...}]`
- 但工作流期望的是对象格式：`"recoder": {...}`
- 这是 Dify 工作流 API 的特殊要求

### 解决方案
改用对象格式而不是列表格式：

**错误格式：**
```python
inputs = {
    "recoder": [
        {
            "transfer_method": "local_file",
            "upload_file_id": file_id,
            "type": "document"
        }
    ]
}
```

**正确格式：**
```python
inputs = {
    "recoder": {
        "transfer_method": "local_file",
        "upload_file_id": file_id,
        "type": "custom"
    }
}
```

### 验证
```bash
✓ 文件上传成功
✓ 工作流执行成功
```

---

## 问题 3: 文件类型不匹配 - 400 Detected file type does not match

### 症状
```
✗ 执行失败: 400 Client Error: BAD REQUEST
响应: {"code":"invalid_param","message":"Detected file type does not match the specified type. Please verify the file.","status":400}
```

### 原因分析
这是最复杂的问题，涉及多个方面：

1. **参数配置不一致**
   - `get_params.py` 返回的参数显示 `recoder` 是 `document` 类型
   - 但 `workflow_config.json` 显示 `recoder` 是 `custom` 类型
   - 工作流实际期望的是 `custom` 类型

2. **文件类型验证严格**
   - Dify 在上传时检测文件类型
   - 在执行工作流时再次验证文件类型
   - 两次检测必须一致

3. **type 字段的含义**
   - 上传时的 `type` 字段：指定文件的分类（document, image, audio, video, custom）
   - 执行时的 `type` 字段：指定文件的具体格式（XML, TXT, PDF 等）

### 调试过程

#### 尝试 1: 使用 document 类型上传 XML
```python
# 上传
data = {'user': USER_ID, 'type': 'document'}

# 执行
inputs = {
    'recoder': {
        'transfer_method': 'local_file',
        'upload_file_id': file_id,
        'type': 'document'
    }
}
# 结果: 失败 - 文件类型不匹配
```

#### 尝试 2: 使用 document 类型上传，执行时用 XML 格式
```python
# 上传
data = {'user': USER_ID, 'type': 'document'}

# 执行
inputs = {
    'recoder': {
        'transfer_method': 'local_file',
        'upload_file_id': file_id,
        'type': 'XML'
    }
}
# 结果: 失败 - 文件类型不匹配
```

#### 尝试 3: 使用 custom 类型上传，执行时不指定 type
```python
# 上传
data = {'user': USER_ID, 'type': 'custom'}

# 执行
inputs = {
    'recoder': {
        'transfer_method': 'local_file',
        'upload_file_id': file_id
    }
}
# 结果: 失败 - 文件类型不匹配
```

#### 尝试 4: 使用 custom 类型上传，执行时指定 custom 和 document
```python
# 上传
recoder: data = {'user': USER_ID, 'type': 'custom'}
stand: data = {'user': USER_ID, 'type': 'document'}

# 执行
inputs = {
    'recoder': {
        'transfer_method': 'local_file',
        'upload_file_id': recoder_id,
        'type': 'custom'
    },
    'stand': {
        'transfer_method': 'local_file',
        'upload_file_id': stand_id,
        'type': 'document'
    }
}
# 结果: ✓ 成功！
```

### 解决方案

**关键发现：** 上传时的 `type` 和执行时的 `type` 必须一致

1. **查看工作流配置**
   ```bash
   python get_params.py
   # 或查看 workflow_config.json
   ```

2. **根据配置上传文件**
   ```python
   # 对于 recoder (custom 类型)
   upload_file(xml_file, "custom", USER_ID)
   
   # 对于 stand (document 类型)
   upload_file(standard_file, "document", USER_ID)
   ```

3. **执行工作流时使用相同的 type**
   ```python
   inputs = {
       "recoder": {
           "transfer_method": "local_file",
           "upload_file_id": recoder_id,
           "type": "custom"  # 必须与上传时一致
       },
       "stand": {
           "transfer_method": "local_file",
           "upload_file_id": stand_id,
           "type": "document"  # 必须与上传时一致
       }
   }
   ```

### 验证
```bash
状态: 200
✓ 执行成功!
状态: succeeded
耗时: 136.261904s
输出: {...}
```

---

## 问题 4: 参数配置不一致

### 症状
- `get_params.py` 返回的参数与 `workflow_config.json` 不一致
- 导致混淆和错误的配置

### 原因分析
- `get_params.py` 调用 API 获取实时参数
- `workflow_config.json` 是本地保存的配置文件
- 两者可能不同步

### 解决方案
**始终使用 API 返回的参数作为真实来源**

```python
# 正确做法
params = client.get_parameters()  # 从 API 获取
print(params['user_input_form'])  # 查看实时配置

# 不要依赖本地配置文件
# workflow_config.json 仅用于参考
```

---

## 最终成功的完整流程

### 步骤 1: 获取应用信息
```bash
GET /v1/info
```
返回应用名称、描述、模式等基本信息。

### 步骤 2: 获取应用参数
```bash
GET /v1/parameters
```
返回：
- `user_input_form`: 输入表单配置
- `file_upload`: 文件上传配置
- `system_parameters`: 系统参数

**关键信息：**
```json
{
  "recoder": {
    "allowed_file_types": ["custom"],
    "allowed_file_extensions": [".xml"]
  },
  "stand": {
    "allowed_file_types": ["document"],
    "allowed_file_extensions": []
  }
}
```

### 步骤 3: 准备文件
```python
# 创建 XML 文件
xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<medical_record>
    <patient_id>P001</patient_id>
    <chief_complaint>头痛</chief_complaint>
    <history_of_present_illness>患者因头痛就诊，持续 3 天</history_of_present_illness>
</medical_record>"""

# 创建标准文件
standard_content = """# 医疗记录质控标准
## 必填项
1. 主诉
2. 现病史
3. 既往史"""
```

### 步骤 4: 上传文件
```python
# 上传 XML 文件 - 使用 custom 类型
response = requests.post(
    f"{BASE_URL}/files/upload",
    headers=upload_headers,
    files={'file': ('test_record.xml', f, 'application/xml')},
    data={'user': USER_ID, 'type': 'custom'}
)
recoder_id = response.json()['id']

# 上传标准文件 - 使用 document 类型
response = requests.post(
    f"{BASE_URL}/files/upload",
    headers=upload_headers,
    files={'file': ('test_standard.txt', f, 'text/plain')},
    data={'user': USER_ID, 'type': 'document'}
)
stand_id = response.json()['id']
```

### 步骤 5: 执行工作流
```python
inputs = {
    "recoder": {
        "transfer_method": "local_file",
        "upload_file_id": recoder_id,
        "type": "custom"  # 与上传时一致
    },
    "stand": {
        "transfer_method": "local_file",
        "upload_file_id": stand_id,
        "type": "document"  # 与上传时一致
    }
}

payload = {
    "inputs": inputs,
    "response_mode": "blocking",
    "user": USER_ID
}

response = requests.post(
    f"{BASE_URL}/workflows/run",
    headers=headers,
    json=payload
)
```

### 步骤 6: 处理结果
```python
result = response.json()
data = result.get('data', {})

print(f"状态: {data.get('status')}")  # succeeded
print(f"耗时: {data.get('elapsed_time')}s")  # 136.26s
print(f"输出: {data.get('outputs')}")  # 工作流输出
```

---

## 关键要点总结

### ✓ 成功的关键因素

1. **正确的 MIME 类型**
   - 根据文件扩展名设置 MIME 类型
   - 不要依赖自动检测

2. **对象格式而不是列表格式**
   - 工作流 API 期望对象格式
   - 不要使用列表包装

3. **上传和执行时的 type 必须一致**
   - 上传时指定的 type
   - 执行时必须使用相同的 type

4. **从 API 获取参数而不是本地配置**
   - 使用 `GET /v1/parameters`
   - 不要依赖 `workflow_config.json`

5. **详细的错误处理**
   - 打印完整的 API 响应
   - 分析错误信息中的具体原因

### ✗ 常见错误

| 错误 | 原因 | 解决方案 |
|------|------|--------|
| 415 UNSUPPORTED MEDIA TYPE | MIME 类型错误 | 使用正确的 MIME 类型映射 |
| 400 invalid_param (must be a file) | 使用列表格式 | 改用对象格式 |
| 400 file type does not match | type 不一致 | 上传和执行时使用相同的 type |
| 401 Unauthorized | API Key 错误 | 检查 API Key 是否正确 |
| 413 file_too_large | 文件过大 | 检查系统参数中的大小限制 |

---

## 调试技巧

### 1. 打印完整的 API 响应
```python
print(f"状态码: {response.status_code}")
print(f"响应内容: {response.text}")
```

### 2. 验证文件上传
```python
if response.status_code in [200, 201]:
    result = response.json()
    print(f"文件 ID: {result.get('id')}")
    print(f"文件信息: {json.dumps(result, indent=2)}")
```

### 3. 检查参数配置
```bash
python get_params.py
# 查看 user_input_form 中的 allowed_file_types
```

### 4. 逐步测试
```bash
# 先测试参数获取
python get_params.py

# 再测试文件上传
python -c "from run_workflow import DifyClient; ..."

# 最后测试完整流程
python run_workflow.py
```

---

## 最终代码

### 完整的工作流执行脚本
```python
import requests
import json
import os

BASE_URL = 'http://localhost/v1'
API_KEY = 'app-wpei4MrUqgH6saiLTAro8AN0'
USER_ID = 'test-user-001'

# 1. 获取参数
params = requests.get(
    f'{BASE_URL}/parameters',
    headers={'Authorization': f'Bearer {API_KEY}'}
).json()

# 2. 上传文件
def upload_file(file_path, file_type):
    mime_type_map = {
        '.xml': 'application/xml',
        '.txt': 'text/plain',
    }
    ext = os.path.splitext(file_path)[1].lower()
    mime_type = mime_type_map.get(ext, 'application/octet-stream')
    
    with open(file_path, 'rb') as f:
        response = requests.post(
            f'{BASE_URL}/files/upload',
            headers={'Authorization': f'Bearer {API_KEY}'},
            files={'file': (os.path.basename(file_path), f, mime_type)},
            data={'user': USER_ID, 'type': file_type}
        )
    return response.json()['id']

recoder_id = upload_file('test_record.xml', 'custom')
stand_id = upload_file('test_standard.txt', 'document')

# 3. 执行工作流
inputs = {
    'recoder': {
        'transfer_method': 'local_file',
        'upload_file_id': recoder_id,
        'type': 'custom'
    },
    'stand': {
        'transfer_method': 'local_file',
        'upload_file_id': stand_id,
        'type': 'document'
    }
}

response = requests.post(
    f'{BASE_URL}/workflows/run',
    headers={
        'Authorization': f'Bearer {API_KEY}',
        'Content-Type': 'application/json'
    },
    json={
        'inputs': inputs,
        'response_mode': 'blocking',
        'user': USER_ID
    }
)

# 4. 处理结果
result = response.json()
data = result.get('data', {})
print(f"状态: {data.get('status')}")
print(f"输出: {json.dumps(data.get('outputs', {}), indent=2)}")
```

---

## 参考资源

- Dify 官方文档：https://docs.dify.ai/
- API 参考：docs/dify.md
- 快速开始：QUICK_START.md
- 完整指南：WORKFLOW_GUIDE.md

---

## 结论

成功执行 Dify 工作流的关键是：
1. **理解参数配置** - 从 API 获取实时参数
2. **正确的文件上传** - 使用正确的 MIME 类型和 type 字段
3. **一致的类型映射** - 上传和执行时使用相同的 type
4. **详细的错误处理** - 分析 API 响应中的错误信息

通过系统的调试和逐步排查，最终成功执行了工作流并获得了预期的输出。
