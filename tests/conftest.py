import os
import sys
from pathlib import Path

# Настройки читаются при импорте app.config — задаём до любых импортов app.*
os.environ.setdefault('BOT_TOKEN', '1:test')
os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///:memory:'

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
