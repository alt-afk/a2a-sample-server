"""Print the Gemini models the key in .env can call, so CLIENT_MODEL and SERVER_MODEL can be set to one that exists.

    python list_models.py
"""

from __future__ import annotations

import config

config.use_key("server")

from google import genai  # noqa: E402

for model in genai.Client().models.list():
    actions = getattr(model, "supported_actions", None) or []
    if "generateContent" in actions or not actions:
        print(model.name.removeprefix("models/"))
