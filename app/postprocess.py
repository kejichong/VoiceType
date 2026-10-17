"""文本后处理：把 ASR 的口语输出整理成可以直接用的书面文字。

原则是「保守」：宁可留一点口水词，也不要改错用户的原话。
所有规则都可开关，改错了能一键关掉。
"""
from __future__ import annotations

import re

# 单独成词的口头填充语：只在句首或标点后出现时才删，
# 「好啊」「那里」这类正常用法不会被误伤
_LEADING_FILLER = re.compile(r"(^|[，。！？；：、\s])(?:嗯+|呃+|啊+|哦+|噢+|唉+|诶+)[，、,.]?\s*")

# 明显的口语赘词（可在配置里追加）
_DEFAULT_REDUNDANT = ["那个那个", "这个这个", "就是说", "然后呢", "对吧对吧"]

_MULTI_PUNCT = re.compile(r"([，。！？；：、,.!?;:])\1+")
_SPACE_AROUND_CJK = re.compile(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([，。！？；：、])")
_END_PUNCT = "。！？!?…~～”』）)】》"


def remove_fillers(text: str, extra: list[str] | None = None) -> str:
    out = _LEADING_FILLER.sub(r"\1", text)
    for word in list(_DEFAULT_REDUNDANT) + list(extra or []):
        if word:
            out = out.replace(word, "")
    # 删除后可能留下「，，」
    return _MULTI_PUNCT.sub(r"\1", out)


def normalize_punctuation(text: str) -> str:
    out = _MULTI_PUNCT.sub(r"\1", text)
    out = _SPACE_BEFORE_PUNCT.sub(r"\1", out)
    out = _SPACE_AROUND_CJK.sub("", out)
    # 纯中文句子里的英文句点/逗号换成中文标点
    if re.search(r"[\u4e00-\u9fff]", out):
        out = out.replace(",", "，").replace(";", "；").replace(":", "：")
        out = re.sub(r"\.(?=\s|$)", "。", out)
    return out


def ensure_end_punct(text: str) -> str:
    if text and text[-1] not in _END_PUNCT:
        return text + "。"
    return text


def tidy(text: str) -> str:
    """完整流水线。空输入返回空串。"""
    if not text:
        return ""
    out = text.strip()
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = normalize_punctuation(out)
    out = ensure_end_punct(out)
    return out


def process(text: str, remove_filler: bool = True, extra_fillers: list[str] | None = None) -> str:
    if not text:
        return ""
    out = text
    if remove_filler:
        out = remove_fillers(out, extra_fillers)
    return tidy(out)
