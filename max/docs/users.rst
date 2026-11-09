Users And Contacts
==================

Что это
-------

PyMax хранит контакты, которые Max вернул на login/sync, и умеет догружать
пользователей по ID или номеру телефона. Эти методы доступны и у ``Client``, и
у ``WebClient``.

Кеш контактов
-------------

После ``start`` можно смотреть контакты, пришедшие в первом sync:

.. code-block:: python

   @client.on_start()
   async def on_start(client: Client) -> None:
       for user in client.contacts:
           if user is not None:
               print(user.id, user.names)

``client.contacts`` не гарантирует полный список всех контактов. Это снимок,
который сервер вернул при login. Для точечной работы используйте методы
загрузки пользователей.

Получить пользователей
----------------------

.. code-block:: python

   cached = client.get_cached_user(123)
   user = await client.get_user(123)
   users = await client.get_users([123, 456])
   fresh = await client.fetch_users([123, 456])

``get_cached_user()`` работает только с локальным кешем и не делает сетевой
запрос. ``get_user()`` и ``get_users()`` сначала используют кеш, а недостающие
контакты догружают с сервера. ``fetch_users()`` всегда запрашивает сервер и
обновляет кеш клиента.

Поиск по телефону
-----------------

.. code-block:: python

   contact = await client.search_by_phone("+79990000000")
   print(contact.id)

Формат телефона должен быть таким, какой принимает Max. Обычно это
международный формат с кодом страны.

Контакты
--------

Добавить и удалить контакт можно через клиента:

.. code-block:: python

   contact = await client.add_contact(123)
   await client.remove_contact(123)

Если ``User`` получен из клиента и привязан к сервису пользователей, можно
вызвать методы самого объекта:

.. code-block:: python

   user = await client.get_user(123)
   if user is not None:
       await user.add_contact()
       await user.remove_contact()

Импортировать контакты из телефонной книги:

.. code-block:: python

   from pymax.types import ContactInfo

   contacts = await client.import_contacts(
       [
           ContactInfo(
               phone="+79990000000",
               first_name="Ada",
               last_name="Lovelace",
           )
       ]
   )

``last_name`` хранится в ``ContactInfo``, но текущий payload импорта Max
использует только телефон и имя.

Личный чат
----------

ID личного чата для пары пользователей вычисляется локально:

.. code-block:: python

   chat_id = client.get_chat_id(first_user_id=123, second_user_id=456)

У привязанного ``User`` есть аналогичный helper:

.. code-block:: python

   user = await client.get_user(123)
   if user is not None and client.me is not None:
       chat_id = user.get_chat_id(client.me.contact.id)

Активные сессии
---------------

Список активных сессий аккаунта доступен через ``get_sessions()``:

.. code-block:: python

   sessions = await client.get_sessions()
   for session in sessions:
       print(session.id, session.device_name, session.current)

Частые ошибки
-------------

``get_cached_user()`` вернул ``None``
   Пользователя еще нет в локальном кеше. Используйте ``get_user()`` или
   ``fetch_users()``.

``search_by_phone()`` не находит контакт
   Проверьте формат номера и права аккаунта. Сервер Max может не возвращать
   пользователя по номеру.

``Class is not bound to a client``
   Методы ``user.add_contact()`` и похожие работают на объектах, полученных
   через клиент. У модели, созданной вручную, нет привязанного API-сервиса.
