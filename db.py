import os
import aiosqlite

PATH = os.getenv("DB_PATH", "bot.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY,
    full_name TEXT,
    phone TEXT,
    username TEXT,
    group_id INTEGER,
    pending_group INTEGER,
    blocked INTEGER DEFAULT 0,
    created_at INTEGER,
    last_active INTEGER
);
CREATE TABLE IF NOT EXISTS admins(
    id INTEGER PRIMARY KEY,
    full_name TEXT
);
CREATE TABLE IF NOT EXISTS groups(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS videos(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT,
    title TEXT,
    subject TEXT,
    created_at INTEGER
);
CREATE TABLE IF NOT EXISTS group_videos(
    group_id INTEGER,
    video_id INTEGER,
    position INTEGER,
    PRIMARY KEY(group_id, video_id)
);
CREATE TABLE IF NOT EXISTS books(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT,
    title TEXT,
    file_id TEXT
);
CREATE TABLE IF NOT EXISTS tests(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    ctype TEXT,
    file_id TEXT,
    text TEXT
);
CREATE TABLE IF NOT EXISTS submissions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id INTEGER,
    user_id INTEGER,
    status TEXT,
    comment TEXT,
    reviewed_by INTEGER,
    created_at INTEGER
);
CREATE TABLE IF NOT EXISTS sub_files(
    sub_id INTEGER,
    file_id TEXT
);
CREATE TABLE IF NOT EXISTS test_questions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id INTEGER,
    position INTEGER,
    path TEXT,
    correct TEXT
);
CREATE TABLE IF NOT EXISTS attempts(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id INTEGER,
    user_id INTEGER,
    answers TEXT DEFAULT '{}',
    score INTEGER,
    total INTEGER,
    started_at INTEGER,
    finished_at INTEGER
);
CREATE TABLE IF NOT EXISTS ads(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    body TEXT,
    path TEXT,
    group_id INTEGER,
    created_at INTEGER
);
"""

# Eski bazalarga kerakli ustunlarni qo'shish
MIGRATIONS = [
    ("tests", "mode TEXT DEFAULT 'manual'"),
    ("tests", "opts TEXT DEFAULT 'ABCD'"),
    ("test_questions", "file_id TEXT"),
    ("test_questions", "text TEXT"),
]


async def init():
    async with aiosqlite.connect(PATH) as d:
        await d.executescript(SCHEMA)
        for table, col in MIGRATIONS:
            cur = await d.execute(f"PRAGMA table_info({table})")
            have = [row[1] for row in await cur.fetchall()]
            if col.split()[0] not in have:
                await d.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
        await d.commit()


async def fetch(sql, args=()):
    async with aiosqlite.connect(PATH) as d:
        d.row_factory = aiosqlite.Row
        cur = await d.execute(sql, args)
        return await cur.fetchall()


async def one(sql, args=()):
    rows = await fetch(sql, args)
    return rows[0] if rows else None


async def count(sql, args=()):
    row = await one(sql, args)
    return row[0] if row else 0


async def run(sql, args=()):
    async with aiosqlite.connect(PATH) as d:
        cur = await d.execute(sql, args)
        await d.commit()
        return cur.lastrowid
