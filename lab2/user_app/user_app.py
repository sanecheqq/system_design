from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from typing import List, Optional, Dict
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="User Service API", 
              description="API для управления пользователями (клиентами и специалистами)",
              version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET_KEY = "secret_key"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


users_db = {
    "admin": {
        "username": "admin",
        "full_name": "Администратор",
        "email": "admin@example.com",
        "hashed_password": pwd_context.hash("secret"),
        "disabled": False,
        "is_specialist": False
    }
}

specialists_db = {}


class UserBase(BaseModel):
    username: str
    full_name: str
    email: EmailStr
    is_specialist: bool = False


class UserCreate(UserBase):
    password: str


class User(UserBase):
    disabled: bool = False


class UserInDB(User):
    hashed_password: str


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def get_user(username: str):
    if username in users_db:
        user_dict = users_db[username]
        return UserInDB(**user_dict)
    if username in specialists_db:
        user_dict = specialists_db[username]
        return UserInDB(**user_dict)
    return None


def authenticate_user(username: str, password: str):
    user = get_user(username)
    if not user:
        return False
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


async def get_current_user(token: str = Depends(oauth2_scheme)):
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
        raise credentials_exception
    user = get_user(username=token_data.username)
    if user is None:
        raise credentials_exception
    return user


@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/users/", response_model=User)
async def create_user(user: UserCreate):
    """Создание нового пользователя (клиента)"""
    if user.username in users_db or user.username in specialists_db:
        raise HTTPException(status_code=400, detail="Username already registered")

    user_dict = user.dict()
    user_dict["hashed_password"] = get_password_hash(user.password)
    del user_dict["password"]
    
    if user.is_specialist:
        specialists_db[user.username] = user_dict
    else:
        users_db[user.username] = user_dict
    
    return User(**user_dict)


@app.get("/users/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_user)):
    """Получение информации о текущем пользователе"""
    return current_user


@app.get("/users/{username}", response_model=User)
async def read_user(username: str):
    """Получение информации о пользователе по логину"""
    user = get_user(username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.get("/users/search/", response_model=List[User])
async def search_users_by_name(name_mask: str):
    """Поиск пользователей по маске имени и фамилии"""
    results = []
    
    for username, user_data in users_db.items():
        if name_mask.lower() in user_data["full_name"].lower():
            results.append(User(**user_data))
    
    for username, user_data in specialists_db.items():
        if name_mask.lower() in user_data["full_name"].lower():
            results.append(User(**user_data))
    
    return results


@app.get("/specialists/", response_model=List[User])
async def get_all_specialists():
    """Получение списка всех специалистов"""
    return [User(**user_data) for user_data in specialists_db.values()]
