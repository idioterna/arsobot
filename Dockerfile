FROM gorialis/discord.py:3.9-alpine

WORKDIR /app

COPY requirements.txt ./
COPY bot.py ./
COPY spam.mp4 ./
COPY settings.py.prod ./settings.py
RUN pip install -r requirements.txt
RUN apk add chromium

ENTRYPOINT ["python", "bot.py"]
