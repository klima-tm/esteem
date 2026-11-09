WebClient
=========

.. currentmodule:: pymax

WebSocket-клиент с QR-авторизацией. Он подходит, когда нужно подключаться как
web-клиент Max.

.. note::

   В штатной конфигурации ``WebClient`` использует только ``DeviceType.WEB``.
   Параметр ``ExtraConfig.device_type`` предназначен для ``Client`` и не
   меняет тип устройства ``WebClient``.

.. autoclass:: WebClient
   :members:
   :inherited-members:
