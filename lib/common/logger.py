"""
日志工具 - 统一的日志管理
"""
import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional


def _get_project_root() -> Path:
    """
    获取项目根目录
    
    Returns:
        项目根目录的Path对象
    """
    current_file = Path(__file__)
    # lib/common/logger.py -> 项目根目录
    return current_file.parent.parent.parent


def setup_logger(
    name: str = "AutoTest",
    log_dir: Optional[str] = None,
    level: int = logging.INFO,
    format_string: Optional[str] = None
) -> logging.Logger:
    """
    设置日志记录器
    
    Args:
        name: 日志记录器名称
        log_dir: 日志目录（相对路径或绝对路径），如果为None则使用项目根目录下的reports/logs
        level: 日志级别
        format_string: 日志格式字符串
    
    Returns:
        配置好的日志记录器
    """
    if format_string is None:
        # 与pytest live log风格接近：2026-03-17 16:08:13 [    INFO] message
        format_string = '%(asctime)s [%(levelname)8s] %(message)s'
    
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 避免重复添加handler
    if logger.handlers:
        return logger
    
    # 控制台handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_formatter = logging.Formatter(format_string, datefmt="%Y-%m-%d %H:%M:%S")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # 文件handler - 使用绝对路径
    if log_dir is None:
        # 默认使用项目根目录下的reports/logs
        project_root = _get_project_root()
        log_path = project_root / "reports" / "logs"
    else:
        log_path = Path(log_dir)
        # 如果是相对路径，转换为基于项目根目录的绝对路径
        if not log_path.is_absolute():
            project_root = _get_project_root()
            log_path = project_root / log_path
    
    log_path.mkdir(parents=True, exist_ok=True)
    
    log_file = log_path / f"autotest_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(level)
    file_formatter = logging.Formatter(format_string, datefmt="%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # 关键：把 FileHandler 同步挂到 root logger，确保所有模块 logger 都能落盘
    # （pytest 控制台输出由 log_cli 接管，这里只负责“写文件”，避免重复打印）
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    has_same_file_handler = False
    for h in root_logger.handlers:
        if isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == str(log_file):
            has_same_file_handler = True
            break
    if not has_same_file_handler:
        root_logger.addHandler(file_handler)

    # 同步把 ConsoleHandler 挂到 root logger，确保各模块 logger（如 app.main）INFO 也能输出到控制台
    # 注意：避免重复添加，且不影响 pytest 的 log_cli（log_cli 自己也会接管/格式化一部分输出）
    has_same_console_handler = False
    for h in root_logger.handlers:
        if isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stdout:
            has_same_console_handler = True
            break
    if not has_same_console_handler:
        root_logger.addHandler(console_handler)
    
    return logger


def get_logger(name: str = None) -> logging.Logger:
    """
    获取日志记录器
    
    Args:
        name: 日志记录器名称，如果为None则使用调用模块名
    
    Returns:
        日志记录器
    """
    if name is None:
        import inspect
        name = inspect.getmodule(inspect.stack()[1][0]).__name__
    
    return logging.getLogger(name)


# 初始化默认logger
setup_logger()
