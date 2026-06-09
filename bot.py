import os
import asyncio
import logging
import random
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from google import genai
from telegram.error import RetryAfter

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Environment Variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "YAHAN_APNA_TELEGRAM_TOKEN_DALEIN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "YAHAN_APNA_GEMINI_KEY_DALEIN")
PORT = int(os.getenv("PORT", 8443))
HEROKU_APP_NAME = os.getenv("HEROKU_APP_NAME")

ai_client = genai.Client(api_key=GEMINI_API_KEY)

# Smart Controls Tracking Dicts
running_tags = {}
paused_tags = {}

# Tagging Styles Data
TAG_STYLES = {
    "hindi": ["Suno dosto!", "Kahan ho sabhi?", "Ek zaroori baat!", "Idhar dekho bhai!"],
    "english": ["Hey everyone!", "Attention please!", "Check this out!", "Wake up guys!"],
    "hinglish": ["Kya chal raha hai?", "Sab log online aao!", "Suno sabke sab!", "Arre idhar toh aao!"],
    "gm": ["Good Morning! ☀️", "Subah ho gayi mamu!", "Have a great day ahead!", "Suprabhat family!"],
    "gn": ["Good Night! 🌙", "Chalo sone jao ab!", "Sweet dreams everyone!", "Shubh ratri dosto!"],
    "joke": ["Ek joke suno aur online aao! 😂", "Haste haste online hazir ho! 💀", "Chalo sab mood fresh karo! ✨"],
    "general": ["Notification Alert! 🔔", "Ping! 😉", "Don't ignore this! 🙌", "Hello hello! 🎉"]
}

# Menu Commands Setup
async def post_init(application: Application) -> None:
    commands = [
        BotCommand("start", "Bot shuru karein"),
        BotCommand("help", "Command list aur styles dekhein"),
        BotCommand("all", "Sabhi members ko tag karein"),
        BotCommand("admin", "Sirf admins ko tag karein"),
        BotCommand("stop", "Tagging poori tarah band karein"),
        BotCommand("pause", "Tagging ko thodi der rokein"),
        BotCommand("resume", "Roki hui tagging fir se shuru karein")
    ]
    await application.bot.set_my_commands(commands)

# Admin Verification Helper
async def is_user_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    user_id = update.effective_user.id
    if chat.type == "private":
        return True
    member = await context.bot.get_chat_member(chat.id, user_id)
    return member.status in ["administrator", "creator"]

# 1. /start Command (DM me buttons ke saath, Group me normal greet)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_type = update.message.chat.type
    bot_username = context.bot.username

    if chat_type == "private":
        # DM ke liye 3 Inline Buttons banana
        keyboard = [
            [InlineKeyboardButton("➕ Add to your group", url=f"https://t.me{bot_username}?startgroup=true")],
            [
                InlineKeyboardButton("❓ Help", callback_data="help_btn"),
                InlineKeyboardButton("📢 Update Support", url="https://t.meyour_support_channel") # Apne channel ka link dalein
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        welcome_text = (
            f"✨ **Welcome {update.effective_user.first_name}!** ✨\n\n"
            "Main ek advanced AI Mention & Mass Tagging Bot hoon.\n"
            "Mujhe apne group me add karke full features ka maza lein. "
            "Neeche diye gaye buttons ka use karein! 👇"
        )
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        # Group me simple message
        await update.message.reply_text("👋 Hello members! Main is group me active hoon. Commands dekhne ke liye `/help` type karein.")

# 2. Callback Query Handler (Help button click handle karne ke liye)
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "help_btn":
        help_text = (
            "📊 **Advanced Tagging Guide & Options**\n\n"
            "🏷️ **8 Tagging Styles:**\n"
            "• `/all hindi [msg]` - Pure Hindi greetings\n"
            "• `/all english [msg]` - Formal English\n"
            "• `/all hinglish [msg]` - Normal chatting language\n"
            "• `/all gm [msg]` - Good Morning wishes\n"
            "• `/all gn [msg]` - Good Night wishes\n"
            "• `/all joke [msg]` - Funny alert style\n"
            "• `/all general [msg]` - Regular notifications\n\n"
            "👮 **Smart Controls (Admins Only):**\n"
            "• `/stop` - Tagging loop ko band karein\n"
            "• `/pause` - Loop ko thodi der rokein\n"
            "• `/resume` - Paused loop ko wapas chalayein"
        )
        # Purane text ko badal kar help text dikhana
        await query.message.reply_text(help_text, parse_mode="Markdown")

# 3. /help Command (Direct text command)
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Yeh code direct /help command chalane par help message bhejega
    class DummyQuery:
        data = "help_btn"
        async def answer(self): pass
        @property
        def message(self): return update.message
    
    update.callback_query = DummyQuery()
    await button_click(update, context)

# 4. Main Advanced Tagging Engine
async def tag_engine(update: Update, context: ContextTypes.DEFAULT_TYPE, target_admins_only=False):
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌ Ye command sirf groups me kaam karega!")
        return

    if not await is_user_admin(update, context):
        await update.message.reply_text("❌ Sirf group admins hi tag commands chala sakte hain!")
        return

    chat_id = chat.id
    running_tags[chat_id] = True
    paused_tags[chat_id] = False

    args = context.args
    style = "general"
    custom_msg = ""

    if args:
        if args[0].lower() in TAG_STYLES:
            style = args[0].lower()
            custom_msg = " ".join(args[1:])
        else:
            custom_msg = " ".join(args)

    try:
        administrators = await chat.get_administrators()
        targets = administrators
        users_to_tag = [admin.user for admin in targets if not admin.user.is_bot]
        
        if not users_to_tag:
            await update.message.reply_text("Tag karne ke liye koi valid members nahi mile.")
            return

        await update.message.reply_text("🚀 Mentioning loop shuru ho chuka hai...")

        for i in range(0, len(users_to_tag), 5):
            if not running_tags.get(chat_id, False):
                await update.message.reply_text("🛑 Tagging process ko stop kar diya gaya hai.")
                break
            
            while paused_tags.get(chat_id, False):
                await asyncio.sleep(2)
                if not running_tags.get(chat_id, False):
                    break

            batch = users_to_tag[i:i+5]
            style_prefix = random.choice(TAG_STYLES[style])
            mention_line = f"✨ {style_prefix}\n✍️ Msg: {custom_msg}\n\n" if custom_msg else f"✨ {style_prefix}\n\n"
            
            for user in batch:
                mention_line += f"[{user.first_name}](tg://user?id={user.id}) "

            try:
                await context.bot.send_message(chat_id=chat_id, text=mention_line, parse_mode="Markdown")
                await asyncio.sleep(3)
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after)

        await update.message.reply_text("✅ Tagging complete!")
        running_tags[chat_id] = False

    except Exception as e:
        logging.error(f"Error in tag_engine: {e}")
        await update.message.reply_text("⚠️ Bot permissions check karein.")

# 5. Smart Controls
async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_user_admin(update, context):
        running_tags[update.effective_chat.id] = False
        paused_tags[update.effective_chat.id] = False

async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_user_admin(update, context):
        paused_tags[update.effective_chat.id] = True
        await update.message.reply_text("⏸️ Tagging process paused. `/resume` se shuru karein.")

async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_user_admin(update, context):
        paused_tags[update.effective_chat.id] = False
        await update.message.reply_text("▶️ Tagging process resumed.")

# 6. AI Message Handler
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    bot_username = context.bot.username
    is_private = update.message.chat.type == "private"
    is_mentioned = f"@{bot_username}" in user_text

    if is_private or is_mentioned:
        clean_prompt = user_text.replace(f"@{bot_username}", "").strip()
        if not clean_prompt:
            await update.message.reply_text("Ji? Mujhse koi sawal poochein!")
            return
        try:
            response = ai_client.models.generate_content(model='gemini-2.5-flash', contents=clean_prompt)
            await update.message.reply_text(response.text)
        except Exception as e:
            logging.error(f"Gemini error: {e}")
            await update.message.reply_text("Sorry, abhi AI busy hai.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("all", lambda u, c: tag_engine(u, c, target_admins_only=False)))
    app.add_handler(CommandHandler("admin", lambda u, c: tag_engine(u, c, target_admins_only=True)))
    
    app.add_handler(CommandHandler("stop", stop_command))
          
