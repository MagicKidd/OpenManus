"""
配置管理模块 (Configuration Management Module)

这个模块实现了应用程序的配置管理系统，负责加载、解析和提供全局配置。
它使用TOML配置文件格式和Pydantic数据模型，结合单例模式确保配置的一致性。

教学点:
1. 单例模式: 确保全局只有一个配置实例，避免重复加载和不一致性
2. 线程安全: 使用锁机制确保在多线程环境中安全初始化
3. Pydantic模型: 使用类型验证实现配置的自动检查和转换
4. 分层配置: 模块化的配置结构，便于扩展和维护
5. 配置文件解析: 使用tomllib标准库解析TOML格式配置
"""

import threading
import tomllib
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


def get_project_root() -> Path:
    """获取项目根目录路径。

    这个辅助函数使用Python的文件路径解析功能，找到包含当前文件的项目根目录。
    它展示了如何使用相对路径定位文件系统中的关键位置。

    教学要点:
    - 使用__file__获取当前文件路径
    - 使用Path对象进行路径操作
    - resolve()方法解析所有符号链接
    - parent属性获取上一级目录

    返回:
        Path: 项目根目录的路径对象
    """
    return Path(__file__).resolve().parent.parent


# 核心路径常量 - 在模块级别定义以便全局访问
PROJECT_ROOT = get_project_root()
WORKSPACE_ROOT = PROJECT_ROOT / "workspace"


class LLMSettings(BaseModel):
    """大语言模型配置类。

    这个类使用Pydantic模型定义LLM连接和使用的相关设置。
    它展示了如何使用类型注解和Field验证创建强类型配置。

    教学要点:
    - Pydantic BaseModel继承
    - 使用类型注解(str, int等)定义字段类型
    - Field类提供附加验证和元数据
    - 可选字段(Optional)与默认值

    属性:
        model: 模型名称标识符
        base_url: API基础URL
        api_key: 认证密钥
        max_tokens: 每个请求的最大令牌数
        max_input_tokens: 所有请求累计的最大输入令牌数
        temperature: 采样温度参数(越高越随机)
        api_type: API类型(如Azure, OpenAI或Ollama)
        api_version: API版本号
    """

    model: str = Field(..., description="Model name")
    base_url: str = Field(..., description="API base URL")
    api_key: str = Field(..., description="API key")
    max_tokens: int = Field(4096, description="Maximum number of tokens per request")
    max_input_tokens: Optional[int] = Field(
        None,
        description="Maximum input tokens to use across all requests (None for unlimited)",
    )
    temperature: float = Field(1.0, description="Sampling temperature")
    api_type: str = Field(..., description="Azure, Openai, or Ollama")
    api_version: str = Field(..., description="Azure Openai version if AzureOpenai")


class ProxySettings(BaseModel):
    """代理服务器配置类。

    这个类定义了网络代理设置，支持认证和无认证代理。
    它展示了如何处理可选配置字段和默认值。

    教学要点:
    - 处理可选字段(Optional)
    - None作为默认值的字段
    - 使用Field描述字段的用途

    属性:
        server: 代理服务器地址(如"http://proxy.example.com:8080")
        username: 代理认证用户名(可选)
        password: 代理认证密码(可选)
    """

    server: str = Field(None, description="Proxy server address")
    username: Optional[str] = Field(None, description="Proxy username")
    password: Optional[str] = Field(None, description="Proxy password")


class SearchSettings(BaseModel):
    """搜索引擎配置类。

    这个类定义了智能体执行Web搜索时的配置选项。
    它展示了如何定义具有默认值和列表类型的配置。

    教学要点:
    - 列表类型字段(List[str])
    - 使用lambda函数创建默认列表值
    - 数值配置的合理默认值
    - 国际化相关配置(语言和国家代码)

    属性:
        engine: 主要搜索引擎名称
        fallback_engines: 备选搜索引擎列表
        retry_delay: 重试等待时间(秒)
        max_retries: 最大重试次数
        lang: 搜索结果语言代码
        country: 搜索结果国家/地区代码
    """

    engine: str = Field(default="Google", description="Search engine the llm to use")
    fallback_engines: List[str] = Field(
        default_factory=lambda: ["DuckDuckGo", "Baidu", "Bing"],
        description="Fallback search engines to try if the primary engine fails",
    )
    retry_delay: int = Field(
        default=60,
        description="Seconds to wait before retrying all engines again after they all fail",
    )
    max_retries: int = Field(
        default=3,
        description="Maximum number of times to retry all engines when all fail",
    )
    lang: str = Field(
        default="en",
        description="Language code for search results (e.g., en, zh, fr)",
    )
    country: str = Field(
        default="us",
        description="Country code for search results (e.g., us, cn, uk)",
    )


class BrowserSettings(BaseModel):
    """浏览器自动化配置类。

    这个类定义了浏览器控制和网页交互的配置选项。
    它展示了如何组合基本类型、嵌套模型和复杂字段。

    教学要点:
    - 布尔值配置字段
    - 嵌套模型字段(ProxySettings)
    - 可选复杂类型(Optional[ProxySettings])
    - 特殊浏览器参数和限制配置

    属性:
        headless: 是否在无界面模式运行浏览器
        disable_security: 是否禁用浏览器安全特性
        extra_chromium_args: 传递给浏览器的额外启动参数
        chrome_instance_path: 自定义Chrome安装路径
        wss_url: WebSocket连接地址
        cdp_url: Chrome开发协议连接地址
        proxy: 浏览器专用代理设置
        max_content_length: 内容检索操作的最大长度限制
    """

    headless: bool = Field(False, description="Whether to run browser in headless mode")
    disable_security: bool = Field(
        True, description="Disable browser security features"
    )
    extra_chromium_args: List[str] = Field(
        default_factory=list, description="Extra arguments to pass to the browser"
    )
    chrome_instance_path: Optional[str] = Field(
        None, description="Path to a Chrome instance to use"
    )
    wss_url: Optional[str] = Field(
        None, description="Connect to a browser instance via WebSocket"
    )
    cdp_url: Optional[str] = Field(
        None, description="Connect to a browser instance via CDP"
    )
    proxy: Optional[ProxySettings] = Field(
        None, description="Proxy settings for the browser"
    )
    max_content_length: int = Field(
        2000, description="Maximum length for content retrieval operations"
    )


class SandboxSettings(BaseModel):
    """沙箱执行环境配置类。

    这个类定义了代码执行沙箱的安全和资源限制选项。
    它展示了容器化环境的关键配置参数和资源约束。

    教学要点:
    - 安全相关配置(网络访问控制)
    - 资源限制(内存、CPU限制)
    - 容器环境配置(镜像、工作目录)
    - 超时配置防止无限执行

    属性:
        use_sandbox: 是否启用沙箱
        image: 容器基础镜像
        work_dir: 容器内工作目录
        memory_limit: 内存使用限制
        cpu_limit: CPU使用限制
        timeout: 命令超时时间(秒)
        network_enabled: 是否允许网络访问
    """

    use_sandbox: bool = Field(False, description="Whether to use the sandbox")
    image: str = Field("python:3.12-slim", description="Base image")
    work_dir: str = Field("/workspace", description="Container working directory")
    memory_limit: str = Field("512m", description="Memory limit")
    cpu_limit: float = Field(1.0, description="CPU limit")
    timeout: int = Field(300, description="Default command timeout (seconds)")
    network_enabled: bool = Field(
        False, description="Whether network access is allowed"
    )


class MCPSettings(BaseModel):
    """模型上下文协议配置类。

    这个类定义了MCP(Model Context Protocol)服务器相关设置。
    它展示了简单配置类的定义和模块引用的处理。

    教学要点:
    - 最小化配置模型
    - 模块引用字符串处理

    属性:
        server_reference: MCP服务器模块的引用路径
    """

    server_reference: str = Field(
        "app.mcp.server", description="Module reference for the MCP server"
    )


class AppConfig(BaseModel):
    """应用总配置模型类。

    这个类作为配置根节点，整合了所有子配置模型。
    它展示了如何组织分层配置结构和处理可选配置组。

    教学要点:
    - 组合多个配置模型
    - 字典类型配置字段
    - 可选配置组处理
    - Pydantic配置类(Config内部类)

    属性:
        llm: LLM配置字典，键为配置名称
        sandbox: 沙箱配置(可选)
        browser_config: 浏览器配置(可选)
        search_config: 搜索配置(可选)
        mcp_config: MCP配置(可选)
    """

    llm: Dict[str, LLMSettings]
    sandbox: Optional[SandboxSettings] = Field(
        None, description="Sandbox configuration"
    )
    browser_config: Optional[BrowserSettings] = Field(
        None, description="Browser configuration"
    )
    search_config: Optional[SearchSettings] = Field(
        None, description="Search configuration"
    )
    mcp_config: Optional[MCPSettings] = Field(None, description="MCP configuration")

    class Config:
        """Pydantic配置内部类"""

        arbitrary_types_allowed = True


class Config:
    """配置管理器类 - 单例实现。

    这个类实现了配置管理的核心功能，负责加载解析配置文件并提供访问接口。
    它使用单例模式确保全局共享一个配置实例，并使用线程锁确保线程安全。

    设计模式:
    1. 单例模式: 确保系统中只有一个配置实例
    2. 懒加载: 首次访问时才初始化配置
    3. 线程安全单例: 使用锁机制防止并发初始化问题
    4. 属性访问模式: 通过属性getter提供配置访问

    教学要点:
    - Python单例模式实现(__new__方法)
    - 线程安全机制(threading.Lock)
    - 惰性初始化技术
    - 配置文件查找和加载策略
    """

    _instance = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls):
        """控制实例创建的特殊方法，实现单例模式。

        这个方法拦截类的实例化过程，确保每次调用Config()都返回相同的实例。
        它展示了Python中如何实现线程安全的单例模式。

        设计要点:
        - 使用类变量_instance存储唯一实例
        - 使用双重检查锁定模式确保线程安全
        - 只在_instance为None时才创建新实例

        返回:
            Config: 唯一的配置管理器实例
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化配置管理器。

        这个方法确保配置只被初始化一次，即使创建多个实例也是如此。
        它展示了如何在单例模式中安全地执行一次性初始化。

        设计要点:
        - 使用_initialized标志跟踪初始化状态
        - 使用锁确保线程安全
        - 调用_load_initial_config完成实际初始化
        """
        if not self._initialized:
            with self._lock:
                if not self._initialized:
                    self._config = None
                    self._load_initial_config()
                    self._initialized = True

    @staticmethod
    def _get_config_path() -> Path:
        """查找配置文件路径。

        这个静态方法实现了配置文件的查找逻辑，先尝试常规配置文件，
        然后回退到示例配置文件。它展示了灵活的配置文件策略。

        算法:
        1. 首先检查config/config.toml是否存在
        2. 如果不存在，尝试使用config.example.toml
        3. 如果两者都不存在，抛出异常

        返回:
            Path: 找到的配置文件路径

        异常:
            FileNotFoundError: 当没有找到任何可用配置文件时
        """
        root = PROJECT_ROOT
        config_path = root / "config" / "config.toml"
        if config_path.exists():
            return config_path
        example_path = root / "config" / "config.example.toml"
        if example_path.exists():
            return example_path
        raise FileNotFoundError("No configuration file found in config directory")

    def _load_config(self) -> dict:
        """加载并解析配置文件。

        这个方法从文件系统读取TOML配置文件，并将其解析为Python字典。
        它展示了如何使用Python标准库处理特定格式的配置文件。

        实现细节:
        - 使用_get_config_path确定文件位置
        - 使用二进制模式打开文件("rb")
        - 使用tomllib解析TOML格式

        返回:
            dict: 解析后的配置字典
        """
        config_path = self._get_config_path()
        with config_path.open("rb") as f:
            return tomllib.load(f)

    def _load_initial_config(self):
        """初始化配置。

        这个方法是配置加载的核心，它解析原始配置字典并构建有结构的配置对象。
        它展示了如何处理复杂的嵌套配置并设置默认值和继承关系。

        实现逻辑:
        1. 加载原始配置字典
        2. 提取基础LLM配置和特定模型覆盖
        3. 处理各种子配置(浏览器、搜索、沙箱等)
        4. 构建最终配置对象
        """
        raw_config = self._load_config()
        base_llm = raw_config.get("llm", {})
        llm_overrides = {
            k: v for k, v in raw_config.get("llm", {}).items() if isinstance(v, dict)
        }

        # 提取默认LLM设置
        default_settings = {
            "model": base_llm.get("model"),
            "base_url": base_llm.get("base_url"),
            "api_key": base_llm.get("api_key"),
            "max_tokens": base_llm.get("max_tokens", 4096),
            "max_input_tokens": base_llm.get("max_input_tokens"),
            "temperature": base_llm.get("temperature", 1.0),
            "api_type": base_llm.get("api_type", ""),
            "api_version": base_llm.get("api_version", ""),
        }

        # 处理浏览器配置
        browser_config = raw_config.get("browser", {})
        browser_settings = None

        if browser_config:
            # 处理代理设置
            proxy_config = browser_config.get("proxy", {})
            proxy_settings = None

            if proxy_config and proxy_config.get("server"):
                proxy_settings = ProxySettings(
                    **{
                        k: v
                        for k, v in proxy_config.items()
                        if k in ["server", "username", "password"] and v
                    }
                )

            # 筛选有效的浏览器参数
            valid_browser_params = {
                k: v
                for k, v in browser_config.items()
                if k in BrowserSettings.__annotations__ and v is not None
            }

            # 如果有代理设置，添加到参数中
            if proxy_settings:
                valid_browser_params["proxy"] = proxy_settings

            # 仅在有有效参数时创建BrowserSettings
            if valid_browser_params:
                browser_settings = BrowserSettings(**valid_browser_params)

        # 处理搜索配置
        search_config = raw_config.get("search", {})
        search_settings = None
        if search_config:
            search_settings = SearchSettings(**search_config)

        # 处理沙箱配置
        sandbox_config = raw_config.get("sandbox", {})
        if sandbox_config:
            sandbox_settings = SandboxSettings(**sandbox_config)
        else:
            sandbox_settings = SandboxSettings()

        # 处理MCP配置
        mcp_config = raw_config.get("mcp", {})
        mcp_settings = None
        if mcp_config:
            mcp_settings = MCPSettings(**mcp_config)
        else:
            mcp_settings = MCPSettings()

        # 构建完整配置字典
        config_dict = {
            "llm": {
                "default": default_settings,
                **{
                    name: {**default_settings, **override_config}
                    for name, override_config in llm_overrides.items()
                },
            },
            "sandbox": sandbox_settings,
            "browser_config": browser_settings,
            "search_config": search_settings,
            "mcp_config": mcp_settings,
        }

        # 使用Pydantic模型验证和解析配置
        self._config = AppConfig(**config_dict)

    @property
    def llm(self) -> Dict[str, LLMSettings]:
        """获取LLM配置。

        这个属性getter提供对LLM配置字典的访问。
        它展示了如何使用Python属性语法提供干净的配置访问接口。

        返回:
            Dict[str, LLMSettings]: LLM配置字典，键为配置名称
        """
        return self._config.llm

    @property
    def sandbox(self) -> SandboxSettings:
        """获取沙箱配置。

        这个属性getter提供对沙箱配置的访问。

        返回:
            SandboxSettings: 沙箱配置对象
        """
        return self._config.sandbox

    @property
    def browser_config(self) -> Optional[BrowserSettings]:
        """获取浏览器配置。

        这个属性getter提供对浏览器配置的访问。

        返回:
            Optional[BrowserSettings]: 浏览器配置对象，可能为None
        """
        return self._config.browser_config

    @property
    def search_config(self) -> Optional[SearchSettings]:
        """获取搜索配置。

        这个属性getter提供对搜索配置的访问。

        返回:
            Optional[SearchSettings]: 搜索配置对象，可能为None
        """
        return self._config.search_config

    @property
    def mcp_config(self) -> MCPSettings:
        """获取MCP配置。

        这个属性getter提供对MCP配置的访问。

        返回:
            MCPSettings: MCP配置对象
        """
        return self._config.mcp_config

    @property
    def workspace_root(self) -> Path:
        """获取工作区根目录。

        这个属性getter提供对工作区目录路径的访问。

        返回:
            Path: 工作区根目录路径
        """
        return WORKSPACE_ROOT

    @property
    def root_path(self) -> Path:
        """获取应用根目录。

        这个属性getter提供对应用根目录路径的访问。

        返回:
            Path: 应用根目录路径
        """
        return PROJECT_ROOT


# 创建全局配置单例实例
config = Config()
