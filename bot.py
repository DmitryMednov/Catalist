"""
Catalist — Telegram bot for processing grant applications
to help cover veterinary costs for stray cats.

Run:
    BOT_TOKEN=... ADMIN_CHAT_IDS=123,456 REVIEW_CHAT_ID=-100... python bot.py
"""

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from telegram import (
    BotCommand,
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_CHAT_IDS = [
    int(x.strip()) for x in os.environ.get("ADMIN_CHAT_IDS", "").split(",") if x.strip()
]
REVIEW_CHAT_ID = int(os.environ["REVIEW_CHAT_ID"])

MAX_GRANT_EUR = 100
GRANT_OPTIONS = [20, 40, 60, 80, 100]

CLINIC_OPTIONS = [
    "Dr. Adventures / Др. Эдвенчерс",
    "Vet Union / Вет Юнион",
    "Alternativa / Альтернатива",
    "Chance Bio / Шанс Био",
    "Cosmos / Космос",
    "Biocenter / Биоцентр",
    "Nordvet / Нордвет",
    "Constellation / Созвездие",
    "LeoVet / ЛеоВет",
    "Bely Klyk / Белый Клык",
    "Best / Бэст",
    "MedVet / МедВет",
]

PROCEDURE_OPTIONS = [
    ("vaccination", "Vaccination"),
    ("sterilisation", "Sterilisation"),
    ("emergency", "Emergency care"),
    ("diagnostics", "Diagnostics"),
    ("treatment", "Treatment"),
    ("other", "Other"),
]

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "catalist.db"
LOGO_PATH = Path(__file__).parent / "logo.png"

# ── Persistent main menu ────────────────────────────────────────────────────

MAIN_MENU = ReplyKeyboardMarkup(
    [["Apply for a grant", "How it works"]],
    resize_keyboard=True,
)

# ── Conversation states ─────────────────────────────────────────────────────

(
    PHOTO,
    CLINIC,
    CLINIC_OTHER,
    PROCEDURE,
    PROCEDURE_OTHER,
    COST,
    FIRST_NAME,
    LAST_NAME,
    PHONE,
    EMAIL,
    COMMENT,
    CONFIRM,
) = range(12)

# ── Database ─────────────────────────────────────────────────────────────────


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS applications (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL,
            chat_id       INTEGER NOT NULL,
            photo_file_id TEXT    NOT NULL,
            clinic        TEXT    NOT NULL DEFAULT '',
            procedure     TEXT    NOT NULL,
            cost          TEXT    NOT NULL,
            first_name    TEXT    NOT NULL,
            last_name     TEXT    NOT NULL,
            phone         TEXT    NOT NULL,
            email         TEXT    NOT NULL,
            comment       TEXT    NOT NULL,
            status        TEXT    NOT NULL DEFAULT 'pending',
            approved_sum  TEXT,
            created_at    TEXT    NOT NULL,
            reviewed_at   TEXT
        )
        """
    )
    # Migrate: add clinic column if missing (old DB schema)
    cursor = conn.execute("PRAGMA table_info(applications)")
    columns = [row[1] for row in cursor.fetchall()]
    if "clinic" not in columns:
        conn.execute("ALTER TABLE applications ADD COLUMN clinic TEXT NOT NULL DEFAULT ''")
    conn.commit()
    conn.close()


def save_application(data: dict) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        """
        INSERT INTO applications
            (user_id, chat_id, photo_file_id, clinic, procedure, cost,
             first_name, last_name, phone, email, comment, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["user_id"],
            data["chat_id"],
            data["photo_file_id"],
            data["clinic"],
            data["procedure"],
            data["cost"],
            data["first_name"],
            data["last_name"],
            data["phone"],
            data["email"],
            data["comment"],
            datetime.now().isoformat(),
        ),
    )
    app_id = cur.lastrowid
    conn.commit()
    conn.close()
    return app_id


def update_application_status(app_id: int, status: str, approved_sum: str = None) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if status == "approved":
        conn.execute(
            "UPDATE applications SET status = ?, approved_sum = ?, reviewed_at = ? WHERE id = ?",
            (status, approved_sum, datetime.now().isoformat(), app_id),
        )
    else:
        conn.execute(
            "UPDATE applications SET status = ?, reviewed_at = ? WHERE id = ?",
            (status, datetime.now().isoformat(), app_id),
        )
    conn.commit()
    row = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Messages ─────────────────────────────────────────────────────────────────

WELCOME_TEXT = (
    "Welcome to Catalist.\n\n"
    "We help cover veterinary costs for stray cats "
    "brought to clinics by caring individuals.\n\n"
    "Use the menu below to get started."
)

HELP_TEXT = (
    "How Catalist works\n\n"
    "1. You find a stray cat that needs veterinary care\n"
    "2. You take it to a veterinary clinic\n"
    "3. You tap \"Apply for a grant\" below\n"
    "4. We review your request and notify you of the decision\n"
    "5. If approved, we cover part or all of the treatment cost (up to €100)\n\n"
    "Questions and feedback: info@catalist.world"
)

APPLY_START = (
    "Grant application.\n\n"
    "This will take a few minutes. "
    "You can cancel at any time — /cancel.\n\n"
    "Please send a photo of the animal."
)

ASK_CLINIC = "Which veterinary clinic will perform the procedure?"
ASK_PROCEDURE = "Select the type of procedure:"
ASK_PROCEDURE_OTHER = "Please describe the procedure."
ASK_COST = "Select the estimated cost of treatment:"
ASK_FIRST_NAME = "Your first name."
ASK_LAST_NAME = "Your last name."
ASK_PHONE = "Your phone number."
ASK_EMAIL = "Your email address."
ASK_COMMENT = (
    "Tell us where and under what circumstances "
    "the cat was found. Any additional information is welcome."
)
CANCEL_TEXT = "Application cancelled."


# ── Post-init: set bot commands menu ────────────────────────────────────────


async def post_init(application) -> None:
    await application.bot.set_my_commands([
        BotCommand("start", "Start the bot"),
        BotCommand("apply", "Apply for a grant"),
        BotCommand("help", "How Catalist works"),
        BotCommand("cancel", "Cancel current application"),
    ])


# ── Conversation handlers ────────────────────────────────────────────────────


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if LOGO_PATH.exists():
        with open(LOGO_PATH, "rb") as logo:
            await update.message.reply_photo(
                photo=logo,
                caption=WELCOME_TEXT,
                reply_markup=MAIN_MENU,
            )
    else:
        await update.message.reply_text(WELCOME_TEXT, reply_markup=MAIN_MENU)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, reply_markup=MAIN_MENU)


async def apply_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(APPLY_START, reply_markup=ReplyKeyboardRemove())
    return PHOTO


async def photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    photo = update.message.photo[-1]
    context.user_data["photo_file_id"] = photo.file_id
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(name, callback_data=f"clinic:{i}")]
         for i, name in enumerate(CLINIC_OPTIONS)]
        + [[InlineKeyboardButton("Other", callback_data="clinic:other")]]
    )
    await update.message.reply_text(ASK_CLINIC, reply_markup=keyboard)
    return CLINIC


async def photo_invalid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Please send a photo of the animal.")
    return PHOTO


async def clinic_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    clinic_key = query.data.split(":", 1)[1]

    if clinic_key == "other":
        await query.edit_message_text(text=f"{ASK_CLINIC}\n\nSelected: Other")
        await query.message.reply_text("Please enter the clinic name.")
        return CLINIC_OTHER

    clinic_name = CLINIC_OPTIONS[int(clinic_key)]
    context.user_data["clinic"] = clinic_name
    await query.edit_message_text(text=f"{ASK_CLINIC}\n\nSelected: {clinic_name}")
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=f"proc:{key}")]
         for key, label in PROCEDURE_OPTIONS]
    )
    await query.message.reply_text(ASK_PROCEDURE, reply_markup=keyboard)
    return PROCEDURE


async def clinic_other_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["clinic"] = update.message.text
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=f"proc:{key}")]
         for key, label in PROCEDURE_OPTIONS]
    )
    await update.message.reply_text(ASK_PROCEDURE, reply_markup=keyboard)
    return PROCEDURE


async def procedure_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    proc_key = query.data.split(":", 1)[1]

    if proc_key == "other":
        await query.edit_message_text(text=f"{ASK_PROCEDURE}\n\nSelected: Other")
        await query.message.reply_text(ASK_PROCEDURE_OTHER)
        return PROCEDURE_OTHER

    proc_label = dict(PROCEDURE_OPTIONS).get(proc_key, proc_key)
    context.user_data["procedure"] = proc_label
    await query.edit_message_text(text=f"{ASK_PROCEDURE}\n\nSelected: {proc_label}")

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"€{amt}", callback_data=f"cost:{amt}")]
         for amt in GRANT_OPTIONS]
    )
    await query.message.reply_text(ASK_COST, reply_markup=keyboard)
    return COST


async def procedure_other_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["procedure"] = update.message.text
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"€{amt}", callback_data=f"cost:{amt}")]
         for amt in GRANT_OPTIONS]
    )
    await update.message.reply_text(ASK_COST, reply_markup=keyboard)
    return COST


async def cost_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    amount = query.data.split(":", 1)[1]
    context.user_data["cost"] = f"€{amount}"
    await query.edit_message_text(text=f"{ASK_COST}\n\nSelected: €{amount}")
    await query.message.reply_text(ASK_FIRST_NAME)
    return FIRST_NAME


async def first_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["first_name"] = update.message.text
    await update.message.reply_text(ASK_LAST_NAME)
    return LAST_NAME


async def last_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["last_name"] = update.message.text
    await update.message.reply_text(ASK_PHONE)
    return PHONE


async def phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["phone"] = update.message.text
    await update.message.reply_text(ASK_EMAIL)
    return EMAIL


async def email_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["email"] = update.message.text
    await update.message.reply_text(ASK_COMMENT)
    return COMMENT


async def comment_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["comment"] = update.message.text

    d = context.user_data
    summary = (
        "Please review your application:\n\n"
        f"Clinic: {d['clinic']}\n"
        f"Procedure: {d['procedure']}\n"
        f"Cost: {d['cost']}\n"
        f"Name: {d['first_name']} {d['last_name']}\n"
        f"Phone: {d['phone']}\n"
        f"Email: {d['email']}\n"
        f"Details: {d['comment']}\n\n"
        "Is everything correct?"
    )

    keyboard = ReplyKeyboardMarkup(
        [["Submit application", "Cancel"]], one_time_keyboard=True, resize_keyboard=True
    )
    await update.message.reply_text(summary, reply_markup=keyboard)
    return CONFIRM


async def confirm_submit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    d = context.user_data
    d["user_id"] = update.effective_user.id
    d["chat_id"] = update.effective_chat.id

    app_id = save_application(d)

    # Send application copy to the user for their records
    user_copy = (
        f"Your application #{app_id}\n\n"
        f"Clinic: {d['clinic']}\n"
        f"Procedure: {d['procedure']}\n"
        f"Cost: {d['cost']}\n"
        f"Name: {d['first_name']} {d['last_name']}\n"
        f"Phone: {d['phone']}\n"
        f"Email: {d['email']}\n"
        f"Details: {d['comment']}"
    )
    await update.message.reply_photo(
        photo=d["photo_file_id"],
        caption=user_copy,
    )

    await update.message.reply_text(
        f"Application #{app_id} has been submitted for review.\n\n"
        "We will notify you of the decision. "
        "Review typically takes a few hours.\n\n"
        "Thank you for caring about the animal.",
        reply_markup=MAIN_MENU,
    )

    admin_text = (
        f"New application #{app_id}\n\n"
        f"Clinic: {d['clinic']}\n"
        f"Procedure: {d['procedure']}\n"
        f"Cost: {d['cost']}\n"
        f"Applicant: {d['first_name']} {d['last_name']}\n"
        f"Phone: {d['phone']}\n"
        f"Email: {d['email']}\n"
        f"Details: {d['comment']}"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Approve", callback_data=f"approve:{app_id}"),
                InlineKeyboardButton("Reject", callback_data=f"reject:{app_id}"),
            ]
        ]
    )

    try:
        await context.bot.send_photo(
            chat_id=REVIEW_CHAT_ID,
            photo=d["photo_file_id"],
            caption=admin_text,
            reply_markup=keyboard,
            message_thread_id=742,
        )
    except Exception as e:
        logger.error("Failed to send application to review group: %s", e)

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(CANCEL_TEXT, reply_markup=MAIN_MENU)
    return ConversationHandler.END


# ── Admin callbacks ──────────────────────────────────────────────────────────

WAITING_FOR_SUM: dict[int, int] = {}


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    reviewer_id = query.from_user.id
    action, app_id_str = query.data.split(":", 1)
    app_id = int(app_id_str)

    if action == "approve":
        WAITING_FOR_SUM[reviewer_id] = app_id
        await query.edit_message_reply_markup(reply_markup=None)
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"€{amt}", callback_data=f"grantsum:{app_id}:{amt}")]
             for amt in GRANT_OPTIONS]
        )
        await query.message.reply_text(
            f"Application #{app_id}: select the grant amount:",
            reply_markup=keyboard,
        )

    elif action == "reject":
        app = update_application_status(app_id, "rejected")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"Application #{app_id} rejected.")

        if app:
            try:
                await context.bot.send_message(
                    chat_id=app["chat_id"],
                    text=(
                        f"Application #{app_id}: unfortunately, we are unable "
                        "to approve this request at this time.\n\n"
                        "This may be due to limited funding "
                        "or the application not meeting programme criteria.\n\n"
                        "You can submit a new application — tap \"Apply for a grant\" below.\n"
                        "Thank you for your care."
                    ),
                )
            except Exception as e:
                logger.error("Failed to notify user about rejection: %s", e)


async def admin_grant_sum_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    reviewer_id = query.from_user.id
    parts = query.data.split(":")
    app_id = int(parts[1])
    approved_sum = parts[2]

    WAITING_FOR_SUM.pop(reviewer_id, None)
    app = update_application_status(app_id, "approved", approved_sum)

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(f"Application #{app_id} approved for €{approved_sum}.")

    if app:
        try:
            clinic_name = app.get("clinic", "the selected clinic")
            await context.bot.send_message(
                chat_id=app["chat_id"],
                text=(
                    f"Application #{app_id} approved!\n\n"
                    f"Catalist will cover the treatment cost "
                    f"in the amount of €{approved_sum}.\n\n"
                    f"Please proceed to the reception desk at "
                    f"{clinic_name} and present this message.\n\n"
                    "Thank you for caring about the animal."
                ),
            )
        except Exception as e:
            logger.error("Failed to notify user about approval: %s", e)

        try:
            donate_keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "Support Catalist", url="https://catalist.world/donation"
                        )
                    ]
                ]
            )
            await context.bot.send_message(
                chat_id=app["chat_id"],
                text=(
                    "Thank you for reaching out to Catalist.\n\n"
                    "Every day we receive requests about cats "
                    "in urgent need of veterinary care. "
                    "Many cases require significant funding.\n\n"
                    "If you are able, please consider supporting the project. "
                    "Your contribution helps us continue our work."
                ),
                reply_markup=donate_keyboard,
            )
        except Exception as e:
            logger.error("Failed to send donation message: %s", e)


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("apply", apply_start),
            MessageHandler(filters.Regex("^Apply for a grant$"), apply_start),
        ],
        states={
            PHOTO: [
                MessageHandler(filters.PHOTO, photo_received),
                MessageHandler(~filters.PHOTO & ~filters.COMMAND, photo_invalid),
            ],
            CLINIC: [CallbackQueryHandler(clinic_selected, pattern=r"^clinic:")],
            CLINIC_OTHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, clinic_other_received)],
            PROCEDURE: [CallbackQueryHandler(procedure_selected, pattern=r"^proc:")],
            PROCEDURE_OTHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, procedure_other_received)],
            COST: [CallbackQueryHandler(cost_selected, pattern=r"^cost:")],
            FIRST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, first_name_received)],
            LAST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, last_name_received)],
            PHONE: [
                MessageHandler(
                    (filters.TEXT | filters.CONTACT) & ~filters.COMMAND, phone_received
                )
            ],
            EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, email_received)],
            COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, comment_received)],
            CONFIRM: [
                MessageHandler(filters.Regex("^Submit application$"), confirm_submit),
                MessageHandler(filters.Regex("^Cancel$"), cancel),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex(r"(?i)^cancel$"), cancel),
        ],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.Regex("^How it works$"), help_cmd))
    app.add_handler(conv_handler)

    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^(approve|reject):\d+$"))
    app.add_handler(CallbackQueryHandler(admin_grant_sum_selected, pattern=r"^grantsum:\d+:\d+$"))

    logger.info("Catalist bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
