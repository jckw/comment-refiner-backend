from litellm import completion
import chromadb
import os

chroma_client = chromadb.Client()


def tidy_text(env_var, text):
    return os.environ.get(env_var, " ".join(text.replace("\n", " ").split()))


INITIAL_PROMPT = tidy_text(
    "INTIAL_PROMPT",
    """A reader has read the following article, and will provide a comment """,
)

OPINION_ASSESSMENT_PROMPT = tidy_text(
    "OPINION_ASSESSMENT_PROMPT",
    """Do you believe that this represents a complete opinion, or is
    there more detail to be extracted? If there are similar opinions
    shared by other users, we need to tell the user about these
    comments and ask them to distinguish their own view from them. Are
    there any misunderstandings by the user?
    If there is more detail to be extracted or something to be probed,
    ask the question that will extract it in the style of a radio talk
    show host -- and keep the question succinct. If you think you have
    enough of a grasp of the user's view, reply DONE.""",
)

ARTICULATION_PROMPT = tidy_text(
    """ARTICULATION_PROMPT""",
    """"Now you must articulate the user's opinion so far, in the 1st person, in a
    conversational manner, in the present tense.""",
)

FINAL_AGREEMENT_PROMPT = tidy_text(
    "FINAL_AGREEMENT_PROMPT",
    """If the user agrees with the comment, reply DONE. Otherwise, ask the user to
    clarify or add more detail.""",
)


class ChatHandler:
    def __init__(self, article, comment_store):
        self.state = "AWAITING_USER_COMMENT"
        self.article = article
        self.latest_comment = None
        self.messages = [
            {
                "role": "system",
                "content": f"{INITIAL_PROMPT}\n\nArticle: {self.article}",
            }
        ]
        self.user_prompt = "Please provide a comment on the article."
        self.comment_store = comment_store

    def to_dict(self):
        return {
            "state": self.state,
            "article": self.article,
            "latest_comment": self.latest_comment,
            "messages": self.messages,
            "user_prompt": self.user_prompt,
            "comment_store_name": self.comment_store.name,
        }

    @classmethod
    def from_dict(cls, data):
        comment_store = chroma_client.get_collection(data["comment_store_name"])
        chat = cls(data["article"], comment_store)
        chat.state = data["state"]
        chat.latest_comment = data.get("latest_comment")
        chat.messages = data.get("messages", [])
        chat.user_prompt = data.get("user_prompt")
        return chat

    def add_message(self, role, content):
        self.messages.append({"role": role, "content": content})

    def assistant_reply(self):
        res = completion(model="gpt-4", messages=self.messages, stream=True)

        whole = ""
        for chunk in res:
            if chunk["choices"][0]["finish_reason"] is not None:
                break
            part = chunk["choices"][0]["delta"]["content"]
            whole += part
            yield part

        content = whole.strip()
        self.add_message("assistant", content)
        return content

    def on_input(self, user_input: str):
        if self.state == "AWAITING_USER_COMMENT":
            for x in self.handle_awaiting_user_comment(user_input):
                yield x
        elif self.state == "AWAITING_USER_REPLY":
            for x in self.handle_user_reply(user_input):
                yield x
        elif self.state == "AWAITING_USER_CONFIRMATION":
            for x in self.handle_awaiting_user_confirmation(user_input):
                yield x
        elif self.state == "COMPLETE":
            return self.latest_comment

    def process_latest_comment(self):
        self.add_message(
            "system",
            OPINION_ASSESSMENT_PROMPT,
        )

        buffer = ""
        sent_buffer = ""
        for reply_chunk in self.assistant_reply():
            buffer += reply_chunk

            # Until we know whether the reply is DONE or not, don't do anything
            if len(buffer) < len("DONE"):
                continue

            if buffer.startswith("DONE"):
                self.state = "AWAITING_USER_CONFIRMATION"
                self.user_prompt = f"It sounds like you're saying: {self.latest_comment}. Is that right or is there anything else to add?"
                self.add_message("assistant", self.user_prompt)
                yield self.user_prompt
                return

            self.user_prompt = buffer
            self.state = "AWAITING_USER_REPLY"
            if sent_buffer == "":
                sent_buffer = buffer
                yield buffer
            else:
                sent_buffer = buffer
                yield reply_chunk

    def handle_awaiting_user_comment(self, user_input: str):
        self.latest_comment = user_input
        self.add_message("user", self.latest_comment)

        for x in self.process_latest_comment():
            yield x

    def handle_user_reply(self, user_input: str):
        self.add_message("user", user_input)
        self.add_message("system", ARTICULATION_PROMPT)

        reply = ""
        for reply_chunk in self.assistant_reply():
            reply += reply_chunk

        self.add_message("assistant", "Okay, so what I'm hearing is: " + reply)

        # Search comments for similar ones
        similar_comments = self.comment_store.query(query_texts=[reply], n_results=2)
        relevant_comments = list(
            filter(
                lambda pair: pair[0] < 0.9,
                zip(similar_comments["distances"][0], similar_comments["documents"][0]),
            )
        )

        if len(relevant_comments) > 0:
            print(relevant_comments)
            self.add_message(
                "system",
                "Other users have said the following: "
                + "\n".join(pair[1] for pair in relevant_comments)
                + "\nThe user may want to clarify or add more detail. Assume they are unaware of the other comments",
            )

        self.latest_comment = reply

        for x in self.process_latest_comment():
            yield x

    def handle_awaiting_user_confirmation(self, user_input: str):
        self.add_message("user", user_input)
        self.add_message("system", FINAL_AGREEMENT_PROMPT)

        buffer = ""
        sent_buffer = ""
        for reply_chunk in self.assistant_reply():
            buffer += reply_chunk

            # Until we know whether the reply is DONE or not, don't do anything
            if len(buffer) < len("DONE"):
                continue

            if buffer.startswith("DONE"):
                self.state = "COMPLETE"
                yield self.latest_comment
                return

            self.user_prompt = buffer
            self.state = "AWAITING_USER_REPLY"
            if sent_buffer == "":
                sent_buffer = buffer
                yield buffer
            else:
                sent_buffer = buffer
                yield reply_chunk
