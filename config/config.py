"""
配置文件管理类
支持端口号、Dify API密钥等配置项管理
"""

import os
import json
from typing import Dict, Any, Optional
from pathlib import Path


class Config:
    """配置管理类"""
    
    def __init__(self, config_file: str = "config/config.json"):
        """
        初始化配置
        
        Args:
            config_file: 配置文件路径
        """
        self.config_file = Path(config_file)
        self._config: Dict[str, Any] = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        # 默认配置
        default_config = {
            "server": {
                "host": "0.0.0.0",
                "port": 8000,
                "debug": False
            },
            "dify": {
                "api_key": "",
                "base_url": "http://localhost/v1",
                "app_id": "",
                "workflow_id": ""
            },
            "file": {
                "upload_dir": "uploads",
                "max_file_size": 10 * 1024 * 1024,  # 10MB
                "allowed_extensions": [".xml", ".md", ".txt", ".json"]
            },
            "database": {
                "history_file": "data/history.json"
            }
        }
        
        # 如果配置文件存在，加载并合并配置
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                # 深度合并配置
                self._merge_config(default_config, user_config)
            except (json.JSONDecodeError, KeyError) as e:
                print(f"警告：配置文件格式错误，使用默认配置: {e}")
        else:
            # 创建配置文件目录
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            # 保存默认配置
            self._save_config(default_config)
        
        # 环境变量覆盖
        self._apply_env_vars(default_config)
        
        return default_config
    
    def _merge_config(self, default: Dict[str, Any], user: Dict[str, Any]) -> None:
        """深度合并配置"""
        for key, value in user.items():
            if key in default:
                if isinstance(value, dict) and isinstance(default[key], dict):
                    self._merge_config(default[key], value)
                else:
                    default[key] = value
    
    def _apply_env_vars(self, config: Dict[str, Any]) -> None:
        """应用环境变量覆盖"""
        # 服务器配置
        if os.getenv('SERVER_HOST'):
            config['server']['host'] = os.getenv('SERVER_HOST')
        if os.getenv('SERVER_PORT'):
            config['server']['port'] = int(os.getenv('SERVER_PORT'))
        if os.getenv('SERVER_DEBUG'):
            config['server']['debug'] = os.getenv('SERVER_DEBUG').lower() == 'true'
        
        # Dify配置
        if os.getenv('DIFY_API_KEY'):
            config['dify']['api_key'] = os.getenv('DIFY_API_KEY')
        if os.getenv('DIFY_BASE_URL'):
            config['dify']['base_url'] = os.getenv('DIFY_BASE_URL')
        if os.getenv('DIFY_APP_ID'):
            config['dify']['app_id'] = os.getenv('DIFY_APP_ID')
        if os.getenv('DIFY_WORKFLOW_ID'):
            config['dify']['workflow_id'] = os.getenv('DIFY_WORKFLOW_ID')
    
    def _save_config(self, config: Dict[str, Any]) -> None:
        """保存配置到文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"保存配置文件失败: {e}")
    
    @property
    def server_host(self) -> str:
        """获取服务器主机地址"""
        return self._config['server']['host']
    
    @property
    def server_port(self) -> int:
        """获取服务器端口号"""
        return self._config['server']['port']
    
    @property
    def server_debug(self) -> bool:
        """获取调试模式"""
        return self._config['server']['debug']
    
    @property
    def dify_api_key(self) -> str:
        """获取Dify API密钥"""
        return self._config['dify']['api_key']
    
    @property
    def dify_base_url(self) -> str:
        """获取Dify基础URL"""
        return self._config['dify']['base_url']
    
    @property
    def dify_app_id(self) -> str:
        """获取Dify应用ID"""
        return self._config['dify']['app_id']
    
    @property
    def dify_workflow_id(self) -> str:
        """获取Dify工作流ID"""
        return self._config['dify']['workflow_id']
    
    @property
    def upload_dir(self) -> str:
        """获取上传目录"""
        return self._config['file']['upload_dir']
    
    @property
    def max_file_size(self) -> int:
        """获取最大文件大小"""
        return self._config['file']['max_file_size']
    
    @property
    def allowed_extensions(self) -> list:
        """获取允许的文件扩展名"""
        return self._config['file']['allowed_extensions']
    
    @property
    def history_file(self) -> str:
        """获取历史记录文件路径"""
        return self._config['database']['history_file']
    
    def update_config(self, section: str, key: str, value: Any) -> bool:
        """更新配置项"""
        try:
            if section in self._config and key in self._config[section]:
                self._config[section][key] = value
                self._save_config(self._config)
                return True
            return False
        except Exception as e:
            print(f"更新配置失败: {e}")
            return False
    
    def reload(self) -> None:
        """重新加载配置"""
        self._config = self._load_config()
    
    def get_all_config(self) -> Dict[str, Any]:
        """获取所有配置"""
        return self._config.copy()


# 全局配置实例
config = Config()
