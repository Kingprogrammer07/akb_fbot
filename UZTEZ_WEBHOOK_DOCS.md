# Uztez Kargo — Foto Hisobot Webhook & API Spetsifikatsiyasi

Ushbu hujjat **Uztez** kargo hamkori dasturchilari uchun mo'ljallangan bo'lib, AKB Cargo tizimidan reys bo'yicha tayyorlangan foto hisobot ma'lumotlarini qabul qilish integratsiyasini tavsiflaydi.

---

## 1. Integratsiya Qanday Ishlaydi?

AKB tizimida operator reysni tanlab **"Foto yuklash" -> "Ma'lumot yuborish"** tugmasini bosganda:
1. Uztez mijozlarining foto hisobotlari Telegram guruhiga odatdagidek yuboriladi.
2. Shu bilan birga, butun reys bo'yicha Uztezga tegishli barcha yuklar, maskalangan va haqiqiy reys nomlari, hamda rasmlar havolalari bitta umumiy paket (batch) sifatida **Uztez Webhook URL** manziliga `POST` so'rovi bilan avtomatik yuboriladi.
3. Qo'shimcha ravishda, Uztez tizimi kerak bo'lganda ushbu ma'lumotlarni to'g'ridan-to'g'ri `GET` so'rovi orqali ham tortib olishi mumkin.

---

## 2. Webhook So'rovining Parametrlari (Outgoing POST)

Uztez dasturchilari o'z serverlarida bitta `POST` endpoint ochib berishlari kerak (masalan: `https://api.uztez.uz/v1/cargo-webhook`).

- **Method:** `POST`
- **Content-Type:** `application/json`
- **User-Agent:** `AKB-Cargo-Bot/1.0`

### Request Headerlar:
| Header | Turi | Tavsif |
| :--- | :--- | :--- |
| `Content-Type` | `string` | `application/json` |
| `X-Webhook-Secret` | `string` | Uztez va AKB o'rtasida kelishilgan maxfiy xavfsizlik kaliti (token) |

---

## 3. Webhook JSON Payload Tuzilishi (Ma'lumotlar sxemasi)

### 3.1. Asosiy Obyekt:
| Maydon | Turi | Tavsif / Qiymat namunasi |
| :--- | :--- | :--- |
| `event` | `string` | Hodisa nomi: doim `"cargo_photos_sent"` |
| `flight_name` | `string` | **Haqiqiy reys kodi** (masalan: `"M200"`) |
| `masked_flight_name` | `string` | **Maskalangan (mijozlarga ko'rsatiladigan) reys nomi** (masalan: `"UZT45"`) |
| `partner_code` | `string` | Hamkor kodi: `"U"` |
| `partner_name` | `string` | Hamkor nomi: `"Uztez"` |
| `sent_at` | `string` (ISO 8601) | Yuborilgan sana va vaqt (`"2026-10-23T18:00:00+05:00"`) |
| `total_clients` | `integer` | Ushbu reysdagi jami Uztez mijozlari soni (`12`) |
| `total_weight` | `number` | Ushbu reysdagi Uztez yuklarining jami brutto vazni kg da (`45.6`) |
| `reports` | `array[ClientReport]` | Har bir mijoz bo'yicha tayyorlangan foto hisobotlar ro'yxati |

---

### 3.2. `reports` Ichidagi Har Bir Mijoz Obyekti (`ClientReport`):
| Maydon | Turi | Tavsif / Qiymat namunasi |
| :--- | :--- | :--- |
| `client_id` | `string` | Mijoz kodi (masalan: `"U10025"`) |
| `track_codes` | `array[string]` | Ushbu mijozning ushbu reysdagi barcha track kodlari ro'yxati |
| `total_weight` | `number` | Mijoz yukining umumiy og'irligi kg da (`3.8`) |
| `extra_charge` | `number` | Qo'shimcha to'lov summasi |
| `payment_card_number` | `string` yoki `null` | To'lov uchun karta raqami |
| `payment_card_holder` | `string` yoki `null` | Karta egasining ismi |
| `items` | `array[CargoItem]` | Yuk ichidagi tovarlar taqsimoti |
| `photo_urls` | `array[string]` | **Yuk rasmlarining to'g'ridan-to'g'ri havolalari** (S3 presigned URL, 60 kun amal qiladi) |
| `message_text` | `string` | Telegram guruhga yuborilgan hisobot matni |

#### `items` Ichidagi Tovar Obyekti:
| Maydon | Turi | Tavsif |
| :--- | :--- | :--- |
| `weight` | `number` | Tovar vazni (`3.8`) |
| `price_usd` | `number` | USD dagi narxi (`30.4`) |
| `price_uzs` | `number` | So'mdagi narxi (`386000`) |
| `category` | `string` | Tovar toifasi (`"Yuk"`) |

---

## 4. Webhook So'rovi Namunasi (JSON Payload)

```json
{
  "event": "cargo_photos_sent",
  "flight_name": "M200",
  "masked_flight_name": "UZT45",
  "partner_code": "U",
  "partner_name": "Uztez",
  "sent_at": "2026-10-23T18:00:00+05:00",
  "total_clients": 2,
  "total_weight": 7.3,
  "reports": [
    {
      "client_id": "U10025",
      "track_codes": [
        "TRK99881122",
        "TRK99881123"
      ],
      "total_weight": 3.8,
      "extra_charge": 0.0,
      "payment_card_number": "8600123456789012",
      "payment_card_holder": "UZTEZ KARGO",
      "items": [
        {
          "weight": 3.8,
          "price_usd": 30.4,
          "price_uzs": 386000.0,
          "category": "Yuk"
        }
      ],
      "photo_urls": [
        "https://akb-bucket.s3.amazonaws.com/china_import_image/M200/photo1.webp?AWSAccessKeyId=AKIA...&Expires=1793280000&Signature=...",
        "https://akb-bucket.s3.amazonaws.com/china_import_image/M200/photo2.webp?AWSAccessKeyId=AKIA...&Expires=1793280000&Signature=..."
      ],
      "message_text": "✈️ Reys: UZT45\n👤 Mijoz: U10025\n📦 Track-kodlar: TRK99881122, TRK99881123\n⚖️ Umumiy og'irlik: 3.8 kg\n💵 Jami: 30.4 $ (386,000 so'm)"
    },
    {
      "client_id": "U10026",
      "track_codes": [
        "TRK99881124"
      ],
      "total_weight": 3.5,
      "extra_charge": 0.0,
      "payment_card_number": "8600123456789012",
      "payment_card_holder": "UZTEZ KARGO",
      "items": [
        {
          "weight": 3.5,
          "price_usd": 28.0,
          "price_uzs": 355600.0,
          "category": "Yuk"
        }
      ],
      "photo_urls": [
        "https://akb-bucket.s3.amazonaws.com/china_import_image/M200/photo3.webp?AWSAccessKeyId=AKIA...&Expires=1793280000&Signature=..."
      ],
      "message_text": "✈️ Reys: UZT45\n👤 Mijoz: U10026\n📦 Track-kodlar: TRK99881124\n⚖️ Umumiy og'irlik: 3.5 kg\n💵 Jami: 28.0 $ (355,600 so'm)"
    }
  ]
}
```

---

## 5. Uztez Serveri Qaytarishi Kerak Bo'lgan Javob

Uztez serveri so'rovni muvaffaqiyatli qabul qilganda **HTTP 200 OK** (yoki 201/204) qaytarishi shart:

```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "success": true,
  "message": "Reports received successfully"
}
```

> **Eslatma:** Agar Uztez serveri 5xx yoki tarmoq xatosi qaytarsa, AKB tizimi 3 martagacha qayta urinib (retry) ko'radi.

---

## 6. Qo'shimcha Pull Endpoint (Zaxira / Test uchun)

Agar Uztez dasturchilari xohlasa, istalgan vaqtda ma'lumotlarni o'zlari `GET` so'rovi orqali ham olishlari mumkin:

```http
GET /api/v1/external/partner/uztez/flight-reports?flight_name=M200 HTTP/1.1
Host: <akb-domain>
X-API-Key: <EXTERNAL_API_KEY>
```

Ushbu endpoint ham yuqoridagi Webhook payload bilan 100% bir xil formatda JSON qaytaradi.

---

## 7. TypeScript Type Ta'riflari (Uztez Dasturchilari Uchun)

```typescript
export interface CargoItemDetail {
  weight: number;
  price_usd: number;
  price_uzs: number;
  category: string;
}

export interface UztezClientReport {
  client_id: string;
  track_codes: string[];
  total_weight: number;
  extra_charge: number;
  payment_card_number: string | null;
  payment_card_holder: string | null;
  items: CargoItemDetail[];
  photo_urls: string[];
  message_text: string;
}

export interface UztezCargoWebhookPayload {
  event: 'cargo_photos_sent';
  flight_name: string;
  masked_flight_name: string;
  partner_code: 'U';
  partner_name: 'Uztez';
  sent_at: string; // ISO 8601
  total_clients: number;
  total_weight: number;
  reports: UztezClientReport[];
}
```
