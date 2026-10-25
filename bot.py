import asyncio
import html
import json
import logging
import os
import time

from dotenv import load_dotenv

load_dotenv()

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import BaseFilter, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    ErrorEvent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.media_group import MediaGroupBuilder
import db
import db

# ----------------------------------------------------------------- SOZLAMALAR
TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x]
VIDEO_GROUP_ID = int(os.getenv("VIDEO_GROUP_ID", "0") or 0)
ABOUT = os.getenv("ABOUT_TEXT", "Matematika o'quv markazi.\nAloqa va kanal ma'lumotlari tez orada.")
SUBJECTS = ["Algebra", "Geometriya", "Boshqa"]

if not TOKEN:
    raise SystemExit("BOT_TOKEN topilmadi. .env faylini to'ldiring.")

logging.basicConfig(level=logging.INFO)
bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
r = Router()
esc = html.escape

# --------------------------------------------------------------- TUGMA MATNLARI
B_TEST = "📝 Test ishlash"
B_VID = "🎬 Video darslar"
B_BOOK = "📚 Kerakli kitoblar"
B_ABOUT = "ℹ️ Biz haqimizda"
B_ADMIN = "🛠 Admin panel"
B_BACK = "⬅️ Asosiy menyu"
A_ADDST = "➕ O'quvchi qo'shish"
A_GROUPS = "👥 Guruhlar"
A_VATT = "🎞 Video biriktirish"
A_RES = "🧾 Test natijalari"
A_TADD = "➕ Test qo'shish"
A_TDEL = "🗑 Testni o'chirish"
A_BADD = "📖 Kitob qo'shish"
A_BC = "📢 Xabar yuborish"
A_STAT = "📊 Statistika"
A_ADMINS = "👮 Adminlar"


def rkb(rows):
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t) for t in row] for row in rows],
        resize_keyboard=True,
    )


def ikb(rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows]
    )


def main_kb(admin):
    rows = [[B_TEST, B_VID], [B_BOOK, B_ABOUT]]
    if admin:
        rows.append([B_ADMIN])
    return rkb(rows)


def admin_kb():
    return rkb([
        [A_ADDST, A_GROUPS],
        [A_VATT, A_RES],
        [A_TADD, A_TDEL],
        [A_BADD],
        [A_BC, A_STAT],
        [A_ADMINS, B_BACK],
    ])


# ------------------------------------------------------------------- YORDAMCHI
async def is_admin(uid):
    return await db.one("SELECT 1 FROM admins WHERE id=?", (uid,)) is not None


class IsAdmin(BaseFilter):
    async def __call__(self, event) -> bool:
        return event.from_user is not None and await is_admin(event.from_user.id)


async def menu_for(uid):
    return main_kb(await is_admin(uid))


async def safe_send(uid, text, markup=None):
    try:
        await bot.send_message(uid, text, reply_markup=markup)
        return True
    except TelegramForbiddenError:
        await db.run("UPDATE users SET blocked=1 WHERE id=?", (uid,))
    except Exception as e:
        logging.warning("send fail %s: %s", uid, e)
    return False


async def get_student(obj):
    """Ro'yxatdan o'tgan va guruhga qo'shilgan o'quvchini qaytaradi."""
    msg = obj if isinstance(obj, Message) else obj.message
    u = await db.one("SELECT * FROM users WHERE id=?", (obj.from_user.id,))
    if not u:
        await msg.answer("Avval /start bosib ro'yxatdan o'ting.")
        return None
    if not u["group_id"]:
        await msg.answer("⏳ Siz hali guruhga qo'shilmagansiz. Admin sizni guruhga qo'shishini kuting.")
        return None
    return u


async def send_content(chat_id, ctype, file_id, text, caption=None, markup=None):
    if ctype == "photo":
        await bot.send_photo(chat_id, file_id, caption=caption, reply_markup=markup)
    elif ctype == "document":
        await bot.send_document(chat_id, file_id, caption=caption, reply_markup=markup)
    else:
        body = f"<b>{esc(caption)}</b>\n\n{esc(text or '')}" if caption else esc(text or "")
        await bot.send_message(chat_id, body, reply_markup=markup)


# ---------------------------------------------------------------------- HOLATLAR
class Reg(StatesGroup):
    name = State()
    phone = State()


class GrpNew(StatesGroup):
    name = State()


class TestAdd(StatesGroup):
    title = State()
    mode = State()
    content = State()
    auto_question = State()
    auto_answer = State()


class BookAdd(StatesGroup):
    file = State()


class Submit(StatesGroup):
    photos = State()


class Review(StatesGroup):
    comment = State()


class Bc(StatesGroup):
    msg = State()


class AdmAdd(StatesGroup):
    name = State()
    uid = State()


# --------------------------------------------------------------- MIDDLEWARE
class Activity(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user:
            await db.run(
                "UPDATE users SET last_active=?, username=? WHERE id=?",
                (int(time.time()), user.username, user.id),
            )
        return await handler(event, data)


# ================================================================== RO'YXATDAN O'TISH
@r.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    u = await db.one("SELECT 1 FROM users WHERE id=?", (m.from_user.id,))
    if u or await is_admin(m.from_user.id):
        await m.answer("Asosiy menyu 👇", reply_markup=await menu_for(m.from_user.id))
        return
    await m.answer(
        "Assalomu alaykum! 👋\nMatematika o'quv botiga xush kelibsiz.\n\n"
        "Ism va familiyangizni yozing:",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(Reg.name)


# ---- menyu tugmalari (har qanday holatda ishlaydi)
@r.message(F.text == B_BACK)
async def back(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Asosiy menyu 👇", reply_markup=await menu_for(m.from_user.id))


@r.message(F.text == B_ABOUT)
async def about(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(ABOUT)


@r.message(F.text == B_ADMIN, IsAdmin())
async def admin_panel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("🛠 Admin panel", reply_markup=admin_kb())


@r.message(Reg.name, F.text)
async def reg_name(m: Message, state: FSMContext):
    name = m.text.strip()
    if len(name) < 3:
        return await m.answer("Iltimos, ism va familiyani to'liq yozing.")
    await state.update_data(name=name)
    await state.set_state(Reg.phone)
    await m.answer(
        "Telefon raqamingizni yuboring (pastdagi tugmani bosing):",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )


@r.message(Reg.phone, F.contact)
async def reg_phone(m: Message, state: FSMContext):
    if m.contact.user_id != m.from_user.id:
        return await m.answer("Iltimos, o'zingizning raqamingizni yuboring.")
    d = await state.get_data()
    now = int(time.time())
    await db.run(
        "INSERT OR REPLACE INTO users(id,full_name,phone,username,created_at,last_active) VALUES(?,?,?,?,?,?)",
        (m.from_user.id, d["name"], m.contact.phone_number, m.from_user.username, now, now),
    )
    await state.clear()
    await m.answer(
        "✅ Ro'yxatdan o'tdingiz!\nAdmin sizni guruhga qo'shgach, darslar ochiladi.",
        reply_markup=await menu_for(m.from_user.id),
    )
    await send_app_button(m)
    for a in await db.fetch("SELECT id FROM admins"):
        await safe_send(a["id"], f"🆕 Yangi foydalanuvchi: <b>{esc(d['name'])}</b>\nUni «O'quvchi qo'shish» orqali guruhga qo'shing.")


@r.message(Reg.phone)
async def reg_phone_bad(m: Message):
    await m.answer("Pastdagi «📱 Raqamni yuborish» tugmasini bosing.")


# ================================================================== O'QUVCHI: VIDEO
@r.message(F.text == B_VID)
async def vid_menu(m: Message, state: FSMContext):
    await state.clear()
    u = await get_student(m)
    if not u:
        return
    g = await db.one("SELECT name FROM groups WHERE id=?", (u["group_id"],))
    await m.answer(
        f"👥 Guruh: <b>{esc(g['name'])}</b>\nFanni tanlang:",
        reply_markup=ikb([[("📐 Algebra", "vs:Algebra"), ("📏 Geometriya", "vs:Geometriya")], [("📂 Boshqa", "vs:Boshqa")]]),
    )


@r.callback_query(F.data.startswith("vs:"))
async def vid_subject(c: CallbackQuery):
    u = await get_student(c)
    if not u:
        return await c.answer()
    subj = c.data.split(":", 1)[1]
    rows = await db.fetch(
        "SELECT v.id, v.title FROM videos v JOIN group_videos gv ON gv.video_id=v.id "
        "WHERE gv.group_id=? AND v.subject=? ORDER BY gv.position, v.id",
        (u["group_id"], subj),
    )
    if not rows:
        return await c.answer("Hozircha bu fandan darslar yo'q.", show_alert=True)
    kb = [[(f"{i}-dars: {row['title']}"[:60], f"vl:{row['id']}")] for i, row in enumerate(rows, 1)]
    await c.message.answer(f"<b>{subj}</b> — mavzular:", reply_markup=ikb(kb))
    await c.answer()


@r.callback_query(F.data.startswith("vl:"))
async def vid_play(c: CallbackQuery):
    u = await get_student(c)
    if not u:
        return await c.answer()
    vid = int(c.data.split(":")[1])
    v = await db.one(
        "SELECT v.* FROM videos v JOIN group_videos gv ON gv.video_id=v.id WHERE gv.group_id=? AND v.id=?",
        (u["group_id"], vid),
    )
    if not v:
        return await c.answer("Bu dars sizga ochiq emas.", show_alert=True)
    await bot.send_video(c.from_user.id, v["file_id"], caption=esc(v["title"]), protect_content=True)
    await c.answer()


# ================================================================== O'QUVCHI: KITOBLAR
@r.message(F.text == B_BOOK)
async def book_menu(m: Message, state: FSMContext):
    await state.clear()
    if not await get_student(m):
        return
    await m.answer("Fanni tanlang:", reply_markup=ikb([[("📐 Algebra", "bs:Algebra"), ("📏 Geometriya", "bs:Geometriya")]]))


@r.callback_query(F.data.startswith("bs:"))
async def book_list(c: CallbackQuery):
    subj = c.data.split(":", 1)[1]
    rows = await db.fetch("SELECT id,title FROM books WHERE subject=? ORDER BY id", (subj,))
    if not rows:
        return await c.answer("Hozircha kitob yo'q.", show_alert=True)
    await c.message.answer(
        f"<b>{subj}</b> kitoblari:", reply_markup=ikb([[(row["title"][:60], f"bg:{row['id']}")] for row in rows])
    )
    await c.answer()


@r.callback_query(F.data.startswith("bg:"))
async def book_get(c: CallbackQuery):
    b = await db.one("SELECT * FROM books WHERE id=?", (int(c.data.split(":")[1]),))
    if b:
        await bot.send_document(c.from_user.id, b["file_id"], caption=esc(b["title"]))
    await c.answer()


# ================================================================== O'QUVCHI: TEST
@r.message(F.text == B_TEST)
async def test_menu(m: Message, state: FSMContext):
    await state.clear()
    if not await get_student(m):
        return
    rows = await db.fetch("SELECT id,title,mode FROM tests ORDER BY id")
    if not rows:
        return await m.answer("Hozircha testlar yo'q.")
    kb = [
        [(f"{i}-test {'🤖' if row['mode'] == 'auto' else '✍️'}: {row['title']}"[:60], f"tp:{row['id']}")]
        for i, row in enumerate(rows, 1)
    ]
    await m.answer("Testni tanlang:", reply_markup=ikb(kb))


@r.callback_query(F.data.startswith("tp:"))
async def test_open(c: CallbackQuery):
    u = await get_student(c)
    if not u:
        return await c.answer()
    tid = int(c.data.split(":")[1])
    t = await db.one("SELECT * FROM tests WHERE id=?", (tid,))
    if not t:
        return await c.answer("Test topilmadi.", show_alert=True)
    if t["mode"] == "auto":
        total = await db.count("SELECT COUNT(*) FROM test_questions WHERE test_id=?", (tid,))
        if not total:
            return await c.answer("Bu testda savollar yo'q.", show_alert=True)
        active = await db.one(
            "SELECT id FROM attempts WHERE test_id=? AND user_id=? AND finished_at IS NULL ORDER BY id DESC LIMIT 1",
            (tid, u["id"]),
        )
        action = ("▶️ Davom ettirish", f"quiz:resume:{active['id']}") if active else ("🚀 Testni boshlash", f"quiz:start:{tid}")
        await c.message.answer(
            f"🤖 <b>{esc(t['title'])}</b>\nSavollar soni: {total}\n"
            "Javoblarni tanlab, savollar orasida oldinga-orqaga o'tishingiz mumkin.",
            reply_markup=ikb([[action]]),
        )
        return await c.answer()
    last = await db.one(
        "SELECT status FROM submissions WHERE test_id=? AND user_id=? ORDER BY id DESC LIMIT 1", (tid, u["id"])
    )
    status = {"approved": "✅ Tasdiqlangan", "pending": "⏳ Tekshirilmoqda", "rejected": "❌ Xato, qayta topshiring"}.get(
        last["status"] if last else "", "🆕 Hali topshirilmagan"
    )
    await send_content(
        c.from_user.id, t["ctype"], t["file_id"], t["text"], caption=t["title"],
        markup=ikb([[("✍️ Javob yuborish", f"tsub:{tid}")]]),
    )
    await c.message.answer(f"Holat: {status}")
    await c.answer()


def quiz_keyboard(attempt_id, index, total, answers):
    selected = answers.get(str(index))
    choices = [[(f"{'✅ ' if selected == letter else ''}{letter}", f"qa:{attempt_id}:{index}:{letter}") for letter in "ABCD"]]
    nav = []
    if index > 0:
        nav.append(("⬅️ Oldingi", f"q:{attempt_id}:{index - 1}"))
    if index + 1 < total:
        nav.append(("Keyingi ➡️", f"q:{attempt_id}:{index + 1}"))
    rows = choices + ([nav] if nav else []) + [[("📋 Javoblarni ko'rish", f"qr:{attempt_id}")]]
    return ikb(rows)


async def show_quiz_question(user_id, attempt_id, index, message=None, edit_existing=False):
    attempt = await db.one(
        "SELECT a.*,t.title FROM attempts a JOIN tests t ON t.id=a.test_id "
        "WHERE a.id=? AND a.user_id=? AND t.mode='auto'",
        (attempt_id, user_id),
    )
    if not attempt:
        if message:
            await message.answer("Test urinishini topib bo'lmadi.")
        return
    if attempt["finished_at"]:
        if message:
            await message.answer("Bu test yakunlangan.")
        return
    questions = await db.fetch(
        "SELECT id,position,file_id,text FROM test_questions WHERE test_id=? ORDER BY position,id",
        (attempt["test_id"],),
    )
    if index < 0 or index >= len(questions):
        if message:
            await message.answer("Savol topilmadi.")
        return
    question = questions[index]
    answers = json.loads(attempt["answers"] or "{}")
    caption = (
        f"<b>{esc(attempt['title'])}</b>\n"
        f"❓ {index + 1}/{len(questions)}-savol"
        + (f"\n\n{esc(question['text'])}" if question["text"] else "")
    )
    keyboard = quiz_keyboard(attempt_id, index, len(questions), answers)
    if not edit_existing:
        await message.answer_photo(question["file_id"], caption=caption, reply_markup=keyboard)
    else:
        await message.edit_media(
            media=InputMediaPhoto(media=question["file_id"], caption=caption),
            reply_markup=keyboard,
        )


@r.callback_query(F.data.startswith("quiz:start:"))
async def quiz_start(c: CallbackQuery):
    u = await get_student(c)
    if not u:
        return await c.answer()
    tid = int(c.data.split(":")[2])
    test = await db.one("SELECT id FROM tests WHERE id=? AND mode='auto'", (tid,))
    if not test:
        return await c.answer("Avtomatik test topilmadi.", show_alert=True)
    active = await db.one(
        "SELECT id FROM attempts WHERE test_id=? AND user_id=? AND finished_at IS NULL ORDER BY id DESC LIMIT 1",
        (tid, u["id"]),
    )
    attempt_id = active["id"] if active else await db.run(
        "INSERT INTO attempts(test_id,user_id,answers,started_at) VALUES(?,?,?,?)",
        (tid, u["id"], "{}", int(time.time())),
    )
    await c.answer()
    await show_quiz_question(c.from_user.id, attempt_id, 0, c.message)


@r.callback_query(F.data.startswith("quiz:resume:"))
async def quiz_resume(c: CallbackQuery):
    u = await get_student(c)
    if not u:
        return await c.answer()
    attempt_id = int(c.data.split(":")[2])
    attempt = await db.one(
        "SELECT id FROM attempts WHERE id=? AND user_id=? AND finished_at IS NULL",
        (attempt_id, u["id"]),
    )
    if not attempt:
        return await c.answer("Davom etadigan test topilmadi.", show_alert=True)
    await c.answer()
    await show_quiz_question(c.from_user.id, attempt_id, 0, c.message)


@r.callback_query(F.data.startswith("q:"))
async def quiz_navigate(c: CallbackQuery):
    _, attempt_id, index = c.data.split(":")
    await show_quiz_question(c.from_user.id, int(attempt_id), int(index), c.message, edit_existing=True)
    await c.answer()


@r.callback_query(F.data.startswith("qa:"))
async def quiz_answer(c: CallbackQuery):
    _, attempt_id, index, answer = c.data.split(":")
    attempt_id, index = int(attempt_id), int(index)
    if answer not in "ABCD" or len(answer) != 1:
        return await c.answer("Javob noto'g'ri.", show_alert=True)
    attempt = await db.one(
        "SELECT * FROM attempts WHERE id=? AND user_id=? AND finished_at IS NULL",
        (attempt_id, c.from_user.id),
    )
    if not attempt:
        return await c.answer("Test urinishini topib bo'lmadi.", show_alert=True)
    questions = await db.fetch(
        "SELECT id FROM test_questions WHERE test_id=? ORDER BY position,id", (attempt["test_id"],)
    )
    if index < 0 or index >= len(questions):
        return await c.answer("Savol topilmadi.", show_alert=True)
    answers = json.loads(attempt["answers"] or "{}")
    answers[str(index)] = answer
    await db.run("UPDATE attempts SET answers=? WHERE id=?", (json.dumps(answers), attempt_id))
    await c.message.edit_reply_markup(
        reply_markup=quiz_keyboard(attempt_id, index, len(questions), answers)
    )
    await c.answer(f"{index + 1}-savol: {answer} tanlandi")


@r.callback_query(F.data.startswith("qr:"))
async def quiz_review(c: CallbackQuery):
    u = await get_student(c)
    if not u:
        return await c.answer()
    attempt_id = int(c.data.split(":")[1])
    attempt = await db.one(
        "SELECT a.*,t.title FROM attempts a JOIN tests t ON t.id=a.test_id "
        "WHERE a.id=? AND a.user_id=? AND a.finished_at IS NULL",
        (attempt_id, u["id"]),
    )
    if not attempt:
        return await c.answer("Test urinishini topib bo'lmadi.", show_alert=True)
    questions = await db.fetch(
        "SELECT id FROM test_questions WHERE test_id=? ORDER BY position,id", (attempt["test_id"],)
    )
    answers = json.loads(attempt["answers"] or "{}")
    lines = [f"{i + 1}. {esc(answers.get(str(i), '—'))}" for i in range(len(questions))]
    buttons = [
        (f"{i + 1}{' ✅ ' + answers[str(i)] if str(i) in answers else ' ❔'}", f"qe:{attempt_id}:{i}")
        for i in range(len(questions))
    ]
    rows = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
    unanswered = len(questions) - len(answers)
    if not unanswered:
        rows.append([("✅ Testni tugatish", f"qf:{attempt_id}")])
    text = f"📋 <b>{esc(attempt['title'])} — javoblaringiz</b>\n\n" + "\n".join(lines)
    if unanswered:
        text += f"\n\n❗ {unanswered} ta savolga javob berilmagan. O'zgartirish uchun savol raqamini bosing."
    await c.message.answer(text, reply_markup=ikb(rows))
    await c.answer()


@r.callback_query(F.data.startswith("qe:"))
async def quiz_edit_answer(c: CallbackQuery):
    u = await get_student(c)
    if not u:
        return await c.answer()
    _, attempt_id, index = c.data.split(":")
    await c.answer()
    await show_quiz_question(c.from_user.id, int(attempt_id), int(index), c.message)


@r.callback_query(F.data.startswith("qf:"))
async def quiz_finish(c: CallbackQuery):
    u = await get_student(c)
    if not u:
        return await c.answer()
    attempt_id = int(c.data.split(":")[1])
    attempt = await db.one(
        "SELECT a.*,t.title FROM attempts a JOIN tests t ON t.id=a.test_id "
        "WHERE a.id=? AND a.user_id=? AND t.mode='auto'",
        (attempt_id, u["id"]),
    )
    if not attempt or attempt["finished_at"]:
        return await c.answer("Bu test allaqachon yakunlangan yoki topilmadi.", show_alert=True)
    questions = await db.fetch(
        "SELECT position,correct FROM test_questions WHERE test_id=? ORDER BY position,id",
        (attempt["test_id"],),
    )
    answers = json.loads(attempt["answers"] or "{}")
    if len(answers) != len(questions) or any(str(i) not in answers for i in range(len(questions))):
        return await c.answer("Avval barcha savollarga javob bering.", show_alert=True)
    score = sum(
        1 for i, question in enumerate(questions)
        if answers[str(i)].upper() == (question["correct"] or "").upper()
    )
    finished_at = int(time.time())
    await db.run(
        "UPDATE attempts SET score=?,total=?,finished_at=? WHERE id=? AND finished_at IS NULL",
        (score, len(questions), finished_at, attempt_id),
    )
    result = f"📊 «{esc(attempt['title'])}» testi natijasi: <b>{score}/{len(questions)}</b>"
    await c.message.answer(f"✅ Test yakunlandi!\n{result}")
    await c.answer()
    admin_text = (
        f"📊 <b>Avtomatik test yakunlandi</b>\n"
        f"👤 {esc(u['full_name'])}\n"
        f"📝 {esc(attempt['title'])}\n"
        f"Natija: <b>{score}/{len(questions)}</b>\n\n"
        + "\n".join(f"{i + 1}. {esc(answers[str(i)])}" for i in range(len(questions)))
    )
    for admin in await db.fetch("SELECT id FROM admins"):
        await safe_send(admin["id"], admin_text)


@r.callback_query(F.data.startswith("tsub:"))
async def test_submit_start(c: CallbackQuery, state: FSMContext):
    u = await get_student(c)
    if not u:
        return await c.answer()
    tid = int(c.data.split(":")[1])
    test = await db.one("SELECT mode FROM tests WHERE id=?", (tid,))
    if not test or test["mode"] != "manual":
        return await c.answer("Bu avtomatik test. Uni testlar ro'yxatidan boshlang.", show_alert=True)
    last = await db.one(
        "SELECT status FROM submissions WHERE test_id=? AND user_id=? ORDER BY id DESC LIMIT 1", (tid, u["id"])
    )
    if last and last["status"] == "approved":
        return await c.answer("Bu test allaqachon tasdiqlangan ✅", show_alert=True)
    if last and last["status"] == "pending":
        return await c.answer("Javobingiz tekshirilmoqda ⏳", show_alert=True)
    await state.set_state(Submit.photos)
    await state.update_data(tid=tid, photos=[])
    await c.message.answer(
        "📸 Yechilgan testni rasmga olib yuboring (bir nechta rasm mumkin, 10 tagacha).",
        reply_markup=ikb([[("❌ Bekor qilish", "tcancel")]]),
    )
    await c.answer()


@r.message(Submit.photos, F.photo)
async def submit_photo(m: Message, state: FSMContext):
    d = await state.get_data()
    photos = d.get("photos", [])
    if len(photos) >= 10:
        return await m.answer("Eng ko'pi bilan 10 ta rasm. «Yuborish» ni bosing.")
    photos.append(m.photo[-1].file_id)
    await state.update_data(photos=photos)
    await m.answer(
        f"📎 {len(photos)} ta rasm qabul qilindi.",
        reply_markup=ikb([[(f"✅ Yuborish ({len(photos)})", "tdone")], [("❌ Bekor qilish", "tcancel")]]),
    )


@r.message(Submit.photos)
async def submit_other(m: Message):
    await m.answer("Iltimos, faqat rasm yuboring.")


@r.callback_query(F.data == "tcancel")
async def submit_cancel(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.answer("Bekor qilindi.")
    await c.answer()


@r.callback_query(F.data == "tdone", Submit.photos)
async def submit_done(c: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    photos = d.get("photos", [])
    if not photos:
        return await c.answer("Avval rasm yuboring.", show_alert=True)
    u = await db.one("SELECT * FROM users WHERE id=?", (c.from_user.id,))
    t = await db.one("SELECT * FROM tests WHERE id=?", (d["tid"],))
    g = await db.one("SELECT name FROM groups WHERE id=?", (u["group_id"],))
    sid = await db.run(
        "INSERT INTO submissions(test_id,user_id,status,created_at) VALUES(?,?,?,?)",
        (d["tid"], u["id"], "pending", int(time.time())),
    )
    for f in photos:
        await db.run("INSERT INTO sub_files(sub_id,file_id) VALUES(?,?)", (sid, f))
    await state.clear()
    await c.message.answer("✅ Javobingiz adminlarga yuborildi. Natijani kuting.")
    await c.answer()

    info = (
        f"📥 <b>Yangi test topshirildi</b>\n👤 {esc(u['full_name'])}\n👥 {esc(g['name'])}\n"
        f"📝 {esc(t['title'])}\n📞 {esc(u['phone'] or '-')}"
    )
    for a in await db.fetch("SELECT id FROM admins"):
        try:
            if len(photos) == 1:
                await bot.send_photo(a["id"], photos[0], caption=info)
            else:
                mg = MediaGroupBuilder(caption=info)
                for f in photos:
                    mg.add_photo(f)
                await bot.send_media_group(a["id"], mg.build())
            await bot.send_message(
                a["id"], "Natijani belgilang:",
                reply_markup=ikb([[("✅ Tasdiqlash", f"sa:{sid}"), ("❌ Xato", f"sr:{sid}")]]),
            )
        except Exception as e:
            logging.warning("admin notify fail %s: %s", a["id"], e)


# ---- admin tekshiruvi
@r.callback_query(F.data.startswith("sa:"), IsAdmin())
async def sub_approve(c: CallbackQuery):
    sid = int(c.data.split(":")[1])
    s = await db.one("SELECT s.*, t.title FROM submissions s JOIN tests t ON t.id=s.test_id WHERE s.id=?", (sid,))
    if not s or s["status"] != "pending":
        return await c.answer("Bu javob allaqachon ko'rib chiqilgan.", show_alert=True)
    await db.run("UPDATE submissions SET status='approved', reviewed_by=? WHERE id=?", (c.from_user.id, sid))
    await c.message.edit_text("✅ Tasdiqlandi")
    await safe_send(s["user_id"], f"✅ «{esc(s['title'])}» testingiz tasdiqlandi. Barakalla! Keyingi darsga o'tishingiz mumkin.")
    await c.answer()


@r.callback_query(F.data.startswith("sr:"), IsAdmin())
async def sub_reject(c: CallbackQuery, state: FSMContext):
    sid = int(c.data.split(":")[1])
    s = await db.one("SELECT status FROM submissions WHERE id=?", (sid,))
    if not s or s["status"] != "pending":
        return await c.answer("Bu javob allaqachon ko'rib chiqilgan.", show_alert=True)
    await state.set_state(Review.comment)
    await state.update_data(sid=sid)
    await c.message.answer("✍️ Xato izohini yozing (nimalar noto'g'ri):")
    await c.answer()


@r.message(Review.comment, F.text)
async def sub_reject_comment(m: Message, state: FSMContext):
    d = await state.get_data()
    sid = d["sid"]
    s = await db.one("SELECT s.*, t.title FROM submissions s JOIN tests t ON t.id=s.test_id WHERE s.id=?", (sid,))
    await state.clear()
    if not s or s["status"] != "pending":
        return await m.answer("Bu javob allaqachon ko'rib chiqilgan.")
    await db.run(
        "UPDATE submissions SET status='rejected', comment=?, reviewed_by=? WHERE id=?",
        (m.text, m.from_user.id, sid),
    )
    await safe_send(
        s["user_id"],
        f"❌ «{esc(s['title'])}» testida xato bor:\n\n{esc(m.text)}\n\nQayta ishlab topshiring.",
        ikb([[("✍️ Qayta topshirish", f"tsub:{s['test_id']}")]]),
    )
    await m.answer("Xato izohi o'quvchiga yuborildi ✅")


# ================================================================== ADMIN: GURUHLAR
async def groups_text_kb():
    rows = await db.fetch(
        "SELECT g.id, g.name, (SELECT COUNT(*) FROM users u WHERE u.group_id=g.id) AS n FROM groups g ORDER BY g.id"
    )
    kb = [[(f"👁 {row['name']} ({row['n']})", f"g:view:{row['id']}")] for row in rows]
    kb.append([("➕ Yangi guruh", "g:new")])
    return ("👥 <b>Guruhlar</b>" if rows else "Hozircha guruhlar yo'q."), ikb(kb)


@r.message(F.text == A_GROUPS, IsAdmin())
async def groups_list(m: Message, state: FSMContext):
    await state.clear()
    text, kb = await groups_text_kb()
    await m.answer(text, reply_markup=kb)


@r.callback_query(F.data == "g:new", IsAdmin())
async def group_new(c: CallbackQuery, state: FSMContext):
    await state.set_state(GrpNew.name)
    await c.message.answer("Yangi guruh nomini yozing:")
    await c.answer()


@r.message(GrpNew.name, F.text)
async def group_new_name(m: Message, state: FSMContext):
    try:
        await db.run("INSERT INTO groups(name) VALUES(?)", (m.text.strip(),))
        await m.answer(f"✅ «{esc(m.text.strip())}» guruhi yaratildi.")
    except Exception:
        await m.answer("Bunday nomli guruh bor.")
    await state.clear()


async def group_view_render(gid):
    g = await db.one("SELECT name FROM groups WHERE id=?", (gid,))
    studs = await db.fetch("SELECT id, full_name FROM users WHERE group_id=? ORDER BY full_name", (gid,))
    text = f"👥 <b>{esc(g['name'])}</b> — {len(studs)} ta o'quvchi\n(🗑 bosilsa guruhdan chiqariladi)"
    kb = [[(f"🗑 {s['full_name']}"[:60], f"g:rm:{gid}:{s['id']}")] for s in studs]
    return text, ikb(kb) if kb else None


@r.callback_query(F.data.startswith("g:view:"), IsAdmin())
async def group_view(c: CallbackQuery):
    text, kb = await group_view_render(int(c.data.split(":")[2]))
    await c.message.answer(text, reply_markup=kb)
    await c.answer()


@r.callback_query(F.data.startswith("g:rm:"), IsAdmin())
async def group_remove(c: CallbackQuery):
    _, _, gid, uid = c.data.split(":")
    await db.run("UPDATE users SET group_id=NULL, pending_group=NULL WHERE id=?", (int(uid),))
    text, kb = await group_view_render(int(gid))
    await c.message.edit_text(text, reply_markup=kb)
    await c.answer("Chiqarildi")


# ================================================================== ADMIN: O'QUVCHI QO'SHISH
@r.message(F.text == A_ADDST, IsAdmin())
async def add_student(m: Message, state: FSMContext):
    await state.clear()
    rows = await db.fetch("SELECT id,name FROM groups ORDER BY id")
    if not rows:
        return await m.answer("Avval «👥 Guruhlar» bo'limida guruh yarating.")
    await m.answer("Qaysi guruhga qo'shamiz?", reply_markup=ikb([[(row["name"], f"as:g:{row['id']}")] for row in rows]))


@r.callback_query(F.data.startswith("as:g:"), IsAdmin())
async def add_student_pick(c: CallbackQuery):
    gid = int(c.data.split(":")[2])
    studs = await db.fetch(
        "SELECT id, full_name FROM users WHERE group_id IS NULL AND blocked=0 ORDER BY created_at DESC LIMIT 60"
    )
    if not studs:
        return await c.answer("Guruhsiz o'quvchi yo'q. O'quvchi avval botda /start bosishi kerak.", show_alert=True)
    await c.message.answer(
        "O'quvchini tanlang:",
        reply_markup=ikb([[(s["full_name"][:50], f"as:u:{gid}:{s['id']}")] for s in studs]),
    )
    await c.answer()


@r.callback_query(F.data.startswith("as:u:"), IsAdmin())
async def add_student_send(c: CallbackQuery):
    _, _, gid, uid = c.data.split(":")
    gid, uid = int(gid), int(uid)
    g = await db.one("SELECT name FROM groups WHERE id=?", (gid,))
    await db.run("UPDATE users SET pending_group=? WHERE id=?", (gid, uid))
    ok = await safe_send(
        uid,
        f"Admin sizni <b>{esc(g['name'])}</b> guruhiga qo'shmoqchi. Rozimisiz?",
        ikb([[("Roziman ✓", f"agree:{gid}"), ("Rad etish", "decline")]]),
    )
    await c.message.answer("📨 So'rov o'quvchiga yuborildi." if ok else "❌ O'quvchiga xabar yuborib bo'lmadi.")
    await c.answer()


@r.callback_query(F.data.startswith("agree:"))
async def student_agree(c: CallbackQuery):
    gid = int(c.data.split(":")[1])
    u = await db.one("SELECT pending_group FROM users WHERE id=?", (c.from_user.id,))
    if not u or u["pending_group"] != gid:
        return await c.answer("So'rov eskirgan.", show_alert=True)
    g = await db.one("SELECT name FROM groups WHERE id=?", (gid,))
    await db.run("UPDATE users SET group_id=?, pending_group=NULL WHERE id=?", (gid, c.from_user.id))
    await c.message.edit_text(f"✅ Siz <b>{esc(g['name'])}</b> guruhiga qo'shildingiz!")
    await c.message.answer("Darslarni boshlashingiz mumkin 👇", reply_markup=await menu_for(c.from_user.id))
    await c.answer()


@r.callback_query(F.data == "decline")
async def student_decline(c: CallbackQuery):
    await db.run("UPDATE users SET pending_group=NULL WHERE id=?", (c.from_user.id,))
    await c.message.edit_text("Rad etildi.")
    await c.answer()


# ================================================================== ADMIN: VIDEO KUTUBXONA
async def save_video(m: Message):
    cap = (m.caption or "").strip()
    subject, title = "Boshqa", cap or "Nomsiz video"
    if "|" in cap:
        a, b = [x.strip() for x in cap.split("|", 1)]
        for s in SUBJECTS:
            if a.lower().startswith(s.lower()[:3]):
                subject, title = s, b or s
                break
    await db.run(
        "INSERT INTO videos(file_id,title,subject,created_at) VALUES(?,?,?,?)",
        (m.video.file_id, title, subject, int(time.time())),
    )
    await m.reply(f"✅ Videolar bazasiga saqlandi: <b>{esc(subject)}</b> — {esc(title)}")


@r.message(F.video, F.chat.id == VIDEO_GROUP_ID)
async def video_from_group(m: Message):
    await save_video(m)


@r.message(F.video, F.chat.type == "private", IsAdmin())
async def video_from_admin(m: Message, state: FSMContext):
    if await state.get_state() is None:
        await save_video(m)


async def picker_kb(gid):
    vids = await db.fetch("SELECT id,title,subject FROM videos ORDER BY id DESC LIMIT 90")
    att = {x["video_id"] for x in await db.fetch("SELECT video_id FROM group_videos WHERE group_id=?", (gid,))}
    kb = []
    for v in vids:
        mark = "✅ " if v["id"] in att else "▫️ "
        kb.append([((mark + f"{v['subject']}: {v['title']}")[:58], f"va:t:{gid}:{v['id']}")])
    kb.append([("☑️ Hammasi", f"va:all:{gid}"), ("🏁 Tayyor", "va:done")])
    return ikb(kb)


@r.message(F.text == A_VATT, IsAdmin())
async def vid_attach(m: Message, state: FSMContext):
    await state.clear()
    if not await db.count("SELECT COUNT(*) FROM videos"):
        return await m.answer(
            "Videolar bazasi bo'sh. Videoni video-guruhga (yoki shu botga) caption bilan yuboring:\n"
            "<code>Algebra | 1-mavzu: Kvadrat tenglama</code>"
        )
    rows = await db.fetch("SELECT id,name FROM groups ORDER BY id")
    if not rows:
        return await m.answer("Avval guruh yarating.")
    await m.answer("Qaysi guruhga video biriktiramiz?", reply_markup=ikb([[(r_["name"], f"va:g:{r_['id']}")] for r_ in rows]))


@r.callback_query(F.data.startswith("va:g:"), IsAdmin())
async def vid_attach_group(c: CallbackQuery):
    gid = int(c.data.split(":")[2])
    await c.message.answer("Guruhga biriktiriladigan videolarni belgilang:", reply_markup=await picker_kb(gid))
    await c.answer()


@r.callback_query(F.data.startswith("va:t:"), IsAdmin())
async def vid_toggle(c: CallbackQuery):
    _, _, gid, vid = c.data.split(":")
    gid, vid = int(gid), int(vid)
    if await db.one("SELECT 1 FROM group_videos WHERE group_id=? AND video_id=?", (gid, vid)):
        await db.run("DELETE FROM group_videos WHERE group_id=? AND video_id=?", (gid, vid))
    else:
        await db.run(
            "INSERT INTO group_videos(group_id,video_id,position) VALUES(?,?,"
            "(SELECT COALESCE(MAX(position),0)+1 FROM group_videos WHERE group_id=?))",
            (gid, vid, gid),
        )
    await c.message.edit_reply_markup(reply_markup=await picker_kb(gid))
    await c.answer()


@r.callback_query(F.data.startswith("va:all:"), IsAdmin())
async def vid_all(c: CallbackQuery):
    gid = int(c.data.split(":")[2])
    for v in await db.fetch("SELECT id FROM videos ORDER BY id"):
        await db.run(
            "INSERT OR IGNORE INTO group_videos(group_id,video_id,position) VALUES(?,?,"
            "(SELECT COALESCE(MAX(position),0)+1 FROM group_videos WHERE group_id=?))",
            (gid, v["id"], gid),
        )
    await c.message.edit_reply_markup(reply_markup=await picker_kb(gid))
    await c.answer("Hammasi biriktirildi")


@r.callback_query(F.data == "va:done", IsAdmin())
async def vid_done(c: CallbackQuery):
    await c.message.edit_text("✅ Videolar biriktirildi.")
    await c.answer()


# ================================================================== ADMIN: TEST QO'SHISH
@r.message(F.text == A_TADD, IsAdmin())
async def test_add(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(TestAdd.title)
    await m.answer("Test nomini yozing (masalan: «Kvadrat tenglamalar»):")


@r.message(TestAdd.title, F.text)
async def test_add_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text.strip())
    await state.set_state(TestAdd.mode)
    await m.answer(
        "Test turini tanlang:",
        reply_markup=ikb([[("✍️ Qo'lda tekshirish", "tam:manual")], [("🤖 Avtomatik test", "tam:auto")]]),
    )


@r.callback_query(F.data.startswith("tam:"), IsAdmin(), TestAdd.mode)
async def test_add_mode(c: CallbackQuery, state: FSMContext):
    mode = c.data.split(":")[1]
    if mode == "manual":
        await state.set_state(TestAdd.content)
        await c.message.answer("Test materialini yuboring: matn, rasm yoki fayl (PDF).")
    elif mode == "auto":
        await state.update_data(questions=[])
        await state.set_state(TestAdd.auto_question)
        await c.message.answer("1-savol rasmini yuboring. Rasmga izoh (caption) qo'shishingiz mumkin.")
    else:
        return await c.answer("Test turi noto'g'ri.", show_alert=True)
    await c.answer()


@r.message(TestAdd.content)
async def test_add_content(m: Message, state: FSMContext):
    d = await state.get_data()
    if m.photo:
        ctype, fid, text = "photo", m.photo[-1].file_id, m.caption
    elif m.document:
        ctype, fid, text = "document", m.document.file_id, m.caption
    elif m.text:
        ctype, fid, text = "text", None, m.text
    else:
        return await m.answer("Matn, rasm yoki fayl yuboring.")
    await db.run(
        "INSERT INTO tests(title,ctype,file_id,text,mode) VALUES(?,?,?,?,?)",
        (d["title"], ctype, fid, text, "manual"),
    )
    await state.clear()
    await m.answer(f"✅ Test qo'shildi: {esc(d['title'])}")


@r.message(TestAdd.auto_question, F.photo)
async def test_add_auto_question(m: Message, state: FSMContext):
    d = await state.get_data()
    await state.update_data(pending_question={"file_id": m.photo[-1].file_id, "text": m.caption or ""})
    await state.set_state(TestAdd.auto_answer)
    await m.answer(
        f"{len(d.get('questions', [])) + 1}-savol uchun to'g'ri javobni kiriting (A, B, C yoki D):"
    )


@r.message(TestAdd.auto_question)
async def test_add_auto_question_invalid(m: Message):
    await m.answer("Savol uchun rasm yuboring.")


@r.message(TestAdd.auto_answer, F.text)
async def test_add_auto_answer(m: Message, state: FSMContext):
    correct = m.text.strip().upper()
    if correct not in {"A", "B", "C", "D"}:
        return await m.answer("To'g'ri javob faqat A, B, C yoki D bo'lishi mumkin.")
    d = await state.get_data()
    questions = d.get("questions", [])
    questions.append({**d["pending_question"], "correct": correct})
    await state.update_data(questions=questions, pending_question=None)
    await m.answer(
        f"✅ {len(questions)}-savol saqlandi. Yana rasm yuboring yoki testni tugating.",
        reply_markup=ikb([[("➕ Keyingi savol", "aq:add")], [("✅ Testni tugatish", "aq:finish")]]),
    )


@r.message(TestAdd.auto_answer)
async def test_add_auto_answer_invalid(m: Message):
    await m.answer("To'g'ri javobni A, B, C yoki D harfi bilan yuboring.")


@r.callback_query(F.data == "aq:add", IsAdmin(), TestAdd.auto_answer)
async def test_add_auto_next(c: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    await state.set_state(TestAdd.auto_question)
    await c.message.answer(f"{len(d.get('questions', [])) + 1}-savol rasmini yuboring.")
    await c.answer()


@r.callback_query(F.data == "aq:finish", IsAdmin(), TestAdd.auto_answer)
async def test_add_auto_finish(c: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    questions = d.get("questions", [])
    if not questions:
        return await c.answer("Avval kamida bitta savol qo'shing.", show_alert=True)
    tid = await db.run(
        "INSERT INTO tests(title,ctype,mode) VALUES(?,?,?)",
        (d["title"], "auto", "auto"),
    )
    for position, question in enumerate(questions, 1):
        await db.run(
            "INSERT INTO test_questions(test_id,position,file_id,text,correct) VALUES(?,?,?,?,?)",
            (tid, position, question["file_id"], question["text"], question["correct"]),
        )
    await state.clear()
    await c.message.answer(f"✅ Avtomatik test qo'shildi: {esc(d['title'])} ({len(questions)} ta savol)")
    await c.answer()


@r.message(F.text == A_TDEL, IsAdmin())
async def test_delete_menu(m: Message):
    rows = await db.fetch("SELECT id,title,mode FROM tests ORDER BY id")
    if not rows:
        return await m.answer("O'chiriladigan test yo'q.")
    await m.answer(
        "O'chirmoqchi bo'lgan testni tanlang:",
        reply_markup=ikb([
            [(f"{'🤖' if row['mode'] == 'auto' else '✍️'} {row['title']}"[:60], f"tdel:ask:{row['id']}")]
            for row in rows
        ]),
    )


@r.callback_query(F.data.startswith("tdel:ask:"), IsAdmin())
async def test_delete_confirm(c: CallbackQuery):
    tid = int(c.data.split(":")[2])
    test = await db.one("SELECT title FROM tests WHERE id=?", (tid,))
    if not test:
        return await c.answer("Test topilmadi.", show_alert=True)
    await c.message.answer(
        f"«{esc(test['title'])}» testini va uning natijalarini butunlay o'chirasizmi?",
        reply_markup=ikb([[("🗑 Ha, o'chirish", f"tdel:yes:{tid}")], [("Bekor qilish", "tdel:no")]]),
    )
    await c.answer()


@r.callback_query(F.data.startswith("tdel:yes:"), IsAdmin())
async def test_delete(c: CallbackQuery):
    tid = int(c.data.split(":")[2])
    test = await db.one("SELECT id FROM tests WHERE id=?", (tid,))
    if not test:
        return await c.answer("Test topilmadi.", show_alert=True)
    await db.run(
        "DELETE FROM sub_files WHERE sub_id IN (SELECT id FROM submissions WHERE test_id=?)", (tid,)
    )
    await db.run("DELETE FROM submissions WHERE test_id=?", (tid,))
    await db.run("DELETE FROM attempts WHERE test_id=?", (tid,))
    await db.run("DELETE FROM test_questions WHERE test_id=?", (tid,))
    await db.run("DELETE FROM tests WHERE id=?", (tid,))
    await c.message.edit_text("✅ Test va unga tegishli natijalar o'chirildi.")
    await c.answer()


@r.callback_query(F.data == "tdel:no", IsAdmin())
async def test_delete_cancel(c: CallbackQuery):
    await c.message.edit_text("O'chirish bekor qilindi.")
    await c.answer()


# ================================================================== ADMIN: KITOB QO'SHISH
@r.message(F.text == A_BADD, IsAdmin())
async def book_add(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Kitob qaysi fandan?", reply_markup=ikb([[("📐 Algebra", "bka:Algebra"), ("📏 Geometriya", "bka:Geometriya")]]))


@r.callback_query(F.data.startswith("bka:"), IsAdmin())
async def book_add_subject(c: CallbackQuery, state: FSMContext):
    await state.set_state(BookAdd.file)
    await state.update_data(subject=c.data.split(":")[1])
    await c.message.answer("Kitob faylini (PDF) yuboring. Caption yozsangiz, o'sha nom bo'ladi.")
    await c.answer()


@r.message(BookAdd.file, F.document)
async def book_add_file(m: Message, state: FSMContext):
    d = await state.get_data()
    title = (m.caption or m.document.file_name or "Kitob").strip()
    await db.run("INSERT INTO books(subject,title,file_id) VALUES(?,?,?)", (d["subject"], title, m.document.file_id))
    await state.clear()
    await m.answer(f"✅ Kitob qo'shildi: {esc(title)}")


# ================================================================== ADMIN: TEST NATIJALARI
@r.message(F.text == A_RES, IsAdmin())
async def results(m: Message, state: FSMContext):
    await state.clear()
    rows = await db.fetch("SELECT id,name FROM groups ORDER BY id")
    if not rows:
        return await m.answer("Guruhlar yo'q.")
    await m.answer("Guruhni tanlang:", reply_markup=ikb([[(x["name"], f"tr:g:{x['id']}")] for x in rows]))


@r.callback_query(F.data.startswith("tr:g:"), IsAdmin())
async def results_group(c: CallbackQuery):
    gid = int(c.data.split(":")[2])
    tests = await db.fetch("SELECT id,title FROM tests ORDER BY id")
    if not tests:
        return await c.answer("Testlar yo'q.", show_alert=True)
    await c.message.answer("Testni tanlang:", reply_markup=ikb([[(t["title"][:50], f"tr:t:{gid}:{t['id']}")] for t in tests]))
    await c.answer()


@r.callback_query(F.data.startswith("tr:t:"), IsAdmin())
async def results_test(c: CallbackQuery):
    _, _, gid, tid = c.data.split(":")
    gid, tid = int(gid), int(tid)
    t = await db.one("SELECT title,mode FROM tests WHERE id=?", (tid,))
    if not t:
        return await c.answer("Test topilmadi.", show_alert=True)
    g = await db.one("SELECT name FROM groups WHERE id=?", (gid,))
    studs = await db.fetch("SELECT id, full_name FROM users WHERE group_id=? ORDER BY full_name", (gid,))
    icons = {"approved": "✅", "pending": "⏳", "rejected": "❌"}
    lines, cnt = [], {"approved": 0, "pending": 0, "rejected": 0, None: 0}
    for s in studs:
        if t["mode"] == "auto":
            attempt = await db.one(
                "SELECT score,total,finished_at FROM attempts WHERE test_id=? AND user_id=? "
                "ORDER BY id DESC LIMIT 1",
                (tid, s["id"]),
            )
            st = "approved" if attempt and attempt["finished_at"] else None
            score_text = (
                f" — {attempt['score']}/{attempt['total']}"
                if attempt and attempt["finished_at"] else ""
            )
        else:
            sub = await db.one(
                "SELECT status FROM submissions WHERE test_id=? AND user_id=? ORDER BY id DESC LIMIT 1",
                (tid, s["id"]),
            )
            st = sub["status"] if sub else None
            score_text = ""
        cnt[st] += 1
        lines.append(f"{icons.get(st, '➖')} {esc(s['full_name'])}{score_text}")
    head = (
        f"🧾 <b>{esc(t['title'])}</b> — {esc(g['name'])}\n"
        f"✅ {cnt['approved']}  ⏳ {cnt['pending']}  ❌ {cnt['rejected']}  ➖ {cnt[None]}\n"
        "(➖ topshirmagan)\n\n"
    )
    await c.message.answer(head + ("\n".join(lines) or "O'quvchilar yo'q."))
    await c.answer()


# ================================================================== ADMIN: XABAR YUBORISH
@r.message(F.text == A_BC, IsAdmin())
async def bc_start(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(
        "Kimga yuboramiz?",
        reply_markup=ikb([[("👥 Hammaga", "bc:all")], [("🏷 Guruhga", "bc:grp")], [("👤 Bitta o'quvchiga", "bc:one")]]),
    )


async def bc_ask(c: CallbackQuery, state: FSMContext, target):
    await state.set_state(Bc.msg)
    await state.update_data(target=target)
    await c.message.answer("Xabarni yuboring (matn, rasm, video, ovozli xabar — hammasi mumkin):")
    await c.answer()


@r.callback_query(F.data == "bc:all", IsAdmin())
async def bc_all(c: CallbackQuery, state: FSMContext):
    await bc_ask(c, state, "all")


@r.callback_query(F.data == "bc:grp", IsAdmin())
async def bc_grp(c: CallbackQuery):
    rows = await db.fetch("SELECT id,name FROM groups ORDER BY id")
    if not rows:
        return await c.answer("Guruhlar yo'q.", show_alert=True)
    await c.message.answer("Guruhni tanlang:", reply_markup=ikb([[(x["name"], f"bc:g:{x['id']}")] for x in rows]))
    await c.answer()


@r.callback_query(F.data.startswith("bc:g:"), IsAdmin())
async def bc_grp_pick(c: CallbackQuery, state: FSMContext):
    await bc_ask(c, state, "g:" + c.data.split(":")[2])


@r.callback_query(F.data == "bc:one", IsAdmin())
async def bc_one(c: CallbackQuery):
    studs = await db.fetch("SELECT id, full_name FROM users ORDER BY full_name LIMIT 80")
    if not studs:
        return await c.answer("O'quvchilar yo'q.", show_alert=True)
    await c.message.answer(
        "O'quvchini tanlang:", reply_markup=ikb([[(s["full_name"][:50], f"bc:u:{s['id']}")] for s in studs])
    )
    await c.answer()


@r.callback_query(F.data.startswith("bc:u:"), IsAdmin())
async def bc_one_pick(c: CallbackQuery, state: FSMContext):
    await bc_ask(c, state, "u:" + c.data.split(":")[2])


@r.message(Bc.msg)
async def bc_send(m: Message, state: FSMContext):
    d = await state.get_data()
    t = d["target"]
    await state.clear()
    if t == "all":
        rows = await db.fetch("SELECT id FROM users WHERE blocked=0")
    elif t.startswith("g:"):
        rows = await db.fetch("SELECT id FROM users WHERE group_id=? AND blocked=0", (int(t[2:]),))
    else:
        rows = await db.fetch("SELECT id FROM users WHERE id=?", (int(t[2:]),))
    ok = fail = 0
    for row in rows:
        try:
            await bot.copy_message(row["id"], m.chat.id, m.message_id)
            ok += 1
        except TelegramForbiddenError:
            await db.run("UPDATE users SET blocked=1 WHERE id=?", (row["id"],))
            fail += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await m.answer(f"📢 Yuborildi: {ok} ta\n⚠️ Yetmadi: {fail} ta")


# ================================================================== ADMIN: STATISTIKA
@r.message(F.text == A_STAT, IsAdmin())
async def stats(m: Message, state: FSMContext):
    await state.clear()
    now = int(time.time())
    total = await db.count("SELECT COUNT(*) FROM users")
    in_group = await db.count("SELECT COUNT(*) FROM users WHERE group_id IS NOT NULL")
    left = await db.count("SELECT COUNT(*) FROM users WHERE blocked=1")
    a24 = await db.count("SELECT COUNT(*) FROM users WHERE last_active>=?", (now - 86400,))
    a7 = await db.count("SELECT COUNT(*) FROM users WHERE last_active>=?", (now - 7 * 86400,))
    a30 = await db.count("SELECT COUNT(*) FROM users WHERE last_active>=?", (now - 30 * 86400,))
    groups = await db.count("SELECT COUNT(*) FROM groups")
    subj = await db.fetch("SELECT subject, COUNT(*) AS n FROM videos GROUP BY subject")
    lessons = "\n".join(f"   • {s['subject']}: {s['n']} ta" for s in subj) or "   • yo'q"
    await m.answer(
        "📊 <b>Statistika</b>\n\n"
        f"👤 Obunachilar soni: <b>{total}</b>\n"
        f"✅ Guruhga qo'shilganlar: <b>{in_group}</b>\n"
        f"🚪 Chiqib ketganlar (botni bloklagan): <b>{left}</b>\n"
        f"👥 Guruhlar: <b>{groups}</b>\n\n"
        "🔥 <b>Faollik</b>\n"
        f"   • Oxirgi 24 soat: {a24}\n   • Oxirgi 7 kun: {a7}\n   • Oxirgi 30 kun: {a30}\n\n"
        f"🎬 <b>Darsliklar soni</b>\n{lessons}"
    )


# ================================================================== ADMIN: ADMINLAR
@r.message(F.text == A_ADMINS, IsAdmin())
async def admins_list(m: Message, state: FSMContext):
    await state.clear()
    rows = await db.fetch("SELECT id, full_name FROM admins")
    text = "👮 <b>Adminlar</b>\n\n" + "\n".join(f"• {esc(a['full_name'])} — <code>{a['id']}</code>" for a in rows)
    await m.answer(text, reply_markup=ikb([[("➕ Admin qo'shish", "ad:new")]]))


@r.callback_query(F.data == "ad:new", IsAdmin())
async def admin_new(c: CallbackQuery, state: FSMContext):
    await state.set_state(AdmAdd.name)
    await c.message.answer("Yangi adminning ism-familiyasini yozing:")
    await c.answer()


@r.message(AdmAdd.name, F.text)
async def admin_new_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text.strip())
    await state.set_state(AdmAdd.uid)
    await m.answer("Uning Telegram ID raqamini yozing (raqam ko'rinishida):")


@r.message(AdmAdd.uid, F.text)
async def admin_new_id(m: Message, state: FSMContext):
    if not m.text.strip().isdigit():
        return await m.answer("ID faqat raqamlardan iborat bo'lishi kerak.")
    d = await state.get_data()
    uid = int(m.text.strip())
    await db.run("INSERT OR REPLACE INTO admins(id,full_name) VALUES(?,?)", (uid, d["name"]))
    await state.clear()
    await m.answer(f"✅ {esc(d['name'])} admin qilindi.")
    await safe_send(uid, "🎉 Siz admin etib tayinlandingiz. /start bosing.")


# ================================================================== XATOLIKLAR
@dp.error()
async def on_error(event: ErrorEvent):
    logging.exception("Xatolik: %s", event.exception)
    for a in await db.fetch("SELECT id FROM admins LIMIT 1"):
        await safe_send(a["id"], f"⚠️ Botda xatolik:\n<code>{esc(str(event.exception))[:500]}</code>")


# ================================================================== ISHGA TUSHIRISH
async def main():
    await db.init()
    for a in ADMIN_IDS:
        await db.run("INSERT OR IGNORE INTO admins(id,full_name) VALUES(?,?)", (a, "Asosiy admin"))
    dp.update.outer_middleware(Activity())
    dp.include_router(r)
    await bot.delete_webhook(drop_pending_updates=True)

    me = await bot.get_me()
    logging.info("Bot ishga tushdi: @%s", me.username)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
