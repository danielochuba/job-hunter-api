"""OpenAI adapter for the LLM port (moved from Phase 1 llm.py). Swap this file to change providers."""
import json


class OpenAILLM:
    def __init__(self, api_key=None, fast_model="gpt-5-mini", strong_model="gpt-5",
                 embed_model="text-embedding-3-small", on_usage=None):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key) if api_key else OpenAI()
        self.fast_model = fast_model
        self.strong_model = strong_model
        self.embed_model = embed_model
        self.on_usage = on_usage  # (purpose, model, input_tokens, output_tokens)

    def _record(self, purpose, model, usage):
        if usage and self.on_usage:
            self.on_usage(purpose, model, getattr(usage, "prompt_tokens", 0) or 0,
                          getattr(usage, "completion_tokens", 0) or 0)

    def embed(self, texts, purpose="embed"):
        out = []
        for i in range(0, len(texts), 64):
            batch = [t[:8000] or " " for t in texts[i:i + 64]]
            resp = self.client.embeddings.create(model=self.embed_model, input=batch)
            self._record(purpose, self.embed_model, resp.usage)
            out.extend(d.embedding for d in resp.data)
        return out

    def structured(self, model, system, user, schema, name, purpose=None):
        """Chat call that must return JSON matching `schema` (strict structured outputs)."""
        resp = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}},
        )
        self._record(purpose or name, model, resp.usage)
        msg = resp.choices[0].message
        if getattr(msg, "refusal", None):
            raise RuntimeError(f"Model refused: {msg.refusal}")
        return json.loads(msg.content)
