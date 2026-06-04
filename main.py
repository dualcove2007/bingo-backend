import os
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse  # <-- Importación para servir HTML
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from dotenv import load_dotenv

# Cargar las variables de entorno
load_dotenv()

app = FastAPI(title="Bingo Platform")

# ===== CONFIGURACIÓN DE CORS =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permite conexiones desde cualquier origen
    allow_credentials=True,
    allow_methods=["*"],  # Permite POST, GET, PUT, DELETE, etc.
    allow_headers=["*"],
)

# Ahora las variables se leen de forma segura desde el entorno (.env o Render)
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
# 🏠 RUTAS DE FRONTEND INTEGRADO (SERVIR PÁGINAS WEB HTML)
# =====================================================================

@app.get("/", response_class=HTMLResponse)
async def read_login():
    """Ruta raíz: Carga directamente la interfaz de Login."""
    try:
        with open("templates/Login.html", "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, 
            detail="Mano, no encontré el archivo 'Login.html' dentro de la carpeta 'templates'."
        )

@app.get("/registro", response_class=HTMLResponse)
async def read_registro():
    """Ruta secundaria: Carga directamente la interfaz de Registro."""
    try:
        with open("templates/Registro.html", "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, 
            detail="Mano, no encontré el archivo 'Registro.html' dentro de la carpeta 'templates'."
        )


# =====================================================================
# 🔐 ENDPOINTS DE LA API (PROCESAMIENTO DE DATOS / AUTENTICACIÓN)
# =====================================================================

@app.post("/auth/register")
async def register(user: UserRegister):
    async with httpx.AsyncClient() as client:
        try:
            # 1. Verificar si el usuario ya existe en Supabase
            url_check = f"{SUPABASE_URL}/rest/v1/usuarios?username=eq.{user.username}"
            res_check = await client.get(url_check, headers=HEADERS)
            
            if res_check.status_code != 200:
                raise HTTPException(
                    status_code=res_check.status_code, 
                    detail=f"Error de autenticación con Supabase. Verifica tu API KEY. Detalles: {res_check.text}"
                )
            
            if len(res_check.json()) > 0:
                raise HTTPException(status_code=400, detail="Ese usuario ya está registrado, bro.")
            
            # 2. Insertar nuevo usuario si el username está libre
            url_insert = f"{SUPABASE_URL}/rest/v1/usuarios"
            payload = {
                "username": user.username,
                "player_name": user.player_name,
                "password": user.password
            }
            
            res_insert = await client.post(url_insert, headers=HEADERS, json=payload)
            
            if res_insert.status_code not in [200, 201]:
                raise HTTPException(
                    status_code=res_insert.status_code, 
                    detail=f"Supabase rechazó los datos. Detalles: {res_insert.text}"
                )
                
            return {"message": "¡Usuario registrado con éxito, pa!", "user": user.username}

        except HTTPException as http_ex:
            raise http_ex
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.post("/auth/login")
async def login(user: UserLogin):
    async with httpx.AsyncClient() as client:
        try:
            url_login = f"{SUPABASE_URL}/rest/v1/usuarios?username=eq.{user.username}"
            res = await client.get(url_login, headers=HEADERS)
            
            if res.status_code != 200:
                raise HTTPException(status_code=res.status_code, detail=f"Error en login base de datos: {res.text}")
                
            datos = res.json()
            if len(datos) == 0:
                raise HTTPException(status_code=404, detail="Ese usuario no existe, mano.")
                
            db_user = datos[0]
            
            if db_user["password"] != user.password:
                raise HTTPException(status_code=401, detail="Contraseña incorrecta, pa.")
                
            return {
                "message": "¡Ingreso exitoso a la sala!",
                "player_name": db_user["player_name"],
                "username": db_user["username"]
            }
            
        except HTTPException as http_ex:
            raise http_ex
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal login error: {str(e)}")