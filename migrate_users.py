"""Add users table and user_id column to orders."""
import sqlite3
import time

conn = sqlite3.connect("orders.db")

conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        apple_user_id TEXT UNIQUE NOT NULL,
        name TEXT DEFAULT '',
        email TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        created_at INTEGER,
        updated_at INTEGER
    )
""")

# Add user_id column to orders (nullable — old orders have no user)
try:
    conn.execute("ALTER TABLE orders ADD COLUMN user_id TEXT")
    print("Added user_id column to orders")
except sqlite3.OperationalError:
    print("user_id column already exists on orders")

# Add index on apple_user_id
conn.execute("CREATE INDEX IF NOT EXISTS idx_users_apple_id ON users(apple_user_id)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id)")

conn.commit()
conn.close()
print("Done — users table created + indexes added")