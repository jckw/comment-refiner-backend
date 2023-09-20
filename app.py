from flask import Flask, request, jsonify, stream_with_context
import redis
import uuid
import pickle
import os
from flask_cors import CORS
from dotenv import load_dotenv
from chat_handler import ChatHandler
import chromadb

load_dotenv()

chroma_client = chromadb.Client()

STORIES = [
    {
        "id": "8356597a-f695-4e37-8717-98389c542828",
        "topic": "Google",
        "title": "Google's Bard AI chatbot will expand integrations",
        "summary": "- Google's Bard AI chatbot can now work with Gmail, Docs, and Drive. It can extract and organize helpful information when asked.\n- Some people are worried about privacy with this new feature. However, Google promises that personal data will not be used to train Bard's public model or be seen by human reviewers.\n- Bard's extensions also link with Maps, YouTube, and Google Flights. This allows it to provide real-time flight information, local attractions, and relevant videos.\n- Google plans to expand Bard's capabilities to more products, both within and outside of Google. The goal is to integrate personal data in a secure and reliable way.",
        "comments": [],
    },
    {
        "id": "ee17953e-0ed8-4678-b3cc-d059072ef873",
        "topic": "X",
        "title": "Elon Musk proposes monthly fee to combat bot problem on X",
        "summary": "- Elon Musk, the owner of X (formerly Twitter), has suggested implementing a small monthly fee for users to address the proliferation of bots on the social media platform.\n- Currently, the X platform only offers one subscription called Premium, which provides additional features and can cost up to $115 per year.\n- Musk's idea to charge all users could potentially lead to a decrease in the number of users and advertising revenue, which currently makes up the majority of X's income.\n- Musk made these comments during a livestreamed conversation with Israeli Prime Minister Benjamin Netanyahu, where they discussed the challenges of managing free speech and hate speech on the platform.",
        "comments": [],
    },
    {
        "id": "40f2ca1f-194d-4303-8020-6d48de6ada02",
        "topic": "AI",
        "title": "Is your CEO a robot yet?",
        "summary": "- Dictador, a Polish drinks company, has an AI-powered humanoid robot named Mika serving as its CEO. Mika's responsibilities include identifying potential clients and choosing bottle designers.\n- Mika works continuously and makes decisions based on thorough data analysis, without any personal bias.\n- Marek Szoldrowski, the European president of Dictador, explains that while Mika handles various tasks, important decisions are still made by human executives.\n- In addition to its CEO role, Mika also leads Dictador's Arthouse Spirits project, which is a decentralized autonomous organization. Mika communicates with the community involved in this project.",
        "comments": [
            {
                "id": "1",
                "text": "Beyond my initial skepticism, I don't think a robot like this can possess the full range of abilities needed to run a company effectively. One paramount quality is empathy, which isn't something I believe a robot could truly emulate. ",
            }
        ],
    },
    {
        "id": "f44a796b-b343-4bc2-ada4-7d33867464bb",
        "topic": "AI Regulation",
        "title": "Tech leaders and Senate unite to tackle AI regulation",
        "summary": "- U.S. Senate and prominent tech executives, such as Elon Musk and Mark Zuckerberg, held a private meeting to discuss the possibility of government regulation of AI.\n- The purpose of the meeting was to foster cooperation between tech giants and Congress in order to pass AI legislation that both parties can agree on within the next year.\n- Although there is a general agreement on the necessity of regulation, the specific limitations and strategies are still unclear due to the intricate nature of AI technology.\n- Apart from the federal initiatives, California state Senator Scott Wiener introduced a bill that suggests transparency obligations for 'frontier' AI systems.",
        "comments": [],
    },
]


def prep_comment_stores():
    for story in STORIES:
        collection = chroma_client.create_collection(story["id"])
        if story["comments"]:
            collection.add(
                documents=[c["text"] for c in story["comments"]],
                ids=[c["id"] for c in story["comments"]],
            )

prep_comment_stores()

app = Flask(__name__)
CORS(app, origins=["http://localhost:3000", "https://comment-refiner.vercel.app"])

redis_db = redis.from_url(
    os.environ.get("REDIS_URL", "redis://localhost:6379"),
)


def save_chat_to_redis(chat_id, obj):
    serialized_obj = pickle.dumps(obj.to_dict())
    redis_db.set(f"chat:{chat_id}", serialized_obj)


def load_chat_from_redis(chat_id):
    serialized_obj = redis_db.get(f"chat:{chat_id}")
    if serialized_obj:
        data = pickle.loads(serialized_obj)
        return ChatHandler.from_dict(data)
    return None


@app.route("/refine", methods=["POST"])
def chat():
    chat_id = request.json.get("chat_id")
    story_id = request.json.get("story_id")

    if chat_id:
        # If chat_id is provided, try to fetch the existing chat from Redis
        chat = load_chat_from_redis(chat_id)
        if not chat:
            return jsonify({"error": "Chat session not found."}), 404
    else:
        # If no chat_id is provided, initialize a new chat on the given story
        chat_id = str(uuid.uuid4())
        chat = ChatHandler(
            article=[s for s in STORIES if s["id"] == story_id][0]["summary"]
        )

    user_input = request.json.get("user_input")
    if not user_input:
        return jsonify({"error": "User input is missing."}), 400

    def generate():
        for chunk in chat.on_input(user_input):
            save_chat_to_redis(chat_id, chat)
            yield '{"chat_id": "%s", "delta": "%s", "state": "%s"}' % (
                chat_id,
                chunk,
                chat.state,
            )

    return app.response_class(
        stream_with_context(generate()), mimetype="application/json"
    )


@app.route("/news/stories", methods=["GET"])
def get_stories():
    return jsonify(STORIES)


if __name__ == "__main__":
    app.run(debug=True, port=8000)
