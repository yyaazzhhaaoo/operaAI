from datetime import datetime

from pydantic import BaseModel, ConfigDict

class DemoLibraryOut(BaseModel):
    model_config = ConfigDict(from_attributes = True)
    id:int
    title:str
    role:str
    banshi:str
    audio_id:int | None = None
    elo_difficulty:float
    created_at: datetime