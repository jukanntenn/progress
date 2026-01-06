"""Claude Code 分析器"""

import subprocess
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class AnalysisResult:
    """分析结果"""

    def __init__(self, data: dict):
        self.summary = data.get('summary', '')
        self.added_structures = data.get('added_structures', [])
        self.removed_structures = data.get('removed_structures', [])
        self.modified_functions = data.get('modified_functions', [])
        self.added_functions = data.get('added_functions', [])
        self.removed_functions = data.get('removed_functions', [])
        self.api_changes = data.get('api_changes', [])
        self.important_changes = data.get('important_changes', [])


class ClaudeCodeAnalyzer:
    """调用 Claude Code CLI 分析代码变化"""

    def __init__(self):
        self.claude_code_path = "claude"

    def analyze_diff(
        self,
        repo_name: str,
        branch: str,
        diff: str,
        commit_messages: list[str]
    ) -> AnalysisResult:
        """分析代码 diff

        Args:
            repo_name: 仓库名称
            branch: 分支名称
            diff: 代码 diff 内容
            commit_messages: 提交消息列表

        Returns:
            AnalysisResult 对象
        """
        # 1. 创建临时的 diff 文件
        diff_file = Path(f"/tmp/{repo_name}_{branch}_diff.patch")
        diff_file.write_text(diff, encoding="utf-8")
        logger.debug(f"创建临时 diff 文件: {diff_file}")

        try:
            # 2. 构造分析提示词
            prompt = self._build_analysis_prompt(repo_name, branch, commit_messages)

            # 3. 调用 claude-code CLI
            logger.info(f"正在分析 {repo_name} 的代码变化...")
            analysis_text = self._run_claude_analysis(diff_file, prompt)

            # 4. 解析结果为结构化数据
            result = self._parse_analysis_result(analysis_text)
            return result

        finally:
            # 清理临时文件
            if diff_file.exists():
                diff_file.unlink()
                logger.debug(f"删除临时文件: {diff_file}")

    def _build_analysis_prompt(
        self,
        repo_name: str,
        branch: str,
        commit_messages: list[str]
    ) -> str:
        """构造分析提示词"""
        commits_str = "\n".join(f"  - {msg}" for msg in commit_messages)

        return f"""请分析这个 GitHub 仓库的代码变化，并返回 JSON 格式的分析结果。

仓库: {repo_name}
分支: {branch}

相关提交消息:
{commits_str}

请按照以下 JSON 格式返回分析结果（只返回 JSON，不要其他内容）:
{{
  "summary": "简要总结这次变更的主要内容（1-2句话）",
  "added_structures": ["新增的类、接口、数据结构等"],
  "removed_structures": ["删除的类、接口、数据结构等"],
  "modified_functions": ["修改的函数或方法（格式：文件名:函数名）"],
  "added_functions": ["新增的函数或方法（格式：文件名:函数名）"],
  "removed_functions": ["删除的函数或方法（格式：文件名:函数名）"],
  "api_changes": ["API 相关的变更说明"],
  "important_changes": ["其他重要变更说明"]
}}

重点关注：
1. 破坏性变更（breaking changes）
2. 新增的公开 API
3. 删除的公开 API
4. 重要功能的修改
5. 性能相关改动

如果没有某类变更，对应的数组可以为空。
"""

    def _run_claude_analysis(self, diff_file: Path, prompt: str) -> str:
        """执行 claude-code CLI 分析"""
        # 使用管道传递 diff 文件内容到 claude
        # 正确用法: cat file | claude -p "query"
        cmd_cat = ["cat", str(diff_file)]
        cmd_claude = [
            self.claude_code_path,
            "-p",
            "--output-format", "json",
            prompt
        ]

        try:
            # 输出完整命令
            logger.info(f"Claude 命令: cat {diff_file} | claude -p --output-format json '<prompt>'")

            # 读取 diff 文件内容
            with open(diff_file, 'r', encoding='utf-8') as f:
                diff_content = f.read()

            # 使用管道传递给 claude
            result = subprocess.run(
                cmd_claude,
                input=diff_content,
                capture_output=True,
                text=True,
                timeout=600  # 10分钟超时
            )

            # 输出 Claude 返回结果
            logger.info(f"Claude 输出: {result.stdout}")

            if result.stderr:
                logger.warning(f"Claude stderr: {result.stderr}")

            return result.stdout
        except subprocess.CalledProcessError as e:
            logger.error(f"Claude Code 分析失败: {e.stderr}")
            raise RuntimeError(f"Claude Code 分析失败: {e.stderr}") from e
        except subprocess.TimeoutExpired:
            logger.error("Claude Code 分析超时")
            raise RuntimeError("Claude Code 分析超时") from None
        except FileNotFoundError as e:
            logger.error(f"文件不存在: {e}")
            raise RuntimeError(f"文件不存在: {e}") from None

    def _parse_analysis_result(self, analysis_text: str) -> AnalysisResult:
        """解析分析结果"""
        try:
            # 首先尝试解析为 Claude API 的 JSON 响应格式
            response_data = json.loads(analysis_text)

            # 检查是否是 Claude API 响应格式
            if 'result' in response_data:
                # 从 result 中提取实际的文本内容
                result_text = response_data.get('result', '')
                logger.info(f"Claude API 返回结果，提取 result 字段")
            elif isinstance(response_data, dict) and 'summary' in response_data:
                # 直接是我们要求的 JSON 格式
                result_text = analysis_text
                logger.info(f"直接解析为分析结果 JSON")
            else:
                # 尝试从其他字段提取
                result_text = str(response_data)
                logger.warning(f"未知的 JSON 格式，尝试直接使用")

            # 现在从 result_text 中提取我们需要的 JSON
            # 首先尝试直接解析
            try:
                data = json.loads(result_text)
                if 'summary' in data:
                    return AnalysisResult(data)
            except json.JSONDecodeError:
                pass

            # 尝试提取 ```json ... ``` 代码块
            if "```json" in result_text:
                start = result_text.find("```json") + 7
                end = result_text.find("```", start)
                json_text = result_text[start:end].strip()
                data = json.loads(json_text)
                return AnalysisResult(data)

            # 尝试提取 ``` ... ``` 代码块
            if "```" in result_text:
                start = result_text.find("```") + 3
                end = result_text.find("```", start)
                json_text = result_text[start:end].strip()
                data = json.loads(json_text)
                return AnalysisResult(data)

            # 如果都失败了，记录原始内容并返回空结果
            logger.warning(f"无法解析 Claude 返回的结果，原始内容: {result_text[:200]}...")
            return AnalysisResult({
                'summary': '无法解析分析结果',
                'added_structures': [],
                'removed_structures': [],
                'modified_functions': [],
                'added_functions': [],
                'removed_functions': [],
                'api_changes': [],
                'important_changes': []
            })

        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析失败: {e}")
            logger.warning(f"原始内容: {analysis_text[:200]}...")
            return AnalysisResult({
                'summary': 'JSON 解析失败',
                'added_structures': [],
                'removed_structures': [],
                'modified_functions': [],
                'added_functions': [],
                'removed_functions': [],
                'api_changes': [],
                'important_changes': []
            })
        except Exception as e:
            logger.error(f"解析分析结果时发生未知错误: {e}")
            return AnalysisResult({
                'summary': f'解析错误: {str(e)}',
                'added_structures': [],
                'removed_structures': [],
                'modified_functions': [],
                'added_functions': [],
                'removed_functions': [],
                'api_changes': [],
                'important_changes': []
            })
