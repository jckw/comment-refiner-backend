from litellm import completion


class ChatHandler:
    def __init__(self, article):
        self.state = "AWAITING_USER_COMMENT"
        self.article = article
        self.latest_comment = None
        self.messages = [
            {
                "role": "system",
                "content": f"A reader has read the following article, and will provide a comment\n\nArticle: {self.article}",
            }
        ]
        self.user_prompt = "Please provide a comment on the article."

    def to_dict(self):
        return {
            "state": self.state,
            "article": self.article,
            "latest_comment": self.latest_comment,
            "messages": self.messages,
            "user_prompt": self.user_prompt,
        }

    @classmethod
    def from_dict(cls, data):
        chat = cls(data["article"])
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
        self.add_message("user", self.latest_comment)

        self.add_message(
            "system",
            "Do you believe that this represents a complete opinion, or is there more detail to be extracted? Are there any misunderstandings by the user? If there is more detail to be extracted or something to be probed, ask the question that will extract it in the style of a radio talk show host -- and keep the question succinct. If not, reply DONE.",
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

        for x in self.process_latest_comment():
            yield x

    def handle_user_reply(self, user_input: str):
        self.add_message("user", user_input)
        self.add_message(
            "system",
            "Now you must articulate the user's opinion so far, in the 1st person, in a conversational manner.",
        )

        reply = ""
        for reply_chunk in self.assistant_reply():
            reply += reply_chunk

        self.add_message(
            "assistant", "I have interpreted the user's opinion so far to be: " + reply
        )

        self.latest_comment = reply

        for x in self.process_latest_comment():
            yield x

    def handle_awaiting_user_confirmation(self, user_input: str):
        self.add_message("user", user_input)
        self.add_message(
            "system",
            "If the user agrees with the comment, reply DONE. Otherwise, ask the user to clarify or add more detail.",
        )

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


