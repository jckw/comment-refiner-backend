from flask import Flask, request, jsonify
import redis
import uuid
import pickle
import os

from chat_handler import ChatHandler

app = Flask(__name__)
redis_db = redis.from_url(
    os.environ.get("REDIS_URL", "redis://localhost:6379"),
)


def save_to_redis(key, obj):
    serialized_obj = pickle.dumps(obj.to_dict())
    redis_db.set(key, serialized_obj)


def load_from_redis(key):
    serialized_obj = redis_db.get(key)
    if serialized_obj:
        data = pickle.loads(serialized_obj)
        return ChatHandler.from_dict(data)
    return None


@app.route("/refine", methods=["POST"])
def chat():
    """
    Expects a JSON object:
        {
            "article": "The article to be refined.",
            "user_input": "The user input."
        }

    or:
        {
            "chat_id": "The chat ID.",
            "user_input": "The user input."
        }

    Returns a JSON object:
        {
            "chat_id": "The chat ID.",
            "state": "The state of the chat.",
            "latest_comment": "The latest comment.",
            "user_prompt": "The user prompt."
        }
    """
    chat_id = request.json.get("chat_id")

    if chat_id:
        # If chat_id is provided, try to fetch the existing chat from Redis
        chat = load_from_redis(chat_id)
        if not chat:
            return jsonify({"error": "Chat session not found."}), 404
    else:
        # If no chat_id is provided, initialize a new chat
        chat_id = str(uuid.uuid4())
        chat = ChatHandler(request.json["article"])

    user_input = request.json.get("user_input")
    if not user_input:
        return jsonify({"error": "User input is missing."}), 400

    chat.on_input(user_input)
    save_to_redis(chat_id, chat)
    return jsonify(
        {
            "chat_id": chat_id,
            "state": chat.state,
            "latest_comment": chat.latest_comment,
            "user_prompt": chat.user_prompt,
        }
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
