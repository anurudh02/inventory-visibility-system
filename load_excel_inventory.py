import sqlite3

# ======================================
# CONNECT DATABASE
# ======================================

conn = sqlite3.connect('database.db')

cursor = conn.cursor()

# ======================================
# RESET TABLE
# ======================================

cursor.execute(
    "DROP TABLE IF EXISTS inventory"
)

# ======================================
# CREATE TABLE
# ======================================

cursor.execute("""

CREATE TABLE inventory (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    item_name TEXT,

    unit_cost REAL,

    quantity REAL,

    quantity_taken REAL,

    quantity_received REAL,

    lead_time INTEGER,

    safety_stock REAL

)

""")

# ======================================
# INVENTORY DATASET
#
# TARGET:
#
# SAFE       = 18
# OVERSTOCK  = 5
# WARNING    = 4
# CRITICAL   = 2
#
# ======================================

inventory_data = [

# ======================================
# SAFE ITEMS (18)
# ======================================

("DROKYD 6194",148.53,15040,4380,8000,12,730),

("MIXED XYLENE",110.89,12349,3066,4200,10,511),

("SLOP OIL",114.55,13797,5809,6500,12,968),

("Long Soya Alkyd 3065-60%",128.54,28760,1150,3500,8,192),

("STEARIC ACID",134.23,13000,2200,7000,8,367),

("TRONOX TIONA 828",278.76,6200,4200,5000,12,700),

("Marble Powder",9,18975,8448,9500,12,1408),

("Bondex P700",110.79,8193,2929,2500,8,488),

("LC80 Pigment",128.3,6065,189,5000,5,32),

("AQACELL HIDE 6299",87.48,5574,833,1800,5,139),

("PEARLGLAN",70.66,5464,457,900,5,76),

("ACRONAL 295 D",109.04,6280,2100,8225,8,315),

("Emdicryl 267S",114.95,3561,1092,1400,8,182),

("Ultra Sheen 1.5 T",21,23165,1381,21000,8,230),

("ROPAQUE ULTRA SD",99.17,7067,726,1500,5,121),

("Calcigloss IP",52.45,7636,197,5000,5,33),

("Emdicryl 269",126.35,10335,142,9600,5,24),

("Limestone Powder 1240",13.24,9509,4080,3000,10,680),

# ======================================
# OVERSTOCK ITEMS (5)
#
# High stock + low usage
# ======================================

("CALCITE A",10.45,26093,807,0,5,135),

("BPCL Mineral Turpentine Oil",98.75,28482,1910,0,8,318),

("Silica Sand",8,14540,320,0,5,53),

("DOLOMITE - 300",3.7,13962,417,0,5,70),

("Quartz 16/32",8,9733,210,0,5,35),

# ======================================
# WARNING ITEMS (4)
#
# Moderate stock + higher usage
# ======================================

("TALC ST 500",19.8,3900,5532,2000,12,922),

("T-800 RFILL GRADE",8.75,1450,575,1400,5,96),

("ACRYSOL DR 110",131.6,1200,142,3035,5,24),

("SAND 25/52",6.08,900,450,0,5,75),

# ======================================
# CRITICAL ITEMS (2)
#
# Low stock + high issue
# ======================================

("VISICRYL 7650",83.53,420,1400,300,5,120),

("ACRONAL 7225",121,850,1587,0,8,264)

]

# ======================================
# INSERT DATA
# ======================================

cursor.executemany("""

INSERT INTO inventory (

    item_name,

    unit_cost,

    quantity,

    quantity_taken,

    quantity_received,

    lead_time,

    safety_stock

)

VALUES (?, ?, ?, ?, ?, ?, ?)

""", inventory_data)

# ======================================
# SAVE DATABASE
# ======================================

conn.commit()

conn.close()

print(
    "Realistic balanced inventory database created successfully."
)