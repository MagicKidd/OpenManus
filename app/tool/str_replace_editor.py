"""
字符串替换编辑器模块 (String Replace Editor Module)

这个模块实现了一个高级文件操作工具，支持查看、创建和编辑文件，同时兼容本地和沙箱环境。
它提供了一组安全、功能丰富的文件操作接口，特别优化了代码文件的编辑和查看操作。

教学点:
1. 文件操作抽象: 提供统一接口同时支持本地和沙箱环境
2. 状态管理: 使用历史记录实现文件编辑的撤销功能
3. 范围操作: 支持行号范围的文件查看和编辑
4. 精确替换: 使用唯一性检测确保字符串替换的精确性
5. 环境适配: 根据配置自动切换文件操作环境
"""

from collections import defaultdict
from pathlib import Path
from typing import Any, DefaultDict, List, Literal, Optional, get_args

from app.config import config
from app.exceptions import ToolError
from app.tool import BaseTool
from app.tool.base import CLIResult, ToolResult
from app.tool.file_operators import (
    FileOperator,
    LocalFileOperator,
    PathLike,
    SandboxFileOperator,
)

Command = Literal[
    "view",
    "create",
    "str_replace",
    "insert",
    "undo_edit",
]

# 常量定义
SNIPPET_LINES: int = 4  # 修改前后显示的上下文行数
MAX_RESPONSE_LEN: int = 16000  # 最大响应长度
TRUNCATED_MESSAGE: str = (
    "<response clipped><NOTE>To save on context only part of this file has been shown to you. "
    "You should retry this tool after you have searched inside the file with `grep -n` "
    "in order to find the line numbers of what you are looking for.</NOTE>"
)

# 工具描述
_STR_REPLACE_EDITOR_DESCRIPTION = """Custom editing tool for viewing, creating and editing files
* State is persistent across command calls and discussions with the user
* If `path` is a file, `view` displays the result of applying `cat -n`. If `path` is a directory, `view` lists non-hidden files and directories up to 2 levels deep
* The `create` command cannot be used if the specified `path` already exists as a file
* If a `command` generates a long output, it will be truncated and marked with `<response clipped>`
* The `undo_edit` command will revert the last edit made to the file at `path`

Notes for using the `str_replace` command:
* The `old_str` parameter should match EXACTLY one or more consecutive lines from the original file. Be mindful of whitespaces!
* If the `old_str` parameter is not unique in the file, the replacement will not be performed. Make sure to include enough context in `old_str` to make it unique
* The `new_str` parameter should contain the edited lines that should replace the `old_str`
"""


def maybe_truncate(
    content: str, truncate_after: Optional[int] = MAX_RESPONSE_LEN
) -> str:
    """截断过长的内容并添加通知信息。

    这个辅助函数用于限制响应大小，防止返回过大的文件内容。
    当内容超过指定长度时，自动截断并添加提示信息。

    参数:
        content: 要检查的内容字符串。
        truncate_after: 截断的长度阈值，默认为MAX_RESPONSE_LEN。

    返回:
        可能被截断的内容字符串。
    """
    if not truncate_after or len(content) <= truncate_after:
        return content
    return content[:truncate_after] + TRUNCATED_MESSAGE


class StrReplaceEditor(BaseTool):
    """字符串替换编辑器工具类。

    这个工具提供了查看、创建和编辑文件的功能，支持本地和沙箱环境。
    它特别优化了代码编辑场景，提供了精确的字符串替换、行插入和撤销功能。

    设计模式:
    1. 策略模式: 使用不同的FileOperator实现不同环境下的文件操作
    2. 命令模式: 通过不同的command参数执行不同的文件操作
    3. 备忘录模式: 使用_file_history保存文件历史状态支持撤销

    属性:
        name: 工具的名称标识符。
        description: 工具功能的详细描述。
        parameters: 工具参数的JSON Schema定义。
        _file_history: 保存文件历史版本的字典，用于撤销操作。
        _local_operator: 本地文件操作实例。
        _sandbox_operator: 沙箱文件操作实例。
    """

    name: str = "str_replace_editor"
    description: str = _STR_REPLACE_EDITOR_DESCRIPTION
    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {
                "description": "The commands to run. Allowed options are: `view`, `create`, `str_replace`, `insert`, `undo_edit`.",
                "enum": ["view", "create", "str_replace", "insert", "undo_edit"],
                "type": "string",
            },
            "path": {
                "description": "Absolute path to file or directory.",
                "type": "string",
            },
            "file_text": {
                "description": "Required parameter of `create` command, with the content of the file to be created.",
                "type": "string",
            },
            "old_str": {
                "description": "Required parameter of `str_replace` command containing the string in `path` to replace.",
                "type": "string",
            },
            "new_str": {
                "description": "Optional parameter of `str_replace` command containing the new string (if not given, no string will be added). Required parameter of `insert` command containing the string to insert.",
                "type": "string",
            },
            "insert_line": {
                "description": "Required parameter of `insert` command. The `new_str` will be inserted AFTER the line `insert_line` of `path`.",
                "type": "integer",
            },
            "view_range": {
                "description": "Optional parameter of `view` command when `path` points to a file. If none is given, the full file is shown. If provided, the file will be shown in the indicated line number range, e.g. [11, 12] will show lines 11 and 12. Indexing at 1 to start. Setting `[start_line, -1]` shows all lines from `start_line` to the end of the file.",
                "items": {"type": "integer"},
                "type": "array",
            },
        },
        "required": ["command", "path"],
    }
    _file_history: DefaultDict[PathLike, List[str]] = defaultdict(
        list
    )  # 文件历史状态字典
    _local_operator: LocalFileOperator = LocalFileOperator()  # 本地文件操作实例
    _sandbox_operator: SandboxFileOperator = SandboxFileOperator()  # 沙箱文件操作实例

    def _get_operator(self) -> FileOperator:
        """获取适当的文件操作器。

        根据配置选择使用本地或沙箱文件操作器。这是策略模式的一个应用，
        允许在运行时切换不同的文件操作实现。

        返回:
            根据配置选择的FileOperator实例。
        """
        return (
            self._sandbox_operator
            if config.sandbox.use_sandbox
            else self._local_operator
        )

    async def execute(
        self,
        *,
        command: Command,
        path: str,
        file_text: str | None = None,
        view_range: list[int] | None = None,
        old_str: str | None = None,
        new_str: str | None = None,
        insert_line: int | None = None,
        **kwargs: Any,
    ) -> str:
        """执行文件操作命令。

        这个方法实现了BaseTool的抽象execute方法，是工具的主要入口点。
        它根据command参数分发不同的文件操作，并进行参数验证。

        命令分派流程:
        1. 获取适当的文件操作器
        2. 验证路径和命令的合法性
        3. 根据命令调用相应的处理方法
        4. 字符串化结果并返回

        参数:
            command: 要执行的命令（view/create/str_replace/insert/undo_edit）。
            path: 文件或目录的绝对路径。
            file_text: 创建命令的文件内容。
            view_range: 查看命令的行号范围。
            old_str: str_replace命令要替换的字符串。
            new_str: str_replace/insert命令的新字符串。
            insert_line: insert命令的插入行号。
            **kwargs: 其他未使用的参数。

        返回:
            操作结果的字符串表示。

        异常:
            ToolError: 如果参数无效或操作失败。
        """
        # 获取适当的文件操作器
        operator = self._get_operator()

        # 验证路径和命令组合
        await self.validate_path(command, Path(path), operator)

        # 执行相应的命令
        if command == "view":
            result = await self.view(path, view_range, operator)
        elif command == "create":
            if file_text is None:
                raise ToolError("Parameter `file_text` is required for command: create")
            await operator.write_file(path, file_text)
            self._file_history[path].append(file_text)
            result = ToolResult(output=f"File created successfully at: {path}")
        elif command == "str_replace":
            if old_str is None:
                raise ToolError(
                    "Parameter `old_str` is required for command: str_replace"
                )
            result = await self.str_replace(path, old_str, new_str, operator)
        elif command == "insert":
            if insert_line is None:
                raise ToolError(
                    "Parameter `insert_line` is required for command: insert"
                )
            if new_str is None:
                raise ToolError("Parameter `new_str` is required for command: insert")
            result = await self.insert(path, insert_line, new_str, operator)
        elif command == "undo_edit":
            result = await self.undo_edit(path, operator)
        else:
            # 这应该由类型检查捕获，但为安全起见包含此处
            raise ToolError(
                f'Unrecognized command {command}. The allowed commands for the {self.name} tool are: {", ".join(get_args(Command))}'
            )

        return str(result)

    async def validate_path(
        self, command: str, path: Path, operator: FileOperator
    ) -> None:
        """验证路径和命令组合是否合法。

        这个方法检查路径是否存在、是否为目录以及与命令的兼容性。
        它实现了输入验证的最佳实践，在操作执行前检查参数有效性。

        验证内容:
        1. 路径必须是绝对路径
        2. 非create命令要求路径必须存在
        3. 只有view命令可以用于目录
        4. create命令要求路径不存在

        参数:
            command: 要执行的命令。
            path: 要验证的路径。
            operator: 用于检查路径的文件操作器。

        异常:
            ToolError: 如果路径与命令组合不合法。
        """
        # 检查路径是否为绝对路径
        if not path.is_absolute():
            raise ToolError(f"The path {path} is not an absolute path")

        # 非create命令才检查路径是否存在
        if command != "create":
            if not await operator.exists(path):
                raise ToolError(
                    f"The path {path} does not exist. Please provide a valid path."
                )

            # 检查路径是否为目录
            is_dir = await operator.is_directory(path)
            if is_dir and command != "view":
                raise ToolError(
                    f"The path {path} is a directory and only the `view` command can be used on directories"
                )

        # 检查create命令的文件是否已存在
        elif command == "create":
            exists = await operator.exists(path)
            if exists:
                raise ToolError(
                    f"File already exists at: {path}. Cannot overwrite files using command `create`."
                )

    async def view(
        self,
        path: PathLike,
        view_range: Optional[List[int]] = None,
        operator: FileOperator = None,
    ) -> CLIResult:
        """显示文件或目录内容。

        这个方法根据路径类型展示文件内容或目录结构。
        对于文件，它支持按行号范围查看部分内容，类似于Unix的cat和head/tail命令的组合。

        处理逻辑:
        1. 确定路径是文件还是目录
        2. 调用相应的处理方法
        3. 返回格式化的结果

        参数:
            path: 要查看的文件或目录路径。
            view_range: 可选的行号范围，格式为[start_line, end_line]。
            operator: 文件操作器实例。

        返回:
            包含文件或目录内容的CLIResult。

        异常:
            ToolError: 如果参数无效或操作失败。
        """
        # 确定路径是否为目录
        is_dir = await operator.is_directory(path)

        if is_dir:
            # 目录处理
            if view_range:
                raise ToolError(
                    "The `view_range` parameter is not allowed when `path` points to a directory."
                )

            return await self._view_directory(path, operator)
        else:
            # 文件处理
            return await self._view_file(path, operator, view_range)

    @staticmethod
    async def _view_directory(path: PathLike, operator: FileOperator) -> CLIResult:
        """显示目录内容。

        这个静态方法使用find命令列出目录中的文件和子目录，不包括隐藏项目。
        它类似于Unix的find命令，但限制了最大深度和排除了隐藏文件。

        查找策略:
        1. 最大深度为2层
        2. 排除以.开头的隐藏项目
        3. 使用操作器运行命令以支持不同环境

        参数:
            path: 要查看的目录路径。
            operator: 文件操作器实例。

        返回:
            包含目录列表的CLIResult。
        """
        find_cmd = f"find {path} -maxdepth 2 -not -path '*/\\.*'"

        # 使用操作器执行命令
        returncode, stdout, stderr = await operator.run_command(find_cmd)

        if not stderr:
            stdout = (
                f"Here's the files and directories up to 2 levels deep in {path}, "
                f"excluding hidden items:\n{stdout}\n"
            )

        return CLIResult(output=stdout, error=stderr)

    async def _view_file(
        self,
        path: PathLike,
        operator: FileOperator,
        view_range: Optional[List[int]] = None,
    ) -> CLIResult:
        """显示文件内容，可选择指定行号范围。

        这个方法读取文件内容并可以提取特定的行号范围，类似于Unix的
        sed命令的行选择功能。它支持各种范围表示，包括从特定行到文件末尾。

        行号处理:
        1. 读取完整文件内容
        2. 根据view_range截取指定行
        3. 验证行号边界
        4. 格式化输出并添加行号

        参数:
            path: 要查看的文件路径。
            operator: 文件操作器实例。
            view_range: 可选的行号范围[start_line, end_line]。

        返回:
            包含格式化文件内容的CLIResult。

        异常:
            ToolError: 如果view_range无效。
        """
        # 读取文件内容
        file_content = await operator.read_file(path)
        init_line = 1

        # 如果指定了view_range则应用
        if view_range:
            if len(view_range) != 2 or not all(isinstance(i, int) for i in view_range):
                raise ToolError(
                    "Invalid `view_range`. It should be a list of two integers."
                )

            file_lines = file_content.split("\n")
            n_lines_file = len(file_lines)
            init_line, final_line = view_range

            # 验证view_range
            if init_line < 1 or init_line > n_lines_file:
                raise ToolError(
                    f"Invalid `view_range`: {view_range}. Its first element `{init_line}` should be "
                    f"within the range of lines of the file: {[1, n_lines_file]}"
                )
            if final_line > n_lines_file:
                raise ToolError(
                    f"Invalid `view_range`: {view_range}. Its second element `{final_line}` should be "
                    f"smaller than the number of lines in the file: `{n_lines_file}`"
                )
            if final_line != -1 and final_line < init_line:
                raise ToolError(
                    f"Invalid `view_range`: {view_range}. Its second element `{final_line}` should be "
                    f"larger or equal than its first `{init_line}`"
                )

            # 应用范围
            if final_line == -1:
                file_content = "\n".join(file_lines[init_line - 1 :])
            else:
                file_content = "\n".join(file_lines[init_line - 1 : final_line])

        # 格式化并返回结果
        return CLIResult(
            output=self._make_output(file_content, str(path), init_line=init_line)
        )

    async def str_replace(
        self,
        path: PathLike,
        old_str: str,
        new_str: Optional[str] = None,
        operator: FileOperator = None,
    ) -> CLIResult:
        """在文件中用新字符串替换唯一的字符串。

        这个方法实现了精确的字符串替换功能，它确保要替换的字符串在文件中是唯一的，
        防止意外的多处替换。它特别适合编辑代码，因为它严格匹配包括空白在内的完整字符串。

        替换策略:
        1. 扩展制表符以确保精确匹配
        2. 检查旧字符串的唯一性
        3. 创建替换后的上下文片段
        4. 保存历史记录支持撤销

        参数:
            path: 要编辑的文件路径。
            old_str: 要替换的原始字符串（必须在文件中唯一）。
            new_str: 替换后的新字符串，默认为空字符串。
            operator: 文件操作器实例。

        返回:
            包含替换结果和片段预览的CLIResult。

        异常:
            ToolError: 如果旧字符串不存在或不唯一。
        """
        # 读取文件内容并扩展制表符
        file_content = (await operator.read_file(path)).expandtabs()
        old_str = old_str.expandtabs()
        new_str = new_str.expandtabs() if new_str is not None else ""

        # 检查old_str在文件中是否唯一
        occurrences = file_content.count(old_str)
        if occurrences == 0:
            raise ToolError(
                f"No replacement was performed, old_str `{old_str}` did not appear verbatim in {path}."
            )
        elif occurrences > 1:
            # 查找出现的行号
            file_content_lines = file_content.split("\n")
            lines = [
                idx + 1
                for idx, line in enumerate(file_content_lines)
                if old_str in line
            ]
            raise ToolError(
                f"No replacement was performed. Multiple occurrences of old_str `{old_str}` "
                f"in lines {lines}. Please ensure it is unique"
            )

        # 用new_str替换old_str
        new_file_content = file_content.replace(old_str, new_str)

        # 将新内容写入文件
        await operator.write_file(path, new_file_content)

        # 将原始内容保存到历史记录
        self._file_history[path].append(file_content)

        # 创建编辑部分的片段
        replacement_line = file_content.split(old_str)[0].count("\n")
        start_line = max(0, replacement_line - SNIPPET_LINES)
        end_line = replacement_line + SNIPPET_LINES + new_str.count("\n")
        snippet = "\n".join(new_file_content.split("\n")[start_line : end_line + 1])

        # 准备成功消息
        success_msg = f"The file {path} has been edited. "
        success_msg += self._make_output(
            snippet, f"a snippet of {path}", start_line + 1
        )
        success_msg += "Review the changes and make sure they are as expected. Edit the file again if necessary."

        return CLIResult(output=success_msg)

    async def insert(
        self,
        path: PathLike,
        insert_line: int,
        new_str: str,
        operator: FileOperator = None,
    ) -> CLIResult:
        """在文件的特定行插入文本。

        这个方法在文件的指定行号后插入新内容。它特别适合向文件中
        添加新代码行、配置项或文本块，同时保留上下文。

        插入流程:
        1. 读取并准备文件内容
        2. 验证插入行号的有效性
        3. 在指定位置插入新内容
        4. 创建包含上下文的预览片段
        5. 保存历史记录支持撤销

        参数:
            path: 要编辑的文件路径。
            insert_line: 要插入内容的行号（内容将插入此行之后）。
            new_str: 要插入的新字符串。
            operator: 文件操作器实例。

        返回:
            包含插入结果和片段预览的CLIResult。

        异常:
            ToolError: 如果insert_line无效。
        """
        # 读取并准备内容
        file_text = (await operator.read_file(path)).expandtabs()
        new_str = new_str.expandtabs()
        file_text_lines = file_text.split("\n")
        n_lines_file = len(file_text_lines)

        # 验证insert_line
        if insert_line < 0 or insert_line > n_lines_file:
            raise ToolError(
                f"Invalid `insert_line` parameter: {insert_line}. It should be within "
                f"the range of lines of the file: {[0, n_lines_file]}"
            )

        # 执行插入
        new_str_lines = new_str.split("\n")
        new_file_text_lines = (
            file_text_lines[:insert_line]
            + new_str_lines
            + file_text_lines[insert_line:]
        )

        # 创建预览片段
        snippet_lines = (
            file_text_lines[max(0, insert_line - SNIPPET_LINES) : insert_line]
            + new_str_lines
            + file_text_lines[insert_line : insert_line + SNIPPET_LINES]
        )

        # 连接行并写入文件
        new_file_text = "\n".join(new_file_text_lines)
        snippet = "\n".join(snippet_lines)

        await operator.write_file(path, new_file_text)
        self._file_history[path].append(file_text)

        # 准备成功消息
        success_msg = f"The file {path} has been edited. "
        success_msg += self._make_output(
            snippet,
            "a snippet of the edited file",
            max(1, insert_line - SNIPPET_LINES + 1),
        )
        success_msg += "Review the changes and make sure they are as expected (correct indentation, no duplicate lines, etc). Edit the file again if necessary."

        return CLIResult(output=success_msg)

    async def undo_edit(
        self, path: PathLike, operator: FileOperator = None
    ) -> CLIResult:
        """撤销对文件的最后一次编辑。

        这个方法实现了编辑撤销功能，它从历史记录中恢复文件的上一个版本。
        这是备忘录模式的一个应用，使用存储的历史状态恢复对象。

        撤销流程:
        1. 检查文件是否有编辑历史
        2. 获取并删除最近的历史版本
        3. 将历史版本写回文件
        4. 返回撤销成功消息

        参数:
            path: 要撤销编辑的文件路径。
            operator: 文件操作器实例。

        返回:
            包含撤销结果的CLIResult。

        异常:
            ToolError: 如果文件没有编辑历史。
        """
        if not self._file_history[path]:
            raise ToolError(f"No edit history found for {path}.")

        old_text = self._file_history[path].pop()
        await operator.write_file(path, old_text)

        return CLIResult(
            output=f"Last edit to {path} undone successfully. {self._make_output(old_text, str(path))}"
        )

    def _make_output(
        self,
        file_content: str,
        file_descriptor: str,
        init_line: int = 1,
        expand_tabs: bool = True,
    ) -> str:
        """格式化文件内容以带行号显示。

        这个辅助方法将文件内容格式化为类似于Unix `cat -n` 命令的输出，
        添加行号并扩展制表符以提高可读性。

        格式化特性:
        1. 可能截断过长内容
        2. 扩展制表符提高可读性
        3. 添加从指定行号开始的行号
        4. 添加描述标题

        参数:
            file_content: 要格式化的文件内容。
            file_descriptor: 文件描述符，用于显示标题。
            init_line: 起始行号，默认为1。
            expand_tabs: 是否扩展制表符，默认为True。

        返回:
            格式化的文件内容字符串，带有行号和标题。
        """
        file_content = maybe_truncate(file_content)
        if expand_tabs:
            file_content = file_content.expandtabs()

        # 为每行添加行号
        file_content = "\n".join(
            [
                f"{i + init_line:6}\t{line}"
                for i, line in enumerate(file_content.split("\n"))
            ]
        )

        return (
            f"Here's the result of running `cat -n` on {file_descriptor}:\n"
            + file_content
            + "\n"
        )
