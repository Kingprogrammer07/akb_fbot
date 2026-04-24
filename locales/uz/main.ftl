# Uzbek translations

# Commands
start = Assalomu alaykum! 👋
    AKB Cargo botiga xush kelibsiz!

start-registered = ✅ Xush kelibsiz, { $full_name }!
    📱 Telefon: { $phone }
    🆔 Client Code: { $client_code }

    Quyidagi menyulardan birini tanlang:

start-not-logged-in = 👋 { $full_name }, yana ko'rishganimizdan xursandmiz!

    Davom etish uchun tizimga kiring:

start-pending-approval = ⏳ { $full_name }, sizning so'rovingiz ko'rib chiqilmoqda.

    Iltimos, admin tomonidan tasdiqlanishini kuting.

start-with-referral = 🎁 Sizni { $referrer_name } taklif qildi!

start-new-user = Botdan foydalanish uchun avval ro'yxatdan o'ting yoki tizimga kiring:

select-language = Tilni tanlang:

language-changed = ✅ Til o'zgartirildi: O'zbekcha

# Buttons
btn-uzbek = 🇺🇿 O'zbekcha
btn-register = 📝 Ro'yxatdan o'tish
btn-login = 🔐 Tizimga kirish
btn-russian = 🇷🇺 Ruscha
btn-profile = 👤 Profil
btn-share = 📤 Botni ulashish
btn-back = ⬅️ Orqaga
btn-admin-panel = 👨‍💼 Admin panel
btn-language = 🌐 Til
btn-add-passport = 🪪 Passport qo'shish
btn-my-passports = 📋 Mening passportlarim
btn-check-track-code = 📦 Track kod tekshirish
btn-invite-friends = 👥 Do'stlarni taklif qilish
btn-contact = 📞 Bog'lanish
btn-make-payment = 💳 To'lov qilish
btn-china-address = 🇨🇳 Xitoy Manzili

btn-save = ✅ Saqlash
btn-cancel = ❌ Bekor qilish
btn-services = 🚚 Xizmatlar
btn-view-info = 📊 Ma'lumotlarni ko'rish
btn-edit-profile = ✏️ Tahrirlash    
btn-logout = 🚪 Tizimdan chiqish
btn-back-to-menu = 🏠 Asosiy menyu
btn-payment-reminder = ⏰ To'lov eslatmasi
btn-devices = 📱 Qurilmalar

# Devices (Session History)
devices-title = 📱 Qurilmalar tarixi
devices-empty = Qurilmalar tarixi topilmadi.
devices-item = 📅 { $date } | 👤 { $client_code } | { $event_type }
event-login = ✅ Kirish
event-relink = 🔄 O'zgartirildi
event-logout = 🚪 Chiqish

# Security Alerts
security-alert-relink = ⚠️ <b>Xavfsizlik ogohlantirishi!</b>

    Sizning Telegram profilingiz orqali yangi tizimga kirish amalga oshirildi va ushbu profil o'chirildi.

    👤 <b>Yangi profil:</b>
    Ism: { $full_name }
    Kod: { $client_code }
    Tel: { $phone }

    Agar bu siz bo'lmasangiz, tizim administratoriga murojaat qiling.




# Validator Errors
passport-series-not-match = Passport seriyasi noto'g'ri formatda. Format: AA1234567
passport-series-incorrect-format = Passport seriyasi '{ $series }' noto'g'ri. Faqat O'zbekiston mahalliy passport seriyalari qabul qilinadi.
pinfl-must-be-14-digits = PINFL 14 raqamdan iborat bo'lishi kerak.
pinfl-incorrect-format = PINFL raqami noto'g'ri.
date-of-birth-incorrect-format = Sana formati noto'g'ri. Format: DD.MM.YYYY (masalan: 15.03.2000)
date-of-birth-not-in-future = Tug'ilgan sana kelajakda bo'lishi mumkin emas.
date-of-birth-too-young = Yoshingiz kamida 16 bo'lishi kerak.
date-of-bith-incorrect = Sana noto'g'ri kiritilgan.
api-error-failed-upload-passport-images = Rasmlarni yuklashda xatolik yuz berdi

api-error-cannot-refer-self = O'zini o'zi taklif qilib bo'lmaydi
api-error-refferer-code-not-found = Client kod topilmadi: { $referrer_client_code }

# Conflict Errors
conflict-pinfl = PINFL allaqachon ro'yxatdan o'tkazilgan
conflict-phone = Telefon raqami allaqachon ro'yxatdan o'tkazilgan
conflict-passport-series = Passport seriyasi allaqachon ro'yxatdan o'tkazilgan
conflict-telegram-id = Siz allaqachon ro'yhatdan o'tgansiz
api-error-client-already-logged-in = Sizning hisobingiz allaqachon boshqa Telegram profilga ulangan.
api-error-telegram-id-already-exists = Ushbu Telegram profil allaqachon boshqa foydalanuvchiga biriktirilgan.

# E-tijorat verification
btn-etijorat-confirmed = ✅ Men ro'yxatdan o'tdim

etijorat-caption = 📱 E-tijorat dasturi bu davlat bojxona xizmatida limitingizni kuzatib borish uchun yaratilgan qulaylik hisoblanadi. Bizning botda ro'yhatdan o'tish uchun avval ushbu dasturdan ro'yhatdan o'tgan bo'lishingiz kerak.

    ⬇️ Quyidagi videoda qanday ro'yhatdan o'tish ko'rsatilgan. Ko'rib chiqqaningizdan so'ng, pastdagi tugmani bosing.

etijorat-send-screenshot = 📸 E-tijorat dasturidan ro'yhatdan o'tganingizni tasdiqlovchi screenshot yuboring.

etijorat-send-screenshot-only-photo = ⚠️ Iltimos, faqat rasm (screenshot) yuboring.

etijorat-screenshot-under-review = ⏳ Screenshotingiz adminlar tomonidan ko'rib chiqilmoqda. Iltimos, kuting.

etijorat-approved = ✅ E-tijorat screenshotingiz tasdiqlandi! Endi ro'yxatdan o'tishingiz mumkin.

etijorat-rejected = ❌ Screenshotingiz rad etildi. Iltimos, avval E-tijorat dasturidan ro'yhatdan o'ting va qaytadan urinib ko'ring (/start).

# Menu
main-menu = 🏠 Asosiy menyu
choose-action = Amalni tanlang:

# Profile
profile-info = 👤 Sizning profilingiz:

    👤 Ism: { $full_name }
    📱 Telefon: { $phone }
    🆔 Client Code: { $client_code }
    📇 Passport: { $passport_series }
    🆔 PINFL: { $pinfl }
    📅 Tug'ilgan sana: { $dob }
    🌍 Viloyat: { $region }
    📍 Manzil: { $address }
    🕒 Ro'yxatdan o'tgan: { $created_at }

profile-select-action = Amalni tanlang:
profile-select-region = Viloyatingizni tanlang:
profile-select-district = Tumaningizni tanlang:
profile-enter-address = 🌍 { $region }, 📍 { $district }
    To'liq manzilingizni kiriting (ko'cha, uy, xonadon):
profile-address-too-short = ❌ Manzil juda qisqa! Kamida 5 ta belgi kiriting.
profile-address-updated = ✅ Manzil muvaffaqiyatli yangilandi!
profile-edit-name = Yangi ismingizni kiriting:
profile-edit-phone = Yangi telefon raqamingizni kiriting (misol: +998901234567):
profile-edit-phone_btn = Yangi telefon raqam
profile-updated = ✅ Profil muvaffaqiyatli yangilandi!
profile-logout-confirm = ⚠️ Rostdan ham tizimdan chiqmoqchimisiz?
profile-logged-out = 👋 Tizimdan muvaffaqiyatli chiqdingiz!

# Admin
admin-panel = 👨‍💼 Admin paneli

    Foydalanuvchilar statistikasi:

user-statistics = 📊 Foydalanuvchilar statistikasi:

    👥 Jami: { $total }
    🆕 Bugun: { $today }
    📅 Bu hafta: { $week }
    📆 Bu oy: { $month }

access-denied = ❌ Kirish rad etildi!
    Sizda bu amalni bajarish uchun ruxsat yo'q.

# Errors
error-occurred = ❌ Xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring.
error-user-not-found = ⚠️ Foydalanuvchi topilmadi!

# Internal Error (for reply_with_internal_error)
error-internal-title = Texnik xatolik yuz berdi
error-internal-description = Iltimos, birozdan so'ng qayta urinib ko'ring.

# Messages
banned-message = 🚫 Siz bloklangansiz va botdan foydalana olmaysiz.

not-provided = Kiritilmagan

# Add Passport Flow
add-passport-start = 🪪 Passport qo'shish

    Iltimos, passport seriyasini kiriting.
    Format: AA1234567 (2 harf + 7 raqam)

    Misol: AC1234567

add-passport-pinfl = PINFL raqamingizni kiriting (14 raqam)

add-passport-dob = Tug'ilgan sanangizni kiriting:

    Format: DD.MM.YYYY
    Misol: 15.03.2000

    Eslatma: Yoshingiz kamida 16 bo'lishi kerak.

add-passport-doc-type = Qanday hujjat rasmini tashlaysiz?

add-passport-id-card = ID Card (ikki tomonlama)
add-passport-passport = Passport (bir tomonlama)

add-passport-id-front = ID Card old tomonini tashlang:

    ✅ Bitta rasm yoki album shaklida 2 ta rasm yuboring (old va orqa)

add-passport-id-back = ID Card orqa tomonini tashlang:

add-passport-id-saved = ✅ Old tomon rasmi saqlandi!

add-passport-passport-photo = Passport rasmini tashlang:

    ✅ Bitta rasm yuboring

add-passport-confirm = Ma'lumotlarni tekshiring:

    📇 Passport: { $passport_series }
    🆔 PINFL: { $pinfl }
    📅 Tug'ilgan sana: { $dob }
    📷 Rasmlar: { $image_count } ta

    Ma'lumotlar to'g'rimi?

add-passport-success = ✅ Passport muvaffaqiyatli qo'shildi!

add-passport-cancelled = ❌ Passport qo'shish bekor qilindi.

add-passport-error = ❌ Xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.

add-passport-max-2-photo = ❌ Maksimal 2 ta rasm!
add-passport-please-select-kyb = Iltimos, tugmalardan birini tanlang:

# My Passports
my-passports-title = 📋 Mening passportlarim

    Jami: { $total } ta

my-passports-empty = Hozircha passportlar qo'shilmagan.

    🪪 Passport qo'shish tugmasini bosing.

my-passports-item = 📇 Passport: { $passport_series }
    🆔 PINFL: { $pinfl }
    📅 Sana: { $dob }
    🕒 Qo'shilgan: { $created_at }

my-passports-page = Sahifa { $current } / { $total }

# Passport View and Delete
passport-not-found = ❌ Passport topilmadi.
passport-deleted-success = ✅ Passport muvaffaqiyatli o'chirildi!
passport-delete-confirm = ⚠️ Rostdan ham bu passportni o'chirmoqchimisiz?
btn-yes-delete = ✅ Ha, o'chirish
btn-no-cancel = ❌ Yo'q, bekor qilish
btn-delete-passport = 🗑 Passportni o'chirish
passport-delete-prompt = Passportni o'chirish uchun quyidagi tugmani bosing:
passport-detail-caption = 📇 Passport: { $passport_series }
    🆔 PINFL: { $pinfl }
    📅 Tug'ilgan sana: { $dob }
    🕒 Qo'shilgan: { $created_at }

# Passport Duplicate Errors
passport-duplicate-error = ❌ Bu passport ma'lumotlari allaqachon mavjud:
passport-duplicate-series = Passport seriyasi allaqachon ro'yxatdan o'tgan
passport-duplicate-pinfl = PINFL allaqachon ro'yxatdan o'tgan

# API Error Messages (for frontend)
api-error-client-not-found = Berilgan ma'lumotlar bilan foydalanuvchi topilmadi
api-error-registration-pending = Sizning so'rovingiz ko'rib chiqilmoqda, admin tasdiqini kuting
api-error-duplicate-data = Takroriy ma'lumotlar topildi: { $fields }
api-error-duplicate-extra-passport = Qo'shimcha passportlarda takroriy ma'lumotlar topildi: { $fields }
api-error-invalid-data = Noto'g'ri ma'lumotlar: { $error }
api-error-registration-failed = Ro'yxatdan o'tish amalga oshmadi: { $error }
api-error-invalid-init-data = Noto'g'ri yoki muddati o'tgan initData
api-success-registration = ⏳ So'rovingiz yuborildi! Admin tomonidan tasdiqlanishini kuting.
api-success-init-data = InitData to'g'ri tasdiqlandi

# Contact Information
contact-info = 📞 Biz bilan bog'lanish:
    ☎️ Telefon: +998908261560
    🏢 Manzil: Toshkent shahar, Chilonzor tumani, Arnasoy ko'chasi
    📩 Admin: @AKB_CARGO

# China Address
china-address-warning = ⚠️ <b>Diqqat!</b>
    Kiritgan manzilingizni @AKB_CARGO ga yuborib tasdiqlashni unutmang!

    Adminlar tomonidan Tasdiqlanmagan manzilga yuborilgan buyurtmalar uchun javobgarlik olinmaydi!

# Info / Flights
info-no-flights = ❌ Hozircha reyslar ma'lumoti topilmadi.
info-flights-list = ✈️ Oxirgi reyslar:

    Reysni tanlang yoki ma'lumotlarni yangilang:
info-flight-selected = ✅ Reys tanlandi
info-flights-refreshed = ✅ Ma'lumotlar yangilandi

# Invite Friends
invite-friends-title = 👥 Do'stlaringizni taklif qiling!

    Botimizni do'stlaringizga ulashing va bonuslar qo'lga kiriting!

    👥 Taklif qilganlar: <code>{ $referral_count }</code> ta

    Sizning havola linkingiz:
invite-url-copied = ✅ Havola nusxalandi!
btn-share-bot = 📤 Botni ulashish
btn-copy-url = 📋 Havolani nusxalash

# Common buttons
btn-refresh = 🔄 Yangilash

# Info - Flights
info-no-orders = ❌ Sizda hali buyurtmalar topilmadi.
info-flights-list = 📋 Reyslaringiz ro'yxati:
info-flights-refreshed = ✅ Ma'lumotlar yangilandi
info-status-paid = ✅ To'langan
info-status-unpaid = ❌ To'lanmagan
info-status-partial = 🧩 Bo'lib to'langan
info-flight-details-with-status = 📋 Reys ma'lumotlari:
    🆔 Mijoz kodi: { $client_code }
    ✈️ Reys: { $worksheet }
    💰 Jami summa: { $summa } so'm
    ⚖️ Vazn: { $vazn } kg
    📦 Track kodlar: <code>{ $trek_kodlari }</code>
    💡 Yuk holati: { $payment_status }
    
info-flight-details-partial = 📋 Reys ma'lumotlari (🧩 Bo'lib to'lov):
    🆔 Mijoz kodi: { $client_code }
    ✈️ Reys: { $worksheet }
    💰 Jami summa: { $total } so'm
    ✅ To'langan: { $paid } so'm
    ⏳ Qolgan: { $remaining } so'm
    🗓️ To'lov muddati: { $deadline }
    ⚖️ Vazn: { $vazn } kg
    📦 Track kodlar: { $trek_kodlari }
    
    ⚠️ Diqqat! Siz to'lovni bo'lib amalga oshiryapsiz. 15 kun ichida to'liq to'lov qilinmasa:
    - yuk berilmaydi
    - omborda saqlash muddati o'tib ketsa, yuk musodara qilinishi mumkin.
    - yukni olib ketish uchun to'liq to'lov qilingan bo'lishi shart!
    
btn-make-payment-now = 💳 To'lov qilish
btn-back-to-flights = ⬅️ Reyslar ro'yxatiga qaytish
btn-view-cargo-photos = 📸 Rasm ko'rish

# Payment breakdown display
info-payment-breakdown-header = 💳 To'lovlar:
info-payment-breakdown-cash =  • Naqd: { $amount } so'm
info-payment-breakdown-total = 📊 Jami: { $total } so'm

# Payment
payment-no-orders = ❌ Sizda to'lov qilish uchun buyurtmalar topilmadi.
payment-all-paid = ✅ Barcha buyurtmalaringiz uchun to'lov qilingan!
payment-select-flight = 💳 To'lov qilish uchun reysni tanlang:
payment-select-type = 💳 To'lov turini tanlang:
payment-no-cards = ❌ Hozirda to'lov kartalari mavjud emas. Admin bilan bog'laning.
payment-info = 📋 To'lov ma'lumotlari:

    🆔 Mijoz kodi: <code>{ $client_code }</code>
    ✈️ Reys: { $worksheet }
    💰 Summa: <code>{ $summa }</code> so'm
    ⚖️ Vazn: { $vazn } kg
    📦 Trek kodlari: { $trek_kodlari }

    💳 Karta raqam: <code>{ $card_number }</code>
    👤 Ism Familiya: { $card_owner }

    📸 To'lov chekini yuborish uchun tugmani bosing:
payment-cash-confirmation = 💵 <b>Naqd to'lov tasdiqlash</b>

    ✈️ Reys: <b>{ $flight_name }</b>
    💰 Summa: <b>{ $summa } so'm</b>
    ⚖️ Vazn: <b>{ $vazn } kg</b>
    📦 Track kodlar: <b>{ $trek_kodlari }</b>

    Siz yukni olib ketishda naqd pul orqali to'lov qilasiz. Tasdiqlaysizmi?
payment-cash-submitted = ✅ Naqd to'lov so'rovi adminga yuborildi. Yukni olib ketishda to'lov qilishingiz mumkin.
payment-cash-confirmed-user = ✅ To'lov naqd pul orqali qabul qilindi va yuk topshirildi!
payment-cancelled = ❌ To'lov bekor qilindi.

payment-send-proof-single = 📸 To'lov chekini yuboring:

    ⚠️ <b>Muhim:</b> Faqat <b>bitta rasm</b> yoki <b>PDF fayl</b> yuboring.
    Bir nechta rasm yuborilsa, faqat birinchisi qabul qilinadi.
payment-submitted = ✅ To'lov chekingiz adminga yuborildi. Kutib turing, admin tasdiqlaydi!

# Payment - Admin notifications
payment-admin-notification = ⚡ Yangi to'lov:

# Payment Type Labels
payment-label-cash = 💵 Naqd pul
payment-label-online-full = 💳 Onlayn (to'liq)
payment-label-online-partial = 🧩 Bo'lib to'lash (onlayn)

# Admin Payment Notifications (Full Details)
payment-admin-notification-full = ⚡ <b>Yangi to'lov</b> ({ $payment_label })
    🆔 Mijoz kodi: <code>{ $client_code }</code>
    ✈️ Reys: <b>{ $worksheet }</b>
    💰 Summa: <b>{ $summa } so'm</b>
    ⚖️ Vazn: <b>{ $vazn } kg</b>
    📦 Track kodlar: <b>{ $track_codes }</b>
    👤 Foydalanuvchi: <b>{ $full_name }</b>
    📱 Telefon: <code>{ $phone }</code>
    💬 Telegram ID: <code>{ $telegram_id }</code>

payment-admin-notification-partial = ⚡ <b>Yangi to'lov</b> ({ $payment_label })
    🆔 Mijoz kodi: <code>{ $client_code }</code>
    ✈️ Reys: <b>{ $worksheet }</b>
    💰 Jami summa: <b>{ $total } so'm</b>
    ✅ To'langan: <b>{ $paid } so'm</b>
    ⏳ Qolgan: <b>{ $remaining } so'm</b>
    🗓️ Muddati: <b>{ $deadline }</b>
    ⚖️ Vazn: <b>{ $vazn } kg</b>
    📦 Track kodlar: <b>{ $track_codes }</b>
    👤 Foydalanuvchi: <b>{ $full_name }</b>
    📱 Telefon: <code>{ $phone }</code>
    💬 Telegram ID: <code>{ $telegram_id }</code>

payment-admin-actions = ⬆️ Yuqoridagi to'lovni tasdiqlash yoki rad etish:

# Payment - Approval buttons
btn-approve-payment = ✅ Tasdiqlash
btn-reject-payment = ❌ Rad etish
btn-reject-with-comment = 💬 Izoh bilan rad etish
btn-send-payment-proof = 📤 To'lov chekini yuborish
btn-payment-online = 💳 Onlayn to'lov
btn-payment-cash = 💵 Borib to'lash
btn-confirm = ✅ Tasdiqlash
btn-cash-payment-confirmed = 💵 Naqd to'lov qilindi
btn-cash-payment-confirm = 💵 Naqd to'lov qilindi
btn-pay-full = ✅ Butun to'lash
btn-pay-partial = 🧩 Bo'lib to'lash
btn-pay-full-remaining = ✅ Qolgan summani to'liq to'lash
btn-enter-amount = 💳 Summani kiritish
btn-pay-full = ✅ Butun to'lash
btn-pay-partial = 🧩 Bo'lib to'lash
btn-pay-full-remaining = ✅ Qolgan summani to'liq to'lash
btn-enter-amount = 💳 Summani kiritish

# Payment - Approval results
payment-approved-user = ✅ To'lovingiz tasdiqlandi!

    ✈️ Reys: { $worksheet }
    💰 To'lov summasi: { $summa } so'm

payment-approved-user-partial = ✅ To'lov tasdiqlandi (Bo'lib to'lov):

    ✈️ Reys: { $worksheet }
    💰 Jami summa: { $total } so'm
    ✅ To'langan: { $paid } so'm
    ⏳ Qolgan: { $remaining } so'm
    📅 Muddati: { $deadline }
payment-approved-group = ✅ { $client_code } ning { $worksheet } reysdagi { $row_number } qatori tasdiqlandi.
payment-approved-success = ✅ To'lov tasdiqlandi!
payment-rejected-user = ⚠️ To'lovingiz rad etildi. Admin bilan bog'laning.
payment-rejected-with-comment = ⚠️ To'lovingiz rad etildi.

    💬 Admin izohi: { $comment }
payment-rejected-group = ❌ To'lov rad etildi.
payment-rejected-success = ❌ To'lov rad etildi!

# Partial Payment
payment-select-amount-type = 💳 To'lov turini tanlang:

    Jami summa: { $total } so'm

payment-partial-info = ⚠️ <b>Bo'lib to'lash ma'lumotlari</b>

    ✈️ Reys: { $flight }
    🆔 Mijoz kodi: { $client_code }
    💰 Jami summa: { $total } so'm
    ✅ To'langan: { $paid } so'm
    ⏳ Qolgan: { $remaining } so'm
    📅 Muddati: { $deadline }

    ⚠️ <b>Diqqat!</b>
    Siz to'lovni bo'lib amalga oshiryapsiz.
    15 kun ichida to'liq to'lov qilinmasa:
    • yuk berilmaydi
    • omborda saqlash muddati o'tib ketsa, yuk musodara qilinishi mumkin.

payment-partial-existing = 💰 <b>Bo'lib to'lov mavjud</b>

    ✈️ Reys: { $flight }
    💰 Jami summa: { $total } so'm
    ✅ To'langan: { $paid } so'm
    ⏳ Qolgan: { $remaining } so'm
    📅 Muddati: { $deadline }

payment-partial-enter-amount = 💳 To'lamoqchi bo'lgan summani kiriting (so'm):

    ⚠️ Minimal summa: 1 000 so'm
    ⚠️ Maksimal summa: qolgan summa

payment-partial-invalid-amount = ❌ Noto'g'ri summa! Faqat raqam kiriting.
payment-partial-min-amount = ❌ Minimal summa { $min } so'm bo'lishi kerak!
payment-partial-max-amount = ❌ Maksimal summa { $max } so'm bo'lishi mumkin!
payment-partial-exceeds-total = ❌ Summa jami summadan oshib ketdi! Jami: { $total } so'm
payment-partial-remaining = qolgan

payment-info-partial = 📋 To'lov ma'lumotlari (Bo'lib to'lov):

    🆔 Mijoz kodi: { $client_code }
    ✈️ Reys: { $worksheet }
    💰 To'lov summasi: { $summa } so'm
    ⚖️ Vazn: { $vazn } kg
    📦 Trek kodlari: { $trek_kodlari }

    💳 To'lov kartasi:
    { $card_number }
    { $card_owner }

payment-info-remaining = 📋 To'lov ma'lumotlari (Qolgan summa):

    🆔 Mijoz kodi: { $client_code }
    ✈️ Reys: { $worksheet }
    💰 To'lov summasi: { $summa } so'm
    ⚖️ Vazn: { $vazn } kg
    📦 Trek kodlari: { $trek_kodlari }

    💳 To'lov kartasi:
    { $card_number }
    { $card_owner }

admin-verification-partial-payment = ⚠️ <b>Bo'lib to'lov:</b>
    To'langan: { $paid } so'm
    Qolgan: { $remaining } so'm
    Muddati: { $deadline }

not-set = O'rnatilmagan

# Admin client payment filters
admin-client-filter-hint = 💳 Mijozlarni to'lov holati bo'yicha filtrlash:
admin-client-filter-paid-btn = To'liq to'langan
admin-client-filter-partial-btn = Bo'lib to'lagan
admin-client-filter-unpaid-btn = To'lanmagan

admin-client-filter-paid = 🟢 To'liq to'langan mijozlar ({ $count } ta):
admin-client-filter-partial = 🟡 Bo'lib to'lagan mijozlar ({ $count } ta):
admin-client-filter-unpaid = 🔴 To'lanmagan mijozlar ({ $count } ta):
admin-client-filter-empty = Bu toifada mijozlar topilmadi.
admin-client-filter-more = ... va yana { $extra } ta mijoz.
payment-rejection-comment-prompt = 💬 Rad etish uchun izoh yozing yoki /stop buyrug'ini yuboring:

# Payment - Channel notification
payment-confirmed-channel = 📌 To'lov TASDIQLANDI!

    🆔 Mijoz kodi: <code>{ $client_code }</code>
    ✈️ Reys: <b>{ $worksheet }</b>
    💰 Summa: <b>{ $summa }</b>
    ⚖️ Vazn: <b>{ $vazn } kg</b>
    📦 Track kodlar: <b>{ $track_codes }</b>
    👤 Admin: <b>{ $full_name }</b>
    📞 Telefon: <code>{ $phone }</code>
    💬 Telegram ID: <code>{ $telegram_id }</code>

payment-confirmed-channel-partial = 📌 To'lov TASDIQLANDI! (🧩 Bo'lib to'lov)

    🆔 Mijoz kodi: <code>{ $client_code }</code>
    ✈️ Reys: <b>{ $worksheet }</b>
    💰 Jami summa: <b>{ $total }</b>
    ✅ To'langan: <b>{ $paid }</b>
    ⏳ Qolgan: <b>{ $remaining }</b>
    🗓️ Muddati: <b>{ $deadline }</b>
    ⚖️ Vazn: <b>{ $vazn } kg</b>
    📦 Track kodlar: <b>{ $track_codes }</b>
    👤 Admin: <b>{ $full_name }</b>
    📞 Telefon: <code>{ $phone }</code>
    💬 Telegram ID: <code>{ $telegram_id }</code>

payment-confirmed-channel-cash = 📌 To'lov TASDIQLANDI! (💵 Naqd pul)

    🆔 Mijoz kodi: <code>{ $client_code }</code>
    ✈️ Reys: <b>{ $worksheet }</b>
    💰 Summa: <b>{ $summa }</b>
    👤 Admin: <b>{ $full_name }</b>
    📞 Telefon: <code>{ $phone }</code>
    💬 Telegram ID: <code>{ $telegram_id }</code>
payment-cash-confirmed-group = ✅ { $client_code } ning { $worksheet } reysdagi { $row_number } qatori naqd pul orqali to'landi va yuk topshirildi. Admin: { $admin_name }
payment-cash-confirmed-success = ✅ Naqd to'lov tasdiqlandi!
payment-already-exists = ⚠️ Bu to'lov allaqachon mavjud!
payment-already-taken = ⚠️ Bu yuk allaqachon olingan!

    🆔 Mijoz ID: { $client_code }
    ✈️ Reysi: { $worksheet }
    💰 Miqdor: { $summa } so'm
    👤 Foydalanuvchi: { $full_name }
    📱 Telefon raqami: { $phone }
    🆔 Telegram ID: { $telegram_id }

# Admin Panel
admin-welcome = Assalomu alaykum!

    🔐 <b>Admin panelga xush kelibsiz!</b>

    Quyidagi tugmalardan foydalaning:
admin-back-to-menu = 🔙 Asosiy menyuga qaytdingiz

# Admin - Databases Import
admin-databases-title = 📥 <b>Bazalarni Import Qilish</b>

    ⚠️ <b>Muhim:</b>
    1️⃣ Namunalardagi formatda Excel tayyorlang
    2️⃣ Quyidagi tugmani bosib import sahifasiga o'ting
    3️⃣ Kerakli bazani tanlang va Excel yuklang

    📊 <b>Bazalar:</b>
    • <b>XITOY BAZA</b> - Pre-flight (Xitoydan kelgan yuklarlar)
    • <b>UZBEK BAZA</b> - Post-flight (O'zbekistonga yetib kelgan yuklarlar)

    💡 <i>Har bir Excel sheet nomi = Reys nomi</i>

admin-db-clear-all-warning = ⚠️ <b>DIQQAT!</b>

    Agar siz tasdiqlasangiz <b>BUTUN IMPORT BAZASI TOZALANADI</b>!

    Bu amalni qaytarib bo'lmaydi!

    Davom etasizmi?

admin-db-clear-recent-warning = ⚠️ <b>DIQQAT!</b>

    Oxirgi <b>5 daqiqa</b> ichida qo'shilgan barcha yozuvlar <b>O'CHIRILADI</b>!

    Davom etasizmi?

admin-db-cleared-all = ✅ Butun import bazasi tozalandi!

    O'chirilgan yozuvlar: { $count } ta

admin-db-cleared-recent = ✅ Oxirgi 5 daqiqadagi yozuvlar tozalandi!

    O'chirilgan yozuvlar: { $count } ta

admin-db-clear-cancelled = ❌ Tozalash bekor qilindi

# Admin - Database Buttons
btn-open-import-page = 🌐 Import sahifasini ochish
btn-clear-all-database = 🗑 Eski bazani o'chirish
btn-clear-recent-imports = ⏱ Oxirgi 5 daqiqadagilarni tozalash
btn-confirm-action = ✅ Tasdiqlash
btn-cancel-action = ❌ Bekor qilish

# Admin Menu Buttons
btn-admin-databases = 📥 Bazalar
btn-admin-track-check = 📦 Track kod tekshirish
btn-admin-user-search = 👤 Foydalanuvchi qidirish
btn-admin-client-verification = ✅ Foydalanuvchi tekshirish
btn-admin-send-message = 📢 Reklama yuborish
btn-admin-upload-photo = 📸 Foto yuklash
btn-admin-get-data = 📁 Ma'lumot olish
btn-admin-referral-data = 🔗 Referal bazani olish
btn-admin-leftover-cargo = 📦 Qoldiq tovarlarni olish
btn-admin-leftover-notifications = 📢 Bildirishnomalar
btn-admin-settings = ⚙️ Sozlamalar

# Admin - Referral Data
admin-referral-title = 📊 <b>Referal statistika</b>
admin-referral-total-users = 👥 <b>Jami foydalanuvchilar:</b> { $count }
admin-referral-total-referrers = 🔗 <b>Jami referrerlar:</b> { $count }
admin-referral-total-invited = 📥 <b>Jami taklif qilinganlar:</b> { $count }
admin-referral-top-referrers-title = 🏆 <b>Top referrerlar:</b>
admin-referral-top-referrer-item = { $index }. { $code } - { $name } ({ $count } ta)
admin-referral-no-top-referrers = ⚠️ Top referrerlar topilmadi.
admin-referral-excel-preparing = ⏳ Excel fayl tayyorlanmoqda...
admin-referral-excel-ready = 📊 Referal bazasi tayyor!
admin-referral-error = ❌ Xatolik yuz berdi: { $error }
admin-referral-error-retry = Iltimos, qayta urinib ko'ring.

# Admin - Get Data
admin-data-title = 📊 <b>Foydalanuvchilar statistika</b>
admin-data-total-clients = 👥 <b>Jami foydalanuvchilar:</b> { $count }
admin-data-active-clients = ✅ <b>Faol foydalanuvchilar:</b> { $count }
admin-data-inactive-clients = ⚪ <b>Nofaol foydalanuvchilar:</b> { $count }
admin-data-first-registration = 📅 <b>Birinchi ro'yxatdan o'tish:</b> { $date }
admin-data-last-registration = 📅 <b>Oxirgi ro'yxatdan o'tish:</b> { $date }
admin-data-not-available = Mavjud emas
admin-data-excel-preparing = ⏳ Excel fayl tayyorlanmoqda...
admin-data-excel-ready = 📊 Foydalanuvchilar bazasi tayyor!
admin-data-error = ❌ Xatolik yuz berdi: { $error }
admin-data-error-retry = Iltimos, qayta urinib ko'ring.

# Admin - Get Data Excel Columns
admin-data-column-id = ID
admin-data-column-telegram-id = Telegram ID
admin-data-column-full-name = F.I.Sh
admin-data-column-phone = Telefon raqam
admin-data-column-language = Til
admin-data-column-is-admin = Admin
admin-data-column-passport-series = Passport seriyasi
admin-data-column-pinfl = PINFL
admin-data-column-date-of-birth = Tug'ilgan sana
admin-data-column-region = Viloyat
admin-data-column-address = Manzil
admin-data-column-client-code = Client ID
admin-data-column-referrer-telegram-id = Referrer Telegram ID
admin-data-column-referrer-client-code = Referrer Client ID
admin-data-column-is-logged-in = Kirgan
admin-data-column-created-at = Ro'yxatdan o'tgan sana

# Admin - Leftover Cargo
admin-leftover-title = 📦 <b>Qoldiq tovarlar statistika</b>
admin-leftover-paid-not-taken = ✅ <b>To'langan lekin olinmagan:</b> { $count } ta
admin-leftover-unpaid-not-taken = ⚠️ <b>To'lanmagan va olinmagan:</b> { $count } ta
admin-leftover-total = 📊 <b>Jami qoldiq:</b> { $count } ta
admin-leftover-estimated-profit = 💰 <b>Taxminiy foyda (to'langan lekin olinmagan):</b> { $amount } so'm
admin-leftover-by-flight-title = ✈️ <b>Reys bo'yicha:</b>
admin-leftover-by-flight-item = • { $flight }: To'langan { $paid }, To'lanmagan { $unpaid }, Jami { $total }
admin-leftover-more-flights = ... va yana { $count } ta reys
admin-leftover-by-region-title = 📍 <b>Viloyat bo'yicha:</b>
admin-leftover-by-region-item = • { $region }: To'langan { $paid }, To'lanmagan { $unpaid }, Jami { $total }
admin-leftover-more-regions = ... va yana { $count } ta viloyat
admin-leftover-excel-preparing = ⏳ Excel fayl tayyorlanmoqda...
admin-leftover-progress-track-codes = 🔍 Track kodlar topilmoqda (DB + Google Sheets)...
admin-leftover-progress-excel = 📄 Excel fayl yig'ilmoqda...
admin-leftover-excel-ready = 📊 Qoldiq tovarlar bazasi tayyor!
admin-leftover-error = ❌ Xatolik yuz berdi: { $error }
admin-leftover-error-retry = Iltimos, qayta urinib ko'ring.

# Admin - Leftover Cargo Excel Columns
admin-leftover-column-client-code = Client ID
admin-leftover-column-full-name = F.I.Sh
admin-leftover-column-region = Viloyat
admin-leftover-column-address = Manzil
admin-leftover-column-phone = Telefon raqam
admin-leftover-column-passport-series = Passport seriyasi
admin-leftover-column-pinfl = PINFL
admin-leftover-column-flight-name = Reys nomi
admin-leftover-column-row-number = Qator raqami
admin-leftover-column-track-code = Track kod
admin-leftover-column-cargo-source = Yuk manbasi
admin-leftover-column-is-paid = To'langan
admin-leftover-column-is-taken-away = Olingan
admin-leftover-column-taken-away-date = Olingan sana
admin-leftover-column-payment-amount = To'lov summasi
admin-leftover-column-payment-date = To'lov sanasi

# Admin - Client Search
admin-search-title = 🔍 <b>Foydalanuvchi qidirish</b>

    Mijoz kodini kiriting (masalan: SS500):

admin-search-invalid-prefix = ❌ <b>Noto'g'ri format!</b>

    Mijoz kodi <code>{ $prefix }</code> bilan boshlanishi kerak.
    Misol: <code>{ $example }</code>

admin-search-invalid-format = ❌ <b>Noto'g'ri format!</b>

    Mijoz kodi raqam bilan tugashi kerak.
    Misol: <code>{ $example }</code>

admin-search-not-found = ❌ <b>Mijoz topilmadi!</b>

    Mijoz kodi: <code>{ $code }</code>

    Ushbu kod bilan mijoz bazada mavjud emas.

admin-search-found = ✅ <b>Mijoz topildi!</b>

admin-search-basic-info = 👤 <b>Asosiy ma'lumotlar:</b>
    ━━━━━━━━━━━━━━━━━━
    🆔 Mijoz kodi: <code>{ $code }</code>
    🆔 Yangi mijoz kodi: <code>{ $new_code }</code>
    ID Legacy code: <code>{ $legacy_code }</code>
    💡 Telegram ID: <code>{ $telegram_id }</code>
    👤 F.I.O: <b>{ $name }</b>
    📞 Telefon: <code>{ $phone }</code>
    🎂 Tug'ilgan sana: <code>{ $birthday }</code>
    📄 Pasport seriyasi: <code>{ $passport }</code>
    🔢 PINFL: <code>{ $pinfl }</code>
    🌍 Viloyat: <code>{ $region }</code>
    📍 Manzil: <code>{ $address }</code>
    👥 Taklif qilganlar: <b>{$referral_count} ta</b>
    📅 Ro'yxatdan o'tgan: <code>{ $created }</code>

admin-search-payments-info = 💳 <b>To'lovlar haqida:</b>
    ━━━━━━━━━━━━━━━━━━
    📊 Jami to'lovlar: <b>{ $count } marta</b>

admin-search-last-payment = 💰 <b>Oxirgi to'lov:</b>
    ✈️ Reys: <code>{ $flight }</code>
    📦 Qator raqami: <code>{ $row }</code>
    💵 Summa: <code>{ $amount } so'm</code>
    📅 Sana: <code>{ $date }</code>

admin-search-has-payment-receipt = 🧾 To'lov cheki mavjud
admin-search-cargo-taken = ✅ Yuk olib ketilgan: <code>{ $date }</code>
admin-search-cargo-not-taken = ⏳ Yuk olib ketilmagan

admin-search-extra-passports = 📋 <b>Qo'shimcha pasportlar:</b>
    ━━━━━━━━━━━━━━━━━━
    📄 Qo'shilgan pasportlar: <b>{ $count } ta</b>

admin-search-passport-images = ⬆️ Pasport rasmlari

btn-add-client = ➕ Mijoz qo'shish
btn-edit-client = ✏️ Tahrirlash
btn-delete-client = 🗑 O'chirish

not-provided = Kiritilmagan
unknown = Noma'lum

admin-delete-confirm = ⚠️ <b>Ogohlantirish!</b>

    Rostdan ham ushbu mijozni o'chirmoqchimisiz?

    👤 F.I.O: <b>{ $name }</b>
    🆔 Kod: <code>{ $code }</code>

    ❗️ Bu amalni bekor qilib bo'lmaydi!

btn-confirm-delete = ✅ Ha, o'chirish
btn-cancel-delete = ❌ Yo'q, bekor qilish

admin-delete-success = ✅ <b>Mijoz o'chirildi!</b>

# Admin - Settings
admin-settings-title = ⚙️ <b>Sozlamalar</b>ㅤㅤㅤㅤㅤ

# Admin - Settings Buttons
admin-settings-btn-foto-hisobot = 📝 Foto hisobot
admin-settings-btn-extra-charge = 💰 Qo'shimcha to'lov
admin-settings-btn-price-per-kg = 📦 1 kg narxi
admin-settings-btn-cards = 💳 Kartalarni tahrirlash
admin-settings-btn-add-admin = ➕ Admin qo'shish
admin-settings-btn-backup = 💾 Backup
admin-settings-btn-ostatka-daily = ♻️ Kunlik yuborish: { $status }
admin-settings-btn-ostatka-flights = ✈️ Reys tanlash
admin-settings-btn-back = ⬅️ Orqaga
admin-settings-btn-back-to-settings = ⬅️ Sozlamalarga qaytish

# Admin - Settings: Ostatka daily digest
admin-settings-ostatka-enabled = ✅ Yoqildi
admin-settings-ostatka-disabled = ⛔️ O'chirildi
admin-settings-ostatka-toggle-success = ♻️ Ostatka kunlik holati yangilandi: { $status }

# Admin - Settings: Ostatka flight selection
admin-settings-ostatka-flights-title = ✈️ <b>Kunlik yuborish uchun reyslarni tanlang</b>

Har kun avtomatik yuboriladigan A- reyslarni belgilang. Belgilangan reyslar ✅, belgilanmaganlar ⬜ ko'rinadi.
admin-settings-ostatka-flights-empty = ⚠️ Hozircha A- reyslar mavjud emas

admin-settings-current-value = Joriy qiymat
admin-settings-no-value = Qiymat o'rnatilmagan

# Admin - Settings: Foto Hisobot
admin-settings-foto-hisobot-title = 📝 <b>Foto hisobotni tahrirlash</b>
admin-settings-foto-hisobot-prompt = Yangi matnni kiriting:
admin-settings-foto-hisobot-success = ✅ Foto hisobot muvaffaqiyatli yangilandi!

# Admin - Settings: Extra Charge
admin-settings-extra-charge-title = 💰 <b>Qo'shimcha to'lovni tahrirlash</b>
admin-settings-extra-charge-current = Joriy qo'shimcha to'lov: <b>{ $amount } so'm</b>
admin-settings-extra-charge-rate = 1$ = <b>{ $rate } so'm</b>
admin-settings-extra-charge-prompt = Yangi qo'shimcha to'lovni kiriting (so'm):
admin-settings-extra-charge-success = ✅ Qo'shimcha to'lov muvaffaqiyatli yangilandi!
admin-settings-extra-charge-invalid-format = ❌ Noto'g'ri format! Faqat raqam kiriting.
admin-settings-extra-charge-invalid-negative = ❌ Manfiy qiymat kiritish mumkin emas!

# Admin - Settings: Price Per Kg
admin-settings-price-per-kg-title = 📦 <b>1 kg narxini tahrirlash</b>
admin-settings-price-per-kg-current = Joriy narx: <code>{ $amount }$</code>
admin-settings-price-per-kg-converted = UZS: <b>{ $amount } so'm</b>
admin-settings-price-per-kg-final = Jami (narx + qo'shimcha to'lov): <b>{ $amount } so'm</b>
admin-settings-price-per-kg-rate = 1$ = <b>{ $rate } so'm</b>
admin-settings-price-per-kg-prompt = Yangi narxni kiriting (USD):
admin-settings-price-per-kg-success = ✅ 1 kg narxi muvaffaqiyatli yangilandi!
admin-settings-price-per-kg-invalid = ❌ Narx 0 dan katta bo'lishi kerak!
admin-settings-price-per-kg-invalid-format = ❌ Noto'g'ri format! Faqat raqam kiriting (masalan: 9.5).

# Admin - Settings: Payment Cards
admin-settings-cards-title = 💳 <b>To'lov kartalari</b>
admin-settings-cards-empty = 💳 To'lov kartalari yo'q.

admin-settings-cards-active = Faol
admin-settings-cards-inactive = Faol emas
admin-settings-cards-activate = ✅ Faollashtirish
admin-settings-cards-deactivate = ❌ O'chirish
admin-settings-cards-add = ➕ Karta qo'shish
admin-settings-cards-page = 📄 Sahifa: { $page }/{ $total }
admin-settings-cards-not-found = ❌ Karta topilmadi!
admin-settings-cards-last-active-warning = ⚠️ Kamida bitta faol karta bo'lishi kerak!
admin-settings-cards-toggle-success = ✅ Karta holati o'zgartirildi!
admin-settings-cards-add-prompt-name = Karta egasining ismini kiriting:
admin-settings-cards-add-prompt-number = Karta raqamini kiriting:
admin-settings-cards-add-invalid-name = ❌ Ism bo'sh bo'lishi mumkin emas!
admin-settings-cards-add-invalid-number-format = ❌ Noto'g'ri format! Faqat raqamlarni kiriting.
admin-settings-cards-add-invalid-number-length = ❌ Karta raqami 16-19 ta raqamdan iborat bo'lishi kerak!
admin-settings-cards-add-duplicate = ❌ Bu karta raqami allaqachon mavjud!
admin-settings-cards-add-success = ✅ Karta muvaffaqiyatli qo'shildi!

admin-settings-error = ❌ Xatolik yuz berdi!

# Admin - Settings: Add Admin
admin-settings-add-admin-prompt = Kirish uchun quyidagilardan birini yuboring:
    - Telegram ID
    - Client code
    - Username (@sizsiz)
admin-settings-add-admin-not-found = ❌ Foydalanuvchi topilmadi!
admin-settings-add-admin-not-found-withid = ❌ Foydalanuvchi topilmadi: { $client_id }
admin-settings-add-admin-multiple-found = ❌ Bir nechta foydalanuvchi topildi! Iltimos, aniqroq identifikator kiriting.
admin-settings-add-admin-already-admin = ⚠️ Bu foydalanuvchi allaqachon admin!
admin-settings-add-admin-success = ✅ Siz { $method } orqali { $identifier } foydalanuvchini admin qildingiz
admin-settings-add-admin-welcome = 🎉 Tabriklaymiz! Siz admin huquqiga ega bo'ldingiz.

# Admin - Settings: Database Backup
admin-settings-backup-creating = 💾 Backup yaratilmoqda...
admin-settings-backup-in-progress = ⏳ Database backup yaratilmoqda, iltimos kuting...
admin-settings-backup-success = ✅ Backup muvaffaqiyatli yaratildi va yuborildi!
admin-settings-backup-error = ❌ Backup yaratishda xatolik yuz berdi. Server loglarini tekshiring.
admin-settings-backup-pgdump-not-found = ❌ pg_dump topilmadi. PostgreSQL client tools o'rnatilganligini tekshiring.
admin-settings-backup-caption = 📦 Database backup

# Admin - Leftover Cargo: Notifications
admin-leftover-notifications-btn = 🔔 Bildirishnomalar
admin-leftover-notifications-title = 🔔 <b>Bildirishnomalar sozlamalari</b>
admin-leftover-notifications-status = Holati
admin-leftover-notifications-on = ✅ Yoqilgan
admin-leftover-notifications-off = ❌ O'chirilgan
admin-leftover-notifications-period = Davriylik
admin-leftover-notifications-days = kun
admin-leftover-notifications-not-set = O'rnatilmagan
admin-leftover-notifications-turn-on = ✅ Yoqish
admin-leftover-notifications-turn-off = ❌ O'chirish
admin-leftover-notifications-updated = ✅ Sozlamalar yangilandi
admin-leftover-notifications-period-set = ✅ Davriylik { $period } kunga o'rnatildi
admin-leftover-notifications-back = ⬅️ Orqaga

# Notification Messages (Leftover Cargo)
notification-leftover-greeting = 👋 Assalomu alaykum!
notification-leftover-explanation = Sizda olib ketilmagan yuklar mavjud.
notification-leftover-paid-count = ✅ To'langan lekin olinmagan: <b>{ $count } ta</b>
notification-leftover-unpaid-count = ⚠️ To'lanmagan va olinmagan: <b>{ $count } ta</b>
notification-leftover-call-to-action = Iltimos, yuklaringizni olib keting yoki to'lovni amalga oshiring.

# Partial Payment Reminders
reminder-partial-deadline-5days = ⏰ <b>Eslatma: Bo'lib to'lov</b>
    ✈️ Reys: { $flight }
    💰 Jami: { $total } so'm
    ✅ To'langan: { $paid } so'm
    ⏳ Qolgan: { $remaining } so'm
    🗓️ Muddati: { $deadline }
    ⚠️ To'lov muddatiga { $days } kun qoldi!

reminder-partial-deadline-2days = ⚠️ <b>Jiddiy eslatma: Bo'lib to'lov</b>
    ✈️ Reys: { $flight }
    💰 Jami: { $total } so'm
    ✅ To'langan: { $paid } so'm
    ⏳ Qolgan: { $remaining } so'm
    🗓️ Muddati: { $deadline }
    ⚠️ To'lov muddatiga faqat { $days } kun qoldi! Iltimos, qolgan summani to'lang.

reminder-partial-deadline-today = 🚨 <b>Oxirgi kun: Bo'lib to'lov</b>
    ✈️ Reys: { $flight }
    💰 Jami: { $total } so'm
    ✅ To'langan: { $paid } so'm
    ⏳ Qolgan: { $remaining } so'm
    🗓️ Muddati: { $deadline }
    🚨 Bugun to'lov muddati! Iltimos, qolgan summani bugun to'lang, aks holda yuk berilmaydi!

# Admin - Client Verification
admin-verification-choose-search-type = 🔍 <b>Foydalanuvchi tekshirish</b>

    Qidirish turini tanlang:

btn-search-by-code = 📋 Mijoz kodi bo'yicha
btn-search-by-flight = ✈️ Reys bo'yicha

admin-verification-ask-client-code = 🔍 <b>Mijoz kodi bo'yicha qidirish</b>

    Mijoz kodini kiriting:

admin-verification-ask-flight-code = ✈️ <b>Reys bo'yicha qidirish</b>

    Reys kodini kiriting (masalan: R123):

admin-verification-client-not-found = ❌ <b>Mijoz topilmadi!</b>

    Iltimos, to'g'ri mijoz kodini kiriting.

admin-verification-cancelled = ❌ Tekshirish bekor qilindi.

admin-verification-client-found = ✅ <b>Mijoz topildi</b>

    🆔 <b>Mijoz kodi:</b> <code>{ $client_code }</code>
    👤 <b>F.I.SH:</b> <b>{ $full_name }</b>
    📱 <b>Telegram ID:</b> <code>{ $telegram_id }</code>

    📊 <b>To'lovlar:</b> <b>{ $total_payments } ta</b>
    ✅ <b>Olib ketilgan:</b> <b>{ $taken_away } ta</b>

btn-verification-full-info = 📋 To'liq ma'lumot
btn-verification-payments-list = 💳 To'lovlar ro'yxati
btn-verification-select-flight = 🛫 Reys tanlash
btn-verification-all-payments = 📋 Barcha to'lovlar
btn-verification-show-cargos = 📦 Yuklarni ko'rish
btn-verification-unpaid-payments = 💰 To'lanmagan to'lovlar

# Unpaid payments section
admin-verification-no-unpaid = ✅ Barcha to'lovlar to'langan.
admin-verification-unpaid-item = 💰 <b>To'lanmagan to'lov</b>
    ✈️ Reys: <code>{ $flight }</code>
    📦 Qator: <code>{ $row }</code>
    💵 Jami: <code>{ $total } so'm</code>
    ⏳ Qoldiq: <code>{ $remaining } so'm</code>
    📅 Sana: <code>{ $date }</code>
admin-verification-unpaid-item-partial = 💰 <b>Bo'lib to'langan</b>
    ✈️ Reys: <code>{ $flight }</code>
    📦 Qator: <code>{ $row }</code>
    💵 Jami: <code>{ $total } so'm</code>
    ✅ To'langan: <code>{ $paid } so'm</code>
    ⏳ Qoldiq: <code>{ $remaining } so'm</code>
    📅 Sana: <code>{ $date }</code>
admin-verification-unpaid-item-no-cargo = 💰 <b>To'lanmagan to'lov</b>
    ✈️ Reys: <code>{ $flight }</code>
    💵 Jami: <code>{ $total } so'm</code>
    ⏳ Qoldiq: <code>{ $remaining } so'm</code>
    📅 Sana: <code>{ $date }</code>
    ⚠️ Yuk ma'lumotlari topilmadi, foto hisobot yuborilmagan.
admin-verification-unpaid-nav = 📄 To'lov { $current }/{ $total }
admin-verification-no-cargo-data = ⚠️ Yuk ma'lumotlari topilmadi

# Common terms
amount = Summa

admin-verification-flights = Reyslar
admin-verification-select-flight-prompt = Qaysi reys to'lovlarini ko'rmoqchisiz?
admin-verification-no-flights = Bu foydalanuvchi uchun reyslar topilmadi
btn-filter-by-flight = ✈️ Reys bo'yicha filter
btn-clear-flight-filter = ❌ Reys filtrini tozalash

admin-verification-no-payments = ℹ️ Hech qanday to'lov topilmadi.
admin-verification-no-cargos = ❌ Bu reys uchun yuklaringiz topilmadi
admin-verification-cargos-shown = ✅ Jami { $count } ta yuk ko'rsatildi
admin-verification-cargo-info = 📦 <b>Yuk ma'lumotlari</b>

    ✈️ Reys: <b>{ $flight }</b>
    👤 Mijoz: <b>{ $client }</b>
    { $weight_info }{ $comment_info }
    📅 Yuklangan: { $date }

    { $status }
admin-verification-cargo-weight = ⚖️ Og'irligi: <b>{ $weight } kg</b>
admin-verification-cargo-comment = 💬 Izoh: <i>{ $comment }</i>
admin-verification-cargo-sent = ✅ <b>Mijozga yuborilgan</b>
admin-verification-cargo-not-sent = ⏳ <b>Mijozga yuborilmagan</b>
admin-verification-cargo-photo-error = ❌ Rasmni yuklashda xatolik: { $error }

admin-verification-payment-info = 💰 <b>To'lov ma'lumoti:</b>
    ✈️ Reys: <code>{ $flight }</code>
    📦 Qator: <code>{ $row }</code>
    💵 Summa: <code>{ $amount } so'm</code>
    ⚖️ Vazn: <code>{ $weight }</code>
    📅 Sana: <code>{ $date }</code>

admin-verification-no-receipt = ℹ️ To'lov cheki mavjud emas

admin-verification-receipt-unavailable = ⚠️ To'lov cheki yuklab olinmadi

admin-verification-page-nav = 📄 Sahifa { $current }/{ $total }

btn-previous = ⬅️ Oldingi
btn-next = Keyingi ➡️

# Filter buttons
btn-filter-all = 🔄 Barchasi
btn-filter-partial = 🧩 Bo'lib to'langan
btn-filter-paid = ✅ To'langan
btn-filter-unpaid = ⏳ To'lanmagan
btn-filter-pending = ⏳ Kutilmoqda
btn-filter-taken = 📦 Olib ketilgan
btn-filter-not-taken = 🔴 Olib ketilmagan

# Sort buttons
btn-sort-newest = 🔽 Yangidan eskiga
btn-sort-oldest = 🔼 Eskidan yangiga

# Mark as taken
btn-mark-as-taken = ✅ Olib ketildi deb belgilash
btn-cash-remainder = 💵 Qoldiq summa naqt to'landi
btn-account-payment = 🧾 Hisobga to'lov
btn-account-payment-click = 💳 Click
btn-account-payment-payme = 💳 Payme
btn-account-payment-cancel = ❌ Bekor qilish
admin-verification-marked-as-taken = ✅ Yuk olib ketildi deb belgilandi!
admin-verification-mark-failed = ❌ Belgilashda xatolik yuz berdi.

# Account payment
admin-account-payment-select-provider = 🧾 <b>To'lov provayderni tanlang:</b>
admin-account-payment-confirm = ⚠️ <b>To'lovni tasdiqlaysizmi?</b>

    💰 Summa: <code>{ $amount } so'm</code>
    🏦 Provayder: <b>{ $provider }</b>
    📋 Transaction ID: <code>{ $transaction_id }</code>

    Tasdiqlash uchun "Ha" tugmasini bosing.

admin-account-payment-cancelled = ❌ To'lov bekor qilindi.
admin-account-payment-success = ✅ Hisobga to'lov muvaffaqiyatli tasdiqlandi!
admin-account-payment-already-confirmed = ⚠️ Bu to'lov allaqachon tasdiqlangan.
admin-account-payment-transaction-not-found = ❌ To'lov topilmadi.
admin-account-payment-error = ❌ To'lovni tasdiqlashda xatolik yuz berdi.

# Account payment channel notification
account-payment-channel-notification = ✅ <b>HISOBGA TO'LOV TASDIQLANDI</b>

    👤 Client: <code>{ $client_code }</code>
    🆔 Transaction ID: <code>{ $transaction_id }</code>
    ✈️ Reys: <b>{ $flight }</b>
    💰 Summa: <b>{ $amount } so'm</b>
    🏦 Provayder: <b>{ $provider }</b>
    👨‍💼 Admin: { $admin_name }
    🕒 Vaqt: { $time }

# Flight search
admin-verification-no-flights-found = ❌ <b>Reys topilmadi!</b>

    Reys <code>{ $flight }</code> bo'yicha hech qanday to'lov topilmadi.

admin-verification-flight-results = ✈️ <b>Reys: { $flight }</b>

    📊 Jami: <b>{ $total } ta to'lov</b>
    📄 Sahifa: <b>{ $page }/{ $total_pages }</b>

admin-verification-flight-item = Kod: <code>{ $code }</code> | Qator: <code>{ $row }</code> | Summa: <code>{ $amount } so'm</code>

    👤 F.I.O: <b>{ $name }</b>
    🆔 Kod: <code>{ $code }</code>

    Mijoz bazadan muvaffaqiyatli o'chirildi.

admin-delete-not-found = ❌ Mijoz topilmadi!

# Track code check
admin-track-check-enter-code = 📦 <b>Track kod tekshirish</b>

    Track kodini kiriting:

admin-track-check-cancelled = ❌ Track kod tekshirish bekor qilindi.

admin-track-check-not-found = ❌ <b>Track kod topilmadi!</b>

    Track kod <code>{ $track_code }</code> bo'yicha hech qanday ma'lumot topilmadi.

    Iltimos, kodni tekshirib qayta urinib ko'ring.

admin-track-check-uzbekistan-info = 🇺🇿 <b>O'ZBEKISTON OMBORIDA</b>

    🔍 <b>Track kod:</b> <code>{ $track_code }</code>
    👤 <b>Mijoz ID:</b> <code>{ $client_id }</code>
    ✈️ <b>Reys:</b> { $flight }
    📅 <b>Kelgan sana:</b> { $arrival_date }
    ⚖️ <b>Vazn:</b> { $weight } kg
    🔢 <b>Miqdor:</b> { $quantity }
    💵 <b>To'lov:</b> { $total_payment } so'm

    ✅ <b>Status:</b> Yuk O'zbekiston omborida mavjud

admin-track-check-china-info = 🇨🇳 <b>XITOY OMBORIDA</b>

    🔍 <b>Track kod:</b> <code>{ $track_code }</code>
    👤 <b>Mijoz ID:</b> <code>{ $client_id }</code>
    ✈️ <b>Reys:</b> { $flight }
    📅 <b>Qabul qilingan:</b> { $checkin_date }
    📦 <b>Mahsulot (RU):</b> { $item_name_ru }
    📦 <b>Mahsulot (CN):</b> { $item_name_cn }
    ⚖️ <b>Vazn:</b> { $weight } kg
    🔢 <b>Miqdor:</b> { $quantity }
    📦 <b>Quti raqami:</b> { $box_number }

    ⚠️ <b>Status:</b> Yuk Xitoy omborida, O'zbekistonga hali kelmagan

admin-track-check-summary = 📊 <b>Qidiruv natijalari:</b>

    📦 Jami topildi: { $total } ta
    🇺🇿 O'zbekistonda: { $in_uzbekistan } ta
    🇨🇳 Xitoyda: { $in_china } ta


# User Track code check
user-track-check-enter-code = 📦 <b>Track kod tekshirish</b>

    Track kodini kiriting:

    <i>Sizning yukingizni topish uchun track kodni kiriting.</i>

user-track-check-cancelled = ❌ Track kod tekshirish bekor qilindi.

user-track-check-not-found = ❌ <b>Track kod topilmadi!</b>

    Track kod <code>{ $track_code }</code> bo'yicha hech qanday ma'lumot topilmadi.

    Iltimos, kodni tekshirib qayta urinib ko'ring yoki admin bilan bog'laning.

user-track-check-uzbekistan-info = ✅ <b>YUKINGIZ O'ZBEKISTONDA!</b>

    🔍 <b>Track kod:</b> <code>{ $track_code }</code>
    ✈️ <b>Reys:</b> { $flight }
    📅 <b>Kelgan sana:</b> { $arrival_date }
    💵 <b>To'lov:</b> { $total_payment } so'm
    ⚖️ <b>Vazn:</b> { $weight } kg
    🔢 <b>Miqdor:</b> { $quantity }

    ✅ Yukingiz O'zbekiston omborimizda mavjud!
    📞 To'lov va olib ketish uchun admin bilan bog'laning.

user-track-check-china-info = 🛫 <b>YUKINGIZ YO'LDA</b>

    🔍 <b>Track kod:</b> <code>{ $track_code }</code>
    📅 <b>Xitoydan qabul qilingan:</b> { $checkin_date }
    📦 <b>Mahsulot:</b> { $item_name }
    ⚖️ <b>Vazn:</b> { $weight } kg
    🔢 <b>Miqdor:</b> { $quantity }
    ✈️ <b>Reys:</b> { $flight }
    📦 <b>Quti raqami:</b> { $box_number }

    ⚠️ Yukingiz Xitoy omborimizda, O'zbekistonga yo'lda.
    ⏰ O'zbekistonga yetib kelishi bilan xabardor qilamiz.

user-track-check-summary = 📊 <b>Natija:</b>

    📦 Jami: { $total } ta yuk
    ✅ O'zbekistonda: { $in_uzbekistan } ta
    🛫 Xitoyda (yo'lda): { $in_china } ta

user-track-check-search-again = 💡 <b>Boshqa yukni tekshirish uchun keyingi track kodni yuboring.</b>
    Jarayonni to'xtatish uchun <i>❌ Bekor qilish</i> tugmasini bosing.

# Photo Upload WebApp
btn-open-photo-webapp = 📸 Foto yuklash (Web)

msg-photo-upload-webapp = 🖼 <b>Foto yuklash tizimi</b>

    Reys va kargo fotosuratlarini yuklash uchun quyidagi tugmani bosing.

    📌 <b>Imkoniyatlar:</b>
    • Reys yaratish va ko'rish
    • Kargo fotosini yuklash
    • Client ID va vazn ko'rsatish
    • Barcha fotolarni ko'rish


# Info - Photos and Reports
btn-view-cargo-photos = 📸 Rasmlarni ko'rish
info-report-not-sent = Hisobot yuborilmagan
info-no-cargo-photos = ⚠️ Ushbu reys uchun rasmlar topilmadi.
info-cargo-photos-summary = 📸 <b>Jami { $total } ta rasm yuborildi</b>

    ✈️ Reys: <b>{ $flight_name }</b>
    👤 Mijoz kodi: <b>{ $client_code }</b>

info-report-not-sent-message = ⚠️ <b>Hisobot yuborilmagan</b>

    ✈️ Reys: <b>{ $flight_name }</b>
    👤 Mijoz kodi: <b>{ $client_code }</b>
    { $track_codes }

    Ushbu reys uchun hali admin tomonidan foto hisobot yuborilmagan.
    Iltimos, admin bilan bog'laning yoki keyinroq qayta urinib ko'ring.

    <i>Tugmani bosib reyslar ro'yxatiga qaytishingiz mumkin.</i>

# Profile - Address and Region Edit
btn-edit-address = 🏠 Manzilni o'zgartirish
profile-select-region = 🌍 <b>Viloyatingizni tanlang:</b>
profile-enter-address = 📍 <b>Aniq manzilni kiriting:</b>

    Masalan: Toshkent tumani, Qibray MFY, Yangi hayot ko'chasi 15-uy

profile-address-updated = ✅ Manzil muvaffaqiyatli yangilandi!

# Profile - Referal Balance
profile-referal-balance = 💰 Referal balansi: { $balance } so'm

# Delivery Request
btn-send-request = 📦 Zayavka qoldirish
delivery-select-type = 🚚 <b>Dastavka turini tanlang:</b>
delivery-type-uzpost = 📮 UZPOST
delivery-type-yandex = 🚕 Yandex
delivery-type-akb = 🍊 AKB Dastavka
delivery-type-bts = 🚌 BTS

btn-confirm-profile = ✅ Tasdiqlash
btn-edit-profile = ✏️ Tahrirlash

delivery-select-flights = ✈️ <b>Reyslarni tanlang:</b>

    Quyidagi reyslardan birini yoki bir nechtasini tanlang:

btn-ready-submit = ✅ Tayyor

delivery-uzpost-warning = ⚠️ <b>Muhim!</b>

    Ushbu dastavkadan foydalanish uchun oldindan to'lov qilish kerak.

    💰 <b>Narxlar:</b>
    • 1 kg uchun: 15,000 so'm
    • Qoraqalpoq, Surxondaryo va Xorazm uchun: 18,000 so'm

btn-submit-delivery-request = 📦 Zayavka qoldirish
btn-select-other-delivery = 🔄 Boshqasini tanlash

admin-settings-cards-delete-success = Karta muvaffaqiyatli o‘chirildi

delivery-send-payment-proof = 💳 <b>To'lov chekini yuboring:</b>

    Iltimos, to'lov qilganingizdan keyin chek rasmini yoki PDF faylini yuboring.

delivery-request-submitted = ✅ Zayavka muvaffaqiyatli yuborildi!

    Tez orada admin tomonidan ko'rib chiqiladi.

# Delivery Request - Admin Notifications
delivery-admin-new-request = 📦 <b>Yangi zayavka!</b>

    Dastavka turi: { $delivery_type }
    🆔 Mijoz ID: { $client_code }
    📞 Tel: { $phone }
    🏠 Manzil: { $region } vil, { $address }
    ✈️ Reyslar: { $flights }

btn-approve-delivery = ✅ Tasdiqlash
btn-reject-delivery = ❌ Rad etish  
btn-reject-delivery-comment = 💬 Izoh bilan rad etish

# Regions of Uzbekistan
region-toshkent-city = Toshkent shahri
region-toshkent = Toshkent viloyati
region-andijan = Andijon
region-bukhara = Buxoro
region-fergana = Farg'ona
region-jizzakh = Jizzax
region-namangan = Namangan
region-navoiy = Navoiy
region-qashqadarya = Qashqadaryo
region-samarkand = Samarqand
region-sirdarya = Sirdaryo
region-surkhandarya = Surxondaryo
region-karakalpakstan = Qoraqalpog'iston
region-khorezm = Xorazm
payment-report-not-sent-message = ⚠️ <b>Hisobot yuborilmagan</b>

    ✈️ Reys: <b>{}</b>
    👤 Mijoz kodi: <b>{}</b>

    Ushbu reys uchun hali admin tomonidan foto hisobot yuborilmagan. Iltimos, admin bilan bog'laning yoki keyinroq qayta urinib ko'ring.
profile-address-too-short = ❌ Manzil kamida 5 ta belgidan iborat bo'lishi kerak\!

# Profile with referrals
profile-info-with-referrals = 👤 <b>Profil ma'lumotlari</b>

    📝 Ism-familiya: <b>{$full_name}</b>
    🆔 Telegram ID: { $telegram_id }
    📞 Telefon: <b>{$phone}</b>
    🆔 Mijoz kodi: <b>{$client_code}</b>
    🪪 Passport seriyasi: <b>{$passport_series}</b>
    🔢 PINFL: <b>{$pinfl}</b>
    📅 Tug'ilgan sana: <b>{$dob}</b>
    📍 Viloyat: <b>{$region}</b>
    🏠 Manzil: <b>{$address}</b>
    👥 Taklif qilganlar: <b>{$referral_count} ta</b>
    📅 Ro'yxatdan o'tgan sana: <b>{$created_at}</b>

# Delivery Request - Missing translations
delivery-incomplete-profile = ⚠️ <b>Profil to'liq emas!</b>

    Zayavka qoldirish uchun profilingizda quyidagi ma'lumotlar bo'lishi kerak:
    • To'liq ism-familiya
    • Telefon raqam
    • Viloyat
    • Aniq manzil

    Iltimos, avval profilni to'ldiring.

delivery-confirm-profile = 📋 <b>Profil ma'lumotlari (zayavka uchun):</b>

    🆔 Mijoz kodi: <b>{$client_code}</b>
    👤 Ism-familiya: <b>{$full_name}</b>
    📞 Telefon: <b>{$phone}</b>
    📍 Viloyat: <b>{$region}</b>
    🏠 Manzil: <b>{$address}</b>

    Ma'lumotlar to'g'rimi?

delivery-edit-profile-first = ℹ️ Iltimos, avval profilni tahrirlang, keyin qaytadan zayavka qoldiring.

delivery-no-flights = ⚠️ Sizning reyslaringiz topilmadi. Zayavka qoldirish uchun avval buyurtmalaringiz bo'lishi yoki to'lovni 100% amalga oshirgan bo'lishingiz kerak.

delivery-select-flights-multiple = ✈️ <b>Reyslarni tanlang:</b>

    Bir yoki bir nechta reysni tanlang. Tanlovni tugatgach "Tayyor" tugmasini bosing.

delivery-select-flight-single = ✈️ <b>Reysni tanlang:</b>

    Quyidagi reyslardan birini tanlang:

btn-done-selecting-flights = ✅ Tayyor

delivery-no-flights-selected = ⚠️ Iltimos, kamida bitta reys tanlang!

delivery-uzpost-send-receipt = 💳 <b>To'lov chekini yuboring:</b>

    Iltimos, to'lov qilganingizdan keyin chek rasmini yoki PDF faylini yuboring.

delivery-request-approved = ✅ <b>Zayavkangiz tasdiqlandi!</b>

    Tez orada yukingiz sizga yetkaziladi.

delivery-request-rejected = ❌ <b>Zayavkangiz rad etildi</b>

    Qo'shimcha ma'lumot olish uchun admin bilan bog'laning.

delivery-approved-by-admin = ✅ Zayavka tasdiqlandi

delivery-rejected-by-admin = ❌ Zayavka rad etildi

please-wait = Iltimos, bir oz sabr qiling, biz sizni tekshirib chiqyapmiz.
delivery-all-flights-paid = ℹ️ Tanlangan barcha reyslar uchun to'lov qilingan. Iltimos, boshqa reyslarni tanlang.

delivery-uzpost-payment-info = 💳 <b>UZPOST - To'lov ma'lumotlari</b>

    ✈️ Reyslar: <b>{$flights}</b>
    ⚖️ Jami vazn: <b>{$total_weight} kg</b>
    💰 1 kg narxi: <b>{$price_per_kg} so'm</b>
    💵 <b>Jami to'lov summasi: {$total_amount} so'm</b>

    📋 <b>To'lov kartasi:</b>
    💳 Karta: <code>{$card_number}</code>
    👤 Egasi: <b>{$card_owner}</b>

    Iltimos, yuqoridagi kartaga to'lov qiling va chekni yuboring.

delivery-uzpost-payment-info_warning = 💳 <b>UZPOST - To'lov ma'lumotlari</b>

    ✈️ Reyslar: <b>{$flights}</b>
    ⚖️ Jami vazn: <b>{$total_weight} kg</b>
    💰 1 kg narxi: <b>{$price_per_kg} so'm</b>
    💵 <b>Jami to'lov summasi: {$total_amount} so'm</b>

    <code>⚠️ UZPOST yetkazib berish xizmati 20 kg dan og'ir bo'lgan yukni yetkazib bera olmaydi.
    Agar savollaringiz bo'lsa admin bilan bog'laning:</code>
    @AKB_CARGO

# Payment Reminder
payment-reminder-none = ✅ Sizda qoldiq to'lovlar yo'q. Barcha to'lovlar to'liq amalga oshirilgan.
payment-reminder-item = ⏰ <b>To'lov eslatmasi</b>
    ✈️ Reys: { $flight }
    💰 Jami: { $total } so'm
    ✅ To'langan: { $paid } so'm
    ⏳ Qolgan: { $remaining } so'm
    🗓️ Muddati: { $deadline }
payment-reminder-warning = ⚠️ <b>Diqqat!</b>
    To'lov muddati o'tib ketsa, yuk berilmaydi va musodara qilinishi mumkin.

payment-online-partial = 📝 Ushbu reys uchun qolgan summa: <code>{ $remaining }</code> so'm

# Admin Approval
admin-approved = ✅ Tasdiqlandi!
admin-approval-success = ✅ Foydalanuvchi { $client_code } tasdiqlandi.
admin-new-user-approved = 📝 <b>Yangi foydalanuvchi ro'yxatdan o'tdi:</b>
    
    🆔 <b>ID:</b> { $client_code }
    👤 <b>Ism:</b> { $full_name }
    📇 <b>Passport:</b> { $passport_series }
    📅 <b>Tug'ilgan sana:</b> { $date_of_birth }
    🏠 <b>Manzil:</b> { $region }, { $address }
    📞 <b>Telefon:</b> { $phone }
    🔢 <b>PINFL:</b> { $pinfl }
    🆔 <b>Telegram ID:</b> { $telegram_id }

client-approval-success-message = 🤝 Hurmatli mijoz, tizimda muvaffaqiyatli ro'yhatdan o'tganingiz bilan tabriklaymiz! 
    Sizga yuqorida Xitoydagi avia pochta manzili va sizning ID kodingizni ({ $client_code }) yubordik. 
    Ushbu manzilni Xitoyning istalgan dasturlariga kiritib, buyurtmalar amalga oshirishingiz mumkin!

    ✅ Kiritgan manzilingizni @AKB_CARGO ga yuborib tasdiqlashni unutmang!

    ⚠️ Adminlar tomonidan Tasdiqlanmagan manzilga yuborilgan buyurtmalar uchun javobgarlik olinmaydi!

# Admin Rejection
admin-rejected = ❌ Rad etildi!
admin-rejection-message = ❌ Foydalanuvchi <b>{ $full_name }</b> [{ $telegram_id }] rad etildi.
admin-rejection-message-with-reason = ❌ Foydalanuvchi <b>{ $full_name }</b> [{ $telegram_id }] rad etildi.
    📄 Sabab: { $reason }
admin-reject-reason-prompt = ❌ Rad etish sababini kiriting
    yoki /skip shunchaki bekor qiling:
client-rejection-message = ⚠️ Hurmatli { $full_name }, sizning ro'yxatdan o'tish so'rovingiz rad etildi.
client-rejection-message-with-reason = ⚠️ Hurmatli { $full_name }, sizning ro'yxatdan o'tish so'rovingiz rad etildi.

    ❌ Sabab: { $reason }

# ===== WALLET (HAMYON) =====

# Button
btn-wallet = 💰 Hamyon

# Wallet Main Screen
wallet-balance-positive = 💰 <b>Hamyon balansi:</b> { $balance } so'm

    ✅ Hisobingizda ortiqcha to'lov mavjud.

    Quyidagi amallardan birini tanlang:

wallet-balance-negative = 💰 <b>Hamyon balansi:</b> -{ $balance } so'm

    ⚠️ Sizda { $balance } so'm qarz mavjud.

    Quyidagi amallardan birini tanlang:

wallet-balance-zero = 💰 <b>Hamyon balansi:</b> 0 so'm

    ✅ Balansda, hech qanday qarz yoki ortiqcha to'lov yo'q.

# Wallet Buttons
btn-wallet-use-balance = ✅ Hisobdan foydalanish
btn-wallet-request-refund = 💸 Refund so'rash
btn-wallet-my-cards = 💳 Mening kartalarim
btn-wallet-pay-debt = 💳 Qarzni to'lash
btn-wallet-new-card = ➕ Yangi karta kiritish
btn-wallet-add-card = ➕ Karta qo'shish
btn-wallet-send-receipt = 📸 Chek yuborish
btn-admin-approve-refund = ✅ Tasdiqlash
btn-admin-reject-refund = ❌ Rad etish
btn-admin-approve-debt = ✅ Tasdiqlash
btn-admin-reject-debt = ❌ Rad etish

# Wallet - Use Balance Info
wallet-use-balance-info = ℹ️ Hisobdan foydalanish uchun "💳 To'lov qilish" bo'limiga o'ting.

    To'lov jarayonida hisobdagi mablag'dan foydalanish imkoniyati paydo bo'ladi.

# Wallet - Refund Flow
wallet-refund-select-card = 💸 <b>Refund so'rash</b>

    Mablag' qaytariladigan kartani tanlang yoki yangi karta raqamini kiriting:

wallet-refund-min-error = ⚠️ Refund qilish uchun minimal summa { $min_amount } so'm bo'lishi kerak.

wallet-refund-min-limit = ⚠️ Refund qilish uchun minimal summa 5,000 so'm bo'lishi kerak.

    Sizning balansigiz: { $balance } so'm.

wallet-refund-enter-card = 💳 Karta raqamini kiriting (16 raqam):

wallet-refund-invalid-card = ⚠️ Karta raqami noto'g'ri. 16 raqam kiriting.

wallet-refund-enter-holder = 👤 Karta egasining ismini kiriting (ixtiyoriy, o'tkazish uchun "otkazish" yozing):

wallet-refund-enter-card-number = 💳 Karta raqamini kiriting (16 raqam):

wallet-refund-enter-holder-name = 👤 Karta egasining ismini kiriting:

wallet-refund-enter-amount = 💰 Refund summasini kiriting (so'mda):

    Mavjud balans: { $balance } so'm
    Minimal summa: 5,000 so'm

wallet-refund-invalid-amount = ⚠️ Noto'g'ri summa. Iltimos, raqam kiriting.

wallet-refund-amount-too-low = ⚠️ Minimal refund summasi: 5,000 so'm.

wallet-refund-amount-too-high = ⚠️ Summa balansdagi mablag'dan oshib ketdi.

    Mavjud balans: { $balance } so'm

wallet-refund-exceeds-balance = ⚠️ Summa balansdagi mablag'dan oshib ketdi.

    Mavjud balans: { $balance } so'm

wallet-refund-confirm = 💸 <b>Refund so'rovi</b>

    💰 Summa: { $amount } so'm
    💳 Karta: { $card }
    👤 Karta egasi: { $holder }

    Tasdiqlaysizmi?

wallet-refund-confirm-old = 💸 <b>Refund so'rovi</b>

    💳 Karta: { $card_number }
    👤 Karta egasi: { $holder_name }
    💰 Summa: { $amount } so'm

    Tasdiqlaysizmi?

wallet-refund-submitted = ✅ Refund so'rovi yuborildi!

    Admin tomonidan ko'rib chiqilgach, sizga xabar beriladi.

wallet-refund-approved-user = ✅ Sizning refund so'rovingiz tasdiqlandi!

    💰 Qaytarilgan summa: { $amount } so'm

wallet-refund-rejected-user = ❌ Sizning refund so'rovingiz rad etildi.

wallet-refund-cancelled = ❌ Refund so'rovi bekor qilindi.

wallet-refund-save-card = 💳 Ushbu kartani saqlaysizmi?

wallet-refund-new-card = ➕ Yangi karta kiritish

# Wallet - Debt Payment Flow
wallet-no-debt = ✅ Sizda qarz mavjud emas.

wallet-debt-no-card = ⚠️ Hozirda to'lov kartasi mavjud emas. Iltimos, keyinroq urinib ko'ring.

wallet-debt-info = 💳 <b>Qarzni to'lash</b>

    ⚠️ Sizda { $debt } so'm qarz mavjud.

    Quyidagi kartaga to'lov qiling va chekni yuboring:

    💳 Karta: <code>{ $card_number }</code>
    👤 Karta egasi: { $card_holder }

wallet-debt-send-receipt-prompt = 📸 To'lov qilganingizdan so'ng "Chek yuborish" tugmasini bosing.

wallet-debt-upload-receipt = 📸 To'lov chekini (rasm yoki hujjat) yuboring:

wallet-debt-send-receipt = 📸 To'lov chekini (rasm yoki hujjat) yuboring:

wallet-debt-submitted = ✅ Qarz to'lovi cheki yuborildi!

    Admin tomonidan tasdiqlanishini kuting.

wallet-debt-approved-user = ✅ Qarz to'lovingiz qabul qilindi!

    💰 Qabul qilingan summa: { $amount } so'm

wallet-debt-rejected-user = ❌ Qarz to'lovingiz rad etildi. Iltimos, qaytadan urinib ko'ring.

wallet-debt-no-cards = ⚠️ Hozirda to'lov kartasi mavjud emas. Iltimos, keyinroq urinib ko'ring.

wallet-debt-cancelled = ❌ Qarz to'lovi bekor qilindi.

# Wallet - User Cards Management
wallet-my-cards-header = 💳 <b>Mening kartalarim</b>

wallet-no-cards = 📭 Sizda saqlangan kartalar yo'q.

    Karta qo'shish uchun quyidagi tugmani bosing.

wallet-card-no-holder = Noma'lum

wallet-card-invalid-number = ⚠️ Karta raqami noto'g'ri. 16 raqam kiriting.

wallet-card-invalid-holder = ⚠️ Karta egasi noto'g'ri. 2-255 belgi kiriting.

wallet-card-limit-reached = ⚠️ Eng ko'p { $limit } ta karta saqlash mumkin.

wallet-card-duplicate = ⚠️ Bu karta allaqachon qo'shilgan.

wallet-add-card-number = 💳 Yangi karta raqamini kiriting (16 raqam):

wallet-add-card-holder = 👤 Karta egasining ismini kiriting:

wallet-card-added = ✅ Karta muvaffaqiyatli qo'shildi!

wallet-card-deleted = ✅ Karta o'chirildi.

wallet-cards-title = 💳 <b>Mening kartalarim</b>

wallet-cards-empty = 📭 Sizda saqlangan kartalar yo'q.

    Karta qo'shish uchun quyidagi tugmani bosing.

wallet-cards-add = ➕ Karta qo'shish

wallet-cards-enter-number = 💳 Yangi karta raqamini kiriting (16 raqam):

wallet-cards-invalid-number = ⚠️ Karta raqami noto'g'ri. 16 raqam kiriting.

wallet-cards-enter-holder = 👤 Karta egasining ismini kiriting (ixtiyoriy, o'tkazish uchun "otkazish" yozing):

wallet-cards-added = ✅ Karta muvaffaqiyatli qo'shildi!

wallet-cards-deactivated = ✅ Karta o'chirildi.

wallet-cards-deleted = ✅ Karta o'chirildi.

wallet-cards-max-limit = ⚠️ Eng ko'p 5 ta karta saqlash mumkin.

wallet-cards-duplicate = ⚠️ Bu karta allaqachon qo'shilgan.

# Wallet - Admin Notifications
wallet-admin-refund-request = 💸 <b>REFUND SO'ROVI</b>

    👤 Mijoz: { $client_code }
    📱 Ism: { $full_name }
    📞 Telefon: { $phone }
    🆔 Telegram ID: { $telegram_id }

    💰 So'ralgan summa: { $amount } so'm

    💳 Karta: { $card }
    👤 Karta egasi: { $holder }

wallet-admin-debt-receipt = 💳 <b>QARZ TO'LOVI</b>

    👤 Mijoz: { $client_code }
    📱 Ism: { $full_name }
    📞 Telefon: { $phone }
    🆔 Telegram ID: { $telegram_id }

    💰 Qarz summasi: { $debt } so'm

wallet-admin-debt-payment = 💳 <b>QARZ TO'LOVI</b>

    👤 Mijoz: { $client_code }
    📱 Ism: { $full_name }
    📞 Telefon: { $phone }
    🆔 Telegram ID: { $telegram_id }

    💰 Qarz summasi: { $debt_amount } so'm

wallet-admin-refund-enter-amount = 💰 Qaytarilgan (actual) summani kiriting:

wallet-admin-refund-approved = ✅ Refund tasdiqlandi!

    👤 Mijoz: { $client_code }
    💰 Summa: { $amount } so'm
    👨‍💼 Tasdiqladi: { $admin_name }

wallet-admin-refund-success = ✅ Refund muvaffaqiyatli tasdiqlandi.

wallet-admin-refund-rejected = ❌ Refund rad etildi.

wallet-admin-refund-exceeds-balance = ⚠️ Summa balansdagi mablag'dan oshib ketdi.

    Mavjud balans: { $balance } so'm
    Kiritilgan summa: { $amount } so'm

wallet-admin-debt-enter-amount = 💰 Qabul qilingan (actual) summani kiriting:

wallet-admin-debt-approved = ✅ Qarz to'lovi tasdiqlandi!

    👤 Mijoz: { $client_code }
    💰 Summa: { $amount } so'm
    👨‍💼 Tasdiqladi: { $admin_name }

wallet-admin-debt-success = ✅ Qarz to'lovi muvaffaqiyatli tasdiqlandi.

wallet-admin-debt-rejected = ❌ Qarz to'lovi rad etildi.

wallet-admin-invalid-amount = ⚠️ Noto'g'ri summa. Iltimos, musbat raqam kiriting.

wallet-admin-amount-exceeds = ⚠️ Summa balansdagi mablag'dan oshib ketdi. Maks: { $max } so'm

wallet-admin-cancelled = ❌ Amal bekor qilindi.

wallet-admin-rejected = ❌ Rad etildi.

wallet-admin-client-not-found = ⚠️ Mijoz topilmadi.

# Admin Payment FSM - Amount Input
admin-payment-enter-amount = 💰 To'lov summasini kiriting:

    📊 Kutilgan summa: { $expected } so'm

    ❌ Bekor qilish uchun /cancel yozing.

admin-cash-payment-enter-amount = 💵 Naqd to'lov summasini kiriting:

    📊 Kutilgan summa: { $expected } so'm

    ❌ Bekor qilish uchun /cancel yozing.

admin-account-payment-enter-amount = 💳 { $provider } to'lov summasini kiriting:

    📊 Kutilgan summa: { $expected } so'm

    ❌ Bekor qilish uchun /cancel yozing.

admin-payment-invalid-amount = ⚠️ Noto'g'ri summa. Iltimos, musbat raqam kiriting.

admin-payment-amount-too-high = ⚠️ Kiritilgan summa juda katta.

    📊 Kutilgan: { $expected } so'm
    💰 Kiritilgan: { $entered } so'm

    Iltimos, to'g'ri summa kiriting.

admin-payment-cancelled = ❌ To'lov tasdiqlash bekor qilindi.

admin-payment-success = ✅ To'lov muvaffaqiyatli tasdiqlandi.

payment-approved-full-success =
    🎉 Tabriklaymiz! To'lovingiz muvaffaqiyatli qabul qilindi!
    ✅ Reys: { $worksheet }
    💰 To'langan summa: { $paid } so'm
    { $overpaid ->
        [0] { "" }
       *[other] 💚 Ortiqcha to'lov (keyingi reysga balans): { $overpaid_fmt } so'm
    }
    Siz muvaffaqiyatli to'lovni to'liq to'ladingiz — endi yetkazib berish
    xizmatlarimizdan bemalol foydalanib, yukingizni qabul qilib olishingiz mumkin.
    👇 Qurilishni tezroq boshlash uchun:

# Debt Allocation Notifications
debt-allocation-fully-paid = ✅ { $flight } - qarz to'liq yopildi
debt-allocation-partial = 💰 { $flight } - { $amount } so'm ayirildi
debt-allocation-credit = 💰 Ortiqcha: { $amount } so'm balansingizga qo'shildi
debt-allocation-new-balance = 📊 Yangi balans: { $balance } so'm

# User Notifications
wallet-user-refund-approved = ✅ Sizning refund so'rovingiz tasdiqlandi!
    💰 Qaytarilgan summa: { $amount } so'm

wallet-user-refund-rejected = ❌ Sizning refund so'rovingiz rad etildi.

wallet-user-debt-approved = ✅ Qarz to'lovingiz qabul qilindi!
    💰 Qabul qilingan summa: { $amount } so'm

wallet-user-debt-rejected = ❌ Qarz to'lovingiz rad etildi. Iltimos, qaytadan urinib ko'ring.

# Admin buttons
wallet-btn-approve-refund = ✅ Refundni tasdiqlash
wallet-btn-reject-refund = ❌ Refundni rad etish
wallet-btn-approve-debt = ✅ Qarz to'lovini tasdiqlash
wallet-btn-reject-debt = ❌ Qarz to'lovini rad etish

# Payment Integration - Balance Toggle
payment-wallet-balance-info = 💰 Hamyon balansi: { $balance } so'm
payment-wallet-toggle-on = ☑ Hisobdan foydalanish (yoqilgan)
payment-wallet-toggle-off = ☐ Hisobdan foydalanish
payment-wallet-fully-covered = ✅ To'lov hamyon hisobidan to'liq qoplanadi.
    Qolgan balans: { $remaining_balance } so'm
payment-wallet-partial-cover = 💰 Hamyondan: { $wallet_amount } so'm
    💳 To'lanishi kerak: { $remaining_payment } so'm

payment-wallet-available = 💰 Hamyon balansi: { $balance } so'm mavjud. Hisobdan foydalanish uchun "💰 Hisobdan foydalanish" tugmasini bosing.

payment-select-type-with-wallet = 💳 To'lov turini tanlang:

    💰 Jami: { $total } so'm
    💳 Hamyondan: { $wallet_deduction } so'm
    💵 To'lanishi kerak: { $final } so'm

btn-payment-use-wallet = 💰 Hisobdan foydalanish
btn-payment-wallet-enabled = ✅ Hisobdan foydalanish (yoqilgan)
btn-payment-wallet-only = ✅ Hamyon hisobidan to'lash

payment-wallet-success = ✅ To'lov muvaffaqiyatli amalga oshirildi!

    ✈️ Reys: { $flight }
    💰 Summa: { $amount } so'm

    To'lov hamyon hisobidan to'liq qoplandi.

# Delivery request wallet
btn-use-wallet = 💰 Hisobdan foydalanish
delivery-wallet-balance-info = 💰 Hamyon balansi: { $balance } so'm. Hisobdan foydalanish uchun Hamyon bo'limiga o'ting.

delivery-uzpost-payment-info-with-wallet = 🚚 <b>UZPOST orqali yetkazib berish</b>

    ⚖️ Umumiy vazn: <b>{ $total_weight } kg</b>
    💵 1 kg narxi: <b>{ $price_per_kg } so'm</b>

    📦 Reyslar:
    <b>{ $flights }</b>

    💰 Umumiy summa: <b>{ $total_amount } so'm</b>

    💳 Hisobdan yechildi: <b>{ $wallet_used } so'm</b>
    💵 To'lash uchun qolgan summa: <b>{ $final_payable } so'm</b>

    🏦 Karta raqami:
    <code>{ $card_number }</code>
    👤 Karta egasi: <b>{ $card_owner }</b>

    📸 Iltimos, to'lov chekini (rasm yoki fayl) yuboring.

delivery-uzpost-wallet-only-info = 🚚 <b>UZPOST orqali yetkazib berish</b>

    ⚖️ Umumiy vazn: <b>{ $total_weight } kg</b>

    📦 Reyslar:
    <b>{ $flights }</b>

    💰 Umumiy summa: <b>{ $total_amount } so'm</b>
    💳 Hisobdan: <b>{ $wallet_used } so'm</b> yechiladi

    🧾 To'lov admin tomonidan tasdiqlanishi kerak.

delivery-wallet-only-submitted = ✅ To'lov so'rovi yuborildi!

    💰 Hamyondan: { $amount } so'm
    🧾 To'lov admin tomonidan tasdiqlanishi kerak.

payment-wallet-only-submitted = ✅ To'lov so'rovi yuborildi!

    ✈️ Reys: { $flight }
    💰 Hamyondan: { $amount } so'm yechiladi
    🧾 To'lov admin tomonidan tasdiqlanishi kerak.

admin-payment-enter-amount-wallet-only = 💰 Hamyon to'lovi — summasini kiriting:

    📊 Jami summa: { $total } so'm
    💳 Hamyondan: { $wallet } so'm
    ⚠️ Faqat hamyon hisobidan to'lov.

    ✅ Tasdiqlash uchun 0 kiriting.
    ❌ Bekor qilish uchun /cancel yozing.

admin-payment-enter-amount-with-wallet = 💰 To'lov summasini kiriting:

    📊 Jami summa: { $total } so'm
    💳 Hamyondan: { $wallet } so'm
    💵 Kutilgan qo'shimcha to'lov: { $expected } so'm

    ❌ Bekor qilish uchun /cancel yozing.

payment-info-with-wallet = 📋 To'lov ma'lumotlari:

    🆔 Mijoz kodi: <code>{ $client_code }</code>
    ✈️ Reys: { $worksheet }
    💰 Jami summa: <code>{ $summa }</code> so'm
    💰 Hamyondan: <code>{ $wallet_used }</code> so'm
    💳 To'lanadi: <code>{ $final_payable }</code> so'm
    ⚖️ Vazn: { $vazn } kg
    📦 Trek kodlari: { $trek_kodlari }

    💳 Karta raqam: <code>{ $card_number }</code>
    👤 Ism Familiya: { $card_owner }

    📸 To'lov chekini yuborish uchun tugmani bosing:

payment-online-options = Onlayn to'lov turini tanlang
btn-view-client = Foydalanuvchini tekshirish

# Admin - Settings: Remove Admin
admin-settings-btn-remove-admin = 🗑 Adminlarni o'chirish
admin-settings-remove-admin-title = 👮‍♂️ <b>Adminlar ro'yxati:</b>
admin-settings-remove-admin-empty = 🤷‍♂️ Tizimda boshqa adminlar topilmadi.
admin-settings-remove-admin-self = ⚠️ Siz o'zingizni adminlikdan olib tashlay olmaysiz!
admin-settings-remove-admin-success = ✅ { $full_name } adminlik huquqidan mahrum qilindi.

# --- Admin Verification WebApp ---
msg-click-to-open-verification = Foydalanuvchilarni qidirish va tekshirish uchun quyidagi tugmani bosing 👇
btn-open-verification-webapp = 🔎 Qidiruv tizimini ochish

# API Payment Notifications (User-facing)
api-payment-success = ✅ To'lov muvaffaqiyatli qabul qilindi!
    💰 Summa: { $amount } so'm

    Balansingiz to'ldirildi.

api-payment-failed = ❌ To'lovda xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.

payment-approved-notification = ✅ Admin to'lovingizni tasdiqladi!
    💰 Summa: { $amount } so'm

payment-rejected-notification = ❌ To'lovingiz rad etildi.
    💬 Sabab: { $reason }

payment-online-confirmed-user = ✅ To'lov ({ $payment_type }) muvaffaqiyatli qabul qilindi!
    💰 Summa: { $amount } so'm
    
    Balansingiz yangilandi.

admin-settings-btn-usd-rate = 💵 USD Kursi
admin-settings-rate-title = <b>💵 Valyuta kursi sozlamalari (USD -> UZS)</b>
admin-settings-rate-status-api = 📊 Joriy holat: <b>API orqali avtomatik olinmoqda</b>
admin-settings-rate-status-custom = 📌 Joriy holat: <b>Qat'iy belgilangan kurs ({ $rate } UZS)</b>
admin-settings-rate-live = 🔄 Jonli API kursi: 1 USD = { $rate } UZS
admin-settings-btn-edit-rate = ✏️ Kursni o'zgartirish
admin-settings-btn-api-rate = 🔄 API ga o'tkazish
admin-settings-btn-custom-rate = 📌 Custom kurs
admin-settings-rate-prompt = <b>Iltimos, 1 USD uchun yangi qiymatni so'mda kiriting (masalan: 12600):</b>
admin-settings-rate-success = ✅ USD kursi muvaffaqiyatli saqlandi va tizim "Custom" (qat'iy) rejimga o'tkazildi!
admin-settings-rate-invalid = ❌ Noto'g'ri qiymat. Iltimos, to'g'ri raqam kiriting (masalan: 12500).
admin-settings-rate-toggle-success = ✅ Valyuta rejimi muvaffaqiyatli o'zgartirildi!
admin-settings-rate-no-custom = ❌ Oldin "Kursni o'zgartirish" orqali custom kursni kiriting!