import httpx


class Disabled:
    enabled = False
    model = "typesafe/jev-1.13"

    def decide(self,state,questions):
        return {}


class Jev:
    enabled = True

    def __init__(self,transport=None,key=None,url="https://openrouter.ai/api/alpha/decisions",model="typesafe/jev-1.13"):
        self.url,self.model = url,model
        self.client = httpx.Client(transport=transport,timeout=httpx.Timeout(2.,connect=.35),
                                   headers={"Authorization":"Bearer "+key} if key else {})

    def complete(self,state,questions):
        payload=dict(model=self.model,state=state if isinstance(state,dict) else {"запрос":state},questions=questions)
        response=self.client.post(self.url,json=payload)
        response.raise_for_status()
        return response.json()

    def decide(self,state,questions):
        return self.complete(state,questions)["answers"]

    def close(self):
        self.client.close()
