import sqlite3

def print_schema():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
    for name, sql in c.fetchall():
        print(f"Table: {name}")
        print(sql)
        print("-" * 50)
    conn.close()

if __name__ == '__main__':
    print_schema()
