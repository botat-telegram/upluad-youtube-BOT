import os
import json
from datetime import datetime
from typing import Optional, Dict
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telethon import TelegramClient
from dotenv import load_dotenv

# تحميل المتغيرات البيئية
load_dotenv()

# ثوابت
SCOPES = ['https://www.googleapis.com/auth/youtube.upload']
TOKEN_FILE = 'token.json'
CLIENT_SECRETS_FILE = "client_secrets.json"

# تحقق من وجود المتغيرات البيئية المطلوبة
required_env_vars = {
    'TELEGRAM_BOT_TOKEN': 'رمز بوت تليجرام',
    'TELEGRAM_API_ID': 'معرف API تليجرام',
    'TELEGRAM_API_HASH': 'مفتاح API تليجرام'
}

missing_vars = []
for var, description in required_env_vars.items():
    if not os.getenv(var):
        missing_vars.append(f"{var} ({description})")

if missing_vars:
    print("❌ خطأ: المتغيرات البيئية التالية مفقودة:")
    for var in missing_vars:
        print(f"- {var}")
    exit(1)

# حالات المحادثة
CHOOSE_TITLE, WAITING_TITLE, CHOOSE_DESCRIPTION, WAITING_DESCRIPTION = range(4)

# إعداد عميل تليجرام
api_id = os.getenv('TELEGRAM_API_ID')
api_hash = os.getenv('TELEGRAM_API_HASH')
client = TelegramClient('bot_session', api_id, api_hash)

def get_youtube_credentials():
    """الحصول على أو تجديد بيانات اعتماد YouTube"""
    creds = None
    
    # محاولة تحميل بيانات الاعتماد المخزنة
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception as e:
            print(f"خطأ في تحميل بيانات الاعتماد: {e}")
    
    # تجديد بيانات الاعتماد إذا انتهت صلاحيتها
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # حفظ بيانات الاعتماد المحدثة
            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())
        except Exception as e:
            print(f"خطأ في تجديد بيانات الاعتماد: {e}")
            creds = None
    
    # إنشاء بيانات اعتماد جديدة إذا لم تكن موجودة
    if not creds or not creds.valid:
        try:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
            # حفظ بيانات الاعتماد الجديدة
            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())
        except Exception as e:
            print(f"خطأ في إنشاء بيانات الاعتماد: {e}")
            return None
    
    return creds

async def extract_telegram_link_info(link: str) -> Optional[Dict]:
    """استخراج معلومات من رابط تليجرام"""
    # نمط للتعرف على روابط التليجرام
    import re
    pattern = r't\.me/([^/]+)/(\d+)'
    match = re.search(pattern, link)
    
    if match:
        return {
            'channel': match.group(1),
            'message_id': int(match.group(2))
        }
    return None

async def download_from_telegram_link(link: str, update: Update) -> Optional[str]:
    """تحميل الفيديو من رابط تليجرام"""
    try:
        # استخراج معلومات الرابط
        link_info = await extract_telegram_link_info(link)
        if not link_info:
            await update.message.reply_text("عذراً، الرابط غير صالح. يرجى إرسال رابط من تليجرام.")
            return None

        # إنشاء مجلد للفيديوهات إذا لم يكن موجوداً
        os.makedirs("videos", exist_ok=True)
        
        # الاتصال بتليجرام وتحميل الفيديو
        async with client:
            # تكوين العميل مع إعدادات محسنة
            client.connection_retries = 5
            client.retry_delay = 1
            client.flood_sleep_threshold = 60
            
            # الحصول على الرسالة
            channel = await client.get_entity(link_info['channel'])
            message = await client.get_messages(channel, ids=link_info['message_id'])
            
            if not message or not message.media:
                await update.message.reply_text("لم يتم العثور على فيديو في الرابط المحدد.")
                return None
            
            # تحميل الفيديو
            video_path = f"videos/telegram_video_{message.id}.mp4"
            
            # إرسال رسالة التقدم الأولية
            progress_message = await update.message.reply_text(
                "⏳ جاري تجهيز التحميل...\n"
                "🔄 يرجى الانتظار قليلاً"
            )
            
            start_time = datetime.now()
            last_update = {
                "percentage": 0,
                "time": start_time,
                "bytes": 0,
                "speed_samples": []
            }
            
            async def progress_callback(current, total):
                try:
                    # حساب النسبة المئوية
                    percentage = int((current * 100) / total)
                    
                    # تحديث كل 2% فقط وبعد مرور نصف ثانية على الأقل
                    current_time = datetime.now()
                    time_diff = (current_time - last_update["time"]).total_seconds()
                    if percentage == last_update["percentage"] or (time_diff < 0.5 and percentage < 100):
                        return
                    
                    # حساب السرعة الحالية
                    bytes_diff = current - last_update["bytes"]
                    if time_diff > 0:
                        current_speed = bytes_diff / (1024 * 1024 * time_diff)  # MB/s
                        
                        # حفظ آخر 5 عينات للسرعة
                        last_update["speed_samples"].append(current_speed)
                        if len(last_update["speed_samples"]) > 5:
                            last_update["speed_samples"].pop(0)
                        
                        # حساب متوسط السرعة
                        avg_speed = sum(last_update["speed_samples"]) / len(last_update["speed_samples"])
                        
                        # حساب الوقت المتبقي
                        remaining_bytes = total - current
                        eta_seconds = int(remaining_bytes / (avg_speed * 1024 * 1024)) if avg_speed > 0 else 0
                        
                        # تحديث المتغيرات
                        last_update["percentage"] = percentage
                        last_update["time"] = current_time
                        last_update["bytes"] = current
                        
                        # إنشاء شريط التقدم
                        progress_length = 20
                        filled_length = int(progress_length * percentage / 100)
                        progress_bar = "█" * filled_length + "░" * (progress_length - filled_length)
                        
                        # تحديث النص
                        text = (
                            f"⏳ جاري تحميل الفيديو...\n"
                            f"{progress_bar} {percentage}%\n"
                            f"🚀 السرعة: {avg_speed:.1f} MB/s\n"
                            f"⏱ الوقت المتبقي: {eta_seconds // 60} دقيقة و {eta_seconds % 60} ثانية"
                        )
                        
                        await progress_message.edit_text(text)
                    
                except Exception as e:
                    print(f"خطأ في تحديث التقدم: {str(e)}")
            
            try:
                # تحميل الفيديو مع إظهار التقدم
                await message.download_media(
                    file=video_path,
                    progress_callback=progress_callback
                )
                
                # تحديث الرسالة النهائية
                total_time = (datetime.now() - start_time).total_seconds()
                file_size = os.path.getsize(video_path) / (1024 * 1024)  # حجم الملف بالميجابايت
                avg_speed = file_size / total_time  # متوسط السرعة الكلي
                
                await progress_message.edit_text(
                    f"✅ تم تحميل الفيديو بنجاح!\n"
                    f"📁 حجم الملف: {file_size:.1f} MB\n"
                    f"⚡ متوسط السرعة: {avg_speed:.1f} MB/s\n"
                    f"⏱ الوقت المستغرق: {int(total_time // 60)} دقيقة و {int(total_time % 60)} ثانية"
                )
                
                return video_path
                
            except Exception as download_error:
                await progress_message.edit_text(
                    f"❌ فشل تحميل الفيديو\n"
                    f"🔴 السبب: {str(download_error)}"
                )
                return None
            
    except Exception as e:
        await update.message.reply_text(f"حدث خطأ أثناء تحميل الفيديو: {str(e)}")
        return None

async def upload_to_youtube(video_path: str, title: str = None, description: str = None) -> Optional[str]:
    """رفع الفيديو إلى يوتيوب"""
    try:
        # الحصول على بيانات الاعتماد
        creds = get_youtube_credentials()
        if not creds:
            return None
            
        # إنشاء خدمة يوتيوب
        youtube = build('youtube', 'v3', credentials=creds)
        
        # إعداد معلومات الفيديو
        if not title:
            title = os.path.basename(video_path)
        if not description:
            description = f"تم الرفع بواسطة بوت تليجرام في {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        body = {
            'snippet': {
                'title': title,
                'description': description,
                'tags': ['telegram', 'bot', 'upload'],
                'categoryId': '22'
            },
            'status': {
                'privacyStatus': 'private',
                'selfDeclaredMadeForKids': False
            }
        }
        
        # تجهيز ملف الفيديو للرفع
        media = MediaFileUpload(
            video_path,
            chunksize=1024*1024,
            resumable=True
        )
        
        # رفع الفيديو
        insert_request = youtube.videos().insert(
            part=','.join(body.keys()),
            body=body,
            media_body=media
        )
        
        response = None
        while response is None:
            status, response = insert_request.next_chunk()
            if status:
                print(f"تم رفع {int(status.progress() * 100)}%")
        
        video_id = response['id']
        return f"https://youtu.be/{video_id}"
        
    except Exception as e:
        print(f"خطأ في رفع الفيديو: {e}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """الرد على أمر /start"""
    await update.message.reply_text(
        "👋 مرحباً بك في بوت رفع الفيديوهات إلى يوتيوب!\n\n"
        "يمكنك إرسال:\n"
        "1️⃣ فيديو مباشرة\n"
        "2️⃣ رابط فيديو من تليجرام\n\n"
        "سأطلب منك عنوان ووصف للفيديو قبل رفعه 🚀"
    )

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة الفيديو المستلم"""
    try:
        # تحميل الفيديو من تليجرام
        video_path = await download_from_telegram(update.message.video, update, context)
        if not video_path:
            await update.message.reply_text("❌ فشل تحميل الفيديو من تليجرام.")
            return

        # سؤال المستخدم عن العنوان
        await update.message.reply_text(
            "🎬 هل تريد تغيير عنوان الفيديو؟",
            reply_markup=ReplyKeyboardMarkup([['نعم', 'لا']], one_time_keyboard=True)
        )
        context.user_data['video_path'] = video_path
        return CHOOSE_TITLE

    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {str(e)}")

async def choose_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة اختيار العنوان"""
    response = update.message.text
    if response == 'نعم':
        await update.message.reply_text(
            "📝 أرسل العنوان الجديد للفيديو:",
            reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_TITLE
    else:
        context.user_data['title'] = None
        await update.message.reply_text(
            "📝 هل تريد إضافة وصف للفيديو؟",
            reply_markup=ReplyKeyboardMarkup([['نعم', 'لا']], one_time_keyboard=True)
        )
        return CHOOSE_DESCRIPTION

async def waiting_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة إدخال العنوان"""
    context.user_data['title'] = update.message.text
    await update.message.reply_text(
        "📝 هل تريد إضافة وصف للفيديو؟",
        reply_markup=ReplyKeyboardMarkup([['نعم', 'لا']], one_time_keyboard=True)
    )
    return CHOOSE_DESCRIPTION

async def choose_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة اختيار الوصف"""
    response = update.message.text
    if response == 'نعم':
        await update.message.reply_text(
            "📝 أرسل وصف الفيديو:",
            reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_DESCRIPTION
    else:
        context.user_data['description'] = None
        return await finish_upload(update, context)

async def waiting_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة إدخال الوصف"""
    context.user_data['description'] = update.message.text
    return await finish_upload(update, context)

async def finish_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """إنهاء عملية الرفع"""
    try:
        video_path = context.user_data.get('video_path')
        title = context.user_data.get('title')
        description = context.user_data.get('description')
        
        # رفع الفيديو إلى يوتيوب
        video_url = await upload_to_youtube(video_path, title, description)
        
        if video_url:
            await update.message.reply_text(
                f"✅ تم رفع الفيديو بنجاح!\n"
                f"🔗 رابط الفيديو: {video_url}",
                reply_markup=ReplyKeyboardRemove()
            )
        else:
            await update.message.reply_text(
                "❌ فشل رفع الفيديو إلى يوتيوب.",
                reply_markup=ReplyKeyboardRemove()
            )

        # حذف الفيديو المحلي
        if os.path.exists(video_path):
            os.remove(video_path)
            
        # تنظيف بيانات المستخدم
        context.user_data.clear()
        return ConversationHandler.END

    except Exception as e:
        await update.message.reply_text(
            f"❌ حدث خطأ: {str(e)}",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة الرسائل النصية"""
    if not update.message or not update.message.text:
        return

    text = update.message.text

    # التحقق مما إذا كان النص رابط تليجرام
    if 't.me/' in text:
        video_path = await download_from_telegram_link(text, update)
        if video_path:
            context.user_data['video_path'] = video_path
            await update.message.reply_text(
                "🎬 هل تريد تغيير عنوان الفيديو؟",
                reply_markup=ReplyKeyboardMarkup([['نعم', 'لا']], one_time_keyboard=True)
            )
            return CHOOSE_TITLE
    else:
        await update.message.reply_text(
            "🤔 عذراً، لم أفهم رسالتك.\n\n"
            "يمكنك إرسال:\n"
            "1️⃣ فيديو مباشرة\n"
            "2️⃣ رابط فيديو من تليجرام"
        )

async def main() -> None:
    """تشغيل البوت"""
    # إنشاء التطبيق
    application = Application.builder().token(os.getenv('TELEGRAM_BOT_TOKEN')).build()

    # إضافة محادثة لمعالجة الفيديو
    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.VIDEO, handle_video),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
        ],
        states={
            CHOOSE_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_title)],
            WAITING_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, waiting_title)],
            CHOOSE_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_description)],
            WAITING_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, waiting_description)],
        },
        fallbacks=[]
    )

    # إضافة المعالجات
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)

    # تشغيل البوت
    await application.run_polling()

if __name__ == '__main__':
    print("🚀 جاري بدء تشغيل البوت...")
    try:
        # تشغيل البوت باستخدام asyncio
        import asyncio
        import nest_asyncio
        nest_asyncio.apply()
        print("✅ تم تطبيق nest_asyncio")
        
        asyncio.run(main())
    except Exception as e:
        print(f"❌ حدث خطأ أثناء تشغيل البوت: {str(e)}")
        import traceback
        print(traceback.format_exc())
