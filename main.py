#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
main.py
نقطة الدخول الرئيسية للبوت - إعداد وتشغيل التطبيق
"""

import asyncio
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler
)
from telegram import Update
from logger import logger
from config import BOT_TOKEN, ADMIN_ID
from database import db
from admin_panel import admin_panel, admin_callback_handler, handle_admin_input
from scheduler import PublishingScheduler
import messages as msg
from utils import is_admin
from quran import get_verse_with_details
from hadith import get_random_hadith, format_hadith
from adhkar import get_random_adhkar, format_adhkar
import fonts

# تهيئة المجدول (سيتم ربطه لاحقاً)
scheduler = None

async def start(update: Update, context):
    """معالج أمر /start"""
    user = update.effective_user
    db.update_user(user.id, user.first_name, user.username)
    await update.message.reply_text(msg.START_MESSAGE, parse_mode='Markdown')
    logger.info(f"User {user.id} started the bot")

async def help_command(update: Update, context):
    """معالج أمر /help"""
    await update.message.reply_text(msg.HELP_MESSAGE, parse_mode='Markdown')

async def admin_command(update: Update, context):
    """معالج أمر /admin - يوجه إلى لوحة التحكم"""
    await admin_panel(update, context)

async def error_handler(update: Update, context):
    """معالج الأخطاء العام"""
    logger.error(f"Update {update} caused error {context.error}")
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(msg.ERROR_MESSAGE)
    except:
        pass

async def publish_job_callback(context):
    """
    دالة النشر التلقائي - تستدعي من المجدول
    """
    channels = db.get_active_channels()
    if not channels:
        logger.warning("No channels to publish")
        return

    # نوع المحتوى محفوظ في context.job.data
    content_type = context.job.data if context.job and context.job.data else 'verse'
    logger.info(f"Auto publishing {content_type} to {len(channels)} channels")

    # تجهيز المحتوى حسب النوع
    message_text = ""
    audio_file = None

    if content_type == 'verse' or content_type == 'all':
        verse_data = await get_verse_with_details()
        if verse_data:
            current_font = fonts.get_current_style()
            message_text = utils.format_verse_info(
                verse_data['surah'],
                verse_data['ayah_number'],
                verse_data['text'],
                verse_data.get('tafsir'),
                verse_data.get('reciter_name'),
                current_font
            )
            audio_file = verse_data.get('audio_url')
    elif content_type == 'hadith':
        hadith = await get_random_hadith()
        if hadith:
            message_text = format_hadith(hadith)
    elif content_type == 'adhkar':
        adhkar = await get_random_adhkar()
        if adhkar:
            message_text = format_adhkar(adhkar)

    if not message_text:
        logger.error(f"Failed to generate content for {content_type}")
        return

    # إرسال إلى جميع القنوات
    for channel in channels:
        try:
            if audio_file and content_type == 'verse':
                await context.bot.send_audio(
                    chat_id=channel['chat_id'],
                    audio=audio_file,
                    caption=message_text[:1024],  # حد التسمية التوضيحية
                    parse_mode='Markdown'
                )
            else:
                await context.bot.send_message(
                    chat_id=channel['chat_id'],
                    text=message_text,
                    parse_mode='Markdown'
                )
            db.add_stat(content_type, channel['chat_id'])
            logger.info(f"Published {content_type} to {channel['chat_id']}")
        except Exception as e:
            logger.error(f"Failed to publish to {channel['chat_id']}: {e}")

async def manual_publish(update: Update, context, content_type: str):
    """نشر يدوي - يتم استدعاؤها من admin_panel"""
    if not is_admin(update.effective_user.id):
        return

    channels = db.get_active_channels()
    if not channels:
        await update.effective_message.reply_text("❌ لا توجد قنوات نشطة.")
        return

    # نستخدم نفس دالة النشر التلقائي ولكن مع نوع محدد
    job_data = content_type
    await publish_job_callback(context.application.job_queue._create_job(
        callback=None, data=job_data, name="manual"
    ))
    await update.effective_message.reply_text("✅ جاري النشر اليدوي...")

def main():
    """الدالة الرئيسية لبدء البوت"""
    global scheduler

    logger.info("Starting Islamic Bot...")

    # بناء التطبيق
    application = ApplicationBuilder() \
        .token(BOT_TOKEN) \
        .concurrent_updates(True) \
        .build()

    # إضافة المجدول
    scheduler = PublishingScheduler(application.job_queue)
    # ربط المجدول مع التطبيق لاستخدامه في callback
    application.bot_data['scheduler'] = scheduler
    application.bot_data['publish_callback'] = publish_job_callback

    # إضافة معالجات الأوامر
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("admin", admin_command))

    # معالج callback queries (الأزرار)
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^publish_"))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^schedule_"))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^reciter_"))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^font_"))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^channel_"))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^del_"))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^manual_"))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))

    # معالج الإدخالات النصية للأدمن (إضافة قناة، تغيير إعدادات)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_admin_input
    ))

    # معالج الأخطاء
    application.add_error_handler(error_handler)

    # بدء المجدول إذا كان مفعلاً
    scheduler.schedule()

    logger.info("Bot is polling...")
    application.run_polling()

if __name__ == "__main__":
    main()