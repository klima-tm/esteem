Client
======

.. currentmodule:: pymax

TCP-клиент с SMS-авторизацией. Это основной клиент для long-running
подключения, обработчиков событий и mobile API Max.

.. note::

   ``Client`` поддерживает ``ExtraConfig.device_type`` со значениями
   ``ANDROID``, ``IOS`` и ``DESKTOP``. Для :meth:`Client.authorize_qr_login`
   используйте ``ANDROID`` или ``IOS``: с ``DESKTOP`` подтверждение QR-входа
   не работает.

.. autoclass:: Client
   :members:
   :inherited-members:
