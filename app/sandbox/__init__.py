"""
Docker沙箱模块 (Docker Sandbox Module)

这个模块提供了一个安全的容器化执行环境，具有资源限制和隔离机制，
用于运行不受信任的代码。对于智能体系统而言，沙箱是一个关键的安全组件。

# 沙箱的概念与作用
沙箱(Sandbox)是一种安全机制，它创建了一个隔离的环境，使程序可以在其中
执行而不会影响主系统。在AI智能体系统中，沙箱使智能体能够安全地:
1. 执行用户提供的代码或命令
2. 尝试可能有风险的操作而不影响主系统
3. 在受控环境中测试和验证解决方案

# Docker技术基础
本模块使用Docker容器技术实现沙箱:
- 容器(Container): 轻量级虚拟化单元，包含代码和所有依赖
- 镜像(Image): 容器的只读模板，定义了容器的内容
- 资源限制: 控制容器可以使用的CPU、内存和网络资源
- 文件系统隔离: 容器有自己的文件系统，与主机系统隔离

# 安全考虑
沙箱提供多层安全保障:
- 资源限制: 防止资源耗尽攻击
- 网络隔离: 控制容器的网络访问能力
- 文件系统隔离: 防止未授权的文件访问
- 超时机制: 防止无限循环或长时间运行的代码

# 学习建议
初学者可以通过研究该模块了解:
1. Python中的抽象基类(ABC)和协议(Protocol)设计模式
2. 现代Python异步编程(async/await)
3. 容器化技术在应用安全中的应用
4. 资源管理和清理策略
"""

from app.sandbox.client import BaseSandboxClient  # 沙箱客户端的抽象基类，定义接口
from app.sandbox.client import LocalSandboxClient  # 本地沙箱客户端实现
from app.sandbox.client import create_sandbox_client  # 创建沙箱客户端的工厂函数
from app.sandbox.core.exceptions import SandboxError  # 沙箱基础异常类
from app.sandbox.core.exceptions import SandboxResourceError  # 资源相关错误(如内存用尽)
from app.sandbox.core.exceptions import SandboxTimeoutError  # 操作超时错误
from app.sandbox.core.manager import SandboxManager  # 沙箱管理器，管理多个沙箱实例
from app.sandbox.core.sandbox import DockerSandbox  # Docker沙箱的核心实现

# 导出的模块和类，使它们可以直接从sandbox包导入
__all__ = [
    "DockerSandbox",  # Docker沙箱实现
    "SandboxManager",  # 沙箱管理器
    "BaseSandboxClient",  # 沙箱客户端抽象基类
    "LocalSandboxClient",  # 本地沙箱客户端
    "create_sandbox_client",  # 客户端工厂函数
    "SandboxError",  # 基础异常
    "SandboxTimeoutError",  # 超时异常
    "SandboxResourceError",  # 资源错误异常
]
