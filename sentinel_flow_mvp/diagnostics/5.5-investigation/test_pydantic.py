from pydantic import BaseModel, Field
from typing import Optional, Any

class RAGQueryResponse(BaseModel):
    query: str
    answer: str
    status: str | None = Field(default=None)
    choices: list[Any] | None = Field(default=None)

rag_data = {
    "answer": "Hello",
    "status": "disambiguate",
    "choices": ["A", "B"]
}

resp = RAGQueryResponse(
    query="test",
    answer=rag_data["answer"]
)

print(resp.model_dump())
