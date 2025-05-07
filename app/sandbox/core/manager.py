import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Dict, Optional, Set

import docker
from docker.errors import APIError, ImageNotFound

from app.config import SandboxSettings
from app.logger import logger
from app.sandbox.core.sandbox import DockerSandbox


class SandboxManager:
    """Docker沙箱管理器。

    管理多个DockerSandbox实例的生命周期，包括创建、监控和清理。
    提供并发访问控制和沙箱资源的自动清理机制。

    教学点:
    1. 单例模式应用: 作为系统中唯一的沙箱管理者
    2. 资源池设计: 管理有限资源的分配和回收
    3. 并发控制: 使用锁机制确保线程安全
    4. 自动清理策略: 通过后台任务实现资源自动回收
    5. 异步上下文管理: 支持Python的async with语法

    Attributes:
        max_sandboxes: 最大允许的沙箱数量。
        idle_timeout: 沙箱空闲超时时间(秒)。
        cleanup_interval: 清理检查间隔(秒)。
        _sandboxes: 活动沙箱实例映射。
        _last_used: 沙箱最后使用时间记录。
    """

    def __init__(
        self,
        max_sandboxes: int = 100,
        idle_timeout: int = 3600,
        cleanup_interval: int = 300,
    ):
        """初始化沙箱管理器。

        设计考虑:
        1. 资源限制: 通过max_sandboxes防止资源耗尽
        2. 空闲回收: 通过idle_timeout回收不活跃资源
        3. 定期检查: 通过cleanup_interval定期运行清理逻辑

        初始化流程:
        1. 设置配置参数
        2. 初始化资源映射和锁
        3. 启动自动清理任务

        Args:
            max_sandboxes: 最大沙箱数量限制。
            idle_timeout: 空闲超时时间(秒)。
            cleanup_interval: 清理检查间隔时间(秒)。
        """
        self.max_sandboxes = max_sandboxes
        self.idle_timeout = idle_timeout
        self.cleanup_interval = cleanup_interval

        # Docker客户端
        self._client = docker.from_env()

        # 资源映射
        self._sandboxes: Dict[str, DockerSandbox] = {}
        self._last_used: Dict[str, float] = {}

        # 并发控制
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self._active_operations: Set[str] = set()

        # 清理任务
        self._cleanup_task: Optional[asyncio.Task] = None
        self._is_shutting_down = False

        # 启动自动清理
        self.start_cleanup_task()

    async def ensure_image(self, image: str) -> bool:
        """确保Docker镜像可用。

        镜像管理策略:
        1. 先检查本地是否存在镜像
        2. 如不存在，尝试从Docker Hub拉取
        3. 处理拉取过程中可能的错误

        并发优化:
        使用run_in_executor将阻塞的Docker操作转为异步执行，避免阻塞事件循环

        Args:
            image: 镜像名称。

        Returns:
            bool: 镜像是否可用。
        """
        try:
            self._client.images.get(image)
            return True
        except ImageNotFound:
            try:
                logger.info(f"Pulling image {image}...")
                await asyncio.get_event_loop().run_in_executor(
                    None, self._client.images.pull, image
                )
                return True
            except (APIError, Exception) as e:
                logger.error(f"Failed to pull image {image}: {e}")
                return False

    @asynccontextmanager
    async def sandbox_operation(self, sandbox_id: str):
        """沙箱操作的上下文管理器。

        提供并发控制和使用时间更新。

        设计模式:
        1. 上下文管理器模式: 使用Python的with语句简化资源管理
        2. 装饰器模式: 使用@asynccontextmanager简化异步上下文管理器的创建
        3. 并发控制模式: 使用锁确保对沙箱的操作是线程安全的

        并发控制细节:
        - 每个沙箱有独立的锁，允许不同沙箱并行操作
        - 在锁内部更新最后使用时间，确保时间更新是原子的
        - 记录活动操作，防止清理正在使用的沙箱

        Args:
            sandbox_id: 沙箱ID。

        Raises:
            KeyError: 如果沙箱未找到。
        """
        if sandbox_id not in self._locks:
            self._locks[sandbox_id] = asyncio.Lock()

        async with self._locks[sandbox_id]:
            if sandbox_id not in self._sandboxes:
                raise KeyError(f"Sandbox {sandbox_id} not found")

            self._active_operations.add(sandbox_id)
            try:
                self._last_used[sandbox_id] = asyncio.get_event_loop().time()
                yield self._sandboxes[sandbox_id]
            finally:
                self._active_operations.remove(sandbox_id)

    async def create_sandbox(
        self,
        config: Optional[SandboxSettings] = None,
        volume_bindings: Optional[Dict[str, str]] = None,
    ) -> str:
        """创建新的沙箱实例。

        创建过程:
        1. 检查是否达到最大沙箱数量
        2. 确保必要的Docker镜像可用
        3. 创建并初始化DockerSandbox实例
        4. 记录相关元数据(ID、使用时间、锁)

        错误处理策略:
        在任何步骤失败时进行清理，确保不留下未完成的资源

        Args:
            config: 沙箱配置。
            volume_bindings: 卷映射配置。

        Returns:
            str: 沙箱ID。

        Raises:
            RuntimeError: 如果达到最大沙箱数量或创建失败。
        """
        async with self._global_lock:
            if len(self._sandboxes) >= self.max_sandboxes:
                raise RuntimeError(
                    f"Maximum number of sandboxes ({self.max_sandboxes}) reached"
                )

            config = config or SandboxSettings()
            if not await self.ensure_image(config.image):
                raise RuntimeError(f"Failed to ensure Docker image: {config.image}")

            sandbox_id = str(uuid.uuid4())
            try:
                sandbox = DockerSandbox(config, volume_bindings)
                await sandbox.create()

                self._sandboxes[sandbox_id] = sandbox
                self._last_used[sandbox_id] = asyncio.get_event_loop().time()
                self._locks[sandbox_id] = asyncio.Lock()

                logger.info(f"Created sandbox {sandbox_id}")
                return sandbox_id

            except Exception as e:
                logger.error(f"Failed to create sandbox: {e}")
                if sandbox_id in self._sandboxes:
                    await self.delete_sandbox(sandbox_id)
                raise RuntimeError(f"Failed to create sandbox: {e}")

    async def get_sandbox(self, sandbox_id: str) -> DockerSandbox:
        """获取沙箱实例。

        教学点:
        这个方法简洁但强大，通过使用上下文管理器(sandbox_operation)自动处理:
        1. 并发控制 - 获取沙箱专用锁
        2. 存在性检查 - 如果沙箱不存在抛出KeyError
        3. 使用时间更新 - 更新最后使用时间
        4. 活动状态标记 - 标记沙箱为活动状态，防止被清理

        Args:
            sandbox_id: 沙箱ID。

        Returns:
            DockerSandbox: 沙箱实例。

        Raises:
            KeyError: 如果沙箱不存在。
        """
        async with self.sandbox_operation(sandbox_id) as sandbox:
            return sandbox

    def start_cleanup_task(self) -> None:
        """启动自动清理任务。

        异步任务设计:
        1. 创建后台任务定期执行清理
        2. 使用无限循环和sleep实现定期执行
        3. 通过标志控制任务终止
        4. 包含错误处理，确保单次清理失败不会中断整个循环
        """

        async def cleanup_loop():
            while not self._is_shutting_down:
                try:
                    await self._cleanup_idle_sandboxes()
                except Exception as e:
                    logger.error(f"Error in cleanup loop: {e}")
                await asyncio.sleep(self.cleanup_interval)

        self._cleanup_task = asyncio.create_task(cleanup_loop())

    async def _cleanup_idle_sandboxes(self) -> None:
        """清理空闲沙箱。

        清理流程:
        1. 获取当前时间
        2. 找出超过空闲超时的沙箱
        3. 逐个删除它们

        并发控制:
        - 使用全局锁防止在识别空闲沙箱时的竞争条件
        - 跳过有活动操作的沙箱，避免中断正在使用的资源
        """
        current_time = asyncio.get_event_loop().time()
        to_cleanup = []

        async with self._global_lock:
            for sandbox_id, last_used in self._last_used.items():
                if (
                    sandbox_id not in self._active_operations
                    and current_time - last_used > self.idle_timeout
                ):
                    to_cleanup.append(sandbox_id)

        for sandbox_id in to_cleanup:
            try:
                await self.delete_sandbox(sandbox_id)
            except Exception as e:
                logger.error(f"Error cleaning up sandbox {sandbox_id}: {e}")

    async def cleanup(self) -> None:
        """清理所有资源。

        这个方法展示了全面的清理策略:
        1. 取消清理任务，防止新的清理操作启动
        2. 获取所有需要清理的沙箱ID
        3. 并发清理所有沙箱，提高效率
        4. 使用超时机制避免无限等待
        5. 清理剩余引用，确保彻底清理

        教学点:
        - 优雅关闭的设计模式
        - 并发清理提高效率
        - 超时机制防止无限等待
        """
        logger.info("Starting manager cleanup...")
        self._is_shutting_down = True

        # 取消清理任务
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await asyncio.wait_for(self._cleanup_task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        # 获取所有要清理的沙箱ID
        async with self._global_lock:
            sandbox_ids = list(self._sandboxes.keys())

        # 并发清理所有沙箱
        cleanup_tasks = []
        for sandbox_id in sandbox_ids:
            task = asyncio.create_task(self._safe_delete_sandbox(sandbox_id))
            cleanup_tasks.append(task)

        if cleanup_tasks:
            # 等待所有清理任务完成，设置超时避免无限等待
            try:
                await asyncio.wait(cleanup_tasks, timeout=30.0)
            except asyncio.TimeoutError:
                logger.error("Sandbox cleanup timed out")

        # 清理剩余引用
        self._sandboxes.clear()
        self._last_used.clear()
        self._locks.clear()
        self._active_operations.clear()

        logger.info("Manager cleanup completed")

    async def _safe_delete_sandbox(self, sandbox_id: str) -> None:
        """安全删除单个沙箱。

        可靠删除策略:
        1. 检查沙箱是否有活动操作，如有则等待一段时间
        2. 获取沙箱对象引用并清理
        3. 从管理器记录中移除沙箱

        错误处理:
        捕获所有可能的异常，确保单个沙箱的删除失败不会影响其他沙箱的清理

        Args:
            sandbox_id: 要删除的沙箱ID。
        """
        try:
            if sandbox_id in self._active_operations:
                logger.warning(
                    f"Sandbox {sandbox_id} has active operations, waiting for completion"
                )
                for _ in range(10):  # 最多等待10次
                    await asyncio.sleep(0.5)
                    if sandbox_id not in self._active_operations:
                        break
                else:
                    logger.warning(
                        f"Timeout waiting for sandbox {sandbox_id} operations to complete"
                    )

            # 获取沙箱对象引用
            sandbox = self._sandboxes.get(sandbox_id)
            if sandbox:
                await sandbox.cleanup()

                # 从管理器记录中移除沙箱
                async with self._global_lock:
                    self._sandboxes.pop(sandbox_id, None)
                    self._last_used.pop(sandbox_id, None)
                    self._locks.pop(sandbox_id, None)
                    logger.info(f"Deleted sandbox {sandbox_id}")
        except Exception as e:
            logger.error(f"Error during cleanup of sandbox {sandbox_id}: {e}")

    async def delete_sandbox(self, sandbox_id: str) -> None:
        """删除指定的沙箱。

        公共接口设计:
        - 简洁的公共方法调用内部实现
        - 对不存在的沙箱静默处理，避免抛出异常
        - 记录错误但不向调用者传播异常，使API更易使用

        这是API设计的常见实践，将复杂性封装在内部，提供简单的外部接口。

        Args:
            sandbox_id: 沙箱ID。
        """
        if sandbox_id not in self._sandboxes:
            return

        try:
            await self._safe_delete_sandbox(sandbox_id)
        except Exception as e:
            logger.error(f"Failed to delete sandbox {sandbox_id}: {e}")

    async def __aenter__(self) -> "SandboxManager":
        """异步上下文管理器入口。

        支持Python的异步上下文管理协议，使管理器可以使用async with语句。
        例如:

        ```python
        async with SandboxManager() as manager:
            # 使用管理器创建和管理沙箱
        # 自动清理所有资源
        ```
        """
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """异步上下文管理器退出。

        确保在上下文退出时(无论是正常退出还是发生异常)，所有资源都被清理。
        这是资源管理的最佳实践，防止资源泄漏。
        """
        await self.cleanup()

    def get_stats(self) -> Dict:
        """获取管理器统计信息。

        监控和调试:
        提供管理器内部状态的快照，用于监控、诊断和调试。

        统计指标选择:
        - 总沙箱数 - 评估资源使用情况
        - 活动操作数 - 了解当前负载
        - 配置参数 - 确认当前设置
        - 关闭状态 - 检查管理器是否正在关闭

        Returns:
            Dict: 统计信息。
        """
        return {
            "total_sandboxes": len(self._sandboxes),
            "active_operations": len(self._active_operations),
            "max_sandboxes": self.max_sandboxes,
            "idle_timeout": self.idle_timeout,
            "cleanup_interval": self.cleanup_interval,
            "is_shutting_down": self._is_shutting_down,
        }
