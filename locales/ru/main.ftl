# Russian translations

# Commands
start = Здравствуйте! 👋
    Добро пожаловать в бот AKB Cargo!

start-registered = ✅ Добро пожаловать, { $full_name }!
    📱 Телефон: { $phone }
    🆔 Client Code: { $client_code }

    Выберите одно из меню:

start-not-logged-in = 👋 { $full_name }, рады видеть вас снова!

    Войдите в систему, чтобы продолжить:

start-pending-approval = ⏳ { $full_name }, ваш запрос рассматривается.

    Пожалуйста, дождитесь подтверждения администратора.

start-with-referral = 🎁 Вас пригласил { $referrer_name }!

start-new-user = Чтобы использовать бот, сначала зарегистрируйтесь или войдите в систему:

select-language = Выберите язык:

language-changed = ✅ Язык изменён: Русский

# Buttons
btn-uzbek = 🇺🇿 Узбекский
btn-register = 📝 Регистрация
btn-login = 🔐 Войти
btn-russian = 🇷🇺 Русский
btn-profile = 👤 Профиль
btn-share = 📤 Поделиться ботом
btn-back = ⬅️ Назад
btn-admin-panel = 👨‍💼 Админ панель

btn-add-passport = 🪪 Добавить паспорт
btn-my-passports = 📋 Мои паспорта
btn-language = 🌐 Язык
btn-check-track-code = 📦 Проверка трек-кода
btn-invite-friends = 👥 Пригласить друзей
btn-contact = 📞 Связаться
btn-make-payment = 💳 Совершить оплату
btn-china-address = 🇨🇳 Адрес в Китае

btn-save = ✅ Сохранить
btn-cancel = ❌ Отмена
btn-services = 🚚 Услуги
btn-view-info = 📊 Просмотр информации
btn-edit-profile = ✏️ Редактировать
btn-logout = 🚪 Выйти из системы
btn-back-to-menu = 🏠 Главное меню
btn-devices = 📱 Устройства

# Devices (Session History)
devices-title = 📱 История устройств
devices-empty = История устройств не найдена.
devices-item = 📅 { $date } | 👤 { $client_code } | { $event_type }
event-login = ✅ Вход
event-relink = 🔄 Смена аккаунта
event-logout = 🚪 Выход

# Security Alerts
security-alert-relink = ⚠️ <b>Предупреждение безопасности!</b>

    С вашего Telegram профиля был выполнен вход в новый аккаунт, и текущий профиль был отключён.

    👤 <b>Новый профиль:</b>
    Имя: { $full_name }
    Код: { $client_code }
    Тел: { $phone }

    Если это были не вы, обратитесь к администратору.

passport-series-not-match = Серия паспорта в неверном формате. Формат: AA1234567
passport-series-incorrect-format = Серия паспорта '{ $series }' неверна. Принимаются только серии паспортов Республики Узбекистан.
pinfl-must-be-14-digits = PINFL должен состоять из 14 цифр.
pinfl-incorrect-format = Неверный формат PINFL.
date-of-birth-incorrect-format = Неверный формат даты. Формат: DD.MM.YYYY (например: 15.03.2000)
date-of-birth-not-in-future = Дата рождения не может быть в будущем.
date-of-birth-too-young = Ваш возраст должен быть не менее 16 лет.
date-of-bith-incorrect = Дата введена неверно.

# Conflict Errors
conflict-pinfl = PINFL уже зарегистрирован
conflict-phone = Телефон уже зарегистрирован
conflict-passport-series = Паспорт с такой серией уже зарегистрирован
conflict-telegram-id = Вы уже зарегистрированы

api-error-client-already-logged-in = Ваш аккаунт уже привязан к другому Telegram-профилю.
api-error-telegram-id-already-exists = Этот Telegram-профиль уже привязан к другому пользователю.

# E-tijorat verification
btn-etijorat-confirmed = ✅ Я зарегистрировался

etijorat-caption = 📱 Приложение E-tijorat — это удобный инструмент для отслеживания вашего лимита в государственной таможенной службе. Для регистрации в нашем боте необходимо сначала зарегистрироваться в этом приложении.

    ⬇️ В видео ниже показано, как зарегистрироваться. После просмотра нажмите кнопку ниже.

etijorat-send-screenshot = 📸 Отправьте скриншот, подтверждающий вашу регистрацию в приложении E-tijorat.

etijorat-send-screenshot-only-photo = ⚠️ Пожалуйста, отправьте только фото (скриншот).

etijorat-screenshot-under-review = ⏳ Ваш скриншот отправлен на проверку администраторам. Пожалуйста, подождите.

etijorat-approved = ✅ Ваш скриншот E-tijorat одобрен! Теперь вы можете зарегистрироваться.

etijorat-rejected = ❌ Ваш скриншот был отклонён. Пожалуйста, сначала зарегистрируйтесь в приложении E-tijorat и попробуйте снова (/start).

# Menu
main-menu = 🏠 Главное меню
choose-action = Выберите действие:

# Profile
profile-info = 👤 Ваш профиль:

    👤 Имя: { $full_name }
    📱 Телефон: { $phone }
    🆔 Client Code: { $client_code }
    📇 Паспорт: { $passport_series }
    🆔 ПИНФЛ: { $pinfl }
    📅 Дата рождения: { $dob }
    🌍 Регион: { $region }
    📍 Адрес: { $address }
    🕒 Зарегистрирован: { $created_at }

profile-select-action = Выберите действие:
profile-select-region = Выберите свой регион:
profile-select-district = Выберите свой район:
profile-enter-address = 🌍 { $region }, 📍 { $district }
    Введите ваш полный адрес (улица, дом, квартира):
profile-address-too-short = ❌ Адрес слишком короткий! Введите минимум 5 символов.
profile-address-updated = ✅ Адрес успешно обновлён!
profile-edit-name = Введите новое имя:
profile-edit-phone = Введите новый номер телефона (пример: +998901234567):
profile-edit-phone_btn = Введите новый номер телефона
profile-updated = ✅ Профиль успешно обновлён!
profile-logout-confirm = ⚠️ Вы действительно хотите выйти из системы?
profile-logged-out = 👋 Вы успешно вышли из системы!

# Admin
admin-panel = 👨‍💼 Админ панель

    Статистика пользователей:

user-statistics = 📊 Статистика пользователей:

    👥 Всего: { $total }
    🆕 Сегодня: { $today }
    📅 На этой неделе: { $week }
    📆 В этом месяце: { $month }

access-denied = ❌ Доступ запрещён!
    У вас нет прав для выполнения этого действия.

# Errors
error-occurred = ❌ Произошла ошибка. Пожалуйста, попробуйте позже.
error-user-not-found = ⚠️ Пользователь не найден!

# Internal Error (for reply_with_internal_error)
error-internal-title = Произошла техническая ошибка
error-internal-description = Пожалуйста, попробуйте снова немного позже.

# Messages
banned-message = 🚫 Вы заблокированы и не можете использовать бот.

not-provided = Не указано

# Add Passport Flow
add-passport-start = 🪪 Добавить паспорт

    Введите серию паспорта.
    Формат: AA1234567

add-passport-pinfl = Введите ПИНФЛ (14 цифр)

add-passport-dob = Введите дату рождения:

    Формат: DD.MM.YYYY
    Пример: 15.03.2000

add-passport-doc-type = Какой документ вы хотите загрузить?

add-passport-id-card = ID Card (двусторонний)
add-passport-passport = Passport (односторонний)

add-passport-id-front = Загрузите фото ID Card (лицевая сторона):

add-passport-id-back = Загрузите фото ID Card (обратная сторона):

add-passport-id-saved = ✅ Лицевая сторона сохранена!

add-passport-passport-photo = Загрузите фото паспорта:

add-passport-confirm = Проверьте данные:

    📇 Паспорт: { $passport_series }
    🆔 ПИНФЛ: { $pinfl }
    📅 Дата рождения: { $dob }
    📷 Фото: { $image_count } шт.

    Данные верны?

add-passport-success = ✅ Паспорт успешно добавлен!

add-passport-cancelled = ❌ Добавление паспорта отменено.

add-passport-error = ❌ Произошла ошибка. Попробуйте снова.

add-passport-max-2-photo = ❌ Максимум 2 изображения!
add-passport-please-select-kyb = Пожалуйста, выберите одну из кнопок:

# My Passports  
my-passports-title = 📋 Мои паспорта

    Всего: { $total } шт.

my-passports-empty = Пока нет добавленных паспортов.

my-passports-item = 📇 Паспорт: { $passport_series }
    🆔 ПИНФЛ: { $pinfl }
    📅 Дата: { $dob }
    🕒 Добавлено: { $created_at }

my-passports-page = Страница { $current } / { $total }

# Passport View and Delete
passport-not-found = ❌ Паспорт не найден.
passport-deleted-success = ✅ Паспорт успешно удалён!
passport-delete-confirm = ⚠️ Вы действительно хотите удалить этот п��спорт?
btn-yes-delete = ✅ Да, удалить
btn-no-cancel = ❌ Нет, отмена
btn-delete-passport = 🗑 Удалить паспорт
passport-delete-prompt = Нажмите кнопку ниже, чтобы удалить паспорт:
passport-detail-caption = 📇 Паспорт: { $passport_series }
    🆔 ПИНФЛ: { $pinfl }
    📅 Дата рождения: { $dob }
    🕒 Добавлено: { $created_at }

# Passport Duplicate Errors
passport-duplicate-error = ❌ Эти данные паспорта уже существуют:
passport-duplicate-series = Серия паспорта уже зарегистрирована
passport-duplicate-pinfl = ПИНФЛ уже зарегистрирован

# API Error Messages (for frontend)
api-error-client-not-found = Пользователь с указанными данными не найден
api-error-registration-pending = Ваш запрос рассматривается, дождитесь подтверждения администратора
api-error-duplicate-data = Обнаружены дублирующиеся данные: { $fields }
api-error-duplicate-extra-passport = Обнаружены дублирующиеся данные в дополнительных паспортах: { $fields }
api-error-invalid-data = Неверные данные: { $error }
api-error-registration-failed = Регистрация не удалась: { $error }
api-error-invalid-init-data = Неверные или устаревшие initData
api-success-registration = ⏳ Ваш запрос отправлен! Дождитесь подтверждения администратора.
api-success-init-data = InitData верны
api-error-failed-upload-passport-images = Ошибка при загрузке изображений паспорта

api-error-cannot-refer-self = Нельзя пригласить самого себя
api-error-refferer-code-not-found = Код клиента не найден

# Contact Information
contact-info = 📞 Связаться с нами:
    ☎️ Телефон: +998908261560
    🏢 Адрес: г. Ташкент, Чиланзарский район, ул. Арнасай
    📩 Админ: @AKB_CARGO

# China Address
china-address-warning = ⚠️ <b>Внимание!</b>
    Не забудьте отправить введённый адрес @AKB_CARGO для подтверждения!

    Ответственность за заказы, отправленные по адресам, не подтверждённым администраторами, не принимается!

# Info / Flights
info-no-flights = ❌ На данный момент информация о рейсах не найдена.
info-flights-list = ✈️ Последние 3 рейса:

    Выберите рейс или обновите информацию:
info-flight-selected = ✅ Рейс выбран
info-flights-refreshed = ✅ Информация обновлена

# Invite Friends
invite-friends-title = 👥 Приглашайте друзей!

    Поделитесь нашим ботом с друзьями и получите бонусы!

    👥 Приглашено: <code>{ $referral_count }</code> чел.

    Ваша реферальная ссылка:
invite-url-copied = ✅ Ссылка скопирована!
btn-share-bot = 📤 Поделиться ботом
btn-copy-url = 📋 Скопировать ссылку

# Common buttons
btn-refresh = 🔄 Обновить

# Info - Flights
info-no-orders = ❌ У вас пока нет заказов.
info-flights-list = 📋 Список ваших рейсов:
info-flights-refreshed = ✅ Данные обновлены
info-status-paid = ✅ Оплачено
info-status-unpaid = ❌ Не оплачено
info-status-partial = 🧩 Частичная оплата
info-flight-details-with-status = 📋 Информация о рейсе:
    🆔 Код клиента: { $client_code }
    ✈️ Рейс: { $worksheet }
    💰 Общая сумма: { $summa } сум
    ⚖️ Вес: { $vazn } кг
    📦 Трек-коды: <code>{ $trek_kodlari }</code>
    💡 Статус груза: { $payment_status }
    
info-flight-details-partial = 📋 Информация о рейсе (🧩 Частичная оплата):
    🆔 Код клиента: { $client_code }
    ✈️ Рейс: { $worksheet }
    💰 Общая сумма: { $total } сум
    ✅ Оплачено: { $paid } сум
    ⏳ Остаток: { $remaining } сум
    🗓️ Срок оплаты: { $deadline }
    ⚖️ Вес: { $vazn } кг
    📦 Трек-коды: { $trek_kodlari }
    
    ⚠️ Внимание! Вы производите частичную оплату. Если полная оплата не будет произведена в течение 15 дней:
    - груз не будет выдан
    - если срок хранения на складе истечёт, груз может быть конфискован.
    - Получение груза возможно только после полной оплаты.
    
btn-make-payment-now = 💳 Оплатить
btn-back-to-flights = ⬅️ Вернуться к списку рейсов
btn-view-cargo-photos = 📸 Посмотреть фото

# Payment breakdown display
info-payment-breakdown-header = 💳 Платежи:
info-payment-breakdown-cash =  • Наличные: { $amount } сум
info-payment-breakdown-total = 📊 Итого: { $total } сум

# Payment
payment-no-orders = ❌ У вас нет заказов для оплаты.
payment-all-paid = ✅ Все ваши заказы оплачены!
payment-select-flight = 💳 Выберите рейс для оплаты:
payment-select-type = 💳 Выберите способ оплаты:
payment-no-cards = ❌ В настоящее время платёжные карты недоступны. Свяжитесь с администратором.
payment-info = 📋 Информация об оплате:

    🆔 Код клиента: <code>{ $client_code }</code>
    ✈️ Рейс: { $worksheet }
    💰 Сумма: <code>{ $summa }</code> сум
    ⚖️ Вес: { $vazn } кг
    📦 Трек-коды: { $trek_kodlari }

    💳 Номер карты: <code>{ $card_number }</code>
    👤 Имя Фамилия: { $card_owner }

    📸 Нажмите кнопку для отправки чека оплаты:

payment-cash-confirmation = 💵 <b>Подтверждение наличной оплаты</b>

    ✈️ Рейс: <b>{ $flight_name }</b>
    💰 Сумма: <b>{ $summa } сум</b>
    ⚖️ Вес: <b>{ $vazn } кг</b>
    📦 Трек-коды: <b>{ $trek_kodlari }</b>

    Вы оплатите наличными при получении груза. Подтверждаете?
payment-cash-submitted = ✅ Запрос на наличную оплату отправлен администратору. Вы можете оплатить при получении груза.
payment-cash-confirmed-user = ✅ Оплата наличными принята и груз выдан!
payment-cancelled = ❌ Оплата отменена.
payment-send-proof-single = 📸 Отправьте чек оплаты:

    ⚠️ <b>Важно:</b> Отправьте только <b>одно фото</b> или <b>PDF файл</b>.
    Если будет отправлено несколько фото, будет принято только первое.
payment-submitted = ✅ Ваш чек отправлен администратору. Ожидайте подтверждения!

# Payment - Admin notifications
payment-admin-notification = ⚡ Новый платёж:

payment-admin-actions = ⬆️ Подтвердите или отклоните платёж выше:

# Payment - Approval buttons
btn-approve-payment = ✅ Подтвердить
btn-reject-payment = ❌ Отклонить
btn-reject-with-comment = 💬 Отклонить с комментарием
btn-send-payment-proof = 📤 Отправить чек
btn-payment-online = 💳 Онлайн оплата
btn-payment-cash = 💵 Оплата наличными
btn-confirm = ✅ Подтвердить
btn-cash-payment-confirmed = 💵 Оплата наличными выполнена
btn-cash-payment-confirm = 💵 Оплата наличными выполнена
btn-pay-full = ✅ Полная оплата
btn-pay-partial = 🧩 Частичная оплата
btn-pay-full-remaining = ✅ Оплатить оставшуюся сумму полностью
btn-enter-amount = 💳 Ввести сумму
btn-pay-full = ✅ Полная оплата
btn-pay-partial = 🧩 Частичная оплата
btn-pay-full-remaining = ✅ Оплатить оставшуюся сумму полностью
btn-enter-amount = 💳 Ввести сумму

# Payment - Approval results
payment-approved-user = ✅ Ваш платёж подтверждён!

    ✈️ Рейс: { $worksheet }
    💰 Сумма оплаты: { $summa } сум

payment-approved-user-partial = ✅ Оплата подтверждена (Частичная оплата):

    ✈️ Рейс: { $worksheet }
    💰 Оплачено: { $paid } сум
    💸 Остаток: { $remaining } сум
    📋 Итого: { $total } сум
    📅 Срок оплаты: { $deadline }

payment-approved-group = ✅ Платёж { $client_code } по рейсу { $worksheet }, строка { $row_number } подтверждён.

# Payment Type Labels
payment-label-cash = 💵 Наличные
payment-label-online-full = 💳 Онлайн (полная)
payment-label-online-partial = 🧩 Частичная оплата (онлайн)

# Admin Payment Notifications (Full Details)
payment-admin-notification-full = ⚡ <b>Новый платёж</b> ({ $payment_label })
    🆔 ID клиента: <code>{ $client_code }</code>
    ✈️ Рейс: <b>{ $worksheet }</b>
    💰 Сумма: <b>{ $summa } сум</b>
    ⚖️ Вес: <b>{ $vazn } кг</b>
    📦 Трек-коды: <b>{ $track_codes }</b>
    👤 Пользователь: <b>{ $full_name }</b>
    📱 Телефон: <code>{ $phone }</code>
    💬 Telegram ID: <code>{ $telegram_id }</code>

payment-admin-notification-partial = ⚡ <b>Новый платёж</b> ({ $payment_label })
    🆔 ID клиента: <code>{ $client_code }</code>
    ✈️ Рейс: <b>{ $worksheet }</b>
    💰 Общая сумма: <b>{ $total } сум</b>
    ✅ Оплачено: <b>{ $paid } сум</b>
    ⏳ Осталось: <b>{ $remaining } сум</b>
    🗓️ Срок: <b>{ $deadline }</b>
    ⚖️ Вес: <b>{ $vazn } кг</b>
    📦 Трек-коды: <b>{ $track_codes }</b>
    👤 Пользователь: <b>{ $full_name }</b>
    📱 Телефон: <code>{ $phone }</code>
    💬 Telegram ID: <code>{ $telegram_id }</code>

payment-approved-success = ✅ Платёж подтверждён!
payment-rejected-user = ⚠️ Ваш платёж отклонён. Свяжитесь с администратором.
payment-rejected-with-comment = ⚠️ Ваш платёж отклонён.

    💬 Комментарий админа: { $comment }
payment-rejected-group = ❌ Платёж отклонён.
payment-rejected-success = ❌ Платёж отклонён!
payment-rejection-comment-prompt = 💬 Напишите комментарий для отклонения или отправьте /stop:

# Partial Payment
payment-select-amount-type = 💳 Выберите тип оплаты:

    Общая сумма: { $total } сум

payment-partial-info = ⚠️ <b>Информация о частичной оплате</b>

    ✈️ Рейс: { $flight }
    🆔 Код клиента: { $client_code }
    💰 Общая сумма: { $total } сум
    ✅ Оплачено: { $paid } сум
    ⏳ Осталось: { $remaining } сум
    📅 Срок: { $deadline }

    ⚠️ <b>Внимание!</b>
    Вы производите частичную оплату.
    Если полная оплата не будет произведена в течение 15 дней:
    • груз не будет выдан
    • если срок хранения на складе истечёт, груз может быть конфискован.

payment-partial-existing = 💰 <b>Существует частичная оплата</b>

    ✈️ Рейс: { $flight }
    💰 Общая сумма: { $total } сум
    ✅ Оплачено: { $paid } сум
    ⏳ Осталось: { $remaining } сум
    📅 Срок: { $deadline }

payment-partial-enter-amount = 💳 Введите сумму для оплаты (сум):

    ⚠️ Минимальная сумма: 1 000 сум
    ⚠️ Максимальная сумма: оставшаяся сумма

payment-partial-invalid-amount = ❌ Неверная сумма! Введите только цифры.
payment-partial-min-amount = ❌ Минимальная сумма должна быть { $min } сум!
payment-partial-max-amount = ❌ Максимальная сумма может быть { $max } сум!
payment-partial-exceeds-total = ❌ Сумма превышает общую сумму! Всего: { $total } сум
payment-partial-remaining = осталось

payment-info-partial = 📋 Информация об оплате (Частичная оплата):

    🆔 Код клиента: { $client_code }
    ✈️ Рейс: { $worksheet }
    💰 Сумма оплаты: { $summa } сум
    ⚖️ Вес: { $vazn } кг
    📦 Трек-коды: { $trek_kodlari }

    💳 Платёжная карта:
    { $card_number }
    { $card_owner }

payment-info-remaining = 📋 Информация об оплате (Оставшаяся сумма):

    🆔 Код клиента: { $client_code }
    ✈️ Рейс: { $worksheet }
    💰 Сумма оплаты: { $summa } сум
    ⚖️ Вес: { $vazn } кг
    📦 Трек-коды: { $trek_kodlari }

    💳 Платёжная карта:
    { $card_number }
    { $card_owner }

admin-verification-partial-payment = ⚠️ <b>Частичная оплата:</b>
    Оплачено: { $paid } сум
    Осталось: { $remaining } сум
    Срок: { $deadline }

not-set = Не установлено

# Admin client payment filters
admin-client-filter-hint = 💳 Фильтрация клиентов по статусу оплаты:
admin-client-filter-paid-btn = Полностью оплачено
admin-client-filter-partial-btn = Частичная оплата
admin-client-filter-unpaid-btn = Не оплачено

admin-client-filter-paid = 🟢 Клиенты с полной оплатой ({ $count }):
admin-client-filter-partial = 🟡 Клиенты с частичной оплатой ({ $count }):
admin-client-filter-unpaid = 🔴 Неоплаченные клиенты ({ $count }):
admin-client-filter-empty = В этой категории клиентов не найдено.
admin-client-filter-more = ... и ещё { $extra } клиентов.

# Payment - Channel notification
payment-confirmed-channel = 📌 Платёж ПОДТВЕРЖДЁН!

    🆔 ID клиента: <code>{ $client_code }</code>
    ✈️ Рейс: <b>{ $worksheet }</b>
    💰 Сумма: <b>{ $summa }</b>
    ⚖️ Вес: <b>{ $vazn } кг</b>
    📦 Трек-коды: <b>{ $track_codes }</b>
    👤 Админ: <b>{ $full_name }</b>
    📱 Телефон: { $phone }
    🆔 Telegram ID: { $telegram_id }

payment-confirmed-channel-partial = 📌 Платёж ПОДТВЕРЖДЁН! (🧩 Частичная оплата)

    🆔 ID клиента: <code>{ $client_code }</code>
    ✈️ Рейс: <b>{ $worksheet }</b>
    💰 Общая сумма: <b>{ $total }</b>
    ✅ Оплачено: <b>{ $paid }</b>
    ⏳ Осталось: <b>{ $remaining }</b>
    🗓️ Срок: <b>{ $deadline }</b>
    ⚖️ Вес: <b>{ $vazn } кг</b>
    📦 Трек-коды: <b>{ $track_codes }</b>
    👤 Админ: <b>{ $full_name }</b>
    📱 Телефон: { $phone }
    🆔 Telegram ID: { $telegram_id }

payment-confirmed-channel-cash = 📌 Платёж ПОДТВЕРЖДЁН! (💵 Наличные)

    🆔 ID клиента: <code>{ $client_code }</code>
    ✈️ Рейс: <b>{ $worksheet }</b>
    💰 Сумма: <b>{ $summa }</b>
    👤 Админ: <b>{ $full_name }</b>
    📱 Телефон: { $phone }
    🆔 Telegram ID: { $telegram_id }
    👤 Админ: <b>{ $full_name }</b>
    📞 Телефон: <code>{ $phone }</code>
    💬 Telegram ID: <code>{ $telegram_id }</code>
payment-cash-confirmed-group = ✅ Платёж { $client_code } по рейсу { $worksheet }, строка { $row_number } оплачен наличными и груз выдан. Админ: { $admin_name }
payment-cash-confirmed-success = ✅ Наличная оплата подтверждена!
payment-already-exists = ⚠️ Этот платёж уже существует!
payment-already-taken = ⚠️ Этот груз уже получен!

    🆔 ID клиента: { $client_code }
    ✈️ Рейс: { $worksheet }
    💰 Сумма: { $summa } сум
    👤 Пользователь: { $full_name }
    📱 Телефон: { $phone }
    🆔 Telegram ID: { $telegram_id }

# Admin Panel
admin-welcome = Здравствуйте!

    🔐 <b>Добро пожаловать в админ-панель!</b>

    Используйте кнопки ниже:
admin-back-to-menu = 🔙 Вы вернулись в главное меню

# Admin - Databases Import
admin-databases-title = 📥 <b>Импорт Баз Данных</b>

    ⚠️ <b>Важно:</b>
    1️⃣ Подготовьте Excel в формате как в примерах
    2️⃣ Нажмите кнопку ниже чтобы перейти на страницу импорта
    3️⃣ Выберите нужную базу и загрузите Excel

    📊 <b>Базы данных:</b>
    • <b>БАЗА КИТАЙ</b> - Pre-flight (грузы прибывшие из Китая)
    • <b>БАЗА УЗБЕКИСТАН</b> - Post-flight (грузы прибывшие в Узбекистан)

    💡 <i>Название каждого листа Excel = Название рейса</i>

admin-db-clear-all-warning = ⚠️ <b>ВНИМАНИЕ!</b>

    Если вы подтвердите, <b>ВСЯ БАЗА ИМПОРТА БУДЕТ ОЧИЩЕНА</b>!

    Это действие необратимо!

    Продолжить?

admin-db-clear-recent-warning = ⚠️ <b>ВНИМАНИЕ!</b>

    Все записи добавленные за последние <b>5 минут</b> будут <b>УДАЛЕНЫ</b>!

    Продолжить?

admin-db-cleared-all = ✅ Вся база импорта очищена!

    Удалено записей: { $count } шт

admin-db-cleared-recent = ✅ Записи за последние 5 минут удалены!

    Удалено записей: { $count } шт

admin-db-clear-cancelled = ❌ Очистка отменена

# Admin - Database Buttons
btn-open-import-page = 🌐 Открыть страницу импорта
btn-clear-all-database = 🗑 Очистить старую базу
btn-clear-recent-imports = ⏱ Очистить последние 5 минут
btn-confirm-action = ✅ Подтвердить
btn-cancel-action = ❌ Отменить

# Admin Menu Buttons
btn-admin-databases = 📥 Базы данных
btn-admin-track-check = 📦 Проверка трек-кода
btn-admin-user-search = 👤 Поиск пользователя
btn-admin-client-verification = ✅ Проверка пользователя
btn-admin-send-message = 📢 Отправить рекламу
btn-admin-upload-photo = 📸 Загрузить фото
btn-admin-get-data = 📁 Получить данные
btn-admin-referral-data = 🔗 Получить базу рефералов
btn-admin-leftover-cargo = 📦 Получить остатки товаров
btn-admin-leftover-notifications = 📢 Уведомления
btn-admin-settings = ⚙️ Настройки

# Admin - Referral Data
admin-referral-title = 📊 <b>Статистика рефералов</b>
admin-referral-total-users = 👥 <b>Всего пользователей:</b> { $count }
admin-referral-total-referrers = 🔗 <b>Всего рефереров:</b> { $count }
admin-referral-total-invited = 📥 <b>Всего приглашённых:</b> { $count }
admin-referral-top-referrers-title = 🏆 <b>Топ рефереры:</b>
admin-referral-top-referrer-item = { $index }. { $code } - { $name } ({ $count } чел.)
admin-referral-no-top-referrers = ⚠️ Топ рефереры не найдены.
admin-referral-excel-preparing = ⏳ Файл Excel готовится...
admin-referral-excel-ready = 📊 База рефералов готова!
admin-referral-error = ❌ Произошла ошибка: { $error }
admin-referral-error-retry = Пожалуйста, попробуйте снова.

# Admin - Get Data
admin-data-title = 📊 <b>Статистика пользователей</b>
admin-data-total-clients = 👥 <b>Всего пользователей:</b> { $count }
admin-data-active-clients = ✅ <b>Активных пользователей:</b> { $count }
admin-data-inactive-clients = ⚪ <b>Неактивных пользователей:</b> { $count }
admin-data-first-registration = 📅 <b>Первая регистрация:</b> { $date }
admin-data-last-registration = 📅 <b>Последняя регистрация:</b> { $date }
admin-data-not-available = Недоступно
admin-data-excel-preparing = ⏳ Подготовка Excel файла...
admin-data-excel-ready = 📊 База пользователей готова!
admin-data-error = ❌ Произошла ошибка: { $error }
admin-data-error-retry = Пожалуйста, попробуйте снова.

# Admin - Get Data Excel Columns
admin-data-column-id = ID
admin-data-column-telegram-id = Telegram ID
admin-data-column-full-name = Ф.И.О.
admin-data-column-phone = Номер телефона
admin-data-column-language = Язык
admin-data-column-is-admin = Админ
admin-data-column-passport-series = Серия паспорта
admin-data-column-pinfl = ПИНФЛ
admin-data-column-date-of-birth = Дата рождения
admin-data-column-region = Область
admin-data-column-address = Адрес
admin-data-column-client-code = Client ID
admin-data-column-referrer-telegram-id = Referrer Telegram ID
admin-data-column-referrer-client-code = Referrer Client ID
admin-data-column-is-logged-in = Вошёл
admin-data-column-created-at = Дата регистрации

# Admin - Leftover Cargo
admin-leftover-title = 📦 <b>Статистика остатков товаров</b>
admin-leftover-paid-not-taken = ✅ <b>Оплачено, но не забрано:</b> { $count } шт.
admin-leftover-unpaid-not-taken = ⚠️ <b>Не оплачено и не забрано:</b> { $count } шт.
admin-leftover-total = 📊 <b>Всего остатков:</b> { $count } шт.
admin-leftover-estimated-profit = 💰 <b>Ориентировочная прибыль (оплачено, но не забрано):</b> { $amount } сум
admin-leftover-by-flight-title = ✈️ <b>По рейсам:</b>
admin-leftover-by-flight-item = • { $flight }: Оплачено { $paid }, Не оплачено { $unpaid }, Всего { $total }
admin-leftover-more-flights = ... и ещё { $count } рейсов
admin-leftover-by-region-title = 📍 <b>По областям:</b>
admin-leftover-by-region-item = • { $region }: Оплачено { $paid }, Не оплачено { $unpaid }, Всего { $total }
admin-leftover-more-regions = ... и ещё { $count } областей
admin-leftover-excel-preparing = ⏳ Подготовка Excel файла...
admin-leftover-progress-track-codes = 🔍 Поиск трек-кодов (БД + Google Sheets)...
admin-leftover-progress-excel = 📄 Формирование Excel файла...
admin-leftover-excel-ready = 📊 База остатков товаров готова!
admin-leftover-error = ❌ Произошла ошибка: { $error }
admin-leftover-error-retry = Пожалуйста, попробуйте снова.

# Admin - Leftover Cargo Excel Columns
admin-leftover-column-client-code = Client ID
admin-leftover-column-full-name = Ф.И.О.
admin-leftover-column-region = Область
admin-leftover-column-address = Адрес
admin-leftover-column-phone = Номер телефона
admin-leftover-column-passport-series = Серия паспорта
admin-leftover-column-pinfl = ПИНФЛ
admin-leftover-column-flight-name = Название рейса
admin-leftover-column-row-number = Номер строки
admin-leftover-column-track-code = Трек-код
admin-leftover-column-cargo-source = Источник груза
admin-leftover-column-is-paid = Оплачено
admin-leftover-column-is-taken-away = Забрано
admin-leftover-column-taken-away-date = Дата получения
admin-leftover-column-payment-amount = Сумма оплаты
admin-leftover-column-payment-date = Дата оплаты

# Admin - Settings
admin-settings-title = ⚙️ <b>Настройки</b>ㅤㅤㅤㅤㅤ

    Что вы хотите отредактировать?

admin-settings-btn-foto-hisobot = 📝 Фото отчёт
admin-settings-btn-extra-charge = 💰 Дополнительная сумма
admin-settings-btn-price-per-kg = 📦 Цена за 1 кг
admin-settings-btn-cards = 💳 Редактировать карты
admin-settings-btn-add-admin = ➕ Добавить администратора
admin-settings-btn-backup = 💾 Резервная копия
admin-settings-btn-ostatka-daily = ♻️ Авто-рассылка: { $status }
admin-settings-btn-ostatka-flights = ✈️ Выбор рейсов
admin-settings-btn-back = ⬅️ Назад
admin-settings-btn-back-to-settings = ⬅️ Вернуться к настройкам

# Admin - Settings: Ostatka daily digest
admin-settings-ostatka-enabled = ✅ Включено
admin-settings-ostatka-disabled = ⛔️ Выключено
admin-settings-ostatka-toggle-success = ♻️ Статус авто-рассылки обновлён: { $status }

# Admin - Settings: Ostatka flight selection
admin-settings-ostatka-flights-title = ✈️ <b>Выберите рейсы для ежедневной рассылки</b>

Отметьте A- рейсы, которые будут отправляться автоматически каждый день. Отмеченные ✅, не отмеченные ⬜.
admin-settings-ostatka-flights-empty = ⚠️ A- рейсов пока нет

admin-settings-current-value = Текущее значение
admin-settings-no-value = Значение не установлено

# Foto Hisobot
admin-settings-foto-hisobot-title = 📝 <b>Редактирование фото отчёта</b>
admin-settings-foto-hisobot-prompt = Введите новый текст:
admin-settings-foto-hisobot-success = ✅ Фото отчёт успешно обновлён!

# Extra Charge
admin-settings-extra-charge-title = 💰 <b>Редактирование дополнительной суммы</b>
admin-settings-extra-charge-current = Текущая дополнительная сумма: <b>{ $amount } сум</b>
admin-settings-extra-charge-rate = 1$ = <b>{ $rate } сум</b>
admin-settings-extra-charge-prompt = Введите новую дополнительную сумму (сум):
admin-settings-extra-charge-success = ✅ Дополнительная сумма успешно обновлена!
admin-settings-extra-charge-invalid-format = ❌ Неверный формат! Введите только число.
admin-settings-extra-charge-invalid-negative = ❌ Нельзя вводить отрицательное значение!

# Price Per KG
admin-settings-price-per-kg-title = 📦 <b>Редактирование цены за 1 кг</b>

    <b>price_per_kg</b> — Цена за 1 кг груза (значение по умолчанию)
admin-settings-price-per-kg-current = Текущая цена: <code>{ $amount }$</code>
admin-settings-price-per-kg-converted = UZS: <b>{ $amount } сум</b>
admin-settings-price-per-kg-final = Итого (цена + доплата): <b>{ $amount } сум</b>
admin-settings-price-per-kg-rate = 1$ = <b>{ $rate } сум</b>
admin-settings-price-per-kg-prompt = Введите новую цену (USD):
admin-settings-price-per-kg-success = ✅ Цена за 1 кг успешно обновлена!
admin-settings-price-per-kg-invalid = ❌ Цена должна быть больше 0!
admin-settings-price-per-kg-invalid-format = ❌ Неверный формат! Введите только число (например: 9.5).

# Payment Cards
admin-settings-cards-title = 💳 <b>Платёжные карты</b>
admin-settings-cards-empty = 💳 Платёжные карты отсутствуют.

    Нажмите кнопку ➕ Добавить карту.
admin-settings-cards-active = Активна
admin-settings-cards-inactive = Неактивна
admin-settings-cards-activate = ✅ Активировать
admin-settings-cards-deactivate = ❌ Деактивировать
admin-settings-cards-add = ➕ Добавить карту
admin-settings-cards-page = 📄 Страница: { $page }/{ $total }
admin-settings-cards-not-found = ❌ Карта не найдена!
admin-settings-cards-last-active-warning = ⚠️ Должна быть хотя бы одна активная карта!
admin-settings-cards-toggle-success = ✅ Статус карты изменён!
admin-settings-cards-add-prompt-name = Введите имя владельца карты:
admin-settings-cards-add-prompt-number = Введите номер карты:
admin-settings-cards-add-invalid-name = ❌ Имя не может быть пустым!
admin-settings-cards-add-invalid-number-format = ❌ Неверный формат! Введите только цифры.
admin-settings-cards-add-invalid-number-length = ❌ Номер карты должен содержать 16-19 цифр!
admin-settings-cards-add-duplicate = ❌ Этот номер карты уже существует!
admin-settings-cards-add-success = ✅ Карта успешно добавлена!

admin-settings-error = ❌ Произошла ошибка!

# Admin - Settings: Add Admin
admin-settings-add-admin-prompt = Отправьте один из следующих идентификаторов:
    - Telegram ID
    - Client code
    - Username (@вашusername)
admin-settings-add-admin-not-found = ❌ Пользователь не найден!
admin-settings-add-admin-not-found-withid = ❌ Пользователь не найден: { $client_id }
admin-settings-add-admin-multiple-found = ❌ Найдено несколько пользователей! Пожалуйста, введите более точный идентификатор.
admin-settings-add-admin-already-admin = ⚠️ Этот пользователь уже является администратором!
admin-settings-add-admin-success = ✅ Вы сделали пользователя { $identifier } администратором через { $method }
admin-settings-add-admin-welcome = 🎉 Поздравляем! Вы получили права администратора.

# Admin - Settings: Database Backup
admin-settings-backup-creating = 💾 Создание резервной копии...
admin-settings-backup-in-progress = ⏳ Создание резервной копии базы данных, пожалуйста, подождите...
admin-settings-backup-success = ✅ Резервная копия успешно создана и отправлена!
admin-settings-backup-error = ❌ Ошибка при создании резервной копии. Проверьте логи сервера.
admin-settings-backup-pgdump-not-found = ❌ pg_dump не найден. Убедитесь, что установлены PostgreSQL client tools.
admin-settings-backup-caption = 📦 Резервная копия базы данных

# Admin - Leftover Cargo: Notifications
admin-leftover-notifications-btn = 🔔 Уведомления
admin-leftover-notifications-title = 🔔 <b>Настройки уведомлений</b>
admin-leftover-notifications-status = Статус
admin-leftover-notifications-on = ✅ Включено
admin-leftover-notifications-off = ❌ Выключено
admin-leftover-notifications-period = Периодичность
admin-leftover-notifications-days = дней
admin-leftover-notifications-not-set = Не установлено
admin-leftover-notifications-turn-on = ✅ Включить
admin-leftover-notifications-turn-off = ❌ Выключить
admin-leftover-notifications-updated = ✅ Настройки обновлены
admin-leftover-notifications-period-set = ✅ Периодичность установлена на { $period } дней
admin-leftover-notifications-back = ⬅️ Назад

# Notification Messages (Leftover Cargo)
notification-leftover-greeting = 👋 Здравствуйте!
notification-leftover-explanation = У вас есть не забранные грузы.
notification-leftover-paid-count = ✅ Оплачено, но не забрано: <b>{ $count } шт</b>
notification-leftover-unpaid-count = ⚠️ Не оплачено и не забрано: <b>{ $count } шт</b>
notification-leftover-call-to-action = Пожалуйста, заберите ваши грузы или произведите оплату.

# Partial Payment Reminders
reminder-partial-deadline-5days = ⏰ <b>Напоминание: Частичная оплата</b>
    ✈️ Рейс: { $flight }
    💰 Всего: { $total } сум
    ✅ Оплачено: { $paid } сум
    ⏳ Остаток: { $remaining } сум
    🗓️ Срок: { $deadline }
    ⚠️ До срока оплаты осталось { $days } дней!

reminder-partial-deadline-2days = ⚠️ <b>Важное напоминание: Частичная оплата</b>
    ✈️ Рейс: { $flight }
    💰 Всего: { $total } сум
    ✅ Оплачено: { $paid } сум
    ⏳ Остаток: { $remaining } сум
    🗓️ Срок: { $deadline }
    ⚠️ До срока оплаты осталось всего { $days } дня! Пожалуйста, оплатите остаток.

reminder-partial-deadline-today = 🚨 <b>Последний день: Частичная оплата</b>
    ✈️ Рейс: { $flight }
    💰 Всего: { $total } сум
    ✅ Оплачено: { $paid } сум
    ⏳ Остаток: { $remaining } сум
    🗓️ Срок: { $deadline }
    🚨 Сегодня последний день оплаты! Пожалуйста, оплатите остаток сегодня, иначе груз не будет выдан!

# Admin - Client Search
admin-search-title = 🔍 <b>Поиск пользователя</b>

    Введите код клиента (например: SS500):

admin-search-invalid-prefix = ❌ <b>Неверный формат!</b>

    Код клиента должен начинаться с <code>{ $prefix }</code>.
    Пример: <code>{ $example }</code>

admin-search-invalid-format = ❌ <b>Неверный формат!</b>

    Код клиента должен заканчиваться цифрой.
    Пример: <code>{ $example }</code>

admin-search-not-found = ❌ <b>Клиент не найден!</b>

    Код клиента: <code>{ $code }</code>

    Клиент с таким кодом не найден в базе.

admin-search-found = ✅ <b>Клиент найден!</b>

admin-search-basic-info = 👤 <b>Основная информация:</b>
    ━━━━━━━━━━━━━━━━━━
    🆔 Код клиента: <code>{ $code }</code>
    🆔 Новый код клиента: <code>{ $new_code }</code>
    ID Legacy code: <code>{ $legacy_code }</code>
    💡 Telegram ID: <code>{ $telegram_id }</code>
    👤 Ф.И.О: <b>{ $name }</b>
    📞 Телефон: <code>{ $phone }</code>
    🎂 Дата рождения: <code>{ $birthday }</code>
    📄 Серия паспорта: <code>{ $passport }</code>
    🔢 ПИНФЛ: <code>{ $pinfl }</code>
    🌍 Область: <code>{ $region }</code>
    📍 Адрес: <code>{ $address }</code>
    👥 Приглашено: <b>{$referral_count} чел.</b>
    📅 Зарегистрирован: <code>{ $created }</code>

admin-search-payments-info = 💳 <b>Информация о платежах:</b>
    ━━━━━━━━━━━━━━━━━━
    📊 Всего платежей: <b>{ $count } раз</b>

admin-search-last-payment = 💰 <b>Последний платёж:</b>
    ✈️ Рейс: <code>{ $flight }</code>
    📦 Номер ряда: <code>{ $row }</code>
    💵 Сумма: <code>{ $amount } сум</code>
    📅 Дата: <code>{ $date }</code>

admin-search-has-payment-receipt = 🧾 Чек оплаты имеется
admin-search-cargo-taken = ✅ Груз забран: <code>{ $date }</code>
admin-search-cargo-not-taken = ⏳ Груз не забран

admin-search-extra-passports = 📋 <b>Дополнительные паспорта:</b>
    ━━━━━━━━━━━━━━━━━━
    📄 Добавлено паспортов: <b>{ $count } шт</b>

admin-search-passport-images = ⬆️ Фотографии паспорта

btn-add-client = ➕ Добавить клиента
btn-edit-client = ✏️ Редактировать
btn-delete-client = 🗑 Удалить

not-provided = Не указано
unknown = Неизвестно

admin-delete-confirm = ⚠️ <b>Предупреждение!</b>

    Вы действительно хотите удалить этого клиента?

    👤 Ф.И.О: <b>{ $name }</b>
    🆔 Код: <code>{ $code }</code>

    ❗️ Это действие нельзя отменить!

btn-confirm-delete = ✅ Да, удалить
btn-cancel-delete = ❌ Нет, отменить

admin-delete-success = ✅ <b>Клиент удалён!</b>

# Admin - Client Verification
admin-verification-choose-search-type = 🔍 <b>Проверка пользователя</b>

    Выберите тип поиска:

btn-search-by-code = 📋 По коду клиента
btn-search-by-flight = ✈️ По рейсу

admin-verification-ask-client-code = 🔍 <b>Поиск по коду клиента</b>

    Введите код клиента:

admin-verification-ask-flight-code = ✈️ <b>Поиск по рейсу</b>

    Введите код рейса (например: R123):

admin-verification-client-not-found = ❌ <b>Клиент не найден!</b>

    Пожалуйста, введите правильный код клиента.

admin-verification-cancelled = ❌ Проверка отменена.

admin-verification-client-found = ✅ <b>Клиент найден</b>

    🆔 <b>Код клиента:</b> <code>{ $client_code }</code>
    👤 <b>Ф.И.О:</b> <b>{ $full_name }</b>
    📱 <b>Telegram ID:</b> <code>{ $telegram_id }</code>

    📊 <b>Платежей:</b> <b>{ $total_payments } шт</b>
    ✅ <b>Забрано:</b> <b>{ $taken_away } шт</b>

btn-verification-full-info = 📋 Полная информация
btn-verification-payments-list = 💳 Список платежей
btn-verification-select-flight = 🛫 Выбрать рейс
btn-verification-all-payments = 📋 Все платежи
btn-verification-show-cargos = 📦 Посмотреть грузы
btn-verification-unpaid-payments = 💰 Неоплаченные платежи

# Unpaid payments section
admin-verification-no-unpaid = ✅ Все платежи оплачены.
admin-verification-unpaid-item = 💰 <b>Неоплаченный платёж</b>
    ✈️ Рейс: <code>{ $flight }</code>
    📦 Ряд: <code>{ $row }</code>
    💵 Итого: <code>{ $total } сум</code>
    ⏳ Остаток: <code>{ $remaining } сум</code>
    📅 Дата: <code>{ $date }</code>
admin-verification-unpaid-item-partial = 💰 <b>Частичная оплата</b>
    ✈️ Рейс: <code>{ $flight }</code>
    📦 Ряд: <code>{ $row }</code>
    💵 Итого: <code>{ $total } сум</code>
    ✅ Оплачено: <code>{ $paid } сум</code>
    ⏳ Остаток: <code>{ $remaining } сум</code>
    📅 Дата: <code>{ $date }</code>
admin-verification-unpaid-item-no-cargo = 💰 <b>Неоплаченный платёж</b>
    ✈️ Рейс: <code>{ $flight }</code>
    💵 Итого: <code>{ $total } сум</code>
    ⏳ Остаток: <code>{ $remaining } сум</code>
    📅 Дата: <code>{ $date }</code>
    ⚠️ Данные о грузе не найдены
admin-verification-unpaid-nav = 📄 Платёж { $current }/{ $total }
admin-verification-no-cargo-data = ⚠️ Данные о грузе не найдены

# Common terms
amount = Сумма

admin-verification-flights = Рейсы
admin-verification-select-flight-prompt = Какой рейс вы хотите посмотреть?
admin-verification-no-flights = Для этого пользователя рейсов не найдено
btn-filter-by-flight = ✈️ Фильтр по рейсам
btn-clear-flight-filter = ❌ Очистить фильтр рейсов

admin-verification-no-payments = ℹ️ Платежи не найдены.
admin-verification-no-cargos = ❌ Грузы для этого рейса не найдены
admin-verification-cargos-shown = ✅ Показано { $count } груз(ов)
admin-verification-cargo-info = 📦 <b>Информация о грузе</b>

    ✈️ Рейс: <b>{ $flight }</b>
    👤 Клиент: <b>{ $client }</b>
    { $weight_info }{ $comment_info }
    📅 Загружено: { $date }

    { $status }
admin-verification-cargo-weight = ⚖️ Вес: <b>{ $weight } кг</b>
admin-verification-cargo-comment = 💬 Комментарий: <i>{ $comment }</i>
admin-verification-cargo-sent = ✅ <b>Отправлено клиенту</b>
admin-verification-cargo-not-sent = ⏳ <b>Не отправлено клиенту</b>
admin-verification-cargo-photo-error = ❌ Ошибка загрузки фото: { $error }

admin-verification-payment-info = 💰 <b>Информация о платеже:</b>
    ✈️ Рейс: <code>{ $flight }</code>
    📦 Ряд: <code>{ $row }</code>
    💵 Сумма: <code>{ $amount } сум</code>
    ⚖️ Вес: <code>{ $weight }</code>
    📅 Дата: <code>{ $date }</code>

admin-verification-no-receipt = ℹ️ Чек оплаты отсутствует

admin-verification-receipt-unavailable = ⚠️ Чек оплаты не загружен

admin-verification-page-nav = 📄 Страница { $current }/{ $total }

btn-previous = ⬅️ Предыдущая
btn-next = Следующая ➡️

# Filter buttons
btn-filter-all = 🔄 Все
btn-filter-partial = 🧩 Частичная оплата
btn-filter-paid = ✅ Оплачено
btn-filter-unpaid = ⏳ Не оплачено
btn-filter-pending = ⏳ Ожидается
btn-filter-taken = 📦 Забрано
btn-filter-not-taken = 🔴 Не забрано

# Sort buttons
btn-sort-newest = 🔽 Новые сначала
btn-sort-oldest = 🔼 Старые сначала

# Mark as taken
btn-mark-as-taken = ✅ Отметить как забрано
btn-cash-remainder = 💵 Остаток наличными
btn-account-payment = 🧾 Оплата на счёт
btn-account-payment-click = 💳 Click
btn-account-payment-payme = 💳 Payme
btn-account-payment-cancel = ❌ Отмена
admin-verification-marked-as-taken = ✅ Груз отмечен как забранный!
admin-verification-mark-failed = ❌ Ошибка при отметке.

# Account payment
admin-account-payment-select-provider = 🧾 <b>Выберите провайдера:</b>
admin-account-payment-confirm = ⚠️ <b>Подтвердить оплату?</b>

    💰 Сумма: <code>{ $amount } сум</code>
    🏦 Провайдер: <b>{ $provider }</b>
    📋 Transaction ID: <code>{ $transaction_id }</code>

    Нажмите "Да" для подтверждения.

admin-account-payment-cancelled = ❌ Оплата отменена.
admin-account-payment-success = ✅ Оплата на счёт успешно подтверждена!
admin-account-payment-already-confirmed = ⚠️ Эта оплата уже подтверждена.
admin-account-payment-transaction-not-found = ❌ Платёж не найден.
admin-account-payment-error = ❌ Ошибка при подтверждении оплаты.

# Account payment channel notification
account-payment-channel-notification = ✅ <b>ОПЛАТА НА СЧЁТ ПОДТВЕРЖДЕНА</b>

    👤 Клиент: <code>{ $client_code }</code>
    🆔 Transaction ID: <code>{ $transaction_id }</code>
    ✈️ Рейс: <b>{ $flight }</b>
    💰 Сумма: <b>{ $amount } сум</b>
    🏦 Провайдер: <b>{ $provider }</b>
    👨‍💼 Админ: { $admin_name }
    🕒 Время: { $time }

# Flight search
admin-verification-no-flights-found = ❌ <b>Рейс не найден!</b>

    По рейсу <code>{ $flight }</code> не найдено платежей.

admin-verification-flight-results = ✈️ <b>Рейс: { $flight }</b>

    📊 Всего: <b>{ $total } платежей</b>
    📄 Страница: <b>{ $page }/{ $total_pages }</b>

admin-verification-flight-item = Код: <code>{ $code }</code> | Ряд: <code>{ $row }</code> | Сумма: <code>{ $amount } сум</code>

    👤 Ф.И.О: <b>{ $name }</b>
    🆔 Код: <code>{ $code }</code>

    Клиент успешно удалён из базы.

admin-delete-not-found = ❌ Клиент не найден!

# Track code check
admin-track-check-enter-code = 📦 <b>Проверка трек-кода</b>

    Введите трек-код:

admin-track-check-cancelled = ❌ Проверка трек-кода отменена.

admin-track-check-not-found = ❌ <b>Трек-код не найден!</b>

    По трек-коду <code>{ $track_code }</code> не найдено никакой информации.

    Пожалуйста, проверьте код и попробуйте снова.

admin-track-check-uzbekistan-info = 🇺🇿 <b>НА СКЛАДЕ В УЗБЕКИСТАНЕ</b>

    🔍 <b>Трек-код:</b> <code>{ $track_code }</code>
    👤 <b>ID клиента:</b> <code>{ $client_id }</code>
    ✈️ <b>Рейс:</b> { $flight }
    📅 <b>Дата прибытия:</b> { $arrival_date }
    ⚖️ <b>Вес:</b> { $weight } кг
    🔢 <b>Количество:</b> { $quantity }
    💵 <b>Оплата:</b> { $total_payment } сум

    ✅ <b>Статус:</b> Груз на складе в Узбекистане

admin-track-check-china-info = 🇨🇳 <b>НА СКЛАДЕ В КИТАЕ</b>

    🔍 <b>Трек-код:</b> <code>{ $track_code }</code>
    👤 <b>ID клиента:</b> <code>{ $client_id }</code>
    ✈️ <b>Рейс:</b> { $flight }
    📅 <b>Принят:</b> { $checkin_date }
    📦 <b>Товар (RU):</b> { $item_name_ru }
    📦 <b>Товар (CN):</b> { $item_name_cn }
    ⚖️ <b>Вес:</b> { $weight } кг
    🔢 <b>Количество:</b> { $quantity }
    📦 <b>Номер коробки:</b> { $box_number }

    ⚠️ <b>Статус:</b> Груз на складе в Китае, еще не прибыл в Узбекистан

admin-track-check-summary = 📊 <b>Результаты поиска:</b>

    📦 Всего найдено: { $total } шт
    🇺🇿 В Узбекистане: { $in_uzbekistan } шт
    🇨🇳 В Китае: { $in_china } шт


# User Track code check
user-track-check-enter-code = 📦 <b>Проверка трек-кода</b>

    Введите трек-код:

    <i>Введите трек-код для поиска вашего груза.</i>

user-track-check-cancelled = ❌ Проверка трек-кода отменена.

user-track-check-not-found = ❌ <b>Трек-код не найден!</b>

    По трек-коду <code>{ $track_code }</code> не найдено никакой информации.

    Пожалуйста, проверьте код и попробуйте снова или свяжитесь с администратором.

user-track-check-uzbekistan-info = ✅ <b>ВАШ ГРУЗ В УЗБЕКИСТАНЕ!</b>

    🔍 <b>Трек-код:</b> <code>{ $track_code }</code>
    ✈️ <b>Рейс:</b> { $flight }
    📅 <b>Дата прибытия:</b> { $arrival_date }
    💵 <b>Оплата:</b> { $total_payment } сум
    ⚖️ <b>Вес:</b> { $weight } кг
    🔢 <b>Количество:</b> { $quantity }

    ✅ Ваш груз на нашем складе в Узбекистане!
    📞 Свяжитесь с администратором для оплаты и получения.

user-track-check-china-info = 🛫 <b>ВАШ ГРУЗ В ПУТИ</b>

    🔍 <b>Трек-код:</b> <code>{ $track_code }</code>
    📅 <b>Принят в Китае:</b> { $checkin_date }
    📦 <b>Товар:</b> { $item_name }
    ⚖️ <b>Вес:</b> { $weight } кг
    🔢 <b>Количество:</b> { $quantity }
    ✈️ <b>Рейс:</b> { $flight }
    📦 <b>Номер коробки:</b> { $box_number }

    ⚠️ Ваш груз на складе в Китае, в пути в Узбекистан.
    ⏰ Мы уведомим вас о прибытии в Узбекистан.

user-track-check-summary = 📊 <b>Результат:</b>

    📦 Всего: { $total } шт
    ✅ В Узбекистане: { $in_uzbekistan } шт
    🛫 В Китае (в пути): { $in_china } шт

user-track-check-search-again = 💡 <b>Отправьте следующий трек-код для проверки другого груза.</b>
    Нажмите кнопку <i>❌ Отмена</i>, чтобы остановить процесс.

# Photo Upload WebApp
btn-open-photo-webapp = 📸 Загрузить фото (Web)

msg-photo-upload-webapp = 🖼 <b>Система загрузки фото</b>

    Нажмите кнопку ниже для загрузки фотографий рейсов и грузов.

    📌 <b>Возможности:</b>
    • Создание и просмотр рейсов
    • Загрузка фото груза
    • Указание Client ID и веса
    • Просмотр всех фотографий


# Info - Photos and Reports  
btn-view-cargo-photos = 📸 Посмотреть фото
info-report-not-sent = Отчет не отправлен
info-no-cargo-photos = ⚠️ Фотографии для этого рейса не найдены.
info-cargo-photos-summary = 📸 <b>Всего отправлено { $total } фото</b>

    ✈️ Рейс: <b>{ $flight_name }</b>
    👤 Код клиента: <b>{ $client_code }</b>

info-report-not-sent-message = ⚠️ <b>Отчет не отправлен</b>

    ✈️ Рейс: <b>{ $flight_name }</b>
    👤 Код клиента: <b>{ $client_code }</b>
    { $track_codes }
    
    Фото-отчет для этого рейса еще не был отправлен администратором.
    Пожалуйста, свяжитесь с администратором или попробуйте позже.

    <i>Нажмите кнопку, чтобы вернуться к списку рейсов.</i>

# Profile - Address and Region Edit
btn-edit-address = 🏠 Изменить адрес
profile-select-region = 🌍 <b>Выберите ваш регион:</b>
profile-enter-address = 📍 <b>Введите точный адрес:</b>

    Например: Ташкентский район, МФЙ Кибрай, улица Янги Хаёт, дом 15

profile-address-updated = ✅ Адрес успешно обновлен!

# Profile - Referal Balance
profile-referal-balance = 💰 Реферальный баланс: { $balance } сум

# Delivery Request
btn-send-request = 📦 Оставить заявку
delivery-select-type = 🚚 <b>Выберите тип доставки:</b>
delivery-type-uzpost = 📮 UZPOST
delivery-type-yandex = 🚕 Yandex
delivery-type-akb = 🍊 akb Dastavka
delivery-type-bts = 🚌 BTS

btn-confirm-profile = ✅ Подтвердить
btn-edit-profile = ✏️ Редактировать

delivery-select-flights = ✈️ <b>Выберите рейсы:</b>

    Выберите один или несколько рейсов из списка:

btn-ready-submit = ✅ Готово

delivery-uzpost-warning = ⚠️ <b>Важно!</b>

    Для использования этой доставки требуется предоплата.

    💰 <b>Цены:</b>
    • За 1 кг: 15,000 сум
    • Для Каракалпакстана, Сурхандарьи и Хорезма: 18,000 сум

btn-submit-delivery-request = 📦 Оставить заявку
btn-select-other-delivery = 🔄 Выбрать другое

delivery-send-payment-proof = 💳 <b>Отправьте чек оплаты:</b>

    Пожалуйста, отправьте фото чека или PDF-файл после оплаты.

delivery-request-submitted = ✅ Заявка успешно отправлена!

    Скоро будет рассмотрена администратором.

# Delivery Request - Admin Notifications
delivery-admin-new-request = 📦 <b>Новая заявка!</b>

    Тип доставки: { $delivery_type }
    🆔 ID клиента: { $client_code }
    📞 Тел: { $phone }
    🏠 Адрес: { $region } область, { $address }
    ✈️ Рейсы: { $flights }

btn-approve-delivery = ✅ Одобрить
btn-reject-delivery = ❌ Отклонить
btn-reject-delivery-comment = 💬 Отклонить с комментарием

# Regions of Uzbekistan
region-toshkent-city = город Ташкент
region-toshkent = Ташкентская область
region-andijan = Андижан
region-bukhara = Бухара
region-fergana = Фергана
region-jizzakh = Джиз

ак
region-namangan = Наманган
region-navoiy = Навои
region-qashqadarya = Кашкадарья
region-samarkand = Самарканд
region-sirdarya = Сырдарья
region-surkhandarya = Сурхандарья
region-karakalpakstan = Каракалпакстан
region-khorezm = Хорезм
payment-report-not-sent-message = ⚠️ <b>Отчет не отправлен</b>

    ✈️ Рейс: <b>{}</b>
    👤 Код клиента: <b>{}</b>

    Для этого рейса администратор еще не отправил фотоотчет. Пожалуйста, свяжитесь с администратором или повторите попытку позже.
profile-address-too-short = ❌ Адрес должен содержать минимум 5 символов\!

# Profile with referrals
profile-info-with-referrals = 👤 <b>Информация профиля</b>

    📝 ФИО: <b>{$full_name}</b>
    🆔 Telegram ID: { $telegram_id }
    📞 Телефон: <b>{$phone}</b>
    🆔 Код клиента: <b>{$client_code}</b>
    🪪 Серия паспорта: <b>{$passport_series}</b>
    🔢 ПИНФЛ: <b>{$pinfl}</b>
    📅 Дата рождения: <b>{$dob}</b>
    📍 Область: <b>{$region}</b>
    🏠 Адрес: <b>{$address}</b>
    👥 Приглашено: <b>{$referral_count} чел.</b>
    📅 Дата регистрации: <b>{$created_at}</b>

# Delivery Request - Missing translations
delivery-incomplete-profile = ⚠️ <b>Профиль не заполнен!</b>

    Для оформления заявки в профиле должны быть указаны:
    • Полное ФИО
    • Номер телефона
    • Область
    • Точный адрес

    Пожалуйста, сначала заполните профиль.

delivery-confirm-profile = 📋 <b>Данные профиля (для заявки):</b>

    🆔 Код клиента: <b>{$client_code}</b>
    👤 ФИО: <b>{$full_name}</b>
    📞 Телефон: <b>{$phone}</b>
    📍 Область: <b>{$region}</b>
    🏠 Адрес: <b>{$address}</b>

    Данные верны?

delivery-edit-profile-first = ℹ️ Пожалуйста, сначала отредактируйте профиль, затем снова оставьте заявку.

delivery-no-flights = ⚠️ Ваши рейсы не найдены. Чтобы оставить заявку, у вас должны быть оформленные заказы или оплата должна быть произведена на 100%.

delivery-select-flights-multiple = ✈️ <b>Выберите рейсы:</b>

    Выберите один или несколько рейсов. После завершения выбора нажмите "Готово".

delivery-select-flight-single = ✈️ <b>Выберите рейс:</b>

    Выберите один из следующих рейсов:

btn-done-selecting-flights = ✅ Готово

delivery-no-flights-selected = ⚠️ Пожалуйста, выберите хотя бы один рейс!

delivery-uzpost-send-receipt = 💳 <b>Отправьте чек оплаты:</b>

Пожалуйста, после оплаты отправьте фото чека или PDF файл.

delivery-request-approved = ✅ <b>Ваша заявка одобрена!</b>

    Ваш груз скоро будет доставлен.

delivery-request-rejected = ❌ <b>Ваша заявка отклонена</b>

    Для получения дополнительной информации свяжитесь с администратором.

delivery-approved-by-admin = ✅ Заявка одобрена

delivery-rejected-by-admin = ❌ Заявка отклонена

please-wait = Пожалуйста, потерпите немного, мы проверяем ваши данные.

delivery-all-flights-paid = ℹ️ За все выбранные рейсы уже оплачено. Пожалуйста, выберите другие рейсы.

delivery-uzpost-payment-info = 💳 <b>UZPOST - Информация об оплате</b>

    ✈️ Рейсы: <b>{$flights}</b>
    ⚖️ Общий вес: <b>{$total_weight} кг</b>
    💰 Цена за 1 кг: <b>{$price_per_kg} сум</b>
    💵 <b>Общая сумма: {$total_amount} сум</b>

    📋 <b>Карта для оплаты:</b>
    💳 Карта: <code>{$card_number}</code>
    👤 Владелец: <b>{$card_owner}</b>

    Пожалуйста, оплатите на указанную карту и отправьте чек.

delivery-uzpost-payment-info_warning = 💳 <b>UZPOST - Информация об оплате</b>

    ✈️ Рейсы: <b>{$flights}</b>
    ⚖️ Общий вес: <b>{$total_weight} кг</b>
    💰 Цена за 1 кг: <b>{$price_per_kg} сум</b>
    💵 <b>Общая сумма: {$total_amount} сум</b>

    <code>⚠️ Служба доставки UZPOST не принимает грузы весом более 20 кг.
    Если у вас есть вопросы, свяжитесь с администратором:</code>
    @AKB_CARGO

admin-settings-cards-delete-success = Карта успешно удалена

# Admin Approval
admin-approved = ✅ Одобрено!
admin-approval-success = ✅ Пользователь { $client_code } одобрен.
admin-new-user-approved = 📝 <b>Новый пользователь зарегистрирован:</b>
    
    🆔 <b>ID:</b> { $client_code }
    👤 <b>Имя:</b> { $full_name }
    📇 <b>Паспорт:</b> { $passport_series }
    📅 <b>Дата рождения:</b> { $date_of_birth }
    🏠 <b>Адрес:</b> { $region }, { $address }
    📞 <b>Телефон:</b> { $phone }
    🔢 <b>PINFL:</b> { $pinfl }
    🆔 <b>Telegram ID:</b> { $telegram_id }

client-approval-success-message = 🤝 Уважаемый клиент, поздравляем с успешной регистрацией в системе! 
    Мы отправили вам выше авиапочтовый адрес в Китае и ваш ID код ({ $client_code }). 
    Вы можете использовать этот адрес в любых китайских приложениях для оформления заказов!

    ✅ Не забудьте отправить введенный вами адрес @AKB_CARGO для подтверждения!

    ⚠️ За заказы, отправленные на неподтвержденный администраторами адрес, ответственность не несется!

# Admin Rejection
admin-rejected = ❌ Отклонено!
admin-rejection-message = ❌ Пользователь <b>{ $full_name }</b> [{ $telegram_id }] отклонен.
admin-rejection-message-with-reason = ❌ Пользователь <b>{ $full_name }</b> [{ $telegram_id }] отклонен.
    📄 Причина: { $reason }
admin-reject-reason-prompt = ❌ Введите причину отклонения
    или /skip для отмены:
client-rejection-message = ⚠️ Уважаемый { $full_name }, ваша заявка на регистрацию отклонена.
client-rejection-message-with-reason = ⚠️ Уважаемый { $full_name }, ваша заявка на регистрацию отклонена.

    ❌ Причина: { $reason }

payment-online-partial = 📝 Оставшаяся сумма для этого рейса: { $remaining } сум

# ===== WALLET (КОШЕЛЁК) =====

# Button
btn-wallet = 💰 Кошелёк

# Wallet Main Screen
wallet-balance-positive = 💰 <b>Баланс кошелька:</b> { $balance } сум

    ✅ На вашем счёте имеется переплата.

    Выберите одно из действий:

wallet-balance-negative = 💰 <b>Баланс кошелька:</b> -{ $balance } сум

    ⚠️ У вас задолженность в размере { $balance } сум.

    Выберите одно из действий:

wallet-balance-zero = 💰 <b>Баланс кошелька:</b> 0 сум

    ✅ Баланс нулевой, задолженности или переплаты нет.

# Wallet Buttons
btn-wallet-use-balance = ✅ Использовать баланс
btn-wallet-request-refund = 💸 Запросить возврат
btn-wallet-my-cards = 💳 Мои карты
btn-wallet-pay-debt = 💳 Оплатить долг
btn-wallet-new-card = ➕ Ввести новую карту
btn-wallet-add-card = ➕ Добавить карту
btn-wallet-send-receipt = 📸 Отправить чек
btn-admin-approve-refund = ✅ Подтвердить
btn-admin-reject-refund = ❌ Отклонить
btn-admin-approve-debt = ✅ Подтвердить
btn-admin-reject-debt = ❌ Отклонить

# Wallet - Use Balance Info
wallet-use-balance-info = ℹ️ Для использования баланса перейдите в раздел "💳 Оплата".

    В процессе оплаты появится возможность использовать средства со счёта.

# Wallet - Refund Flow
wallet-refund-select-card = 💸 <b>Запрос возврата</b>

    Выберите карту для возврата или введите номер новой карты:

wallet-refund-min-error = ⚠️ Минимальная сумма для возврата — { $min_amount } сум.

wallet-refund-min-limit = ⚠️ Минимальная сумма для возврата — 5 000 сум.

    Ваш баланс: { $balance } сум.

wallet-refund-enter-card = 💳 Введите номер карты (16 цифр):

wallet-refund-enter-card-number = 💳 Введите номер карты (16 цифр):

wallet-refund-enter-holder-name = 👤 Введите имя владельца карты:

wallet-refund-invalid-card = ⚠️ Неверный номер карты. Введите 16 цифр.

wallet-refund-enter-holder = 👤 Введите имя владельца карты (необязательно, для пропуска напишите "пропустить"):

wallet-refund-enter-amount = 💰 Введите сумму возврата (в сумах):

    Доступный баланс: { $balance } сум
    Минимальная сумма: 5 000 сум

wallet-refund-invalid-amount = ⚠️ Неверная сумма. Пожалуйста, введите число.

wallet-refund-amount-too-low = ⚠️ Минимальная сумма возврата: 5 000 сум.

wallet-refund-amount-too-high = ⚠️ Сумма превышает баланс.

    Доступный баланс: { $balance } сум

wallet-refund-exceeds-balance = ⚠️ Сумма превышает баланс.

    Доступный баланс: { $balance } сум

wallet-refund-confirm = 💸 <b>Запрос на возврат</b>

    💰 Сумма: { $amount } сум
    💳 Карта: { $card }
    👤 Владелец: { $holder }

    Подтверждаете?

wallet-refund-submitted = ✅ Запрос на возврат отправлен!

    Вы будете уведомлены после рассмотрения администратором.

wallet-refund-approved-user = ✅ Ваш запрос на возврат одобрен!

    💰 Возвращённая сумма: { $amount } сум

wallet-refund-rejected-user = ❌ Ваш запрос на возврат отклонён.

wallet-refund-cancelled = ❌ Запрос на возврат отменён.

wallet-refund-save-card = 💳 Сохранить эту карту?

wallet-refund-new-card = ➕ Ввести новую карту

# Wallet - Debt Payment Flow
wallet-no-debt = ✅ У вас нет задолженности.

wallet-debt-no-card = ⚠️ В данный момент нет карт для оплаты. Попробуйте позже.

wallet-debt-info = 💳 <b>Оплата долга</b>

    ⚠️ У вас задолженность { $debt } сум.

    Переведите оплату на карту ниже и отправьте чек:

    💳 Карта: <code>{ $card_number }</code>
    👤 Владелец: { $card_holder }

wallet-debt-send-receipt-prompt = 📸 После оплаты нажмите "Отправить чек".

wallet-debt-upload-receipt = 📸 Отправьте чек оплаты (фото или документ):

wallet-debt-send-receipt = 📸 Отправьте чек оплаты (фото или документ):

wallet-debt-submitted = ✅ Чек оплаты долга отправлен!

    Ожидайте подтверждения от администратора.

wallet-debt-approved-user = ✅ Оплата долга принята!

    💰 Принятая сумма: { $amount } сум

wallet-debt-rejected-user = ❌ Оплата долга отклонена. Попробуйте снова.

wallet-debt-no-cards = ⚠️ В данный момент нет карт для оплаты. Попробуйте позже.

wallet-debt-cancelled = ❌ Оплата долга отменена.

# Wallet - User Cards Management
wallet-my-cards-header = 💳 <b>Мои карты</b>

wallet-no-cards = 📭 У вас нет сохранённых карт.

    Нажмите кнопку ниже, чтобы добавить карту.

wallet-card-no-holder = Неизвестно

wallet-card-invalid-number = ⚠️ Неверный номер карты. Введите 16 цифр.

wallet-card-invalid-holder = ⚠️ Неверное имя владельца. Введите 2-255 символов.

wallet-card-limit-reached = ⚠️ Максимум можно сохранить { $limit } карт.

wallet-card-duplicate = ⚠️ Эта карта уже добавлена.

wallet-add-card-number = 💳 Введите номер новой карты (16 цифр):

wallet-add-card-holder = 👤 Введите имя владельца карты:

wallet-card-added = ✅ Карта успешно добавлена!

wallet-card-deleted = ✅ Карта удалена.

wallet-cards-title = 💳 <b>Мои карты</b>

wallet-cards-empty = 📭 У вас нет сохранённых карт.

    Нажмите кнопку ниже, чтобы добавить карту.

wallet-cards-add = ➕ Добавить карту

wallet-cards-enter-number = 💳 Введите номер новой карты (16 цифр):

wallet-cards-invalid-number = ⚠️ Неверный номер карты. Введите 16 цифр.

wallet-cards-enter-holder = 👤 Введите имя владельца карты (необязательно, для пропуска напишите "пропустить"):

wallet-cards-added = ✅ Карта успешно добавлена!

wallet-cards-deactivated = ✅ Карта удалена.

wallet-cards-deleted = ✅ Карта удалена.

wallet-cards-max-limit = ⚠️ Максимум можно сохранить 5 карт.

wallet-cards-duplicate = ⚠️ Эта карта уже добавлена.

# Wallet - Admin Notifications
wallet-admin-refund-request = 💸 <b>ЗАПРОС НА ВОЗВРАТ</b>

    👤 Клиент: { $client_code }
    📱 Имя: { $full_name }
    📞 Телефон: { $phone }
    🆔 Telegram ID: { $telegram_id }

    💰 Запрашиваемая сумма: { $amount } сум

    💳 Карта: { $card }
    👤 Владелец: { $holder }

wallet-admin-debt-receipt = 💳 <b>ОПЛАТА ДОЛГА</b>

    👤 Клиент: { $client_code }
    📱 Имя: { $full_name }
    📞 Телефон: { $phone }
    🆔 Telegram ID: { $telegram_id }

    💰 Сумма долга: { $debt } сум

wallet-admin-debt-payment = 💳 <b>ОПЛАТА ДОЛГА</b>

    👤 Клиент: { $client_code }
    📱 Имя: { $full_name }
    📞 Телефон: { $phone }
    🆔 Telegram ID: { $telegram_id }

    💰 Сумма долга: { $debt_amount } сум

wallet-admin-refund-enter-amount = 💰 Введите фактически возвращённую сумму:

wallet-admin-refund-approved = ✅ Возврат подтверждён!

    👤 Клиент: { $client_code }
    💰 Сумма: { $amount } сум
    👨‍💼 Подтвердил: { $admin_name }

wallet-admin-refund-success = ✅ Возврат успешно подтверждён.

wallet-admin-refund-rejected = ❌ Возврат отклонён.

wallet-admin-refund-exceeds-balance = ⚠️ Сумма превышает баланс.

    Доступный баланс: { $balance } сум
    Введённая сумма: { $amount } сум

wallet-admin-debt-enter-amount = 💰 Введите фактически полученную сумму:

wallet-admin-debt-approved = ✅ Оплата долга подтверждена!

    👤 Клиент: { $client_code }
    💰 Сумма: { $amount } сум
    👨‍💼 Подтвердил: { $admin_name }

wallet-admin-debt-success = ✅ Оплата долга успешно подтверждена.

wallet-admin-debt-rejected = ❌ Оплата долга отклонена.

wallet-admin-invalid-amount = ⚠️ Неверная сумма. Введите положительное число.

wallet-admin-amount-exceeds = ⚠️ Сумма превышает баланс. Макс: { $max } сум

wallet-admin-cancelled = ❌ Действие отменено.

wallet-admin-rejected = ❌ Отклонено.

wallet-admin-client-not-found = ⚠️ Клиент не найден.

payment-reminder-warning = ⚠️ <b>Внимание!</b>
    Если срок оплаты истечёт, груз не будет выдан и может быть конфискован.


# Admin Payment FSM - Amount Input
admin-payment-enter-amount = 💰 Введите сумму оплаты:

    📊 Ожидаемая сумма: { $expected } сум

    ❌ Для отмены напишите /cancel.

admin-cash-payment-enter-amount = 💵 Введите сумму наличной оплаты:

    📊 Ожидаемая сумма: { $expected } сум

    ❌ Для отмены напишите /cancel.

admin-account-payment-enter-amount = 💳 Введите сумму оплаты { $provider }:

    📊 Ожидаемая сумма: { $expected } сум

    ❌ Для отмены напишите /cancel.

admin-payment-invalid-amount = ⚠️ Неверная сумма. Пожалуйста, введите положительное число.

admin-payment-amount-too-high = ⚠️ Введённая сумма слишком велика.

    📊 Ожидаемая: { $expected } сум
    💰 Введённая: { $entered } сум

    Пожалуйста, введите корректную сумму.

admin-payment-cancelled = ❌ Подтверждение оплаты отменено.

admin-payment-success = ✅ Оплата успешно подтверждена.

payment-approved-full-success =
    🎉 Поздравляем! Ваш платёж успешно принят!
    ✅ Рейс: { $worksheet }
    💰 Оплачено: { $paid } сум
    { $overpaid ->
        [0] { "" }
       *[other] 💚 Переплата (баланс на следующий рейс): { $overpaid_fmt } сум
    }
    Вы успешно оплатили полную стоимость — теперь вы можете воспользоваться
    нашими услугами доставки и забрать свой груз.
    👇 Оставьте заявку прямо сейчас:

# Debt Allocation Notifications
debt-allocation-fully-paid = ✅ { $flight } - долг полностью погашен
debt-allocation-partial = 💰 { $flight } - списано { $amount } сум
debt-allocation-credit = 💰 Остаток: { $amount } сум добавлен на ваш баланс
debt-allocation-new-balance = 📊 Новый баланс: { $balance } сум

# User Notifications
wallet-user-refund-approved = ✅ Ваш запрос на возврат одобрен!
    💰 Возвращённая сумма: { $amount } сум

wallet-user-refund-rejected = ❌ Ваш запрос на возврат отклонён.

wallet-user-debt-approved = ✅ Оплата долга принята!
    💰 Принятая сумма: { $amount } сум

wallet-user-debt-rejected = ❌ Оплата долга отклонена. Попробуйте снова.

# Admin buttons
wallet-btn-approve-refund = ✅ Подтвердить возврат
wallet-btn-reject-refund = ❌ Отклонить возврат
wallet-btn-approve-debt = ✅ Подтвердить оплату долга
wallet-btn-reject-debt = ❌ Отклонить оплату долга

# Payment Integration - Balance Toggle
payment-wallet-balance-info = 💰 Баланс кошелька: { $balance } сум
payment-wallet-toggle-on = ☑ Использовать баланс (включено)
payment-wallet-toggle-off = ☐ Использовать баланс
payment-wallet-fully-covered = ✅ Оплата полностью покрывается из кошелька.
    Остаток: { $remaining_balance } сум
payment-wallet-partial-cover = 💰 Из кошелька: { $wallet_amount } сум
    💳 К оплате: { $remaining_payment } сум

payment-wallet-available = 💰 Баланс кошелька: { $balance } сум доступно. Нажмите "💰 Использовать баланс" для использования.

payment-select-type-with-wallet = 💳 Выберите способ оплаты:

    💰 Всего: { $total } сум
    💳 Из кошелька: { $wallet_deduction } сум
    💵 К оплате: { $final } сум

btn-payment-use-wallet = 💰 Использовать баланс
btn-payment-wallet-enabled = ✅ Использовать баланс (включено)
btn-payment-wallet-only = ✅ Оплатить из кошелька

payment-wallet-success = ✅ Оплата успешно выполнена!

    ✈️ Рейс: { $flight }
    💰 Сумма: { $amount } сум

    Оплата полностью покрыта из кошелька.

# Delivery request wallet
btn-use-wallet = 💰 Использовать баланс
delivery-wallet-balance-info = 💰 Баланс кошелька: { $balance } сум. Для использования баланса перейдите в раздел Кошелёк.

delivery-uzpost-payment-info-with-wallet =
    🚚 <b>Доставка через UZPOST</b>

    ⚖️ Общий вес: <b>{ $total_weight } кг</b>
    💵 Цена за 1 кг: <b>{ $price_per_kg } сум</b>

    📦 Рейсы:
    <b>{ $flights }</b>

    💰 Общая сумма: <b>{ $total_amount } сум</b>

    💳 Списано с баланса: <b>{ $wallet_used } сум</b>
    💵 Осталось оплатить: <b>{ $final_payable } сум</b>

    🏦 Номер карты:
    <code>{ $card_number }</code>
    👤 Владелец карты: <b>{ $card_owner }</b>

    📸 Пожалуйста, отправьте чек об оплате (фото или файл).

delivery-uzpost-wallet-only-info = 🚚 <b>Доставка через UZPOST</b>

    ⚖️ Общий вес: <b>{ $total_weight } кг</b>

    📦 Рейсы:
    <b>{ $flights }</b>

    💰 Общая сумма: <b>{ $total_amount } сум</b>
    💳 С баланса: <b>{ $wallet_used } сум</b> будет списано

    🧾 Платёж ожидает подтверждения администратора.

delivery-wallet-only-submitted = ✅ Запрос на оплату отправлен!

    💰 С баланса: { $amount } сум
    🧾 Платёж ожидает подтверждения администратора.

payment-wallet-only-submitted = ✅ Запрос на оплату отправлен!

    ✈️ Рейс: { $flight }
    💰 С баланса будет списано: { $amount } сум
    🧾 Платёж ожидает подтверждения администратора.

admin-payment-enter-amount-wallet-only = 💰 Оплата из кошелька — введите сумму:

    📊 Общая сумма: { $total } сум
    💳 Из кошелька: { $wallet } сум
    ⚠️ Только оплата из кошелька.

    ✅ Для подтверждения введите 0.
    ❌ Для отмены напишите /cancel.

admin-payment-enter-amount-with-wallet = 💰 Введите сумму оплаты:

    📊 Общая сумма: { $total } сум
    💳 Из кошелька: { $wallet } сум
    💵 Ожидаемая доплата: { $expected } сум

    ❌ Для отмены напишите /cancel.

payment-info-with-wallet = 📋 Информация об оплате:

    🆔 Код клиента: <code>{ $client_code }</code>
    ✈️ Рейс: { $worksheet }
    💰 Общая сумма: <code>{ $summa }</code> сум
    💰 Из кошелька: <code>{ $wallet_used }</code> сум
    💳 К оплате: <code>{ $final_payable }</code> сум
    ⚖️ Вес: { $vazn } кг
    📦 Трек-коды: { $trek_kodlari }

    💳 Номер карты: <code>{ $card_number }</code>
    👤 ФИО: { $card_owner }

    📸 Нажмите кнопку для отправки чека:

payment-online-options = Выберите тип онлайн-оплаты
btn-view-client = Проверить пользователя

# Admin - Settings: Remove Admin
admin-settings-btn-remove-admin = 🗑 Удалить админа
admin-settings-remove-admin-title = 👮‍♂️ <b>Список администраторов:</b>
admin-settings-remove-admin-empty = 🤷‍♂️ Другие администраторы не найдены.
admin-settings-remove-admin-self = ⚠️ Вы не можете снять права администратора с самого себя!
admin-settings-remove-admin-success = ✅ { $full_name } успешно лишен прав администратора.

# --- Admin Verification WebApp ---
msg-click-to-open-verification = Нажмите на кнопку ниже для поиска и проверки пользователей 👇
btn-open-verification-webapp = 🔎 Открыть систему поиска

# API Payment Notifications (User-facing)
api-payment-success = ✅ Оплата успешно принята!
    💰 Сумма: { $amount } сум

    Ваш баланс пополнен.

api-payment-failed = ❌ Ошибка при оплате. Пожалуйста, попробуйте снова.

payment-approved-notification = ✅ Администратор подтвердил ваш платёж!
    💰 Сумма: { $amount } сум

payment-rejected-notification = ❌ Ваш платёж отклонён.
    💬 Причина: { $reason }

payment-online-confirmed-user = ✅ Оплата ({ $payment_type }) успешно принята!
    💰 Сумма: { $amount } сум
    
    Ваш баланс обновлен.


admin-settings-btn-usd-rate = 💵 Курс USD
admin-settings-rate-title = <b>💵 Настройки курса валют (USD -> UZS)</b>
admin-settings-rate-status-api = 📊 Текущий статус: <b>Автоматически через API</b>
admin-settings-rate-status-custom = 📌 Текущий статус: <b>Фиксированный курс ({ $rate } UZS)</b>
admin-settings-rate-live = 🔄 Живой курс API: 1 USD = { $rate } UZS
admin-settings-btn-edit-rate = ✏️ Изменить курс
admin-settings-btn-api-rate = 🔄 Переключить на API
admin-settings-btn-custom-rate = 📌 Фикс. курс
admin-settings-rate-prompt = <b>Пожалуйста, введите новое значение для 1 USD в сумах (например: 12600):</b>
admin-settings-rate-success = ✅ Курс USD успешно сохранен, система переведена в фиксированный режим!
admin-settings-rate-invalid = ❌ Неверное значение. Пожалуйста, введите правильное число (например: 12500).
admin-settings-rate-toggle-success = ✅ Режим валюты успешно изменен!
admin-settings-rate-no-custom = ❌ Сначала введите свой курс через кнопку "Изменить курс"!