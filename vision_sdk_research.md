# Python vision SDK notes

Sources:
- Context7: /openai/openai-python
- OpenAI docs: images-vision
- GitHub: openai/openai-python/examples/image_stream.py
- GitHub: OthersideAI/self-operating-computer/operate/models/apis.py
- GitHub: vllm-project/vllm/examples/online_serving/openai_chat_completion_client_for_multimodal.py

Key findings:
- Preferred modern pattern: `client = OpenAI(base_url=..., api_key=...)` then `client.responses.create(...)`.
- Responses API uses `input=[{"role":"user","content":[{"type":"input_text"...},{"type":"input_image","image_url":...}]}]`.
- Legacy chat.completions uses `messages=[{"role":"user","content":[{"type":"text"...},{"type":"image_url","image_url":{"url":...}}]}]`.
- Base64 should be sent as a data URL: `data:image/png;base64,...` or `data:image/jpeg;base64,...`.
- For OpenAI-compatible backends, `base_url="http://host:port/v1"` is the key client override.
