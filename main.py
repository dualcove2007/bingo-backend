import os
import asyncio
import random
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import json
from dotenv import load_dotenv
 
load_dotenv()
 
app = FastAPI(title="Bingo Async Platform - Realtime Engine")
 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
 
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
 
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("❌ ERROR: No se encontraron las variables de entorno en el archivo .env")
 
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}
 
class UserRegister(BaseModel):
    username: str
    player_name: str
    password: str
 
class UserLogin(BaseModel):
    username: str
    password: str
 
 
# =====================================================================
# 🌐 LOBBY MANAGER
# =====================================================================
class LobbyManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self._game_starting = False
 
    async def connect(self, websocket: WebSocket, player_name: str):
        await websocket.accept()
        self.active_connections[player_name] = websocket
        await self._broadcast_status_only()
        await self.check_and_start_game()
 
    async def disconnect(self, player_name: str):
        if player_name in self.active_connections:
            del self.active_connections[player_name]
        if len(self.active_connections) < 2:
            self._game_starting = False
        await self._broadcast_status_only()
 
    async def _broadcast_status_only(self):
        lista_jugadores = list(self.active_connections.keys())
        payload = {
            "tipo": "actualizacion_sala",
            "total": len(lista_jugadores),
            "jugadores": lista_jugadores
        }
        disconnected = []
        for name, connection in list(self.active_connections.items()):
            try:
                await connection.send_text(json.dumps(payload))
            except Exception:
                disconnected.append(name)
        for name in disconnected:
            if name in self.active_connections:
                del self.active_connections[name]
 
    async def check_and_start_game(self):
        if self._game_starting:
            return
        if len(self.active_connections) >= 2:
            self._game_starting = True
            await asyncio.sleep(0.5)
            await self._broadcast_start_game()
 
    async def _broadcast_start_game(self):
        payload = {"action": "START_GAME"}
        for connection in list(self.active_connections.values()):
            try:
                await connection.send_text(json.dumps(payload))
            except Exception:
                pass
        self.active_connections.clear()
        self._game_starting = False
 
 
# =====================================================================
# 🎮 GAME MANAGER (PARTIDA EN CURSO)
# =====================================================================
class GameManager:
    def __init__(self):
        # {player_name: {ws, mode}}
        self.players: dict[str, dict] = {}
        self._ball_task = None
        self._called_balls = []
        self._game_active = False
 
    async def connect(self, websocket: WebSocket, player_name: str):
        await websocket.accept()
        self.players[player_name] = {"ws": websocket, "mode": None}
 
    async def disconnect(self, player_name: str):
        if player_name in self.players:
            del self.players[player_name]
        # Si queda un solo jugador y el juego estaba activo, el otro gana
        if self._game_active and len(self.players) == 1:
            winner = list(self.players.keys())[0]
            await self._send(winner, {"tipo": "resultado_bingo", "ganaste": True})
            self._reset()
 
    async def set_mode(self, player_name: str, mode: str):
        if player_name not in self.players:
            return
        self.players[player_name]["mode"] = mode
 
        # Si hay exactamente 2 jugadores con modo registrado, comparar
        if len(self.players) == 2:
            names = list(self.players.keys())
            modes = [self.players[n]["mode"] for n in names]
            if all(m is not None for m in modes):
                if modes[0] == modes[1]:
                    # Modos iguales — arrancar
                    for n in names:
                        await self._send(n, {"tipo": "modo_ok", "mode": modes[0]})
                    if not self._game_active:
                        self._game_active = True
                        self._called_balls = self._generate_balls()
                        self._ball_task = asyncio.create_task(self._broadcast_balls())
                else:
                    # Modos distintos — notificar a cada jugador
                    await self._send(names[0], {
                        "tipo": "modo_mismatch",
                        "my_mode": modes[0],
                        "opponent_mode": modes[1]
                    })
                    await self._send(names[1], {
                        "tipo": "modo_mismatch",
                        "my_mode": modes[1],
                        "opponent_mode": modes[0]
                    })
 
    def _generate_balls(self):
        """Genera lista aleatoria de las 75 balotas estándar."""
        columns = {
            'B': range(1, 16),
            'I': range(16, 31),
            'N': range(31, 46),
            'G': range(46, 61),
            'O': range(61, 76)
        }
        balls = []
        for letter, nums in columns.items():
            for n in nums:
                balls.append({"letra": letter, "numero": n})
        random.shuffle(balls)
        return balls
 
    async def _broadcast_balls(self):
        """Canta una balota cada 5 segundos a todos los jugadores."""
        for ball in self._called_balls:
            if not self._game_active:
                break
            await asyncio.sleep(5)
            payload = {"tipo": "balota", **ball}
            for name in list(self.players.keys()):
                await self._send(name, payload)
 
    async def handle_bingo_claim(self, claimer: str, data: dict):
        """Valida si el jugador que cantó bingo realmente ganó."""
        if not self._game_active:
            return
 
        marked = set(data.get("marked", []))
        called = set(data.get("called", []))
        card = data.get("card", [])   # lista de 5 columnas, cada una con 5 números
        mode = data.get("mode", "carton_lleno")
 
        valid = self._validate_bingo(marked, called, card, mode)
 
        if valid:
            self._game_active = False
            if self._ball_task:
                self._ball_task.cancel()
            # Notificar a todos
            for name in list(self.players.keys()):
                ganaste = (name == claimer)
                await self._send(name, {"tipo": "resultado_bingo", "ganaste": ganaste})
            self._reset()
        else:
            # Bingo inválido — avisar solo al que lo cantó
            await self._send(claimer, {
                "tipo": "bingo_invalido",
                "mensaje": "Tu cartón no cumple las condiciones todavía. ¡Sigue jugando!"
            })
 
    def _validate_bingo(self, marked: set, called: set, card: list, mode: str) -> bool:
        """
        Valida que todas las posiciones del patrón estén:
        1. Marcadas por el jugador
        2. Con números que el servidor efectivamente cantó
        """
        pattern = self._get_pattern(mode)
        for (col, row) in pattern:
            pos = f"{col}-{row}"
            if pos not in marked:
                return False
            num = card[col][row]
            if num not in called:
                return False
        return True
 
    def _get_pattern(self, mode: str):
        """Devuelve lista de (col, row) que forman el patrón."""
        positions = []
        for col in range(5):
            for row in range(5):
                if col == 2 and row == 2:
                    continue  # FREE
                include = False
                if mode == 'carton_lleno':
                    include = True
                elif mode == 'en_x':
                    include = (col == row) or (col + row == 4)
                elif mode == 'en_o':
                    include = (row == 0 or row == 4 or col == 0 or col == 4)
                elif mode == 'en_l':
                    include = (col == 0 or row == 4)
                if include:
                    positions.append((col, row))
        return positions
 
    async def _send(self, player_name: str, payload: dict):
        if player_name in self.players:
            try:
                await self.players[player_name]["ws"].send_text(json.dumps(payload))
            except Exception:
                pass
 
    def _reset(self):
        self.players.clear()
        self._called_balls = []
        self._game_active = False
        self._ball_task = None
 
 
lobby_manager = LobbyManager()
game_manager = GameManager()
 
 
# =====================================================================
# 🏠 RUTAS WEB
# =====================================================================
def cargar_template(nombre_archivo: str) -> str:
    try:
        with open(f"templates/{nombre_archivo}", "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No encontré '{nombre_archivo}' en templates/.")
 
@app.get("/", response_class=HTMLResponse)
async def read_login(): return cargar_template("login.html")
 
@app.get("/registro", response_class=HTMLResponse)
async def read_registro(): return cargar_template("registro.html")
 
@app.get("/menu", response_class=HTMLResponse)
async def read_menu(): return cargar_template("menu.html")
 
@app.get("/opciones", response_class=HTMLResponse)
async def read_opciones(): return cargar_template("opciones.html")
 
@app.get("/lobby", response_class=HTMLResponse)
async def read_lobby(): return cargar_template("lobby.html")
 
@app.get("/juego", response_class=HTMLResponse)
async def read_juego(): return cargar_template("juego.html")
 
@app.get("/ganador", response_class=HTMLResponse)
async def read_ganador(): return cargar_template("ganador.html")
 
@app.get("/perdedor", response_class=HTMLResponse)
async def read_perdedor(): return cargar_template("perdedor.html")
 
 
# =====================================================================
# ⚡ WEBSOCKETS
# =====================================================================
@app.websocket("/ws/lobby/{player_name}")
async def websocket_lobby(websocket: WebSocket, player_name: str):
    await lobby_manager.connect(websocket, player_name)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await lobby_manager.disconnect(player_name)
    except Exception:
        await lobby_manager.disconnect(player_name)
 
 
@app.websocket("/ws/juego/{player_name}")
async def websocket_juego(websocket: WebSocket, player_name: str):
    await game_manager.connect(websocket, player_name)
    try:
        while True:
            raw = await websocket.receive_text()
            if raw == "PING":
                await websocket.send_text("PONG")
                continue
            try:
                data = json.loads(raw)
                if data.get("tipo") == "modo_juego":
                    await game_manager.set_mode(player_name, data["mode"])
                elif data.get("tipo") == "claim_bingo":
                    await game_manager.handle_bingo_claim(player_name, data)
            except Exception as e:
                print(f"Error procesando mensaje de {player_name}: {e}")
    except WebSocketDisconnect:
        await game_manager.disconnect(player_name)
    except Exception:
        await game_manager.disconnect(player_name)
 
 
# =====================================================================
# 🔐 AUTENTICACIÓN
# =====================================================================
@app.post("/auth/register")
async def register(user: UserRegister):
    async with httpx.AsyncClient() as client:
        try:
            res_check = await client.get(
                f"{SUPABASE_URL}/rest/v1/usuarios?username=eq.{user.username}", headers=HEADERS)
            if res_check.status_code != 200:
                raise HTTPException(status_code=res_check.status_code, detail="Error de comunicación con DB.")
            if len(res_check.json()) > 0:
                raise HTTPException(status_code=400, detail="Ese usuario ya está registrado, bro.")
            payload = {"username": user.username, "player_name": user.player_name, "password": user.password}
            res_insert = await client.post(f"{SUPABASE_URL}/rest/v1/usuarios", headers=HEADERS, json=payload)
            if res_insert.status_code not in [200, 201]:
                raise HTTPException(status_code=res_insert.status_code, detail="Error al guardar usuario.")
            return {"message": "¡Usuario registrado con éxito!", "user": user.username}
        except HTTPException as e:
            raise e
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
 
@app.post("/auth/login")
async def login(user: UserLogin):
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(
                f"{SUPABASE_URL}/rest/v1/usuarios?username=eq.{user.username}", headers=HEADERS)
            if res.status_code != 200:
                raise HTTPException(status_code=res.status_code, detail="Error en consulta.")
            datos = res.json()
            if len(datos) == 0:
                raise HTTPException(status_code=404, detail="Ese usuario no existe, mano.")
            db_user = datos[0]
            if db_user["password"] != user.password:
                raise HTTPException(status_code=401, detail="Contraseña incorrecta, pa.")
            return {
                "message": "¡Ingreso exitoso!",
                "player_name": db_user["player_name"],
                "username": db_user["username"]
            }
        except HTTPException as e:
            raise e
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
 