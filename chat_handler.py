from litellm import completion

class ChatHandler:
    def __init__(self, article):
        self.state = "AWAITING_USER_COMMENT"
        self.article = article
        self.latest_comment = None
        self.messages = [
            {
                "role": "system",
                "content": f"A reader has read the following article, and will provide a comment\n\nArticle: {self.article}"
            }
        ]
        self.user_prompt = "Please provide a comment on the article."

    def to_dict(self):
        return {
            "state": self.state,
            "article": self.article,
            "latest_comment": self.latest_comment,
            "messages": self.messages,
            "user_prompt": self.user_prompt
        }

    @classmethod
    def from_dict(cls, data):
        chat = cls(data['article'])
        chat.state = data['state']
        chat.latest_comment = data.get('latest_comment')
        chat.messages = data.get('messages', [])
        chat.user_prompt = data.get('user_prompt')
        return chat

    def add_message(self, role, content):
        self.messages.append({
            "role": role,
            "content": content
        })

    def assistant_reply(self):
        res = completion(
            model="gpt-4",
            messages=self.messages
        )
        content = res.choices[0].message.content.strip()
        self.add_message("assistant", content)
        return content

    def on_input(self, user_input: str):
        if self.state == "AWAITING_USER_COMMENT":
            self.handle_awaiting_user_comment(user_input)
        elif self.state == "AWAITING_USER_REPLY":
            self.handle_user_reply(user_input)
        elif self.state == "AWAITING_USER_CONFIRMATION":
            self.handle_awaiting_user_confirmation(user_input)
        elif self.state == "DONE":
            self.handle_done(user_input)

    def process_latest_comment(self):
        self.add_message("user", self.latest_comment)

        self.add_message("system", "Do you believe that this represents a complete opinion, or is there more detail to be extracted? Are there any misunderstandings by the user? If there is more detail to be extracted or something to be probed, ask the question that will extract it in the style of a radio talk show host -- and keep the question succinct. If not, reply DONE.")
        reply = self.assistant_reply()

        if reply == "DONE":
            self.user_prompt = f"It sounds like you're saying: {self.latest_comment}. Is that right or is there anything else to add?"
            self.add_message("assistant", self.user_prompt)
            self.state = "AWAITING_USER_CONFIRMATION"
            return

        self.user_prompt = reply
        self.state = "AWAITING_USER_REPLY"

    def handle_awaiting_user_comment(self, user_input: str):
        self.latest_comment = user_input

        self.process_latest_comment()

    def handle_user_reply(self, user_input: str):
        self.add_message("user", user_input)
        self.add_message("system", "Now you must articulate the user's opinion so far, in the 1st person, in a conversational manner.")
        reply = self.assistant_reply()
        self.add_message("assistant", f"I have interpreted the user's opinion so far to be: {reply}")

        self.latest_comment = reply

        self.process_latest_comment()

    def handle_awaiting_user_confirmation(self, user_input: str):
        self.add_message("user", user_input)
        self.add_message("system", "If the user agrees with the comment, reply DONE. Otherwise, ask the user to clarify or add more detail.")
        reply = self.assistant_reply()

        if reply == "DONE":
            self.state = "COMPLETE"
            return

        self.user_prompt = reply
        self.state = "AWAITING_USER_REPLY"
