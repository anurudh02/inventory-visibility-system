import sqlite3
import pandas as pd

# ======================================
# CONNECT DATABASE
# ======================================

conn = sqlite3.connect(
    'database.db'
)

# ======================================
# LOAD TABLE
# ======================================

df = pd.read_sql_query(

    "SELECT * FROM inventory",

    conn

)

# ======================================
# DISPLAY HEADERS + DATA
# ======================================

print("\n INVENTORY DATABASE \n")

print(df)

# ======================================
# COLUMN HEADERS
# ======================================

print("\n COLUMN HEADERS \n")

print(df.columns)

conn.close()
