import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect('database.db')
c = conn.cursor()

# 🔥 Your data (item_name, total_issue)
data = [
("Long Soya Alkyd 3065-60%", 1150),
("BPCL Mineral Turpentine Oil (TG I GRADE)", 1910),
("CALCITE A", 807),
("Ultra Sheen 1.5 T", 1381),
("TALC ST 500", 5532),
("Marble Powder", 8448),
("DROKYD 6194", 4380),
("Silica Sand", 0),
("DOLOMITE - 300", 417),
("SLOP OIL", 5809),
("STEARIC ACID", 0),
("MIXED XYLENE", 3066),
("Emdicryl 269", 0),
("Quartz 16/32", 0),
("Limestone powder", 4080),
("Bondex P700", 2929),
("Calcigloss IP", 197),
("ROPAQUE ULTRA SD", 726),
("Acronal 7225", 1587),
("LC80 Pigment", 189)
]

# 🔥 Distribute over last 15 days
days = 15

for item, total_issue in data:

    if total_issue == 0:
        continue

    daily = int(total_issue / days)

    for i in range(days):
        date = datetime.now() - timedelta(days=i)

        c.execute("""
        INSERT INTO transactions (item_name, action, quantity, user, timestamp)
        VALUES (?, ?, ?, ?, ?)
        """, (item, "ISSUED", daily, "system", date))

conn.commit()
conn.close()

print("✅ Issue transactions added!")