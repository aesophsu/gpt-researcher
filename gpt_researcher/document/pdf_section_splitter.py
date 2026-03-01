import re
from typing import Dict, List


class PDFSectionSplitter:
    """Split academic PDF text by semantic sections."""

    SECTION_PATTERNS: Dict[str, List[str]] = {
        "abstract": [r"abstract", r"摘要"],
        "introduction": [r"introduction", r"导言", r"引言", r"简介"],
        "background": [r"background", r"背景"],
        "related_work": [r"related work", r"相关工作", r"文献综述"],
        "method": [r"method(?:ology)?", r"methods", r"方法", r"研究方法", r"材料与方法"],
        "experiment": [r"experiments?", r"实验", r"实验设置"],
        "result": [r"results?", r"结果", r"研究结果"],
        "discussion": [r"discussion", r"讨论", r"分析与讨论"],
        "conclusion": [r"conclusion", r"conclusions", r"结论", r"总结"],
        "reference": [r"references?", r"bibliography", r"citation", r"参考文献", r"引用"],
    }

    _MAX_HEADING_LEN = 120

    @classmethod
    def split(cls, text: str) -> List[Dict[str, str]]:
        if not text or not text.strip():
            return []

        lines = text.splitlines()
        sections: List[Dict[str, str]] = []

        current_section = "title"
        buffer: List[str] = []

        for line in lines:
            heading_section = cls._match_section_heading(line)
            if heading_section:
                cls._flush_section(sections, current_section, buffer)
                current_section = heading_section
            else:
                buffer.append(line)

        cls._flush_section(sections, current_section, buffer)

        if not sections:
            return [{"section": "content", "raw_content": text.strip()}]
        return sections

    @classmethod
    def _flush_section(
        cls,
        sections: List[Dict[str, str]],
        section_name: str,
        buffer: List[str],
    ) -> None:
        content = "\n".join(buffer).strip()
        buffer.clear()
        if content:
            sections.append({"section": section_name, "raw_content": content})

    @classmethod
    def _match_section_heading(cls, line: str) -> str | None:
        cleaned = line.strip()
        if not cleaned or len(cleaned) > cls._MAX_HEADING_LEN:
            return None

        # Common heading style: "1 Introduction", "2.1 Methods", "III. Results"
        cleaned = re.sub(r"^\s*\d+(\.\d+)*\s*[\.\-:\)]?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^\s*[IVXLCM]+\b[\.\-:\)]?\s+", "", cleaned, flags=re.IGNORECASE)
        normalized = re.sub(r"\s+", " ", cleaned).strip().lower()

        for section, patterns in cls.SECTION_PATTERNS.items():
            for pattern in patterns:
                if re.fullmatch(pattern, normalized, flags=re.IGNORECASE):
                    return section
        return None
