import pandas as pd
import sqlite3

print("Starting export...")

conn = sqlite3.connect("database.db")

print("Database connected!")

inventory_df = pd.read_sql_query(
    "SELECT * FROM inventory",
    conn
)

print("Inventory loaded!")

inventory_df.to_excel(
    "inventory.xlsx",
    index=False
)

print("Inventory exported!")

transactions_df = pd.read_sql_query(
    "SELECT * FROM transactions",
    conn
)

transactions_df.to_excel(
    "transactions.xlsx",
    index=False
)

print("Transactions exported!")

requests_df = pd.read_sql_query(
    "SELECT * FROM requests",
    conn
)

requests_df.to_excel(
    "requests.xlsx",
    index=False
)

print("Requests exported!")

conn.close()

print("Excel files exported successfully!")