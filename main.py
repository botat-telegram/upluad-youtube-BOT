from config.config import Configs
from src.users import Users
from telebot import TeleBot
from src.youtube import YoutubeObj
from src.mp4_to_mp3 import convertToMp3
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
import os

bot = TeleBot(Configs["bot_token"])

@bot.message_handler(commands=["start"])
def start(msg):
    Users[msg.chat.id] = {
        "url": "",
        "video_path": "",
        "audio_path": ""
    }
    bot.send_message(msg.chat.id, "🎬 Send me a YouTube link to download and convert it to audio!")


@bot.message_handler(func=lambda msg: YoutubeObj.is_url(msg.text))
def send_url(msg):
    chat_id = msg.chat.id
    text = msg.text

    if chat_id not in Users:
        Users[chat_id] = {
            "url": str(text),
            "video_path": "",
            "audio_path": ""
        }
    else:
        Users[chat_id]["url"] = text

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("Download video", callback_data="download_video"),
        InlineKeyboardButton("Download audio", callback_data="download_audio")
    )

    bot.reply_to(
        msg,
        "What would you like to download?",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data == "download_video")
def download_video(call):
    chat_id = call.message.chat.id
    video_url = Users[chat_id]["url"]

    if not video_url:
        bot.send_message(chat_id, "⚠️ Please send a valid YouTube link first.")
        return
    
    try:
        youtube = YoutubeObj(video_url)

        bot.send_message(chat_id, "📥 Downloading video...")

        video_path = youtube.Download(Configs["videos_path"])["filename"]
        Users[chat_id]["video_path"] = video_path
        
        bot.send_message(chat_id=chat_id, text="The video will be sent in a few minutes. Please be patient... ⏳")

        with open(video_path, 'rb') as video_file:
            bot.send_video(chat_id, video_file)

    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {str(e)}")


@bot.callback_query_handler(func=lambda call: call.data == "download_audio")
def download_audio(call):
    chat_id = call.message.chat.id
    video_url = Users[chat_id]["url"]

    if not video_url:
        bot.send_message(chat_id, "⚠️ Please send a valid YouTube link first.")
        return
    
    try:
        youtube = YoutubeObj(video_url)

        bot.send_message(chat_id, "📥 Downloading video to convert to audio...")

        video_path = youtube.Download(Configs["videos_path"])
        if not video_path or "filename" not in video_path:
            bot.send_message(chat_id, "❌ Failed to download video.")
            return

        Users[chat_id]["video_path"] = video_path["filename"]

        print(f"Downloaded video path: {Users[chat_id]}")

        audio_filename = f"{video_path['title']}.mp3"  
        audio_path = os.path.join(Configs["audios_path"], audio_filename)

        audio_path = convertToMp3(video_path["filename"], audio_path)  
        Users[chat_id]["audio_path"] = audio_path

        bot.send_message(chat_id=chat_id, text="The audio will be sent in a few minutes. Please be patient... ⏳")

        with open(audio_path, 'rb') as audio_file:
            bot.send_audio(chat_id, audio_file)

    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {str(e)}")
        print(f"Error in downloading audio: {str(e)}")


bot.polling()
