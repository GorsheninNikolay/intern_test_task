import asyncio
import logging
import os

from aiohttp import web
from aiohttp_swagger import setup_swagger, swagger_path
from dotenv import load_dotenv
from elasticsearch import AsyncElasticsearch
from elasticsearch import helpers
from motor.motor_asyncio import AsyncIOMotorClient

# Загрузка переменных окружения
load_dotenv()

# Подключение к кластеру
client = AsyncIOMotorClient(os.getenv("URL_DB", "mongodb://localhost:27017"))
# Получение коллекции
documents = client.InterDB.documents

# Router для регистрации ендпоинтов
routes = web.RouteTableDef()
# Клиент ElasticSearch
es = AsyncElasticsearch(os.getenv("URL_ES", 'http://localhost:9200'))


logging.basicConfig(
    format=("%(asctime)s\t %(levelname)s\t %(name)s\t %(message)s\t"),
    level=logging.INFO,
)

@swagger_path('docs/index.yaml')
@routes.get('/', allow_head=False)
async def start(request: web.Request) -> web.json_response:
    """
    Description: Загружаем тестовые данные
    Method: GET
    """
    try:
        ans = {"result": ""}
        if await es.indices.exists(index="documents"):
            ans["result"] = ("Данные уже были загружены, "
                            "можно переходить /api/docs.")
            return web.json_response(ans, status=200)

        data = documents.find({}) # Получаем все записи
        actions = []  # Массив для хранения данных

        # Формируем запрос для elasticsearch
        async for doc in data:
            actions.append(
                {
                "_index": "documents",
                "_op_type": "create",
                "_id": doc["doc_id"],
                '_source': {
                    "text": doc["text"]
                }
                }
            )
        # Загружаем тестовые данные
        await helpers.async_bulk(client=es, actions=actions)

        # Возвращаем результат 201 Created
        ans["result"] = "Данные успешно загружены, можно переходить /api/docs."
        return web.json_response(ans, status=201)
    except Exception as error:
        logging.error(error)


@swagger_path("docs/post_document.yaml")
@routes.post('/documents')
async def get_documents(request: web.Request) -> str:
    """
    Description: По заданному тексту в теле запроса находим документы.
    Method: POST
    """
    try:
        # Данные в теле запроса
        request_data = await request.json()

        # Ответ
        ans = {"result": ""}

        if len(request_data) != 1 or request_data.get('text') is None:
            ans["result"] = "В запросе должно быть только 1 поле text."
            return await web.json_response(ans, status=400)

        # Формируем запрос
        query = {
            "match": {
                "text": request_data["text"]
            },
        }
        # ElasticSearch находит документы по заданному тексту
        resp = await es.search(
            index="documents", query=query, source=["id"], size=20)

        # Формируем список id для запроса в базу данных
        arr_id = [int(doc["_id"]) for doc in resp["hits"]["hits"]]

        # Запрашиваем документы у базы данных
        data = documents.find(
            {"doc_id": {"$in": arr_id}},
            {"_id": 0}
        ).sort('created_data')

        # Формируем ответ
        ans["result"] = await data.to_list(length=20)

        return web.json_response(ans)
    except Exception as error:
        logging.error(error)


@swagger_path('docs/delete_document.yaml')
@routes.delete('/document/{document_id}')
async def delete_document(request: web.Request) -> web.json_response:
    """
    Description: Удаление документов из ElasticSearch и DataBase.
    Method: POST
    """
    try:
        ans = {"result": ""}

        # Получение id
        doc_id = int(request._match_info["document_id"])

        # Поиск документа по заданному id
        doc = await documents.find_one({"doc_id": doc_id})

        # Если документ не найден, то возвращаем статус 204 No Content
        if doc is None:
            ans["result"] = "No Content."
            return web.json_response(ans, status=204)

        # Иначе удаляем документы в базе данных и в индексе ElasticSearch
        await documents.delete_one({"doc_id": doc_id})
        await es.delete(index="documents", id=doc_id)

        # Вовзращаем успех, 200 OK
        ans["result"] = (f"Document with id {doc_id} "
                         "has been successfully deleted.")
        return web.json_response(ans, status=200)

    # Ловим исключение для обработки нечисловых данных
    except ValueError:
        ans["result"] = "Make sure to enter a numeric value."
        return web.json_response(ans, status=400)
    except Exception as error:
        logging.error(error)


def main() -> None:
    """
    Основная функция запуска
    """
    loop = asyncio.get_event_loop()  # Event loop
    app = web.Application()  # Приложение

    # Загрузка эндпоинтов
    app.add_routes(routes)
    logging.info("Эндпоинты зарегистрированы")

    # Swagger
    setup_swagger(
        app, swagger_url="/api/docs", ui_version=2)
    logging.info("Swagger загружен")

    tasks = [
        web.run_app(app)
    ]
    logging.info("Запуск!")
    loop.run_until_complete(asyncio.wait(tasks))


if __name__ == "__main__":
    logging.info("Поехали!")
    main()
