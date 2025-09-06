import aiosqlite

async def init_db():
    async with aiosqlite.connect("bot.db") as db:
        # users
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                referrer_id INTEGER,
                balance REAL DEFAULT 0,
                paid INTEGER DEFAULT 0
            )
        """)

        # payments (входящие оплаты)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT UNIQUE,
                user_id INTEGER,
                status TEXT
            )
        """)

        # withdrawals (заявки на вывод)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                network TEXT NOT NULL,
                address TEXT NOT NULL,
                memo TEXT,
                status TEXT DEFAULT 'pending', -- pending | approved | rejected
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # индексы
        await db.execute("CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_withdrawals_user_id ON withdrawals(user_id)")
        await db.commit()
