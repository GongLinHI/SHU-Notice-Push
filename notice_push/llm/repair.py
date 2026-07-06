from __future__ import annotations


def render_summary_repair_prompt(original_user_prompt: str, markdown: str) -> str:
    return (
        "请只修复下面摘要的 Markdown 格式，使其严格包含这些字段："
        "发布时间、影响对象、核心信息、行动指引、截止时间、相关链接。\n"
        "不要新增事实，不要改变原摘要含义；缺失字段如无信息请写“未提及”。\n\n"
        f"原通知上下文：\n{original_user_prompt}\n\n"
        f"待修复摘要：\n{markdown}\n"
    )
