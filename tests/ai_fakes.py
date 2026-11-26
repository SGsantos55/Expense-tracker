from langchain_core.messages import AIMessage


class FakeChatModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        response = self.responses[index]
        if isinstance(response, Exception):
            raise response
        return AIMessage(content=response)


def valid_summary_json():
    return """{
        "overview": "Your recorded activity is shown above.",
        "key_findings": [],
        "budget_analysis": "Your budget status is shown above.",
        "category_analysis": [],
        "recommendations": [],
        "warnings": []
    }"""
