import os
import base64
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify
from openai import OpenAI
import anthropic

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # reject uploads over 5 MB

# Each provider: where its key lives in .env, a default model, and how to talk to it.
# Default model names change over time, so users can override them in the form.
PROVIDERS = {
    "openai": {
        "env": "OPENAI_API_KEY",
        "model": "gpt-4o-mini",
        "base_url": None,
        "kind": "openai",
    },
    "anthropic": {
        "env": "ANTHROPIC_API_KEY",
        "model": "claude-haiku-5-5",
        "base_url": None,
        "kind": "anthropic",
    },
    "gemini": {
        "env": "GEMINI_API_KEY",
        "model": "gemini-2.5-flash",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "kind": "openai",
    },
    "custom": {
        "env": "OPENAI_API_KEY",
        "model": "gpt-4o-mini",
        "base_url": None,  # comes from the form or OPENAI_API_BASE
        "kind": "openai",
    },
}

SYSTEM_PROMPT = """You are an elite real estate copywriter.
Write a compelling listing description based on the property details provided.
Rules:
- Keep it under 200 words.
- Open with an emotional hook.
- Use ONLY the facts provided. Do not mention the neighborhood, schools, or amenities unless they are in the input.
- Mention every feature provided, and if an unfinished space is listed, describe it as "potential" or "a blank canvas". If none is listed, do not mention one.
- If a photo is attached, work in 2 or 3 details that are clearly visible in it, such as exterior material, landscaping, windows, or setting. Do not describe anything you cannot clearly see.
- No adjectives about the neighborhood unless they are in the input.
- End with a short call to action."""


def call_openai_style(api_key, base_url, model, text, image):
    """Works for OpenAI, Gemini, and any OpenAI-compatible service."""
    client = OpenAI(api_key=api_key, base_url=base_url)
    content = [{"type": "text", "text": text}]
    if image:
        mime, encoded = image
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{encoded}"},
        })
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
    )
    return response.choices[0].message.content


def call_anthropic(api_key, model, text, image):
    """Claude uses its own library and message format."""
    client = anthropic.Anthropic(api_key=api_key)
    content = []
    if image:
        mime, encoded = image
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": mime, "data": encoded},
        })
    content.append({"type": "text", "text": text})
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )
    return response.content[0].text


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    data = request.form
    photo = request.files.get("photo")

    # 1. Work out which provider, key, model and base URL to use
    provider = data.get("provider", "openai")
    config = PROVIDERS.get(provider)
    if not config:
        return jsonify({"error": "Unknown provider."}), 400

    api_key = data.get("api_key", "").strip() or os.getenv(config["env"])
    if not api_key:
        return jsonify({
            "error": "No API key. Paste one into the form, or add "
                     f"{config['env']} to your .env file."
        }), 400

    model = data.get("model", "").strip() or config["model"]

    base_url = config["base_url"]
    if provider == "custom":
        base_url = data.get("base_url", "").strip() or os.getenv("OPENAI_API_BASE")
        if not base_url:
            return jsonify({"error": "Custom provider needs a base URL."}), 400

    # 2. Build the text prompt
    text = (
        f"Location: {data.get('location', '')}\n"
        f"Bedrooms: {data.get('bedrooms', '')}\n"
        f"Bathrooms: {data.get('bathrooms', '')}\n"
        f"Style/tone: {data.get('style', '')}\n"
        f"Key features: {data.get('features', '')}"
    )

    # 3. Handle the optional photo
    image = None
    if photo and photo.filename:
        if not photo.mimetype.startswith("image/"):
            return jsonify({"error": "Please upload an image file."}), 400
        text += (
            "\n\nA photo of the property is attached. "
            "Mention 2 or 3 details clearly visible in it, "
            "such as the exterior material or landscaping."
        )
        image = (photo.mimetype, base64.b64encode(photo.read()).decode("utf-8"))

    # 4. Call the chosen provider
    try:
        if config["kind"] == "anthropic":
            listing = call_anthropic(api_key, model, text, image)
        else:
            listing = call_openai_style(api_key, base_url, model, text, image)
        return jsonify({"listing": listing})
    except Exception as e:
        print("Error:", e)
        return jsonify({"error": f"{type(e).__name__}: {str(e)[:300]}"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5001)