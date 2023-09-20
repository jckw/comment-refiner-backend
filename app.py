from flask import Flask, request, jsonify, stream_with_context
import redis
import uuid
import pickle
import os
from flask_cors import CORS
import requests
from dotenv import load_dotenv

load_dotenv()


from chat_handler import ChatHandler

app = Flask(__name__)
CORS(app, origins=["http://localhost:3000", "https://comment-refiner.vercel.app"])

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

    def generate():
        for chunk in chat.on_input(user_input):
            save_to_redis(chat_id, chat)
            yield '{"chat_id": "%s", "delta": "%s", "state": "%s"}' % (
                chat_id,
                chunk,
                chat.state
            )

    return app.response_class(stream_with_context(generate()), mimetype="application/json")


@app.route('/news/stories', methods=['GET'])
def get_stories():
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.environ.get('CRYPTO_BACKEND_TOKEN')}",
    }

    url = "https://crypto-backend.staging.delphia.com/news/stories"
    response = requests.get(url, headers=headers)
    stories = response.json()

    results = []
    # Only get the latest 4 stories
    for story in stories['results'][:4]:
        story_url = f"https://crypto-backend.staging.delphia.com/news/story/{story['id']}"
        story_detail = requests.get(story_url, headers=headers).json()
        results.append(story_detail)

    return jsonify(results)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
