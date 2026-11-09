PyMax 2.2.0
===========

Изменения относительно ``2.1.3``.

Добавлено
---------

* Получение сообщений по ID через ``get_message()`` и ``get_messages()``.
  Те же операции доступны на bound-объекте ``Chat``.
* Редактирование сообщений через ``edit_message()`` и ``Message.edit()`` с
  поддержкой markdown, фото, видео и файлов.
* События ``TypingEvent``, ``PresenceEvent``, ``MessageReadEvent`` и
  ``ReactionUpdateEvent`` с обработчиками ``on_typing()``, ``on_presence()``,
  ``on_message_read()`` и ``on_reaction_update()``.
* ``join_channel()`` для вступления в канал по полной ссылке или join-токену.
* Автоматическое завершение SMS-регистрации нового аккаунта через
  ``RegistrationConfig`` в ``ExtraConfig.registration_config``.
* Поддержка Python 3.14 в метаданных пакета и CI-матрице.

Исправлено
----------

* Позиции markdown-элементов теперь корректно считаются в UTF-16 для emoji и
  других символов вне BMP.
* Удаление сообщения в ``WebClient`` распознается из события
  ``NOTIF_MESSAGE`` со статусом ``REMOVED``.
* ``MessageDeleteEvent`` принимает обе формы payload-а Max и не требует поле
  ``ttl``.
* ``PresenceEvent`` принимает частичные обновления, в которых Max присылает
  ``seen`` без ``status``.
* ``read_message()`` сохраняет тип ``message_id``: ``int`` для ``Client`` и
  ``str`` для ``WebClient``.
* Вложенные ``Message``, ``Chat`` и ``User`` из API-ответов и событий
  привязываются к сервисам клиента, поэтому их bound-методы работают
  последовательно.

Изменилось
----------

* ``MessageDeleteEvent`` всегда содержит ``chat_id``. Поля ``chat`` и
  ``message`` зависят от формы события и могут быть ``None``.
* Проверка типов ``pyright`` ограничена релизным пакетом ``src`` и снова
  проходит без ошибок.
* Документация клиента разделена на отдельные API-страницы для ``Client``,
  ``WebClient`` и конфигурации.

Миграция
--------

* В обработчике удаления используйте ``event.chat_id`` вместо
  ``event.chat.id``: ``event.chat`` может отсутствовать в ``WebClient``.
* При прямом вызове ``read_message()`` передавайте ``int`` в ``Client`` и
  ``str`` в ``WebClient``.
* Для регистрации нового номера задайте
  ``ExtraConfig(registration_config=RegistrationConfig(...))``. Для уже
  существующих аккаунтов настройка не нужна.
