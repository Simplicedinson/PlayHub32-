# run_server.py
import uvicorn
from pathlib import Path
from dotenv import load_dotenv
from main import app


load_dotenv()                       # charge ton .env s’il existe

APP_MODULE = "main:app"         # adapter si ton entry-point change
BASE_DIR = Path(__file__).parent

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        workers=1,                  # 1 suffit sur la machine d’admin
        reload=False,               # PAS de --reload pour l'exe
    )
