"""提示词模板（全中文）：系统角色、引用标注、兜底与问题改写。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

DEFAULT_APP_NAME = "企业知识库智能问答"

SYSTEM_PROMPT = """你是「{app_name}」的智能助手，服务对象是企业内部员工与客户。
你的任务是依据提供的【参考资料】准确回答用户问题，帮助用户快速获得可信的企业知识。

请严格遵守以下回答规则：
1. 先给结论，再给依据；结论要直接对应问题，不要复述用户提问。
2. 答案中的关键信息必须来自【参考资料】，并用方括号标注来源编号，例如「……需要提前 7 天提交申请[1]」；多个来源可写作 [1][3]。
3. 如果【参考资料】不足以回答问题，请明确说明「根据现有知识库资料未找到相关内容」，再基于通用常识给出谨慎的补充建议，并提示「以下内容不来自企业知识库，仅供参考」。
4. 严禁编造资料中不存在的数字、条款、人名、日期、链接等信息；不确定时直接说明不确定。
5. 若不同资料存在冲突，请指出冲突点，并分别说明各自来源编号，让用户判断。
6. 回答使用简体中文，条理清晰，必要时使用分点或小标题；长度以 150~400 字为宜，复杂问题可适当加长。
7. 不要输出与问题无关的寒暄，也不要提及「参考资料」这一说法本身，直接给出答案。
"""

NO_CONTEXT_HINT = """【参考资料】
（本次未检索到相关内容：用户尚未选择知识库，或所选知识库中没有与问题相关的资料。）

请按照规则 3 处理：先说明未在知识库中找到相关内容，再给出通用性建议，并提醒用户该建议不来自企业知识库。
"""

CONTEXT_TEMPLATE = """【参考资料】
{blocks}
"""

CONTEXT_BLOCK_TEMPLATE = """[{index}] 来源：{doc_name}｜知识库：{kb_name}{page_text}｜相似度：{score:.2f}
{content}
"""

QUERY_REWRITE_PROMPT = """你是检索查询改写助手。请把用户的口语化问题改写为一条更适合向量检索的中文查询语句。

改写要求：
1. 保留原始问题的全部关键实体（产品名、部门名、时间、数字等）。
2. 补充同义表述与上位概念，用空格分隔多个关键词。
3. 只输出改写后的查询语句本身，不要解释、不要加引号、不要换行。

用户问题：{question}
改写结果："""


@dataclass
class ContextItem:
    """注入提示词的单条参考资料。"""

    index: int
    content: str
    doc_name: str = "未知文档"
    kb_name: str = "未知知识库"
    page_no: int | None = None
    score: float = 0.0


def format_context(item: ContextItem) -> str:
    """格式化单条参考资料。"""
    page_text = f"｜第 {item.page_no} 页" if item.page_no else ""
    content = " ".join((item.content or "").split())
    return CONTEXT_BLOCK_TEMPLATE.format(
        index=item.index,
        doc_name=item.doc_name,
        kb_name=item.kb_name,
        page_text=page_text,
        score=item.score,
        content=content,
    )


def build_context_text(items: Sequence[ContextItem], max_chars: int = 6000) -> str:
    """拼接参考资料文本，超出长度限制时截断较后的资料。"""
    if not items:
        return ""
    blocks: list[str] = []
    used = 0
    for item in items:
        block = format_context(item)
        if used + len(block) > max_chars and blocks:
            break
        blocks.append(block)
        used += len(block)
    return "\n".join(blocks).strip()


def build_system_prompt(items: Sequence[ContextItem], app_name: str = DEFAULT_APP_NAME, max_chars: int = 6000) -> str:
    """构建系统提示词（角色规则 + 参考资料）。"""
    base = SYSTEM_PROMPT.format(app_name=app_name)
    context_text = build_context_text(items, max_chars=max_chars)
    if not context_text:
        return f"{base}\n{NO_CONTEXT_HINT}"
    return f"{base}\n{CONTEXT_TEMPLATE.format(blocks=context_text)}"


def build_messages(
    question: str,
    items: Sequence[ContextItem],
    history: Sequence[dict[str, str]] | None = None,
    app_name: str = DEFAULT_APP_NAME,
    max_chars: int = 6000,
) -> list[dict[str, str]]:
    """组装发给大模型的消息列表：系统提示词 + 历史对话 + 当前问题。"""
    messages: list[dict[str, str]] = [
        {"role": "system", "content": build_system_prompt(items, app_name=app_name, max_chars=max_chars)}
    ]
    for message in history or []:
        role = message.get("role")
        content = (message.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question.strip()})
    return messages


def build_rewrite_messages(question: str) -> list[dict[str, str]]:
    """构建问题改写消息。"""
    return [{"role": "user", "content": QUERY_REWRITE_PROMPT.format(question=question.strip())}]


def session_title_from_question(question: str, limit: int = 20) -> str:
    """用首句问题生成默认会话名称。"""
    text = " ".join((question or "").split())
    if not text:
        return "新对话"
    return text if len(text) <= limit else f"{text[:limit]}…"
