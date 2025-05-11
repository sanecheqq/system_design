from fastapi import FastAPI, Depends, HTTPException, status, Header
from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime
import httpx
import jwt
import uuid

app = FastAPI(title="Service API", 
              description="API для управления услугами",
              version="1.0.0")

SECRET_KEY = "secret_key"
ALGORITHM = "HS256"

services_db: Dict[str, Dict] = {}

class ServiceBase(BaseModel):
    title: str
    description: str
    price: float
    specialist_username: str


class ServiceCreate(ServiceBase):
    pass


class Service(ServiceBase):
    id: str
    created_at: datetime


async def get_current_user(authorization: Optional[str] = Header(None)):
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = authorization.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        return {"username": username}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


@app.post("/services/", response_model=Service)
async def create_service(service: ServiceCreate, current_user: dict = Depends(get_current_user)):
    """Создание новой услуги"""
    # проверка, что юзер - специалист
    
    service_id = str(uuid.uuid4())
    service_data = service.dict()
    service_data["id"] = service_id
    service_data["created_at"] = datetime.now()
    
    services_db[service_id] = service_data
    
    return Service(**service_data)


@app.get("/services/", response_model=List[Service])
async def get_services():
    """Получение списка всех услуг"""
    return [Service(**service) for service in services_db.values()]


@app.get("/services/{service_id}", response_model=Service)
async def get_service(service_id: str):
    """Получение информации об услуге по ID"""
    if service_id not in services_db:
        raise HTTPException(status_code=404, detail="Service not found")
    
    return Service(**services_db[service_id])


@app.get("/services/specialist/{specialist_username}", response_model=List[Service])
async def get_specialist_services(specialist_username: str):
    """Получение всех услуг конкретного специалиста"""
    specialist_services = [
        Service(**service) 
        for service in services_db.values() 
        if service["specialist_username"] == specialist_username
    ]
    
    return specialist_services
