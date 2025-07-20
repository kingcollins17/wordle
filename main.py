import asyncio
import redis.asyncio as aioredis

# Connect to Redis
redis = aioredis.from_url("redis://localhost", decode_responses=True)


async def check_connection():
    try:
        await redis.ping()
        print("✅ Connected to Redis!")
    except Exception as e:
        print("❌ Failed to connect to Redis:", str(e))


# Publisher function
async def publisher():
    await asyncio.sleep(1)  # wait to ensure subscriber is ready
    for i in range(5):
        message = f"Message {i}"
        await redis.publish("news", message)
        print(f"📤 Published: {message}")
        await asyncio.sleep(1)


# Subscriber function
async def subscriber():
    pubsub = redis.pubsub()
    await pubsub.subscribe("news")
    print("📥 Subscribed to 'news' channel.")

    async for message in pubsub.listen():
        print(message)
        if message["type"] == "message":
            print(f"📨 Received: {message['data']}")
            if message["data"] == "Message 4":
                break
    await pubsub.unsubscribe("news")
    await pubsub.close()


# Run everything
async def main():
    await check_connection()

    # Set and get a value
    await redis.set("greeting", "Hello from Python!")
    greeting = await redis.get("greeting")
    print("Stored value:", greeting)

    # await asyncio.gather(subscriber(), publisher())

    await redis.rpush("tasks", "task1", "task2", "task3")  # Right push
    items = await redis.lrange("tasks", 0, -1)
    print("List:", items)
    print(type(items))

    await redis.sadd("skills", "Python", "Redis", "FastAPI")
    skills = await redis.smembers("skills")
    print("Set:", skills)
    print(type(skills))

    await redis.hset("user:1001", mapping={"name": "Collins", "age": "30"})
    user = await redis.hgetall("user:1001")
    print("Hash:", user)
    print(type(user))


asyncio.run(main())
