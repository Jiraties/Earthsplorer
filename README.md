# Earthsplorer

Why use a mouse and keyboard when the world was meant to be explored like a game? Connect your DualSense Controller and enjoy google street view like a game.

## Install Libraries

For Mac

```
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

For Windows

```
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Make sure your DualSense Controller is connected
and add Google Maps Javascript API Key in .env

## Start Game

```
python main.py
python main.py --mock-controller
python main.py --start=13.73830,100.52956 --port 8765
```
