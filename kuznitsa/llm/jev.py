import httpx


class Disabled:
    enabled = False

    def decide(self,state,questions):
        return {}


class Jev:
    enabled = True

    def __init__(self,transport=None,key=None,url="https://openrouter.ai/api/alpha/decisions",model="typesafe/jev-1.13"):
        self.url,self.model = url,model
        self.client = httpx.Client(transport=transport,timeout=httpx.Timeout(6,connect=2),
                                   headers={"Authorization":"Bearer "+key} if key else {})

    def decide(self,state,questions):
        response = self.client.post(self.url,json=dict(model=self.model,state={"запрос":state},questions=questions))
        response.raise_for_status()
        return response.json()["answers"]

    def close(self):
        self.client.close()
