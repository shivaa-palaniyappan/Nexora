import sqlite3, os

db = './data/code_graph.db'

if not os.path.exists(db):
    print('DATABASE DOES NOT EXIST - never created')
else:
    conn = sqlite3.connect(db)
    total = conn.execute('SELECT COUNT(*) FROM symbols').fetchone()[0]
    files = conn.execute('SELECT COUNT(DISTINCT file) FROM symbols').fetchone()[0]
    tsx   = conn.execute("SELECT COUNT(*) FROM symbols WHERE file LIKE '%.tsx'").fetchone()[0]
    py    = conn.execute("SELECT COUNT(*) FROM symbols WHERE file LIKE '%.py'").fetchone()[0]
    sample = conn.execute("SELECT name, file, line_start FROM symbols WHERE file LIKE '%.tsx' LIMIT 10").fetchall()

    print(f'Total symbols : {total}')
    print(f'Unique files  : {files}')
    print(f'TSX symbols   : {tsx}')
    print(f'PY symbols    : {py}')
    print('Sample TSX:')
    for r in sample:
        print(f'  {r[0]:30} {r[1]} line {r[2]}')

    all_files = conn.execute("SELECT DISTINCT file FROM symbols LIMIT 30").fetchall()
    print('\nAll indexed files:')
    for r in all_files:
        print(f'  {r[0]}')
    conn.close()