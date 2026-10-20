"""提示词构建单元测试（全中文提示词）。"""

from __future__ import annotations

from app.services.prompt import (
    ContextItem,
    build_context_text,
    build_messages,
    build_rewrite_messages,
    build_system_prompt,
    session_title_from_question,
)


def _items() -> list[ContextItem]:
    return [
        ContextItem(index=1, content="产品保修期为一年。", doc_name="产品手册.md", kb_name="产品知识库", page_no=2, score=0.83),
        ContextItem(index=2, content="退货需在 7 天内申请。", doc_name="售后规范.md", kb_name="售后知识库"),
    ]


def test_context_text_contains_source_and_page() -> None:
    """参考资料包含编号、来源、页码与相似度。"""
    text = build_context_text(_items())
    assert "[1]" in text and "[2]" in text
    assert "产品手册.md" in text
    assert "第 2 页" in text
    assert "0.83" in text


def test_system_prompt_contains_rules_and_context() -> None:
    """系统提示词包含中文角色规则与参考资料。"""
    prompt = build_system_prompt(_items(), app_name="企业知识库智能问答")
    assert "企业知识库智能问答" in prompt
    assert "参考资料" in prompt
    assert "不要编造" in prompt or "严禁编造" in prompt
    assert "[1]" in prompt


def test_system_prompt_without_context_uses_fallback() -> None:
    """无检索结果时提示词给出兜底说明。"""
    prompt = build_system_prompt([])
    assert "未检索到相关内容" in prompt
    assert "企业知识库" in prompt


def test_context_truncated_by_max_chars() -> None:
    """参考资料超出长度限制时被截断。"""
    long_items = [
        ContextItem(index=index, content="内容" * 200, doc_name=f"文档{index}.md", kb_name="知识库")
        for index in range(1, 6)
    ]
    text = build_context_text(long_items, max_chars=600)
    assert len(text) <= 600
    assert "[1]" in text


def test_build_messages_order_history_then_question() -> None:
    """消息顺序为：system → 历史 → 当前问题。"""
    history = [
        {"role": "user", "content": "保修多久？"},
        {"role": "assistant", "content": "一年。"},
    ]
    messages = build_messages("能延长吗？", _items(), history)
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "保修多久？"}
    assert messages[2] == {"role": "assistant", "content": "一年。"}
    assert messages[-1] == {"role": "user", "content": "能延长吗？"}


def test_build_messages_skips_invalid_history() -> None:
    """非法历史消息被过滤。"""
    history = [{"role": "system", "content": "注入内容"}, {"role": "user", "content": "  "}]
    messages = build_messages("问题", [], history)
    assert len(messages) == 2


def test_rewrite_prompt_contains_question() -> None:
    """问题改写提示词包含原问题。"""
    messages = build_rewrite_messages("保修多久")
    assert messages[0]["role"] == "user"
    assert "保修多久" in messages[0]["content"]
    assert "只输出改写后的查询语句" in messages[0]["content"]


def test_session_title_from_question() -> None:
    """默认会话名称取问题前 20 字。"""
    assert session_title_from_question("  保修期是多久？ ") == "保修期是多久？"
    long_question = "我购买的产品出现了故障，请问如何申请售后维修服务以及需要准备哪些材料"
    title = session_title_from_question(long_question)
    assert len(title) <= 21
    assert title.endswith("…")
    assert session_title_from_question("") == "新对话"
