import math
from typing import Dict, List, Optional, Union

import tiktoken
from openai import (
    APIError,
    AsyncAzureOpenAI,
    AsyncOpenAI,
    AuthenticationError,
    OpenAIError,
    RateLimitError,
)
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from app.bedrock import BedrockClient
from app.config import LLMSettings, config
from app.exceptions import TokenLimitExceeded
from app.logger import logger  # Assuming a logger is set up in your app
from app.schema import (
    ROLE_VALUES,
    TOOL_CHOICE_TYPE,
    TOOL_CHOICE_VALUES,
    Message,
    ToolChoice,
)

REASONING_MODELS = ["o1", "o3-mini"]
MULTIMODAL_MODELS = [
    "gpt-4-vision-preview",
    "gpt-4o",
    "gpt-4o-mini",
    "claude-3-opus-20240229",
    "claude-3-sonnet-20240229",
    "claude-3-haiku-20240307",
]


class TokenCounter:
    """
    令牌计数器类，用于计算消息和图像的token数量。

    这是系统的关键组件，因为准确的token计数对于：
    1. 避免超出模型上下文窗口限制
    2. 优化API成本
    3. 确保响应质量
    都是至关重要的。
    """

    # Token常量，用于计算不同消息类型的token消耗
    BASE_MESSAGE_TOKENS = 4  # 每条消息的基础token数
    FORMAT_TOKENS = 2  # 格式化token数
    LOW_DETAIL_IMAGE_TOKENS = 85  # 低详细度图像的token数
    HIGH_DETAIL_TILE_TOKENS = 170  # 高详细度图像每个tile的token数

    # 图像处理常量
    MAX_SIZE = 2048  # 图像最大尺寸
    HIGH_DETAIL_TARGET_SHORT_SIDE = 768  # 高详细度目标短边尺寸
    TILE_SIZE = 512  # 图像tile大小

    def __init__(self, tokenizer):
        """
        初始化TokenCounter

        Args:
            tokenizer: tiktoken分词器实例，用于文本token计算
        """
        self.tokenizer = tokenizer

    def count_text(self, text: str) -> int:
        """
        计算文本字符串的token数量

        Args:
            text: 要计算的文本

        Returns:
            int: token数量
        """
        return 0 if not text else len(self.tokenizer.encode(text))

    def count_image(self, image_item: dict) -> int:
        """
        基于详细度级别和尺寸计算图像的token数量

        图像token计算是复杂的：
        - "low"详细度: 固定85 tokens
        - "high"详细度: 基于尺寸计算，将图像切分为512px的tiles

        Args:
            image_item: 包含图像信息的字典

        Returns:
            int: 估计的token数量
        """
        detail = image_item.get("detail", "medium")

        # 低详细度固定返回token数
        if detail == "low":
            return self.LOW_DETAIL_IMAGE_TOKENS

        # 中等详细度（OpenAI默认）使用高详细度计算方法
        # OpenAI没有为medium指定单独的计算方法

        # 高详细度基于尺寸计算
        if detail == "high" or detail == "medium":
            # 如果提供了尺寸信息
            if "dimensions" in image_item:
                width, height = image_item["dimensions"]
                return self._calculate_high_detail_tokens(width, height)

        # 当尺寸不可用或详细度未知时的默认值
        if detail == "high":
            # 高详细度默认为1024x1024图像
            return self._calculate_high_detail_tokens(1024, 1024)  # 765 tokens
        elif detail == "medium":
            # 中等详细度默认为中等大小图像
            return 1024
        else:
            # 未知详细度使用medium作为默认
            return 1024

    def _calculate_high_detail_tokens(self, width: int, height: int) -> int:
        """
        基于尺寸计算高详细度图像的token数量

        计算步骤：
        1. 缩放以适应MAX_SIZE × MAX_SIZE方框
        2. 缩放使最短边为HIGH_DETAIL_TARGET_SHORT_SIDE
        3. 计算512px tiles数量
        4. 计算最终token数量

        Args:
            width: 图像宽度
            height: 图像高度

        Returns:
            int: 估计的token数量
        """
        # 步骤1: 缩放以适应MAX_SIZE × MAX_SIZE
        if width > self.MAX_SIZE or height > self.MAX_SIZE:
            scale = self.MAX_SIZE / max(width, height)
            width = int(width * scale)
            height = int(height * scale)

        # 步骤2: 缩放使最短边为HIGH_DETAIL_TARGET_SHORT_SIDE
        scale = self.HIGH_DETAIL_TARGET_SHORT_SIDE / min(width, height)
        scaled_width = int(width * scale)
        scaled_height = int(height * scale)

        # 步骤3: 计算512px tiles数量
        tiles_x = math.ceil(scaled_width / self.TILE_SIZE)
        tiles_y = math.ceil(scaled_height / self.TILE_SIZE)
        total_tiles = tiles_x * tiles_y

        # 步骤4: 计算最终token数量
        return (
            total_tiles * self.HIGH_DETAIL_TILE_TOKENS
        ) + self.LOW_DETAIL_IMAGE_TOKENS

    def count_content(self, content: Union[str, List[Union[str, dict]]]) -> int:
        """
        计算消息内容的token数量

        处理多种内容格式：
        - 字符串文本
        - 内容项列表（文本+图像混合）

        Args:
            content: 消息内容（字符串或列表）

        Returns:
            int: 估计的token数量
        """
        if not content:
            return 0

        # 如果内容是字符串，直接计算文本tokens
        if isinstance(content, str):
            return self.count_text(content)

        # 如果内容是列表，分别计算每个项目
        token_count = 0
        for item in content:
            if isinstance(item, str):
                token_count += self.count_text(item)
            elif isinstance(item, dict):
                if "text" in item:
                    token_count += self.count_text(item["text"])
                elif "image_url" in item:
                    token_count += self.count_image(item)
        return token_count

    def count_tool_calls(self, tool_calls: List[dict]) -> int:
        """
        计算工具调用的token数量

        Args:
            tool_calls: 工具调用列表

        Returns:
            int: 估计的token数量
        """
        token_count = 0
        for tool_call in tool_calls:
            if "function" in tool_call:
                function = tool_call["function"]
                token_count += self.count_text(function.get("name", ""))
                token_count += self.count_text(function.get("arguments", ""))
        return token_count

    def count_message_tokens(self, messages: List[dict]) -> int:
        """
        计算消息列表的总token数量

        组合了所有token计算方法，全面评估整个消息列表的token使用情况。

        Args:
            messages: 消息字典列表

        Returns:
            int: 总token数量
        """
        total_tokens = self.FORMAT_TOKENS  # 基础格式tokens

        for message in messages:
            tokens = self.BASE_MESSAGE_TOKENS  # 每条消息的基础tokens

            # 添加角色tokens
            tokens += self.count_text(message.get("role", ""))

            # 添加内容tokens
            if "content" in message:
                tokens += self.count_content(message["content"])

            # 添加工具调用tokens
            if "tool_calls" in message:
                tokens += self.count_tool_calls(message["tool_calls"])

            # 添加name和tool_call_id tokens
            tokens += self.count_text(message.get("name", ""))
            tokens += self.count_text(message.get("tool_call_id", ""))

            total_tokens += tokens

        return total_tokens


class LLM:
    """
    大型语言模型(LLM)客户端类，处理与不同LLM提供商的通信

    设计特点：
    1. 单例模式 - 每个配置名称只创建一个实例
    2. 支持多种API（OpenAI, Azure, AWS Bedrock）
    3. 自动令牌计数和限制检查
    4. 内置重试机制处理临时故障
    5. 支持流式响应
    6. 支持多模态输入（文本+图像）
    7. 支持工具/函数调用
    """

    _instances: Dict[str, "LLM"] = {}  # 类变量，存储所有实例的字典

    def __new__(
        cls, config_name: str = "default", llm_config: Optional[LLMSettings] = None
    ):
        """
        实现单例模式，确保每个配置名称只创建一个实例

        单例模式优势:
        - 避免重复创建相同配置的实例
        - 减少资源消耗
        - 便于全局访问和管理

        Args:
            config_name: 配置名称，用于标识不同实例
            llm_config: 可选的LLM配置

        Returns:
            LLM: 现有或新创建的LLM实例
        """
        if config_name not in cls._instances:
            instance = super().__new__(cls)
            instance.__init__(config_name, llm_config)
            cls._instances[config_name] = instance
        return cls._instances[config_name]

    def __init__(
        self, config_name: str = "default", llm_config: Optional[LLMSettings] = None
    ):
        """
        初始化LLM实例

        只在实例首次创建时执行初始化，后续访问同一配置名称的实例将跳过初始化

        Args:
            config_name: 配置名称
            llm_config: 可选的LLM配置
        """
        if not hasattr(self, "client"):  # 只有未初始化时才执行
            llm_config = llm_config or config.llm
            llm_config = llm_config.get(config_name, llm_config["default"])

            # 从配置加载各种设置
            self.model = llm_config.model  # 使用的模型名称
            self.max_tokens = llm_config.max_tokens  # 生成的最大token数
            self.temperature = llm_config.temperature  # 采样温度
            self.api_type = llm_config.api_type  # API类型（如'openai', 'azure', 'aws'）
            self.api_key = llm_config.api_key  # API密钥
            self.api_version = llm_config.api_version  # API版本
            self.base_url = llm_config.base_url  # API基础URL

            # 添加令牌计数相关属性
            self.total_input_tokens = 0  # 累计输入token数
            self.total_completion_tokens = 0  # 累计完成token数
            self.max_input_tokens = (
                llm_config.max_input_tokens
                if hasattr(llm_config, "max_input_tokens")
                else None
            )  # 最大输入token限制

            # 初始化分词器
            try:
                # 尝试获取特定模型的分词器
                self.tokenizer = tiktoken.encoding_for_model(self.model)
            except KeyError:
                # 如果模型不在tiktoken的预设中，使用cl100k_base作为默认
                self.tokenizer = tiktoken.get_encoding("cl100k_base")

            # 基于API类型创建相应的客户端
            if self.api_type == "azure":
                self.client = AsyncAzureOpenAI(
                    base_url=self.base_url,
                    api_key=self.api_key,
                    api_version=self.api_version,
                )
            elif self.api_type == "aws":
                self.client = BedrockClient()
            else:
                self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

            # 创建token计数器实例
            self.token_counter = TokenCounter(self.tokenizer)

    def count_tokens(self, text: str) -> int:
        """
        计算文本中的token数量

        Args:
            text: 要计算的文本

        Returns:
            int: token数量
        """
        if not text:
            return 0
        return len(self.tokenizer.encode(text))

    def count_message_tokens(self, messages: List[dict]) -> int:
        """
        计算消息列表中的token数量

        代理到token_counter的相应方法

        Args:
            messages: 消息字典列表

        Returns:
            int: 总token数量
        """
        return self.token_counter.count_message_tokens(messages)

    def update_token_count(self, input_tokens: int, completion_tokens: int = 0) -> None:
        """
        更新token计数

        用于跟踪累计token使用情况，便于监控和限制控制

        Args:
            input_tokens: 输入token数
            completion_tokens: 完成token数
        """
        # 只在设置了max_input_tokens时跟踪token
        self.total_input_tokens += input_tokens
        self.total_completion_tokens += completion_tokens
        logger.info(
            f"Token usage: Input={input_tokens}, Completion={completion_tokens}, "
            f"Cumulative Input={self.total_input_tokens}, Cumulative Completion={self.total_completion_tokens}, "
            f"Total={input_tokens + completion_tokens}, Cumulative Total={self.total_input_tokens + self.total_completion_tokens}"
        )

    def check_token_limit(self, input_tokens: int) -> bool:
        """
        检查是否超出token限制

        Args:
            input_tokens: 当前请求的输入token数

        Returns:
            bool: 是否在限制内
        """
        if self.max_input_tokens is not None:
            return (self.total_input_tokens + input_tokens) <= self.max_input_tokens
        # 如果未设置max_input_tokens，始终返回True
        return True

    def get_limit_error_message(self, input_tokens: int) -> str:
        """
        生成token限制超出的错误消息

        Args:
            input_tokens: 当前请求的输入token数

        Returns:
            str: 错误消息
        """
        if (
            self.max_input_tokens is not None
            and (self.total_input_tokens + input_tokens) > self.max_input_tokens
        ):
            return f"Request may exceed input token limit (Current: {self.total_input_tokens}, Needed: {input_tokens}, Max: {self.max_input_tokens})"

        return "Token limit exceeded"

    @staticmethod
    def format_messages(
        messages: List[Union[dict, Message]], supports_images: bool = False
    ) -> List[dict]:
        """
        将消息格式化为LLM API所需的格式

        处理两种主要任务：
        1. 将Message对象转换为API所需的字典格式
        2. 处理图像（如果模型支持）

        Args:
            messages: 消息列表（字典或Message对象）
            supports_images: 目标模型是否支持图像输入

        Returns:
            List[dict]: 格式化后的消息列表

        Raises:
            ValueError: 消息无效或缺少必填字段
            TypeError: 提供了不支持的消息类型
        """
        formatted_messages = []

        for message in messages:
            # 将Message对象转换为字典
            if isinstance(message, Message):
                message = message.to_dict()

            if isinstance(message, dict):
                # 确保消息字典包含必需字段
                if "role" not in message:
                    raise ValueError("Message dict must contain 'role' field")

                # 如果存在base64图像且模型支持图像，处理图像
                if supports_images and message.get("base64_image"):
                    # 初始化或转换内容为适当格式
                    if not message.get("content"):
                        message["content"] = []
                    elif isinstance(message["content"], str):
                        message["content"] = [
                            {"type": "text", "text": message["content"]}
                        ]
                    elif isinstance(message["content"], list):
                        # 将字符串项转换为正确的文本对象
                        message["content"] = [
                            (
                                {"type": "text", "text": item}
                                if isinstance(item, str)
                                else item
                            )
                            for item in message["content"]
                        ]

                    # 将图像添加到内容
                    message["content"].append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{message['base64_image']}"
                            },
                        }
                    )

                    # 删除base64_image字段
                    del message["base64_image"]
                # 如果模型不支持图像但消息有base64_image，优雅处理
                elif not supports_images and message.get("base64_image"):
                    # 只删除base64_image字段并保留文本内容
                    del message["base64_image"]

                if "content" in message or "tool_calls" in message:
                    formatted_messages.append(message)
                # else: 不包括消息
            else:
                raise TypeError(f"Unsupported message type: {type(message)}")

        # 验证所有消息都有必需字段
        for msg in formatted_messages:
            if msg["role"] not in ROLE_VALUES:
                raise ValueError(f"Invalid role: {msg['role']}")

        return formatted_messages

    # ===== 核心API方法：文本请求 =====
    @retry(
        wait=wait_random_exponential(min=1, max=60),  # 指数退避策略，最小1秒，最大60秒
        stop=stop_after_attempt(6),  # 最多重试6次
        retry=retry_if_exception_type(
            (OpenAIError, Exception, ValueError)
        ),  # 重试这些类型的异常
    )
    async def ask(
        self,
        messages: List[Union[dict, Message]],
        system_msgs: Optional[List[Union[dict, Message]]] = None,
        stream: bool = True,
        temperature: Optional[float] = None,
    ) -> str:
        """
        向LLM发送提示并获取响应

        这是最基本的API方法，处理纯文本对话。

        重试设计：
        - 指数退避等待（避免连续快速重试）
        - 最多尝试6次（避免无限重试）
        - 只重试特定类型的错误（避免重试不可恢复的错误）

        Args:
            messages: 对话消息列表
            system_msgs: 可选的系统消息（前置）
            stream: 是否流式传输响应
            temperature: 响应的采样温度

        Returns:
            str: 生成的响应

        Raises:
            TokenLimitExceeded: 超出token限制
            ValueError: 消息无效或响应为空
            OpenAIError: API调用失败
            Exception: 意外错误
        """
        try:
            # 检查模型是否支持图像
            supports_images = self.model in MULTIMODAL_MODELS

            # 格式化系统消息和用户消息
            if system_msgs:
                system_msgs = self.format_messages(system_msgs, supports_images)
                messages = system_msgs + self.format_messages(messages, supports_images)
            else:
                messages = self.format_messages(messages, supports_images)

            # 计算输入token数
            input_tokens = self.count_message_tokens(messages)

            # 检查是否超出token限制
            if not self.check_token_limit(input_tokens):
                error_message = self.get_limit_error_message(input_tokens)
                # 抛出特殊异常，不会重试
                raise TokenLimitExceeded(error_message)

            # 构建API参数
            params = {
                "model": self.model,
                "messages": messages,
            }

            # 根据模型类型添加特定参数
            if self.model in REASONING_MODELS:
                params["max_completion_tokens"] = self.max_tokens
            else:
                params["max_tokens"] = self.max_tokens
                params["temperature"] = (
                    temperature if temperature is not None else self.temperature
                )

            if not stream:
                # 非流式请求
                response = await self.client.chat.completions.create(
                    **params, stream=False
                )

                if not response.choices or not response.choices[0].message.content:
                    raise ValueError("Empty or invalid response from LLM")

                # 更新token计数
                self.update_token_count(
                    response.usage.prompt_tokens, response.usage.completion_tokens
                )

                return response.choices[0].message.content

            # 流式请求，在发出请求前更新估计的token计数
            self.update_token_count(input_tokens)

            # 创建流式响应
            response = await self.client.chat.completions.create(**params, stream=True)

            # 收集流式块
            collected_messages = []
            completion_text = ""
            async for chunk in response:
                chunk_message = chunk.choices[0].delta.content or ""
                collected_messages.append(chunk_message)
                completion_text += chunk_message
                print(chunk_message, end="", flush=True)  # 实时打印流式内容

            print()  # 流式后的换行
            full_response = "".join(collected_messages).strip()
            if not full_response:
                raise ValueError("Empty response from streaming LLM")

            # 估计流式响应的完成token
            completion_tokens = self.count_tokens(completion_text)
            logger.info(
                f"Estimated completion tokens for streaming response: {completion_tokens}"
            )
            self.total_completion_tokens += completion_tokens

            return full_response

        except TokenLimitExceeded:
            # 重新抛出token限制错误，不记录日志
            raise
        except ValueError:
            logger.exception(f"Validation error")
            raise
        except OpenAIError as oe:
            logger.exception(f"OpenAI API error")
            if isinstance(oe, AuthenticationError):
                logger.error("Authentication failed. Check API key.")
            elif isinstance(oe, RateLimitError):
                logger.error("Rate limit exceeded. Consider increasing retry attempts.")
            elif isinstance(oe, APIError):
                logger.error(f"API error: {oe}")
            raise
        except Exception:
            logger.exception(f"Unexpected error in ask")
            raise

    # ===== 核心API方法：带图像的请求 =====
    @retry(
        wait=wait_random_exponential(min=1, max=60),
        stop=stop_after_attempt(6),
        retry=retry_if_exception_type((OpenAIError, Exception, ValueError)),
    )
    async def ask_with_images(
        self,
        messages: List[Union[dict, Message]],
        images: List[Union[str, dict]],
        system_msgs: Optional[List[Union[dict, Message]]] = None,
        stream: bool = False,
        temperature: Optional[float] = None,
    ) -> str:
        """
        向LLM发送带图像的提示并获取响应

        这个方法专门处理多模态输入（文本+图像），仅适用于支持图像的模型。

        Args:
            messages: 对话消息列表
            images: 图像URL或图像数据字典列表
            system_msgs: 可选的系统消息
            stream: 是否流式传输响应
            temperature: 响应的采样温度

        Returns:
            str: 生成的响应

        Raises:
            TokenLimitExceeded: 超出token限制
            ValueError: 消息无效、响应为空或模型不支持图像
            OpenAIError: API调用失败
            Exception: 意外错误
        """
        try:
            # 验证模型支持图像
            if self.model not in MULTIMODAL_MODELS:
                raise ValueError(
                    f"Model {self.model} does not support images. Use a model from {MULTIMODAL_MODELS}"
                )

            # 格式化消息，启用图像支持
            formatted_messages = self.format_messages(messages, supports_images=True)

            # 确保最后一条消息来自用户，用于附加图像
            if not formatted_messages or formatted_messages[-1]["role"] != "user":
                raise ValueError(
                    "The last message must be from the user to attach images"
                )

            # 处理最后一条用户消息以包含图像
            last_message = formatted_messages[-1]

            # 将内容转换为多模态格式
            content = last_message["content"]
            multimodal_content = (
                [{"type": "text", "text": content}]
                if isinstance(content, str)
                else content if isinstance(content, list) else []
            )

            # 将图像添加到内容
            for image in images:
                if isinstance(image, str):
                    multimodal_content.append(
                        {"type": "image_url", "image_url": {"url": image}}
                    )
                elif isinstance(image, dict) and "url" in image:
                    multimodal_content.append({"type": "image_url", "image_url": image})
                elif isinstance(image, dict) and "image_url" in image:
                    multimodal_content.append(image)
                else:
                    raise ValueError(f"Unsupported image format: {image}")

            # 使用多模态内容更新消息
            last_message["content"] = multimodal_content

            # 添加系统消息（如果提供）
            if system_msgs:
                all_messages = (
                    self.format_messages(system_msgs, supports_images=True)
                    + formatted_messages
                )
            else:
                all_messages = formatted_messages

            # 计算token并检查限制
            input_tokens = self.count_message_tokens(all_messages)
            if not self.check_token_limit(input_tokens):
                raise TokenLimitExceeded(self.get_limit_error_message(input_tokens))

            # 设置API参数
            params = {
                "model": self.model,
                "messages": all_messages,
                "stream": stream,
            }

            # 添加模型特定参数
            if self.model in REASONING_MODELS:
                params["max_completion_tokens"] = self.max_tokens
            else:
                params["max_tokens"] = self.max_tokens
                params["temperature"] = (
                    temperature if temperature is not None else self.temperature
                )

            # 处理非流式请求
            if not stream:
                response = await self.client.chat.completions.create(**params)

                if not response.choices or not response.choices[0].message.content:
                    raise ValueError("Empty or invalid response from LLM")

                self.update_token_count(response.usage.prompt_tokens)
                return response.choices[0].message.content

            # 处理流式请求
            self.update_token_count(input_tokens)
            response = await self.client.chat.completions.create(**params)

            collected_messages = []
            async for chunk in response:
                chunk_message = chunk.choices[0].delta.content or ""
                collected_messages.append(chunk_message)
                print(chunk_message, end="", flush=True)

            print()  # 流式后的换行
            full_response = "".join(collected_messages).strip()

            if not full_response:
                raise ValueError("Empty response from streaming LLM")

            return full_response

        except TokenLimitExceeded:
            raise
        except ValueError as ve:
            logger.error(f"Validation error in ask_with_images: {ve}")
            raise
        except OpenAIError as oe:
            logger.error(f"OpenAI API error: {oe}")
            if isinstance(oe, AuthenticationError):
                logger.error("Authentication failed. Check API key.")
            elif isinstance(oe, RateLimitError):
                logger.error("Rate limit exceeded. Consider increasing retry attempts.")
            elif isinstance(oe, APIError):
                logger.error(f"API error: {oe}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in ask_with_images: {e}")
            raise

    # ===== 核心API方法：工具/函数调用 =====
    @retry(
        wait=wait_random_exponential(min=1, max=60),
        stop=stop_after_attempt(6),
        retry=retry_if_exception_type((OpenAIError, Exception, ValueError)),
    )
    async def ask_tool(
        self,
        messages: List[Union[dict, Message]],
        system_msgs: Optional[List[Union[dict, Message]]] = None,
        timeout: int = 300,
        tools: Optional[List[dict]] = None,
        tool_choice: TOOL_CHOICE_TYPE = ToolChoice.AUTO,  # type: ignore
        temperature: Optional[float] = None,
        **kwargs,
    ) -> ChatCompletionMessage | None:
        """
        使用函数/工具向LLM发送请求并返回响应

        这个方法专门处理需要工具使用的交互，如函数调用、代码生成等。

        Args:
            messages: 对话消息列表
            system_msgs: 可选的系统消息
            timeout: 请求超时时间（秒）
            tools: 工具列表
            tool_choice: 工具选择策略
            temperature: 响应的采样温度
            **kwargs: 额外的完成参数

        Returns:
            ChatCompletionMessage: 模型响应

        Raises:
            TokenLimitExceeded: 超出token限制
            ValueError: 工具、工具选择或消息无效
            OpenAIError: API调用失败
            Exception: 意外错误
        """
        try:
            # 验证tool_choice
            if tool_choice not in TOOL_CHOICE_VALUES:
                raise ValueError(f"Invalid tool_choice: {tool_choice}")

            # 检查模型是否支持图像
            supports_images = self.model in MULTIMODAL_MODELS

            # 格式化消息
            if system_msgs:
                system_msgs = self.format_messages(system_msgs, supports_images)
                messages = system_msgs + self.format_messages(messages, supports_images)
            else:
                messages = self.format_messages(messages, supports_images)

            # 计算输入token数
            input_tokens = self.count_message_tokens(messages)

            # 如果有工具，计算工具描述的token数
            tools_tokens = 0
            if tools:
                for tool in tools:
                    tools_tokens += self.count_tokens(str(tool))

            input_tokens += tools_tokens

            # 检查是否超出token限制
            if not self.check_token_limit(input_tokens):
                error_message = self.get_limit_error_message(input_tokens)
                # 抛出特殊异常，不会重试
                raise TokenLimitExceeded(error_message)

            # 验证工具（如果提供）
            if tools:
                for tool in tools:
                    if not isinstance(tool, dict) or "type" not in tool:
                        raise ValueError("Each tool must be a dict with 'type' field")

            # 设置完成请求
            params = {
                "model": self.model,
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "timeout": timeout,
                **kwargs,
            }

            # 添加模型特定参数
            if self.model in REASONING_MODELS:
                params["max_completion_tokens"] = self.max_tokens
            else:
                params["max_tokens"] = self.max_tokens
                params["temperature"] = (
                    temperature if temperature is not None else self.temperature
                )

            # 工具请求始终使用非流式
            params["stream"] = False
            response: ChatCompletion = await self.client.chat.completions.create(
                **params
            )

            # 检查响应是否有效
            if not response.choices or not response.choices[0].message:
                print(response)
                # 无效响应返回None而不抛出异常
                return None

            # 更新token计数
            self.update_token_count(
                response.usage.prompt_tokens, response.usage.completion_tokens
            )

            return response.choices[0].message

        except TokenLimitExceeded:
            # 重新抛出token限制错误，不记录日志
            raise
        except ValueError as ve:
            logger.error(f"Validation error in ask_tool: {ve}")
            raise
        except OpenAIError as oe:
            logger.error(f"OpenAI API error: {oe}")
            if isinstance(oe, AuthenticationError):
                logger.error("Authentication failed. Check API key.")
            elif isinstance(oe, RateLimitError):
                logger.error("Rate limit exceeded. Consider increasing retry attempts.")
            elif isinstance(oe, APIError):
                logger.error(f"API error: {oe}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in ask_tool: {e}")
            raise
