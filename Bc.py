# pip install playwright python-telegram-bot
# playwright install chromium

import asyncio
import random
import re
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# ───────── CONFIG ─────────
BOT_TOKEN = "8375060248:AAEOCPp8hU2lBYqDGt1SYwluQDQgqmDfWWA"
INSTA_SIGNUP = "https://www.instagram.com/accounts/emailsignup/"
HEADLESS = False

SCREENSHOTS = Path("ig_signup_shots")
SCREENSHOTS.mkdir(exist_ok=True)

EMAIL, NAME, PASSWORD, CONFIRM, OTP, USERNAME, FINAL = range(7)

# ───────── HUMAN UTILS ─────────
async def human_delay(a=0.4, b=1.4):
    await asyncio.sleep(random.uniform(a, b))

async def human_type(page, selector, text):
    el = await page.wait_for_selector(selector, timeout=15000)
    await el.scroll_into_view_if_needed()
    await el.click(force=True)
    await asyncio.sleep(0.4)

    # clear field safely
    await page.keyboard.down("Control")
    await page.keyboard.press("A")
    await page.keyboard.up("Control")
    await page.keyboard.press("Backspace")
    await asyncio.sleep(0.3)

    for ch in text:
        await page.keyboard.type(ch)
        await asyncio.sleep(random.uniform(0.07, 0.18))

# ───────── HELPERS ─────────
def rnd_birthday():
    return random.randint(1, 28), random.randint(1, 12), random.randint(1990, 2005)

async def snap(page, chat_id, ctx, tag):
    ts = datetime.now().strftime("%H%M%S")
    p = SCREENSHOTS / f"{chat_id}_{tag}_{ts}.png"
    await page.screenshot(path=p)
    await ctx.bot.send_photo(chat_id, photo=p, caption=tag)

async def accept_cookies(page):
    for text in ["accept", "allow all"]:
        try:
            await page.get_by_role("button", name=re.compile(text, re.I)).click(timeout=3000)
            await human_delay()
            return
        except:
            pass

async def force_remove_overlays(page):
    await page.evaluate("""
        document.querySelectorAll(
            '[role="dialog"], [aria-modal="true"], ._a9--'
        ).forEach(e => e.remove());
    """)

async def fill_dob(page):
    d, m, y = rnd_birthday()
    selects = await page.query_selector_all("select")
    if len(selects) >= 3:
        await selects[0].select_option(str(m))
        await selects[1].select_option(str(d))
        await selects[2].select_option(str(y))
        return
    for k, v in {"day": d, "month": m, "year": y}.items():
        try:
            await human_type(page, f'input[name="{k}"]', str(v))
        except:
            pass

# ───────── FLOW ─────────
async def start(update, ctx):
    await update.message.reply_text("📧 Send email")
    return EMAIL

async def email_step(update, ctx):
    ctx.user_data["email"] = update.message.text.strip()
    await update.message.reply_text("👤 Send full name")
    return NAME

async def name_step(update, ctx):
    ctx.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("🔑 Send password")
    return PASSWORD

async def password_step(update, ctx):
    ctx.user_data["password"] = update.message.text
    asyncio.create_task(run_browser(ctx, update.effective_chat.id))
    await update.message.reply_text("🚀 Browser launched. Reply **yes**")
    return CONFIRM

async def run_browser(ctx, chat_id):
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=HEADLESS,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
        ]
    )

    page = await browser.new_page()
    await page.set_viewport_size({"width": 1366, "height": 900})
    await page.evaluate("document.body.style.zoom='100%'")

    ctx.user_data.update({
        "browser": browser,
        "page": page,
        "pw": pw,
    })

    await page.goto(INSTA_SIGNUP, timeout=60000)
    await accept_cookies(page)
    await snap(page, chat_id, ctx, "opened")

async def confirm_step(update, ctx):
    if update.message.text.lower() != "yes":
        return CONFIRM

    p = ctx.user_data["page"]

    await human_type(p, 'input[name="emailOrPhone"]', ctx.user_data["email"])
    await human_type(p, 'input[name="fullName"]', ctx.user_data["name"])
    await fill_dob(p)

    await snap(p, update.effective_chat.id, ctx, "details_filled")
    await update.message.reply_text("Reply **yes** for password step")
    return OTP

async def otp_step(update, ctx):
    if update.message.text.lower() != "yes":
        return OTP

    p = ctx.user_data["page"]

    for sel in [
        'input[name="password"]',
        'input[aria-label="Password"]',
        'input[type="password"]'
    ]:
        try:
            await human_type(p, sel, ctx.user_data["password"])
            break
        except:
            continue

    await force_remove_overlays(p)
    await p.get_by_role("button", name=re.compile("Next", re.I)).click(force=True)
    await human_delay(2, 3)

    await update.message.reply_text("🆔 Send username or **yes**")
    return USERNAME

async def username_step(update, ctx):
    p = ctx.user_data["page"]
    chat_id = update.effective_chat.id

    base = update.message.text.strip()
    if base.lower() == "yes":
        base = "user"

    selectors = [
        'input[name="username"]',
        'input[aria-label="Username"]'
    ]

    field = None
    for sel in selectors:
        try:
            field = await p.query_selector(sel)
            if field:
                selector = sel
                break
        except:
            pass

    if not field:
        await update.message.reply_text("❌ Username field not found")
        return USERNAME

    for _ in range(10):
        username = f"{base}{random.randint(1000,999999)}"

        await human_type(p, selector, username)
        await p.keyboard.press("Tab")
        await human_delay(2, 3)
        await force_remove_overlays(p)

        try:
            btn = p.get_by_role("button", name=re.compile("Next", re.I))
            if not await btn.get_attribute("disabled"):
                await snap(p, chat_id, ctx, f"username_{username}")
                await update.message.reply_text(f"✅ Username accepted: `{username}`\nReply **yes**")
                return FINAL
        except:
            pass

    await update.message.reply_text("❌ Username failed. Send another base.")
    return USERNAME

async def final_step(update, ctx):
    p = ctx.user_data["page"]

    await force_remove_overlays(p)
    await p.get_by_role("button", name=re.compile("Next|Create", re.I)).click(force=True)
    await human_delay(3, 4)

    await snap(p, update.effective_chat.id, ctx, "done")

    await ctx.user_data["browser"].close()
    await ctx.user_data["pw"].stop()
    ctx.user_data.clear()

    await update.message.reply_text("🎉 Signup finished")
    return ConversationHandler.END

async def cancel(update, ctx):
    try:
        await ctx.user_data["browser"].close()
        await ctx.user_data["pw"].stop()
    except:
        pass
    ctx.user_data.clear()
    await update.message.reply_text("❌ Cancelled")
    return ConversationHandler.END

# ───────── MAIN ─────────
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            EMAIL: [MessageHandler(filters.TEXT, email_step)],
            NAME: [MessageHandler(filters.TEXT, name_step)],
            PASSWORD: [MessageHandler(filters.TEXT, password_step)],
            CONFIRM: [MessageHandler(filters.TEXT, confirm_step)],
            OTP: [MessageHandler(filters.TEXT, otp_step)],
            USERNAME: [MessageHandler(filters.TEXT, username_step)],
            FINAL: [MessageHandler(filters.TEXT, final_step)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv)
    app.run_polling()

if __name__ == "__main__":
    main()
