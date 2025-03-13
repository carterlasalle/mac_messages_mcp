import sqlite3
import datetime
import subprocess
import os

def get_chat_mapping(db_location):
    conn = sqlite3.connect(db_location)
    cursor = conn.cursor()

    cursor.execute("SELECT room_name, display_name FROM chat")
    result_set = cursor.fetchall()

    mapping = {room_name: display_name for room_name, display_name in result_set}

    conn.close()

    return mapping
def read_messages(db_location, n=10, self_number='Me', human_readable_date=True):
    conn = sqlite3.connect(db_location)
    cursor = conn.cursor()

    query = """
    SELECT message.ROWID, message.date, message.text, message.attributedBody, handle.id, message.is_from_me, message.cache_roomnames
    FROM message
    LEFT JOIN handle ON message.handle_id = handle.ROWID
    """

    if n is not None:
        query += f" ORDER BY message.date DESC LIMIT {n}"

    results = cursor.execute(query).fetchall()
    messages = []

    for result in results:
        rowid, date, text, attributed_body, handle_id, is_from_me, cache_roomname = result

        if handle_id is None:
            phone_number = self_number
        else:
            phone_number = handle_id

        if text is not None:
            body = text
        elif attributed_body is None:
            continue
        else:
            attributed_body = attributed_body.decode('utf-8', errors='replace')

            if "NSNumber" in str(attributed_body):
                attributed_body = str(attributed_body).split("NSNumber")[0]
                if "NSString" in attributed_body:
                    attributed_body = str(attributed_body).split("NSString")[1]
                    if "NSDictionary" in attributed_body:
                        attributed_body = str(attributed_body).split("NSDictionary")[0]
                        attributed_body = attributed_body[6:-12]
                        body = attributed_body

        if human_readable_date:
            date_string = '2001-01-01'
            mod_date = datetime.datetime.strptime(date_string, '%Y-%m-%d')
            unix_timestamp = int(mod_date.timestamp())*1000000000
            new_date = int((date+unix_timestamp)/1000000000)
            date = datetime.datetime.fromtimestamp(new_date).strftime("%Y-%m-%d %H:%M:%S")

        mapping = get_chat_mapping(db_location)

        try:
            mapped_name = mapping[cache_roomname]
        except:
            mapped_name = None

        messages.append(
            {"rowid": rowid, "date": date, "body": body, "phone_number": phone_number, "is_from_me": is_from_me,
             "cache_roomname": cache_roomname, 'group_chat_name' : mapped_name})

    conn.close()
    return messages


def print_messages(messages):
    for message in messages:
        print(f"RowID: {message['rowid']}")
        print(f"Body: {message['body']}")
        print(f"Phone Number: {message['phone_number']}")
        print(f"Is From Me: {message['is_from_me']}")
        print(f"Cache Roomname: {message['cache_roomname']}")
        print(f"Group Chat Name: {message['group_chat_name']}")
        print(f"Date: {message['date']}")
        print("\n")


def send_message(message, phone_number, group_chat = False):
    # creating a file - note: text files end up being sent as normal text messages, so this is handy for
    # sending messages that osascript doesn't like due to strange formatting or characters
    file_path = os.path.abspath('imessage_tmp.txt')

    with open(file_path, 'w') as f:
        f.write(message)

    if not group_chat:
        command = f'tell application "Messages" to send (read (POSIX file "{file_path}") as «class utf8») to buddy "{phone_number}"'
    else:
        command = f'tell application "Messages" to send (read (POSIX file "{file_path}") as «class utf8») to chat "{phone_number}"'

    subprocess.run(['osascript', '-e', command])

    print(f"Sent message to {phone_number}: {message}")