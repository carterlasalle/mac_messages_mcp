import os

# Path to the AddressBook-v22.abcddb file
address_book_path = os.path.expanduser('~/Library/Application Support/AddressBook')

# Check if the AddressBook directory exists
address_book_exists = os.path.exists(address_book_path)
print(f"AddressBook directory exists: {address_book_exists}")

# Check if the AddressBook-v22.abcddb file exists
address_book_file_exists = os.path.exists(address_book_path + '/AddressBook-v22.abcddb')
print(f"AddressBook-v22.abcddb file exists: {address_book_file_exists}")

