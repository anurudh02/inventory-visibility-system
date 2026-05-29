import sqlite3

# connect to database
conn = sqlite3.connect('database.db')
c = conn.cursor()

# your data from excel
data = [
("Long Soya Alkyd 3065-60%", 28760, 1150, 0),
("BPCL Mineral Turpentine Oil (TG I GRADE)", 28482.6, 1910, 0),
("CALCITE A", 26093, 807, 0),
("Ultra Sheen 1.5 T", 23165.596, 1381, 21000),
("TALC ST 500", 19071.2, 5532, 0),
("Marble Powder", 18975.6, 8448, 9500),
("DROKYD 6194", 15040.15, 4380, 8000),
("Silica Sand", 14540, 0, 0),
("DOLOMITE - 300", 13962, 417, 0),
("SLOP OIL", 13797.85, 5809, 0),
("STEARIC ACID", 13000, 0, 7000),
("MIXED XYLENE", 12349.5, 3066, 0),
("Emdicryl 269", 10335, 0, 9600),
("Quartz 16/32", 9733.25, 0, 0),
("Limestone powder", 9509.5, 4080.5, 0),
("Bondex P700", 8193, 2929, 0),
("Calcigloss IP", 7636.5, 197, 5000),
("ROPAQUE ULTRA SD", 7067.768, 726, 0),
("Acronal 7225", 6638, 1587, 0),
("LC80 Pigment", 6065.5, 189, 5000)
]

# insert into database
for item in data:
    c.execute("""
    INSERT OR REPLACE INTO inventory
    (item_name, unit_cost, quantity, quantity_taken, quantity_received, lead_time, safety_stock)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (item[0], 0, item[1], item[2], item[3], 5, 1000))

conn.commit()
conn.close()

print("✅ Data inserted successfully!")