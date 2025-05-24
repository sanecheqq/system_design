import os
import time
import logging
import json
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Index, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
import redis
from functools import wraps
import time

time.sleep(5)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("user_app.log")
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI(title="User API", 
              description="API для управления пользователями (заказчиками и специалистами)",
              version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "secret_key")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
CACHE_EXPIRE_SECONDS = 300  # 5 min

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/services_db")
engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=3600,
        connect_args={"connect_timeout": 10}
    )
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


redis_client = redis.from_url(REDIS_URL, decode_responses=True)

class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    full_name = Column(String(100))
    email = Column(String(100))
    hashed_password = Column(String(100), nullable=False)
    is_specialist = Column(Boolean, default=False, nullable=False)
    disabled = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        Index('idx_users_username', username),
        Index('idx_users_full_name', full_name),
        Index('idx_users_email', email),
    )

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def benchmark(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        result = await func(*args, **kwargs)
        execution_time = time.time() - start_time
        logger.info(f"Function {func.__name__} took {execution_time:.4f} seconds to execute")
        return result
    return wrapper

class UserBase(BaseModel):
    username: str
    full_name: str
    email: EmailStr
    is_specialist: bool = False

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: Optional[int] = None
    disabled: bool = False
    created_at: Optional[datetime] = None

    class Config:
        orm_mode = True

class UserInDB(User):
    hashed_password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

def serialize_user(user: Any) -> str:
    """Сериализация пользователя в JSON строку"""
    if isinstance(user, UserModel):
        user_dict = {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "email": user.email,
            "is_specialist": user.is_specialist,
            "disabled": user.disabled,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "hashed_password": user.hashed_password 
        }
        return json.dumps(user_dict)
    elif isinstance(user, dict):
        if user.get("created_at") and isinstance(user["created_at"], datetime):
            user["created_at"] = user["created_at"].isoformat()
        return json.dumps(user)
    else:
        raise ValueError(f"Unsupported type for serialization: {type(user)}")

def deserialize_user(json_str: str) -> dict:
    """Десериализация пользователя из JSON строки"""
    return json.loads(json_str)

def get_user_cache_key(username: str) -> str:
    """Получение ключа кеша для пользователя по логину"""
    return f"user:username:{username}"

def get_user_id_cache_key(user_id: int) -> str:
    """Получение ключа кеша для пользователя по ID"""
    return f"user:id:{user_id}"

def get_search_cache_key(name_mask: str) -> str:
    """Получение ключа кеша для поиска пользователей по маске имени"""
    return f"search:name:{name_mask}"

def get_specialists_cache_key() -> str:
    """Получение ключа кеша для списка специалистов"""
    return "specialists:all"

def get_user_by_username(db: Session, username: str):
    cache_key = get_user_cache_key(username)
    cached_user = redis_client.get(cache_key)
    
    if cached_user:
        logger.info(f"Cache HIT for user: {username}")
        return deserialize_user(cached_user)
    
    logger.info(f"Cache MISS for user: {username}")
    user = db.query(UserModel).filter(UserModel.username == username).first()
    
    if user:
        redis_client.setex(cache_key, CACHE_EXPIRE_SECONDS, serialize_user(user))
        redis_client.setex(get_user_id_cache_key(user.id), CACHE_EXPIRE_SECONDS, serialize_user(user))
    
    return user

async def get_user_by_username_no_cache(db: Session, username: str):
    """Получение пользователя по логину в обход кеша"""
    logger.info(f"Direct database query for user: {username}")
    return db.query(UserModel).filter(UserModel.username == username).first()

def get_user_by_id(db: Session, user_id: int):
    cache_key = get_user_id_cache_key(user_id)
    cached_user = redis_client.get(cache_key)
    
    if cached_user:
        logger.info(f"Cache HIT for user ID: {user_id}")
        return deserialize_user(cached_user)
    
    logger.info(f"Cache MISS for user ID: {user_id}")
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    
    if user:
        redis_client.setex(cache_key, CACHE_EXPIRE_SECONDS, serialize_user(user))
        redis_client.setex(get_user_cache_key(user.username), CACHE_EXPIRE_SECONDS, serialize_user(user))
    
    return user

async def get_user_by_id_no_cache(db: Session, user_id: int):
    """Получение пользователя по ID без использования кеша"""
    logger.info(f"Direct database query for user ID: {user_id}")
    return db.query(UserModel).filter(UserModel.id == user_id).first()

def create_db_user(db: Session, user: UserCreate, hashed_password: str):
    db_user = UserModel(
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        is_specialist=user.is_specialist,
        hashed_password=hashed_password
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    redis_client.setex(get_user_cache_key(db_user.username), CACHE_EXPIRE_SECONDS, serialize_user(db_user))
    redis_client.setex(get_user_id_cache_key(db_user.id), CACHE_EXPIRE_SECONDS, serialize_user(db_user))
    
    redis_client.delete(get_specialists_cache_key())
    
    return db_user

def search_users_by_name(db: Session, name_mask: str):
    cache_key = get_search_cache_key(name_mask)
    cached_results = redis_client.get(cache_key)
    
    if cached_results:
        logger.info(f"Cache HIT for search: {name_mask}")
        return [deserialize_user(user) for user in json.loads(cached_results)]
    
    logger.info(f"Cache MISS for search: {name_mask}")
    search_pattern = f"%{name_mask}%"
    users = db.query(UserModel).filter(UserModel.full_name.ilike(search_pattern)).all()
    
    if users:
        serialized_users = [serialize_user(user) for user in users]
        redis_client.setex(cache_key, CACHE_EXPIRE_SECONDS, json.dumps(serialized_users))
    
    return users

async def search_users_by_name_no_cache(db: Session, name_mask: str):
    """Поиск пользователей по маске имени и фамилии без использования кеша"""
    logger.info(f"Direct database query for search: {name_mask}")
    search_pattern = f"%{name_mask}%"
    return db.query(UserModel).filter(UserModel.full_name.ilike(search_pattern)).all()

def get_specialists(db: Session):
    cache_key = get_specialists_cache_key()
    cached_results = redis_client.get(cache_key)
    
    if cached_results:
        logger.info("Cache HIT for specialists list")
        return [deserialize_user(user) for user in json.loads(cached_results)]
    
    logger.info("Cache MISS for specialists list")
    specialists = db.query(UserModel).filter(UserModel.is_specialist == True).all()
    
    if specialists:
        serialized_specialists = [serialize_user(specialist) for specialist in specialists]
        redis_client.setex(cache_key, CACHE_EXPIRE_SECONDS, json.dumps(serialized_specialists))
    
    return specialists

async def get_specialists_no_cache(db: Session):
    """Получение списка всех специалистов без использования кеша"""
    logger.info("Direct database query for specialists list")
    return db.query(UserModel).filter(UserModel.is_specialist == True).all()

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def authenticate_user(db: Session, username: str, password: str):
    user = get_user_by_username(db, username)
    if not user:
        return False
    
    if isinstance(user, dict):
        if not verify_password(password, user.get("hashed_password", "")):
            return False
        return user
    else:
        if not verify_password(password, user.hashed_password):
            return False
        return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        logger.warning("Invalid token")
        raise credentials_exception
    
    user = get_user_by_username(db, username=token_data.username)
    if user is None:
        logger.warning(f"User {username} not found")
        raise credentials_exception
    return user

@app.on_event("startup")
async def startup_db():
    logger.info("Initializing database...")
    try:
        redis_client.ping()
        logger.info("Redis connection successful")
    except redis.ConnectionError as e:
        logger.error(f"Redis connection failed: {e}")
        
    db = SessionLocal()
    try:
        admin_user = get_user_by_username(db, "admin")
        if not admin_user:
            hashed_password = get_password_hash("secret")
            admin_user = UserModel(
                username="admin",
                full_name="Admin User",
                email="admin@example.com",
                hashed_password=hashed_password,
                is_specialist=False
            )
            db.add(admin_user)
            db.commit()
            logger.info("Test user 'admin' created")
        
        specialist_user = get_user_by_username(db, "specialist1")
        if not specialist_user:
            hashed_password = get_password_hash("specialist123")
            specialist_user = UserModel(
                username="specialist1",
                full_name="Test Specialist",
                email="specialist@example.com",
                hashed_password=hashed_password,
                is_specialist=True
            )
            db.add(specialist_user)
            db.commit()
            logger.info("Test specialist 'specialist1' created")
        
        logger.info("Database initialization completed")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
    finally:
        db.close()

@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        logger.warning(f"Failed login attempt for user: {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    username = user.username if isinstance(user, UserModel) else user.get("username")
    access_token = create_access_token(
        data={"sub": username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/users/", response_model=User, status_code=201)
async def create_user(user: UserCreate, db: Session = Depends(get_db)):
    """Создание нового пользователя"""
    logger.info(f"Creating user: {user.username}")
    db_user = get_user_by_username(db, username=user.username)
    if db_user:
        logger.warning(f"Username {user.username} already exists")
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed_password = get_password_hash(user.password)
    db_user = create_db_user(db=db, user=user, hashed_password=hashed_password)
    return db_user

@app.get("/users/me", response_model=User)
async def read_users_me(current_user: UserModel = Depends(get_current_user)):
    """Получение информации о текущем пользователе"""
    return current_user

@app.get("/users/{username}", response_model=User)
@benchmark
async def read_user(username: str, db: Session = Depends(get_db)):
    """Получение информации о пользователе по логину"""
    user = get_user_by_username(db, username=username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@app.get("/users/search/", response_model=List[User])
@benchmark
async def search_users_by_name(name_mask: str, db: Session = Depends(get_db)):
    """Поиск пользователей по маске имени и фамилии"""
    logger.info(f"Searching users by name: {name_mask}")
    users = search_users_by_name(db, name_mask)
    return users

@app.get("/specialists/", response_model=List[User])
@benchmark
async def get_all_specialists(db: Session = Depends(get_db)):
    """Получение списка всех специалистов"""
    logger.info("Fetching all specialists")
    specialists = get_specialists(db)
    return specialists

@app.get("/nocache/users/{username}", response_model=User)
@benchmark
async def read_user_no_cache(username: str, db: Session = Depends(get_db)):
    """Получение информации о пользователе по логину без использования кеша"""
    user = await get_user_by_username_no_cache(db, username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@app.get("/nocache/users/search/", response_model=List[User])
@benchmark
async def search_users_by_name_no_cache(name_mask: str, db: Session = Depends(get_db)):
    """Поиск пользователей по маске имени и фамилии без использования кеша"""
    users = await search_users_by_name_no_cache(db, name_mask)
    return users

@app.get("/nocache/specialists/", response_model=List[User])
@benchmark
async def get_all_specialists_no_cache(db: Session = Depends(get_db)):
    """Получение списка всех специалистов без использования кеша"""
    logger.info("Fetching all specialists without cache")
    specialists = await get_specialists_no_cache(db)
    return specialists

@app.post("/admin/cache/clear")
async def clear_cache(pattern: str = "*", current_user: Any = Depends(get_current_user)):
    """Очистка кеша администратором"""
    is_admin = False
    if isinstance(current_user, dict):
        is_admin = current_user.get("username") == "admin"
    else:
        is_admin = current_user.username == "admin"
    
    if not is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")

    keys = redis_client.keys(pattern)
    if keys:
        deleted = redis_client.delete(*keys)
        return {"message": f"Cleared {deleted} keys matching pattern '{pattern}'"}
    return {"message": "No keys found matching the pattern"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
