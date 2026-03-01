from gpt_researcher.document.pdf_section_splitter import PDFSectionSplitter


def test_pdf_section_splitter_recognizes_common_sections():
    text = """
Awesome Paper Title

Abstract
This paper studies retrieval quality.

1 Introduction
Intro content.

2 Background
Background content.

3 Methods
Method content.

4 Results
Result content.

5 Discussion
Discussion content.

References
[1] Example citation.
""".strip()

    sections = PDFSectionSplitter.split(text)
    section_names = [s["section"] for s in sections]

    assert "title" in section_names
    assert "abstract" in section_names
    assert "introduction" in section_names
    assert "background" in section_names
    assert "method" in section_names
    assert "result" in section_names
    assert "discussion" in section_names
    assert "reference" in section_names


def test_pdf_section_splitter_supports_chinese_headings():
    text = """
论文题目

摘要
这里是摘要内容。

导言
这里是导言内容。

方法
这里是方法内容。

结果
这里是结果内容。

讨论
这里是讨论内容。

参考文献
[1] 中文引用。
""".strip()

    sections = PDFSectionSplitter.split(text)
    section_names = [s["section"] for s in sections]

    assert "abstract" in section_names
    assert "introduction" in section_names
    assert "method" in section_names
    assert "result" in section_names
    assert "discussion" in section_names
    assert "reference" in section_names
