import yt_dlp
import re

class YoutubeObj:
    def __init__(self, link: str):
        self.link = link

    @staticmethod
    def is_url(text: str) -> bool:
        regex = re.compile(
            r'^(https?://)?(www\.)?((youtube\.com/)|(youtu\.be/))[\w\-\?=&#./]+$'
        )
        return re.match(regex, text) is not None
    

    def Download(self, save_path: str = None) -> dict | None:
        try:
            ydl_opts = {
                'outtmpl': f'{save_path}/%(title)s.%(ext)s' if save_path else '%(title)s.%(ext)s',
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract info and download
                info = ydl.extract_info(self.link, download=True)
            
            print("Download completed successfully.")
            
            return {
                "title": info.get("title"),
                "duration": info.get("duration"),
                "uploader": info.get("uploader"),
                "filename": ydl.prepare_filename(info),
                "webpage_url": info.get("webpage_url"),
            }

        except Exception as e:
            print(f"An error occurred: {e}")
            return None