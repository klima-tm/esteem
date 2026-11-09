PyMax 2.1.0
===========

Изменения относительно ``2.0.1``.

Добавлено
---------

* Заявки на вступление в группы и каналы: ``get_join_requests()``,
  ``confirm_join_request()`` /
  ``confirm_join_requests()`` и отклонить их через ``decline_join_request()`` /
  ``decline_join_requests()``.
* Доменные типы ``Member`` и ``Presence`` для заявок.
* 2FA: ``check_2fa()`` и ``change_password()``.
* QR-вход: ``authorize_qr_login(qr_link)``.
* Web app-боты: ``get_bot_init_data(bot_id, chat_id, start_param=None)``.

Исправлено
----------

* TCP-заголовок приведен к схеме Max: ``ver:1``, ``cmd:1``, ``seq:2``,
  ``opcode:2``, ``len/cof:4``. ``seq`` больше не падает после ``255``.
* Upload фото, видео и файлов использует ``ExtraConfig.proxy`` для HTTP-отправки
  на upload URL.
* ``MaxApiError.title`` и ``MaxApiError.localized_message`` могут быть ``None``.

Изменилось
----------

* ``check_2fa()`` возвращает ``False``, если профиль еще не загружен или сервер
  не прислал ``profile_options``.
* При заданном ``ExtraConfig.proxy`` upload-запросы тоже идут через proxy.
  Proxy должен выдерживать большие HTTP POST-запросы.
* ``Capability`` разделен на ``ProfileOptions`` и ``TwoFactorAction``.
* ``ApiFacade`` получил ``bots``-сервис.

Миграция
--------

* Код на ``Client`` и ``WebClient`` обычно менять не нужно.
* Импорт ``pymax.api.auth.enums.Capability`` замените на ``TwoFactorAction`` или
  ``ProfileOptions``.
* Если код ждал строку в ``MaxApiError.title``, теперь нужно учитывать ``None``.
