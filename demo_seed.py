import os
import sqlite3
import time

def main():
    DB_PATH = "intent_store.db"
    if not os.path.exists(DB_PATH):
        print("Database not found. Please run 'python3 cli.py scan demo/' first.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    now = time.time()
    
    # 1 day = 86400 seconds
    
    overrides = {
        "invoice_2024.txt": {"atime": now - 200*86400, "mtime": now - 500*86400},
        "invoice_2025.txt": {"atime": now - 30*86400,  "mtime": now - 30*86400},
        "debug_crawler_2022.log": {"atime": now - 1500*86400, "mtime": now - 1600*86400},
        "project_alpha_notes_2021.md": {"atime": now - 900*86400, "mtime": now - 1000*86400},
        "tax_return_2025.txt": {"atime": now - 320*86400, "mtime": now - 320*86400},
        "tax_return_2024.txt": {"atime": now - 720*86400, "mtime": now - 720*86400},
        "random_meeting_notes_2020.txt": {"atime": now - 1800*86400, "mtime": now - 2000*86400},
    }

    count = 0
    for fname, times in overrides.items():
        # Find path
        row = conn.execute("SELECT path FROM files WHERE path LIKE ?", (f"%{fname}",)).fetchone()
        if row:
            path = row["path"]
            conn.execute("UPDATE files SET atime = ?, mtime = ? WHERE path = ?", (times["atime"], times["mtime"], path))
            
            d_atime = (now - times['atime']) / 86400
            d_mtime = (now - times['mtime']) / 86400
            print(f"  set atime={d_atime:.0f}d ago  mtime={d_mtime:.0f}d ago  → {fname}")
            count += 1
            
    conn.commit()
    conn.close()
    print(f"\nSeeded {count} file(s).")

if __name__ == "__main__":
    main()
