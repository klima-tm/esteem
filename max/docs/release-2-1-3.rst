PyMax 2.1.3
===========

Изменения относительно ``2.1.2``.

Добавлено
---------

* ``UnknownAttachment`` для вложений с неизвестным ``_type``. Такие вложения
  больше не ломают парсинг ``Message`` и сохраняют дополнительные поля
  payload-а.

Исправлено
----------

* ``Message`` больше не падает на неизвестных типах вложений вроде
  ``UNSUPPORTED``.
* ``AudioAttachment`` принимает payload без ``duration`` и ``audioId``.
* ``VideoAttachment`` принимает payload без ``duration``.
* ``ElementAttributes.url`` и ``Element.length`` стали необязательными для
  элементов, где Max не присылает эти поля.
* ``Photo(url=...)`` корректно определяет расширение и MIME type, если в URL
  есть query string.
* При потере соединения ``App.started`` сбрасывается, ping-task отменяется, а
  pending API-запросы очищаются без ``Future exception was never retrieved``.
* Reconnect/close после штатного сетевого обрыва стало меньше шуметь
  exception-логами.

Изменилось
----------

* ``configure_logging()`` теперь уважает уже настроенный logging
  host-приложения: PyMax не очищает чужие handler-ы и не добавляет свой
  stderr-handler, если logging уже сконфигурирован.
* Если logging не настроен, PyMax по-прежнему включает pretty-логи из коробки.
* Для принудительного включения pretty-логов PyMax добавлен аргумент
  ``configure_logging(..., force=True)``.
* TCP msgpack decoder стал проще и подробнее логирует payload при ошибках
  декодирования.

Миграция
--------

* Код на ``Client`` и ``WebClient`` обычно менять не нужно.
* Если приложение рассчитывало, что ``configure_logging()`` всегда заменяет
  существующие handler-ы ``pymax``, передайте ``force=True``.
* Если код обрабатывал ``ValidationError`` для неизвестных вложений, теперь
  вместо ошибки придет ``UnknownAttachment``.
