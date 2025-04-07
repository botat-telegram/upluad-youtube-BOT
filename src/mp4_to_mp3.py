from moviepy import VideoFileClip
from pathlib import Path
import os

def convertToMp3(link: str, output_path: str) -> str:
    try:
        if not output_path.endswith('.mp3'):
            output_path = f"{output_path}.mp3"
   
        output_path = Path(output_path).resolve() 

        output_dir = output_path.parent  
        if not output_dir.exists():
            output_dir.mkdir(parents=True) 
        
        with VideoFileClip(link) as video:
            audio = video.audio
            audio.write_audiofile(str(output_path), codec='mp3')

        print(f"Successfully converted {link} to {output_path}")
        
        
        return str(output_path)
    
    except Exception as e:
        print(f"An error occurred: {e}")
        return None 
