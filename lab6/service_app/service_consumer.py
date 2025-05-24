from kafka import KafkaConsumer
import json
import os
import time
import logging
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Index, func, Numeric
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("service_consumer.log")]
)
logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")
KAFKA_TOPIC = 'service_created'

logger.info(f"Using Kafka bootstrap servers: {KAFKA_BOOTSTRAP_SERVERS}")
logger.info(f"Using Kafka topic: {KAFKA_TOPIC}")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/services_db")
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    connect_args={"connect_timeout": 10}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

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

def save_service_to_db(db: Session, service_data):
    try:
        db_service = ServiceModel(
            id=int(service_data['id']),
            title=service_data['title'],
            description=service_data['description'],
            price=service_data['price'],
            specialist_id=int(service_data['specialist_id']),
            created_at=service_data['created_at']
        )
        db.add(db_service)
        db.commit()
        logger.info(f"Successfully saved service {service_data['id']} to database")
    except Exception as e:
        logger.error(f"Error saving service to database: {e}")
        db.rollback()
        raise

def wait_for_kafka(max_retries=30, retry_interval=2):
    """Ожидание Kafka"""
    for i in range(max_retries):
        try:
            consumer = KafkaConsumer(
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                value_deserializer=lambda x: json.loads(x.decode('utf-8')),
                auto_offset_reset='earliest',
                enable_auto_commit=True
            )
            consumer.close()
            logger.info("Successfully connected to Kafka")
            return True
        except Exception as e:
            logger.warning(f"Attempt {i+1}/{max_retries}: Kafka not available yet. Error: {e}")
            if i < max_retries - 1:
                time.sleep(retry_interval)
    return False

def main():
    logger.info("Starting service consumer...")
    logger.info("Waiting for Kafka to become available...")
    if not wait_for_kafka():
        logger.error("Failed to connect to Kafka after maximum retries")
        return

    db = SessionLocal()
    
    try:
        logger.info(f"Creating Kafka consumer for topic {KAFKA_TOPIC}")
        consumer = KafkaConsumer(
            KAFKA_TOPIC,
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_deserializer=lambda x: json.loads(x.decode('utf-8')),
            auto_offset_reset='earliest',
            enable_auto_commit=True,
            group_id='service_consumer_group'
        )
        
        logger.info("Successfully created Kafka consumer")
        logger.info("Starting to consume messages...")
        
        for message in consumer:
            try:
                service_data = message.value
                logger.info(f"Received message: {service_data}")
                save_service_to_db(db, service_data)
                logger.info(f"Successfully processed service {service_data['id']}")
            except Exception as e:
                logger.error(f"Error processing message: {e}")
    except Exception as e:
        logger.error(f"Error in consumer loop: {e}")
    finally:
        logger.info("Closing database connection")
        db.close()
        logger.info("Closing Kafka consumer")
        consumer.close()

if __name__ == "__main__":
    main() 