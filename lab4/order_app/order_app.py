import logging
import os
from fastapi import FastAPI, Depends, HTTPException, status, Security
from fastapi.security import OAuth2PasswordBearer, HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from jose import jwt
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("order_service.log")]
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Order Service API", 
    description="API для управления заказами услуг",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongo:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "services_db")
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "secret_key")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
SERVICE_SERVICE_URL = os.getenv("SERVICE_SERVICE_URL", "http://localhost:8001")
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://localhost:8000")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{USER_SERVICE_URL}/token")
http_bearer = HTTPBearer()

class OrderItem(BaseModel):
    service_id: str
    specialist_id: str
    price: Optional[float] = None
    quantity: int = 1
    status: str = "pending"

class OrderCreate(BaseModel):
    items: List[OrderItem]
    notes: Optional[str] = None

class Order(BaseModel):
    id: Optional[str] = Field(alias="_id", default=None)
    order_id: str
    client_id: str
    items: List[OrderItem]
    total_price: float
    status: str = "pending"  # pending, in_progress, completed, cancelled
    created_at: datetime = None
    updated_at: Optional[datetime] = None
    notes: Optional[str] = None

    class Config:
        allow_population_by_field_name = True

class OrderUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None

class OrderItemUpdate(BaseModel):
    item_index: int
    status: str

async def get_db():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DATABASE_NAME]
    try:
        yield db
    finally:
        client.close()

def process_mongodb_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Преобразует _id из ObjectId в строку для MongoDB документов"""
    if result and "_id" in result:
        result["_id"] = str(result["_id"])
    return result

def generate_order_id():
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"ORD-{timestamp}"

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

@app.on_event("startup")
async def startup_db():
    logger.info("Initializing MongoDB...")
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DATABASE_NAME]
    try:
        await db.orders.create_index([("order_id", 1)], unique=True)
        await db.orders.create_index([("client_id", 1)])
        await db.orders.create_index([("items.specialist_id", 1)])
        await db.orders.create_index([("status", 1)])
        await db.orders.create_index([("created_at", -1)])
        logger.info("MongoDB indexes created")

        if await db.orders.count_documents({}) == 0:
            test_orders = [
                {
                    "order_id": "ORD-001",
                    "client_id": "admin",
                    "items": [
                        {
                            "service_id": "SRV-001",
                            "specialist_id": "specialist1",
                            "price": 100.00,
                            "quantity": 1,
                            "status": "completed"
                        }
                    ],
                    "total_price": 100.00,
                    "status": "completed",
                    "created_at": datetime.utcnow(),
                    "notes": "Тестовый заказ 1"
                },
                {
                    "order_id": "ORD-002",
                    "client_id": "admin",
                    "items": [
                        {
                            "service_id": "SRV-002",
                            "specialist_id": "specialist1",
                            "price": 250.00,
                            "quantity": 1,
                            "status": "pending"
                        },
                        {
                            "service_id": "SRV-003",
                            "specialist_id": "specialist2",
                            "price": 50.00,
                            "quantity": 1,
                            "status": "pending"
                        }
                    ],
                    "total_price": 300.00,
                    "status": "pending",
                    "created_at": datetime.utcnow(),
                    "notes": "Тестовый заказ 2"
                }
            ]
            await db.orders.insert_many(test_orders)
            logger.info("Test orders added to MongoDB")
    except Exception as e:
        logger.error(f"MongoDB initialization error: {e}")
    finally:
        client.close()

async def check_order_access(order, current_user, require_admin=False, require_client=False):
    """Проверка доступа к заказу"""
    is_admin = current_user["username"] == "admin"
    is_client = current_user["username"] == order["client_id"]
    is_specialist = any(item["specialist_id"] == current_user["username"] for item in order["items"])
    
    if require_admin and not is_admin:
        raise HTTPException(status_code=403, detail="Only admin can perform this action")
    
    if require_client and not (is_admin or is_client):
        raise HTTPException(status_code=403, detail="Only client or admin can perform this action")
        
    if not (is_admin or is_client or is_specialist):
        raise HTTPException(status_code=403, detail="Not authorized to access this order")
    
    return is_admin, is_client, is_specialist

def calculate_order_status(order_items):
    """Расчет общего статуса заказа на основе статусов элементов"""
    all_completed = all(item["status"] == "completed" for item in order_items)
    all_cancelled = all(item["status"] == "cancelled" for item in order_items)
    any_in_progress = any(item["status"] == "in_progress" for item in order_items)
    any_cancelled = any(item["status"] == "cancelled" for item in order_items)
    
    if all_completed:
        return "completed"
    elif all_cancelled:
        return "cancelled"
    elif any_in_progress:
        return "in_progress"
    elif any_cancelled and not all_cancelled:
        return "in_progress"
    return "pending"

@app.post("/orders/", response_model=Order, status_code=201)
async def create_order(
    order: OrderCreate,
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Создание нового заказа"""
    logger.info(f"Creating order for user: {current_user['username']}")
    total_price = sum(item.price * item.quantity for item in order.items if item.price)
    order_data = {
        "order_id": generate_order_id(),
        "client_id": current_user["username"],
        "items": [item.dict() for item in order.items],
        "total_price": total_price,
        "status": "pending",
        "created_at": datetime.utcnow(),
        "notes": order.notes
    }
    
    try:
        result = await db.orders.insert_one(order_data)
        created_order = await db.orders.find_one({"_id": result.inserted_id})
        return process_mongodb_result(created_order)
    except Exception as e:
        logger.error(f"Error creating order: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/orders/", response_model=List[Order])
async def get_orders(
    client_id: Optional[str] = None,
    specialist_id: Optional[str] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 10,
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Получение списка заказов с фильтрацией"""
    query = {}
    is_admin = current_user["username"] == "admin"
    if client_id:
        if not is_admin and current_user["username"] != client_id:
            raise HTTPException(status_code=403, detail="Not authorized to view these orders")
        query["client_id"] = client_id
    
    if specialist_id:
        query["items.specialist_id"] = specialist_id

    if not (is_admin or client_id or specialist_id):
        query["$or"] = [
            {"client_id": current_user["username"]},
            {"items.specialist_id": current_user["username"]}
        ]
        
    if status:
        query["status"] = status
    
    try:
        orders = await db.orders.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
        return [process_mongodb_result(order) for order in orders]
    except Exception as e:
        logger.error(f"Error fetching orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/orders/{order_id}", response_model=Order)
async def get_order(
    order_id: str,
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Получение заказа по ID"""
    try:
        order = await db.orders.find_one({"order_id": order_id})
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        await check_order_access(order, current_user)
        
        return process_mongodb_result(order)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching order {order_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/orders/{order_id}", response_model=Order)
async def update_order(
    order_id: str,
    order_update: OrderUpdate,
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Обновление статуса заказа"""
    try:
        existing_order = await db.orders.find_one({"order_id": order_id})
        if not existing_order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        await check_order_access(existing_order, current_user, require_client=True)
        
        update_data = {
            "updated_at": datetime.utcnow()
        }
        if order_update.status:
            update_data["status"] = order_update.status
        if order_update.notes is not None:
            update_data["notes"] = order_update.notes
        
        await db.orders.update_one(
            {"order_id": order_id},
            {"$set": update_data}
        )
        
        updated_order = await db.orders.find_one({"order_id": order_id})
        return process_mongodb_result(updated_order)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating order {order_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/orders/{order_id}/items", response_model=Order)
async def update_order_item(
    order_id: str,
    item_update: OrderItemUpdate,
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Обновление статуса конкретной услуги в заказе"""
    try:
        existing_order = await db.orders.find_one({"order_id": order_id})
        if not existing_order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        if item_update.item_index < 0 or item_update.item_index >= len(existing_order["items"]):
            raise HTTPException(status_code=400, detail="Invalid item index")
        
        item = existing_order["items"][item_update.item_index]
        await check_order_access(existing_order, current_user)
        
        if (not current_user["username"] == "admin" and 
            not current_user["username"] == existing_order["client_id"] and
            not current_user["username"] == item["specialist_id"]):
            raise HTTPException(status_code=403, detail="Not authorized to update this specific item")
        
        update_field = f"items.{item_update.item_index}.status"
        await db.orders.update_one(
            {"order_id": order_id},
            {"$set": {
                update_field: item_update.status,
                "updated_at": datetime.utcnow()
            }}
        )
        
        updated_order = await db.orders.find_one({"order_id": order_id})
        new_status = calculate_order_status(updated_order["items"])
        
        if new_status != updated_order["status"]:
            await db.orders.update_one(
                {"order_id": order_id},
                {"$set": {"status": new_status}}
            )
            updated_order["status"] = new_status
        
        return process_mongodb_result(updated_order)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating order item {order_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/orders/{order_id}", status_code=204)
async def delete_order(
    order_id: str,
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Удаление заказа (только для администраторов)"""
    try:
        existing_order = await db.orders.find_one({"order_id": order_id})
        if not existing_order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        await check_order_access(existing_order, current_user, require_admin=True)
        
        result = await db.orders.delete_one({"order_id": order_id})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Order not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting order {order_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/orders/client/{client_id}", response_model=List[Order])
async def get_client_orders(
    client_id: str,
    status: Optional[str] = None,
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Получение всех заказов клиента"""
    if current_user["username"] != "admin" and current_user["username"] != client_id:
        raise HTTPException(status_code=403, detail="Not authorized to view these orders")
    
    query = {"client_id": client_id}
    if status:
        query["status"] = status
    
    try:
        orders = await db.orders.find(query).sort("created_at", -1).to_list(100)
        return [process_mongodb_result(order) for order in orders]
    except Exception as e:
        logger.error(f"Error fetching orders for client {client_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/orders/specialist/{specialist_id}", response_model=List[Order])
async def get_specialist_orders(
    specialist_id: str,
    status: Optional[str] = None,
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Получение всех заказов для конкретного специалиста"""
    if current_user["username"] != "admin" and current_user["username"] != specialist_id:
        raise HTTPException(status_code=403, detail="Not authorized to view these orders")
    
    query = {"items.specialist_id": specialist_id}
    if status:
        query["status"] = status
    
    try:
        orders = await db.orders.find(query).sort("created_at", -1).to_list(100)
        return [process_mongodb_result(order) for order in orders]
    except Exception as e:
        logger.error(f"Error fetching orders for specialist {specialist_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
