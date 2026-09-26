"""配置管理：读取 config/conf_{project}_{env}.ini。"""
import configparser
import os
from pathlib import Path
from typing import Dict, Optional

from lib.common.logger import get_logger

logger = get_logger(__name__)


class Config:
    """使用 configparser 读取 .ini 配置文件。"""

    def __init__(self, file_path: str):
        self.config_parser = configparser.ConfigParser()
        self.file_path = file_path

        if not os.path.exists(file_path):
            logger.warning(f"配置文件不存在: {file_path}")
        else:
            self.config_parser.read(file_path, encoding="utf-8")

    def get(self, section: str, option: str, fallback: Optional[str] = None) -> Optional[str]:
        try:
            return self.config_parser.get(section, option)
        except (configparser.NoSectionError, configparser.NoOptionError):
            if fallback is not None:
                return fallback
            logger.warning(f"配置项不存在: [{section}]{option}")
            return None

    def set(self, section: str, option: str, value: str):
        if not self.config_parser.has_section(section):
            self.config_parser.add_section(section)
        self.config_parser.set(section, option, value)

    def save(self):
        with open(self.file_path, "w", encoding="utf-8") as config_file:
            self.config_parser.write(config_file)

    def get_section(self, section: str) -> Dict[str, str]:
        if not self.config_parser.has_section(section):
            return {}
        return dict(self.config_parser.items(section))

    def has_section(self, section: str) -> bool:
        return self.config_parser.has_section(section)


class ConfigManager:
    """按 project + env 缓存配置。"""

    _configs: Dict[str, Config] = {}

    @classmethod
    def get_config(cls, project: str, env: str = None) -> Config:
        if env is None:
            env = get_env()

        config_key = f"{project}_{env}"

        if config_key not in cls._configs:
            base_dir = Path(__file__).parent.parent.parent / "config"
            conf_file = base_dir / f"conf_{project}_{env}.ini"
            if not conf_file.exists():
                logger.warning(f"配置文件不存在: {conf_file}")
            cls._configs[config_key] = Config(str(conf_file))

        return cls._configs[config_key]


def get_env() -> str:
    """环境名：ENV / TEST_ENV，默认 test。"""
    return os.environ.get("ENV", os.environ.get("TEST_ENV", "test")).lower()


try:
    from dotenv import load_dotenv

    root_dir = Path(__file__).parent.parent.parent
    env_file = root_dir / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        logger.info(f"已加载环境配置文件: {env_file}")
except ImportError:
    pass


def get_project_config(project: str, env: str = None) -> Config:
    if env is None:
        env = get_env()
    return ConfigManager.get_config(project, env)
