from walkem import read_messages, print_messages, send_message

# Path to the chat.db file
chat_db = "/Users/rocket/Library/Messages/chat.db"
# Phone number or label for "you"
self_number = "Me"
# Number of messages to return
n = 10

# Read the messages
messages = read_messages(chat_db, n=n, self_number=self_number, human_readable_date=True)

# Print the messages
print_messages(messages)