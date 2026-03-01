from typing import List, Union

from gpt_researcher.core.documents import DefaultDocumentLoader, DocumentSource


class DocumentLoader:

    def __init__(self, path: Union[str, List[str]]):
        self.path = path

    async def load(self) -> list:
        loader = DefaultDocumentLoader()
        raw_docs = await loader.load(DocumentSource(path=self.path, recursive=True))

        docs = []
        for doc in raw_docs:
            docs.append(
                {
                    "raw_content": doc.raw_content,
                    "url": doc.source.split("/")[-1],
                    "section": doc.section,
                }
            )

        if not docs:
            raise ValueError("🤷 Failed to load any documents!")
        return docs
