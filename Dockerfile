FROM gorialis/discord.py:3.9-alpine

WORKDIR /app

COPY requirements.txt ./
COPY bot.py ./
COPY settings.py.prod ./settings.py
RUN pip install -r requirements.txt

ENTRYPOINT ["python", "bot.py"]
