import io
from pydub import AudioSegment

def convert_ogg_to_wav(ogg_data: bytes) -> bytes:
    """Конвертирует OGG Opus в WAV"""
    ogg_io = io.BytesIO(ogg_data)
    audio = AudioSegment.from_file(ogg_io, format="ogg")
    
    wav_io = io.BytesIO()
    audio.export(wav_io, format="wav")
    return wav_io.getvalue()
