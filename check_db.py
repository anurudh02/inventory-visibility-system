import sqlite3

conn = sqlite3.connect('database.db')
c = conn.cursor()

c.execute("SELECT * FROM inventory")
rows = c.fetchall()

for r in rows:
    print(r)

conn.close()