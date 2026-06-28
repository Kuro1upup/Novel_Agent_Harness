"""Deterministic style analysis with an optional LLM refinement."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from typing import Any

from novel_harness.models.style import StyleProfile

from ._base import call_provider, format_prompt, load_prompt, make_model, normalize_texts


class StyleAnalyzer:
    """Summarize techniques without copying an author's prose."""

    def __init__(self, llm_provider: Any | None = None) -> None:
        self.llm_provider = llm_provider

    def analyze(
        self,
        texts: str | Sequence[str],
        *,
        project_id: str = "default",
    ) -> StyleProfile:
        samples = normalize_texts(texts)
        if not samples:
            raise ValueError("at least one non-empty style sample is required")
        joined = "\n".join(samples)
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n|\n", joined) if part.strip()]
        sentences = [
            part.strip() for part in re.split(r"(?<=[。！？!?；;])", joined) if part.strip()
        ]
        sentence_lengths = [len(re.sub(r"\s+", "", part)) for part in sentences] or [len(joined)]
        paragraph_lengths = [len(re.sub(r"\s+", "", part)) for part in paragraphs] or [len(joined)]
        avg_sentence = sum(sentence_lengths) / len(sentence_lengths)
        avg_paragraph = sum(paragraph_lengths) / len(paragraph_lengths)

        quoted = re.findall(r"[“「『\"](.*?)[”」』\"]", joined, re.DOTALL)
        dialogue_chars = sum(len(value) for value in quoted)
        dialogue_ratio = round(dialogue_chars / max(len(joined), 1), 3)
        first_person = len(re.findall(r"(?<![你他她它])我(?:们)?", joined))
        third_person = len(re.findall(r"(?:他|她|主角|少年|男人|女人)", joined))
        narrative_pov = "第一人称" if first_person > third_person * 1.3 else "第三人称限知"

        words = re.findall(r"[\u4e00-\u9fff]{2,6}", joined)
        stop = {"一个", "这个", "那个", "他们", "自己", "没有", "什么", "只是", "已经"}
        common_phrases = [
            word for word, count in Counter(words).most_common(30) if count > 1 and word not in stop
        ][:8]
        devices: list[str] = []
        if re.search(r"像|仿佛|如同|宛若", joined):
            devices.append("比喻")
        if re.search(r"难道|岂非|怎会|何尝", joined):
            devices.append("反问")
        if re.search(r"！.*！|。[^。]{0,15}。[^。]{0,15}。", joined):
            devices.append("短句强化")
        if re.search(r"(.)\1{2,}", joined):
            devices.append("重复强调")
        if not devices:
            devices.append("动作与感受交替")

        emotional_hits = len(re.findall(r"怒|惊|恐|喜|痛|激|冷|热|颤|疯", joined))
        emotional_temperature = "高张力" if emotional_hits / max(len(joined), 1) > 0.015 else "克制"
        pacing = "快节奏" if avg_sentence < 22 or dialogue_ratio > 0.28 else "中缓节奏"
        sentence_label = (
            "短句为主" if avg_sentence < 18 else "中等句长" if avg_sentence < 35 else "长句为主"
        )
        paragraph_label = (
            "短段落" if avg_paragraph < 80 else "中等段落" if avg_paragraph < 180 else "长段落"
        )
        guideline = [
            f"采用{narrative_pov}，保持视角稳定",
            f"句式特征为{sentence_label}，段落采用{paragraph_label}",
            f"对白占比目标约 {dialogue_ratio:.0%}，服务人物行动与冲突",
            f"保持{pacing}与{emotional_temperature}，但使用全新的措辞和场景细节",
            "只复用抽象风格特征，不复刻样本文句、独特意象或连续表达",
        ]
        data = {
            "project_id": project_id,
            "narrative_pov": narrative_pov,
            "tense": "过去时叙述",
            "sentence_length": round(avg_sentence, 2),
            "paragraph_length": round(avg_paragraph, 2),
            "dialogue_ratio": dialogue_ratio,
            "common_phrases": common_phrases,
            "rhetorical_devices": devices,
            "pacing": pacing,
            "emotional_temperature": emotional_temperature,
            "taboo_patterns": ["复制样本长句", "照搬独特意象", "模仿可识别作者签名表达"],
            "style_summary": (
                f"{narrative_pov}；{sentence_label}、{paragraph_label}；"
                f"{pacing}，情绪表达{emotional_temperature}。"
            ),
            "continuation_guidelines": guideline,
        }
        return make_model(StyleProfile, data)

    async def aanalyze(
        self,
        texts: str | Sequence[str],
        *,
        project_id: str = "default",
    ) -> StyleProfile:
        baseline = self.analyze(texts, project_id=project_id)
        if self.llm_provider is None:
            return baseline
        prompt = format_prompt(
            load_prompt("style_analyzer"),
            {
                "samples": normalize_texts(texts),
                "local_statistics": baseline,
            },
        )
        return await call_provider(
            self.llm_provider,
            prompt=prompt,
            response_model=StyleProfile,
        )

    async def run(
        self,
        texts: str | Sequence[str],
        *,
        project_id: str = "default",
    ) -> StyleProfile:
        return await self.aanalyze(texts, project_id=project_id)
