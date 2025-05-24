from fastapi import FastAPI, Depends, HTTPException, status, Header, Security
from fastapi.security import OAuth2PasswordBearer, HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime
import httpx
from jose import jwt
import uuid
from kafka import KafkaProducer
import json
import redis
import os
import time
import logging
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Index, func, Numeric
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("service_app.log")]
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Service API", 
              description="API для управления услугами",
              version="1.0.0")

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "secret_key")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://localhost:8000")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{USER_SERVICE_URL}/token")
http_bearer = HTTPBearer()

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")
KAFKA_TOPIC = 'service_created'

REDIS_HOST = 'redis'
REDIS_PORT = 6379

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/services_db")
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    connect_args={"connect_timeout": 10}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def wait_for_kafka(max_retries=30, retry_interval=2):
    """Ожидание Kafka"""
    for i in range(max_retries):
        try:
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )
            producer.close()
            print("Successfully connected to Kafka")
            return True
        except Exception as e:
            print(f"Attempt {i+1}/{max_retries}: Kafka not available yet. Error: {e}")
            if i < max_retries - 1:
                time.sleep(retry_interval)
    return False

producer = None

@app.on_event("startup")
async def startup_event():
    global producer
    print("Waiting for Kafka to become available...")
    if not wait_for_kafka():
        print("Failed to connect to Kafka after maximum retries")
        return
    
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

class ServiceModel(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(String)
    price = Column(Numeric(10, 2), nullable=False)
    specialist_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        Index('idx_services_specialist_id', specialist_id),
    )

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class ServiceBase(BaseModel):
    title: str
    description: str
    price: float
    specialist_id: int


class ServiceCreate(ServiceBase):
    pass


class Service(ServiceBase):
    id: int
    created_at: datetime

    class Config:
        orm_mode = True


async def validate_token(token: str):
    """Валидация JWT токена"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {"username": username}
    except jwt.ExpiredSignatureError:
        logger.warning("Token expired")
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        logger.warning("Invalid token")
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        logger.error(f"Error validating token: {str(e)}")
        raise HTTPException(status_code=401, detail=f"Error validating token: {str(e)}")

async def get_current_user_oauth(token: str = Depends(oauth2_scheme)):
    logger.info(f"Validating OAuth token: {token[:10]}...")
    return await validate_token(token)

async def get_current_user_bearer(credentials: HTTPAuthorizationCredentials = Security(http_bearer)):
    logger.info(f"Validating Bearer token: {credentials.credentials[:10]}...")
    return await validate_token(credentials.credentials)

async def get_current_user(
    oauth_user: dict = Depends(get_current_user_oauth),
    bearer_user: dict = Security(get_current_user_bearer, use_cache=False)
):
    if bearer_user:
        return bearer_user
    return oauth_user


@app.post("/services/", response_model=Service)
async def create_service(service: ServiceCreate, current_user: dict = Depends(get_current_user)):
    """Создание новой услуги"""
    # проверка, что юзер - специалист
    if current_user["username"] != "admin" and str(service.specialist_id) != current_user["username"]:
        raise HTTPException(status_code=403, detail="You can only create services for yourself")
    
    service_id = int(uuid.uuid4().int % (10**9))
    service_data = service.dict()
    service_data["id"] = service_id
    service_data["created_at"] = datetime.now().isoformat()
    
    if producer is None:
        raise HTTPException(status_code=503, detail="Kafka producer is not available")
    
    producer.send(KAFKA_TOPIC, value=service_data)
    redis_client.hset(f"service:{service_id}", mapping=service_data)
    
    return Service(**service_data)


@app.get("/services/", response_model=List[Service])
async def get_services(db: Session = Depends(get_db)):
    """Получение списка всех услуг"""
    services = []
    for key in redis_client.keys("service:*"):
        service_data = redis_client.hgetall(key)
        if service_data:
            services.append(Service(**service_data))
    
    if not services:
        db_services = db.query(ServiceModel).all()
        services = [Service.from_orm(service) for service in db_services]
        
        for service in services:
            service_dict = service.dict()
            redis_client.hset(f"service:{service.id}", mapping=service_dict)
    
    return services


@app.get("/services/{service_id}", response_model=Service)
async def get_service(service_id: int, db: Session = Depends(get_db)):
    """Получение информации об услуге по ID"""
    service_data = redis_client.hgetall(f"service:{service_id}")
    
    if not service_data:
        db_service = db.query(ServiceModel).filter(ServiceModel.id == service_id).first()
        if not db_service:
            raise HTTPException(status_code=404, detail="Service not found")
        
        service = Service.from_orm(db_service)
        service_dict = service.dict()
        redis_client.hset(f"service:{service_id}", mapping=service_dict)
        return service
    
    return Service(**service_data)


@app.get("/services/specialist/{specialist_id}", response_model=List[Service])
async def get_specialist_services(specialist_id: int, db: Session = Depends(get_db)):
    """Получение всех услуг конкретного специалиста"""
    services = []
    for key in redis_client.keys("service:*"):
        service_data = redis_client.hgetall(key)
        if service_data and int(service_data.get("specialist_id")) == specialist_id:
            services.append(Service(**service_data))
    
    if not services:
        db_services = db.query(ServiceModel).filter(ServiceModel.specialist_id == specialist_id).all()
        services = [Service.from_orm(service) for service in db_services]
        
        for service in services:
            service_dict = service.dict()
            redis_client.hset(f"service:{service.id}", mapping=service_dict)
    
    return services


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
