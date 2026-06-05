import os
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from dotenv import load_dotenv

# Cargar las variables de entorno
load_dotenv()

app = FastAPI(title="Bingo Async Platform - Full Engine")

# ===== CONFIGURACIÓN DE CORS =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Variables de entorno de Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("❌ ERROR: No se encontraron las variables de entorno en el archivo .env")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

# Modelos de datos (Pydantic)
class UserRegister(BaseModel):
    username: str
    player_name: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str


# =====================================================================
# 🏠 SISTEMA DE RUTAS WEB (FRONTEND INTEGRADO)
# =====================================================================

def cargar_template(nombre_archivo: str) -> str:
    """Función auxiliar para leer de forma segura los archivos HTML."""
    try:
        with open(f"templates/{nombre_archivo}", "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, 
            detail=f"Mano, no encontré el archivo '{nombre_archivo}' dentro de la carpeta 'templates'."
        )

@app.get("/", response_class=HTMLResponse)
async def read_login():
    return cargar_template("Login.html")

@app.get("/registro", response_class=HTMLResponse)
async def read_registro():
    return cargar_template("registro.html")

@app.get("/menu", response_class=HTMLResponse)
async def read_menu():
    return cargar_template("menu.html")

@app.get("/opciones", response_class=HTMLResponse)
async def read_opciones():
    return cargar_template("opciones.html")

@app.get("/lobby", response_class=HTMLResponse)
async def read_lobby():
    return cargar_template("lobby.html")

@app.get("/juego", response_class=HTMLResponse)
async def read_juego():
    return cargar_template("juego.html")

@app.get("/ganador", response_class=HTMLResponse)
async def read_ganador():
    return cargar_template("ganador.html")

@app.get("/perdedor", response_class=HTMLResponse)
async def read_perdedor():
    return cargar_template("perdedor.html")


# =====================================================================
# 🔐 ENDPOINTS DE LA API (AUTENTICACIÓN & LÓGICA)
# =====================================================================

@app.post("/auth/register")
async def register(user: UserRegister):
    async with httpx.AsyncClient() as client:
        try:
            url_check = f"{SUPABASE_URL}/rest/v1/usuarios?username=eq.{user.username}"
            res_check = await client.get(url_check, headers=HEADERS)
            
            if res_check.status_code != 200:
                raise HTTPException(status_code=res_check.status_code, detail="Error de comunicación con DB.")
            
            if len(res_check.json()) > 0:
                raise HTTPException(status_code=400, detail="Ese usuario ya está registrado, bro.")
            
            url_insert = f"{SUPABASE_URL}/rest/v1/usuarios"
            payload = {"username": user.username, "player_name": user.player_name, "password": user.password}
            res_insert = await client.post(url_insert, headers=HEADERS, json=payload)
            
            if res_insert.status_code not in [200, 201]:
                raise HTTPException(status_code=res_insert.status_code, detail="Error al guardar usuario.")
                
            return {"message": "¡Usuario registrado con éxito!", "user": user.username}
        except HTTPException as http_ex:
            raise http_ex
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/auth/login")
async def login(user: UserLogin):
    async with httpx.AsyncClient() as client:
        try:
            url_login = f"{SUPABASE_URL}/rest/v1/usuarios?username=eq.{user.username}"
            res = await client.get(url_login, headers=HEADERS)
            
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
        except HTTPException as http_ex:
            raise http_ex
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))