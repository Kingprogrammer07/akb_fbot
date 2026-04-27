"""Region/district constants and lookup helpers.

The project no longer uses ``AVIA_CODES`` (the old 4-letter prefix scheme such
as ``STBK``/``SAAN``).  Instead, every region has a numeric code (``01``,
``10`` … ``95``) and every district has a hierarchical code
(``{region_code}-{seq}``, e.g. ``01-9``).

The new ``client_code`` format consumed by ``api.utils.code_generator`` is:

* Tashkent (region ``01``)        → ``A{region}-{district}/{seq}`` (per-district seq)
* All other regions               → ``A{region}/{seq}``           (per-region seq)

Helpers in this module convert legacy free-text keys still stored in
``clients.region`` and ``clients.district`` (``"toshkent_city"``,
``"uchtepa"`` …) into the new codes used by the generator.
"""

from __future__ import annotations

from typing import Final


# ---------------------------------------------------------------------------
# Region table — code → display name
# ---------------------------------------------------------------------------

REGIONS: Final[dict[str, str]] = {
    "01": "Toshkent shahar",
    "10": "Toshkent viloyati",
    "20": "Sirdaryo",
    "25": "Jizzax",
    "30": "Samarqand",
    "40": "Farg'ona",
    "50": "Namangan",
    "60": "Andijon",
    "70": "Qashqadaryo",
    "75": "Surxondaryo",
    "80": "Buxoro",
    "85": "Navoiy",
    "90": "Xorazm",
    "95": "Qoraqalpog'iston",
}


# ---------------------------------------------------------------------------
# District table — district_code → metadata
# ---------------------------------------------------------------------------

DISTRICTS: Final[dict[str, dict[str, str]]] = {
    # Toshkent shahar (01)
    "01-1":  {"name": "Bektemir",        "region_code": "01"},
    "01-2":  {"name": "Chilonzor",       "region_code": "01"},
    "01-3":  {"name": "Yakkasaroy",      "region_code": "01"},
    "01-4":  {"name": "Mirobod",         "region_code": "01"},
    "01-5":  {"name": "Mirzo Ulug'bek",  "region_code": "01"},
    "01-6":  {"name": "Olmazor",         "region_code": "01"},
    "01-7":  {"name": "Sergeli",         "region_code": "01"},
    "01-8":  {"name": "Shayxontohur",    "region_code": "01"},
    "01-9":  {"name": "Uchtepa",         "region_code": "01"},
    "01-10": {"name": "Yunusobod",       "region_code": "01"},
    "01-11": {"name": "Yashnobod",       "region_code": "01"},
    "01-12": {"name": "Yangihayot",      "region_code": "01"},

    # Toshkent viloyati (10)
    "10-1":  {"name": "Bekobod tumani",          "region_code": "10"},
    "10-2":  {"name": "Bo'ka tumani",            "region_code": "10"},
    "10-3":  {"name": "Bo'stonliq tumani",       "region_code": "10"},
    "10-4":  {"name": "Chinoz tumani",           "region_code": "10"},
    "10-5":  {"name": "Qibray tumani",           "region_code": "10"},
    "10-6":  {"name": "Ohangaron tumani",        "region_code": "10"},
    "10-7":  {"name": "Oqqo'rg'on tumani",       "region_code": "10"},
    "10-8":  {"name": "Parkent tumani",          "region_code": "10"},
    "10-9":  {"name": "Piskent tumani",          "region_code": "10"},
    "10-10": {"name": "Quyi Chirchiq tumani",    "region_code": "10"},
    "10-11": {"name": "O'rta Chirchiq tumani",   "region_code": "10"},
    "10-12": {"name": "Yuqori Chirchiq tumani",  "region_code": "10"},
    "10-13": {"name": "Zangiota tumani",         "region_code": "10"},
    "10-14": {"name": "Yangiyo'l tumani",        "region_code": "10"},
    "10-15": {"name": "Angren shahri",           "region_code": "10"},
    "10-16": {"name": "Bekobod shahri",          "region_code": "10"},
    "10-17": {"name": "Chirchiq shahri",         "region_code": "10"},
    "10-18": {"name": "Olmaliq shahri",          "region_code": "10"},
    "10-19": {"name": "Ohangaron shahri",        "region_code": "10"},
    "10-20": {"name": "Yangiyo'l shahri",        "region_code": "10"},
    "10-21": {"name": "Nurafshon shahri",        "region_code": "10"},

    # Sirdaryo (20)
    "20-1":  {"name": "Boyovut tumani",     "region_code": "20"},
    "20-2":  {"name": "Guliston tumani",    "region_code": "20"},
    "20-3":  {"name": "Mirzaobod tumani",   "region_code": "20"},
    "20-4":  {"name": "Oqoltin tumani",     "region_code": "20"},
    "20-5":  {"name": "Sardoba tumani",     "region_code": "20"},
    "20-6":  {"name": "Sayxunobod tumani",  "region_code": "20"},
    "20-7":  {"name": "Sirdaryo tumani",    "region_code": "20"},
    "20-8":  {"name": "Xovos tumani",       "region_code": "20"},
    "20-9":  {"name": "Guliston shahri",    "region_code": "20"},
    "20-10": {"name": "Shirin shahri",      "region_code": "20"},
    "20-11": {"name": "Yangiyer shahri",    "region_code": "20"},

    # Jizzax (25)
    "25-1":  {"name": "Arnasoy tumani",     "region_code": "25"},
    "25-2":  {"name": "Baxmal tumani",      "region_code": "25"},
    "25-3":  {"name": "Do'stlik tumani",    "region_code": "25"},
    "25-4":  {"name": "Forish tumani",      "region_code": "25"},
    "25-5":  {"name": "G'allaorol tumani",  "region_code": "25"},
    "25-6":  {"name": "Jizzax tumani",      "region_code": "25"},
    "25-7":  {"name": "Mirzacho'l tumani",  "region_code": "25"},
    "25-8":  {"name": "Paxtakor tumani",    "region_code": "25"},
    "25-9":  {"name": "Yangiobod tumani",   "region_code": "25"},
    "25-10": {"name": "Zafarobod tumani",   "region_code": "25"},
    "25-11": {"name": "Zarbdor tumani",     "region_code": "25"},
    "25-12": {"name": "Zomin tumani",       "region_code": "25"},
    "25-13": {"name": "Jizzax shahri",      "region_code": "25"},
    "25-14": {"name": "G'allaorol shahri",  "region_code": "25"},

    # Samarqand (30)
    "30-1":  {"name": "Bulung'ur tumani",     "region_code": "30"},
    "30-2":  {"name": "Ishtixon tumani",      "region_code": "30"},
    "30-3":  {"name": "Jomboy tumani",        "region_code": "30"},
    "30-4":  {"name": "Kattaqo'rg'on tumani", "region_code": "30"},
    "30-5":  {"name": "Narpay tumani",        "region_code": "30"},
    "30-6":  {"name": "Nurobod tumani",       "region_code": "30"},
    "30-7":  {"name": "Oqdaryo tumani",       "region_code": "30"},
    "30-8":  {"name": "Paxtachi tumani",      "region_code": "30"},
    "30-9":  {"name": "Payariq tumani",       "region_code": "30"},
    "30-10": {"name": "Pastdarg'om tumani",   "region_code": "30"},
    "30-11": {"name": "Qo'shrabot tumani",    "region_code": "30"},
    "30-12": {"name": "Samarqand tumani",     "region_code": "30"},
    "30-13": {"name": "Toyloq tumani",        "region_code": "30"},
    "30-14": {"name": "Urgut tumani",         "region_code": "30"},
    "30-15": {"name": "Samarqand shahri",     "region_code": "30"},
    "30-16": {"name": "Kattaqo'rg'on shahri", "region_code": "30"},

    # Farg'ona (40)
    "40-1":  {"name": "Oltiariq tumani",   "region_code": "40"},
    "40-2":  {"name": "Bag'dod tumani",    "region_code": "40"},
    "40-3":  {"name": "Beshariq tumani",   "region_code": "40"},
    "40-4":  {"name": "Buvayda tumani",    "region_code": "40"},
    "40-5":  {"name": "Dang'ara tumani",   "region_code": "40"},
    "40-6":  {"name": "Farg'ona tumani",   "region_code": "40"},
    "40-7":  {"name": "Furqat tumani",     "region_code": "40"},
    "40-8":  {"name": "O'zbekiston tumani","region_code": "40"},
    "40-9":  {"name": "Quva tumani",       "region_code": "40"},
    "40-10": {"name": "Rishton tumani",    "region_code": "40"},
    "40-11": {"name": "So'x tumani",       "region_code": "40"},
    "40-12": {"name": "Toshloq tumani",    "region_code": "40"},
    "40-13": {"name": "Uchko'prik tumani", "region_code": "40"},
    "40-14": {"name": "Yozyovon tumani",   "region_code": "40"},
    "40-15": {"name": "Farg'ona shahri",   "region_code": "40"},
    "40-16": {"name": "Qo'qon shahri",     "region_code": "40"},
    "40-17": {"name": "Marg'ilon shahri",  "region_code": "40"},
    "40-18": {"name": "Quvasoy shahri",    "region_code": "40"},

    # Namangan (50)
    "50-1":  {"name": "Chortoq tumani",     "region_code": "50"},
    "50-2":  {"name": "Chust tumani",       "region_code": "50"},
    "50-3":  {"name": "Kosonsoy tumani",    "region_code": "50"},
    "50-4":  {"name": "Mingbuloq tumani",   "region_code": "50"},
    "50-5":  {"name": "Namangan tumani",    "region_code": "50"},
    "50-6":  {"name": "Norin tumani",       "region_code": "50"},
    "50-7":  {"name": "Pop tumani",         "region_code": "50"},
    "50-8":  {"name": "To'raqo'rg'on tumani","region_code": "50"},
    "50-9":  {"name": "Uchqo'rg'on tumani", "region_code": "50"},
    "50-10": {"name": "Uychi tumani",       "region_code": "50"},
    "50-11": {"name": "Yangiqo'rg'on tumani","region_code": "50"},
    "50-12": {"name": "Namangan shahri",    "region_code": "50"},
    "50-13": {"name": "Chust shahri",       "region_code": "50"},
    "50-14": {"name": "Chortoq shahri",     "region_code": "50"},
    "50-15": {"name": "Kosonsoy shahri",    "region_code": "50"},

    # Andijon (60)
    "60-1":  {"name": "Andijon tumani",       "region_code": "60"},
    "60-2":  {"name": "Asaka tumani",         "region_code": "60"},
    "60-3":  {"name": "Baliqchi tumani",      "region_code": "60"},
    "60-4":  {"name": "Bo'z tumani",          "region_code": "60"},
    "60-5":  {"name": "Buloqboshi tumani",    "region_code": "60"},
    "60-6":  {"name": "Izboskan tumani",      "region_code": "60"},
    "60-7":  {"name": "Jalaquduq tumani",     "region_code": "60"},
    "60-8":  {"name": "Marhamat tumani",      "region_code": "60"},
    "60-9":  {"name": "Oltinko'l tumani",     "region_code": "60"},
    "60-10": {"name": "Paxtaobod tumani",     "region_code": "60"},
    "60-11": {"name": "Shahrixon tumani",     "region_code": "60"},
    "60-12": {"name": "Ulug'nor tumani",      "region_code": "60"},
    "60-13": {"name": "Xo'jaobod tumani",     "region_code": "60"},
    "60-14": {"name": "Qo'rg'ontepa tumani",  "region_code": "60"},
    "60-15": {"name": "Andijon shahri",       "region_code": "60"},
    "60-16": {"name": "Asaka shahri",         "region_code": "60"},
    "60-17": {"name": "Shahrixon shahri",     "region_code": "60"},
    "60-18": {"name": "Xonobod shahri",       "region_code": "60"},

    # Qashqadaryo (70)
    "70-1":  {"name": "Dehqonobod tumani",   "region_code": "70"},
    "70-2":  {"name": "G'uzor tumani",       "region_code": "70"},
    "70-3":  {"name": "Kasbi tumani",        "region_code": "70"},
    "70-4":  {"name": "Kitob tumani",        "region_code": "70"},
    "70-5":  {"name": "Koson tumani",        "region_code": "70"},
    "70-6":  {"name": "Mirishkor tumani",    "region_code": "70"},
    "70-7":  {"name": "Muborak tumani",      "region_code": "70"},
    "70-8":  {"name": "Nishon tumani",       "region_code": "70"},
    "70-9":  {"name": "Qamashi tumani",      "region_code": "70"},
    "70-10": {"name": "Qarshi tumani",       "region_code": "70"},
    "70-11": {"name": "Shahrisabz tumani",   "region_code": "70"},
    "70-12": {"name": "Yakkabog' tumani",    "region_code": "70"},
    "70-13": {"name": "Chiroqchi tumani",    "region_code": "70"},
    "70-14": {"name": "Qarshi shahri",       "region_code": "70"},
    "70-15": {"name": "Shahrisabz shahri",   "region_code": "70"},

    # Surxondaryo (75)
    "75-1":  {"name": "Angor tumani",       "region_code": "75"},
    "75-2":  {"name": "Bandixon tumani",    "region_code": "75"},
    "75-3":  {"name": "Boysun tumani",      "region_code": "75"},
    "75-4":  {"name": "Denov tumani",       "region_code": "75"},
    "75-5":  {"name": "Jarqo'rg'on tumani", "region_code": "75"},
    "75-6":  {"name": "Muzrabot tumani",    "region_code": "75"},
    "75-7":  {"name": "Oltinsoy tumani",    "region_code": "75"},
    "75-8":  {"name": "Qiziriq tumani",     "region_code": "75"},
    "75-9":  {"name": "Qumqo'rg'on tumani", "region_code": "75"},
    "75-10": {"name": "Sariosiyo tumani",   "region_code": "75"},
    "75-11": {"name": "Sherobod tumani",    "region_code": "75"},
    "75-12": {"name": "Sho'rchi tumani",    "region_code": "75"},
    "75-13": {"name": "Termiz tumani",      "region_code": "75"},
    "75-14": {"name": "Uzun tumani",        "region_code": "75"},
    "75-15": {"name": "Termiz shahri",      "region_code": "75"},
    "75-16": {"name": "Denov shahri",       "region_code": "75"},

    # Buxoro (80)
    "80-1":  {"name": "Buxoro tumani",       "region_code": "80"},
    "80-2":  {"name": "G'ijduvon tumani",    "region_code": "80"},
    "80-3":  {"name": "Jondor tumani",       "region_code": "80"},
    "80-4":  {"name": "Kogon tumani",        "region_code": "80"},
    "80-5":  {"name": "Olot tumani",         "region_code": "80"},
    "80-6":  {"name": "Peshku tumani",       "region_code": "80"},
    "80-7":  {"name": "Qorako'l tumani",     "region_code": "80"},
    "80-8":  {"name": "Qorovulbozor tumani", "region_code": "80"},
    "80-9":  {"name": "Romitan tumani",      "region_code": "80"},
    "80-10": {"name": "Shofirkon tumani",    "region_code": "80"},
    "80-11": {"name": "Vobkent tumani",      "region_code": "80"},
    "80-12": {"name": "Buxoro shahri",       "region_code": "80"},
    "80-13": {"name": "Kogon shahri",        "region_code": "80"},

    # Navoiy (85)
    "85-1":  {"name": "Konimex tumani",   "region_code": "85"},
    "85-2":  {"name": "Karmana tumani",   "region_code": "85"},
    "85-3":  {"name": "Qiziltepa tumani", "region_code": "85"},
    "85-4":  {"name": "Navbahor tumani",  "region_code": "85"},
    "85-5":  {"name": "Nurota tumani",    "region_code": "85"},
    "85-6":  {"name": "Tomdi tumani",     "region_code": "85"},
    "85-7":  {"name": "Uchquduq tumani",  "region_code": "85"},
    "85-8":  {"name": "Xatirchi tumani",  "region_code": "85"},
    "85-9":  {"name": "Navoiy shahri",    "region_code": "85"},
    "85-10": {"name": "Zarafshon shahri", "region_code": "85"},

    # Xorazm (90)
    "90-1":  {"name": "Bog'ot tumani",      "region_code": "90"},
    "90-2":  {"name": "Gurlan tumani",      "region_code": "90"},
    "90-3":  {"name": "Hazorasp tumani",    "region_code": "90"},
    "90-4":  {"name": "Xiva tumani",        "region_code": "90"},
    "90-5":  {"name": "Qo'shko'pir tumani", "region_code": "90"},
    "90-6":  {"name": "Shovot tumani",      "region_code": "90"},
    "90-7":  {"name": "Urganch tumani",     "region_code": "90"},
    "90-8":  {"name": "Yangiariq tumani",   "region_code": "90"},
    "90-9":  {"name": "Yangibozor tumani",  "region_code": "90"},
    "90-10": {"name": "Tuproqqal'a tumani", "region_code": "90"},
    "90-11": {"name": "Xonqa tumani",       "region_code": "90"},
    "90-12": {"name": "Urganch shahri",     "region_code": "90"},
    "90-13": {"name": "Xiva shahri",        "region_code": "90"},

    # Qoraqalpog'iston (95)
    "95-1":  {"name": "Amudaryo tumani",     "region_code": "95"},
    "95-2":  {"name": "Beruniy tumani",      "region_code": "95"},
    "95-3":  {"name": "Chimboy tumani",      "region_code": "95"},
    "95-4":  {"name": "Ellikqal'a tumani",   "region_code": "95"},
    "95-5":  {"name": "Kegeyli tumani",      "region_code": "95"},
    "95-6":  {"name": "Mo'ynoq tumani",      "region_code": "95"},
    "95-7":  {"name": "Nukus tumani",        "region_code": "95"},
    "95-8":  {"name": "Qanliko'l tumani",    "region_code": "95"},
    "95-9":  {"name": "Qo'ng'irot tumani",   "region_code": "95"},
    "95-10": {"name": "Qorao'zak tumani",    "region_code": "95"},
    "95-11": {"name": "Shumanay tumani",     "region_code": "95"},
    "95-12": {"name": "Taxtako'pir tumani",  "region_code": "95"},
    "95-13": {"name": "To'rtko'l tumani",    "region_code": "95"},
    "95-14": {"name": "Xo'jayli tumani",     "region_code": "95"},
    "95-15": {"name": "Nukus shahri",        "region_code": "95"},
    "95-16": {"name": "Beruniy shahri",      "region_code": "95"},
    "95-17": {"name": "To'rtko'l shahri",    "region_code": "95"},
    "95-18": {"name": "Xo'jayli shahri",     "region_code": "95"},
    "95-19": {"name": "Taxiatosh shahri",    "region_code": "95"},
    "95-20": {"name": "Qo'ng'irot shahri",   "region_code": "95"},
    "95-21": {"name": "Chimboy shahri",      "region_code": "95"},
    "95-22": {"name": "Mo'ynoq shahri",      "region_code": "95"},
}


# ---------------------------------------------------------------------------
# Legacy free-text key → new code mapping
# ---------------------------------------------------------------------------
#
# Existing rows in ``clients.region`` and ``clients.district`` use the snake
# case keys defined by the previous ``AVIA_CODES`` dict.  These tables let the
# code generator (and any other consumer) translate the legacy values without
# requiring a frontend change.

LEGACY_REGION_KEY_TO_CODE: Final[dict[str, str]] = {
    "toshkent_city":   "01",
    "toshkent":        "10",
    "sirdarya":        "20",
    "jizzakh":         "25",
    "samarkand":       "30",
    "fergana":         "40",
    "namangan":        "50",
    "andijan":         "60",
    "kashkadarya":     "70",
    "surkhandarya":    "75",
    "bukhara":         "80",
    "navoi":           "85",
    "khorezm":         "90",
    "karakalpakstan":  "95",
}


LEGACY_DISTRICT_KEY_TO_CODE: Final[dict[str, str]] = {
    # Toshkent shahar
    "bektemir": "01-1", "chilonzor": "01-2", "yakkasaroy": "01-3",
    "mirobod": "01-4", "mirzo_ulugbek": "01-5", "olmazor": "01-6",
    "sergeli": "01-7", "shayxontohur": "01-8", "uchtepa": "01-9",
    "yunusobod": "01-10", "yashnobod": "01-11", "yangihayot": "01-12",
    # Toshkent viloyati
    "bekobod_t": "10-1", "boka": "10-2", "bostonliq": "10-3", "chinoz": "10-4",
    "qibray": "10-5", "ohangaron_t": "10-6", "oqqorgon": "10-7",
    "parkent": "10-8", "piskent": "10-9", "quyi_chirchiq": "10-10",
    "orta_chirchiq": "10-11", "yuqori_chirchiq": "10-12", "zangiota": "10-13",
    "yangiyo'l_t": "10-14", "yangiyol_t": "10-14",
    "angren": "10-15", "bekobod_s": "10-16", "chirchiq": "10-17",
    "olmaliq": "10-18", "ohangaron_s": "10-19",
    "yangiyo'l_s": "10-20", "yangiyol_s": "10-20",
    "nurafshon": "10-21",
    # Sirdaryo
    "boyovut": "20-1", "guliston_t": "20-2", "mirzaobod": "20-3",
    "oqoltin": "20-4", "sardoba": "20-5", "sayxunobod": "20-6",
    "sirdaryo_t": "20-7", "xovos": "20-8", "guliston_s": "20-9",
    "shirin": "20-10", "yangiyer": "20-11",
    # Jizzax
    "arnasoy": "25-1", "baxmal": "25-2", "dostlik": "25-3", "forish": "25-4",
    "gallaorol_t": "25-5", "jizzax_t": "25-6", "mirzachol": "25-7",
    "paxtakor": "25-8", "yangiobod": "25-9", "zafarobod": "25-10",
    "zarbdor": "25-11", "zomin": "25-12", "jizzax_s": "25-13",
    "gallaorol_s": "25-14",
    # Samarqand
    "bulungur": "30-1", "ishtixon": "30-2", "jomboy": "30-3",
    "kattaqorgon_t": "30-4", "narpay": "30-5", "nurobod": "30-6",
    "oqdaryo": "30-7", "paxtachi": "30-8", "payariq": "30-9",
    "pastdargom": "30-10", "qoshrabot": "30-11", "samarqand_t": "30-12",
    "toyloq": "30-13", "urgut": "30-14", "samarqand_s": "30-15",
    "kattaqorgon_s": "30-16",
    # Farg'ona
    "oltiariq": "40-1", "bagdod": "40-2", "beshariq": "40-3", "buvayda": "40-4",
    "dangara": "40-5", "fargona_t": "40-6", "furqat": "40-7",
    "ozbekiston": "40-8", "quva_t": "40-9", "rishton": "40-10",
    "sox": "40-11", "toshloq": "40-12", "uchkoprik": "40-13",
    "yozyovon": "40-14", "fargona_s": "40-15", "qoqon": "40-16",
    "margilon": "40-17", "quvasoy": "40-18",
    # Namangan
    "chortoq_t": "50-1", "chust_t": "50-2", "kosonsoy_t": "50-3",
    "mingbuloq": "50-4", "namangan_t": "50-5", "norin": "50-6",
    "pop": "50-7", "toraqorgon": "50-8", "uchqorgon": "50-9",
    "uychi": "50-10", "yangiqorgon": "50-11", "namangan_s": "50-12",
    "chust_s": "50-13", "chortoq_s": "50-14", "kosonsoy_s": "50-15",
    # Andijon
    "andijon_t": "60-1", "asaka_t": "60-2", "baliqchi": "60-3", "boz": "60-4",
    "buloqboshi": "60-5", "izboskan": "60-6", "jalaquduq": "60-7",
    "marhamat": "60-8", "oltinkol": "60-9", "paxtaobod": "60-10",
    "shahrixon_t": "60-11", "ulugnar": "60-12", "xojaobod": "60-13",
    "qorgontepa": "60-14", "andijon_s": "60-15", "asaka_s": "60-16",
    "shahrixon_s": "60-17", "xonobod": "60-18",
    # Qashqadaryo
    "dehqonobod": "70-1", "guzor": "70-2", "kasbi": "70-3", "kitob": "70-4",
    "koson": "70-5", "mirishkor": "70-6", "muborak": "70-7", "nishon": "70-8",
    "qamashi": "70-9", "qarshi_t": "70-10", "shahrisabz_t": "70-11",
    "yakkabog": "70-12", "chiroqchi": "70-13", "qarshi_s": "70-14",
    "shahrisabz_s": "70-15",
    # Surxondaryo
    "angor": "75-1", "bandixon": "75-2", "boysun": "75-3", "denov_t": "75-4",
    "jarqorgon": "75-5", "muzrabot": "75-6", "oltinsoy": "75-7",
    "qiziriq": "75-8", "qumqorgon": "75-9", "sariosiyo": "75-10",
    "sherobod": "75-11", "shorchi": "75-12", "termiz_t": "75-13",
    "uzun": "75-14", "termiz_s": "75-15", "denov_s": "75-16",
    # Buxoro
    "buxoro_t": "80-1", "gijduvon": "80-2", "jondor": "80-3",
    "kogon_t": "80-4", "olot": "80-5", "peshku": "80-6", "qarakol": "80-7",
    "qarovulbozor": "80-8", "romitan": "80-9", "shofirkon": "80-10",
    "vobkent": "80-11", "buxoro_s": "80-12", "kogon_s": "80-13",
    # Navoiy
    "konimex": "85-1", "karmana": "85-2", "qiziltepa": "85-3",
    "navbahor": "85-4", "nurota": "85-5", "tomdi": "85-6", "uchquduq": "85-7",
    "xatirchi": "85-8", "navoiy_s": "85-9", "zarafshon": "85-10",
    # Xorazm
    "bogot": "90-1", "gurlan": "90-2", "hazorasp": "90-3", "xiva_t": "90-4",
    "qoshkopir": "90-5", "shovot": "90-6", "urganch_t": "90-7",
    "yangiariq": "90-8", "yangibozor": "90-9", "tuproqqala": "90-10",
    "xonqa": "90-11", "urganch_s": "90-12", "xiva_s": "90-13",
    # Qoraqalpog'iston
    "amudaryo": "95-1", "beruniy_t": "95-2", "chimboy_t": "95-3",
    "ellikqala": "95-4", "kegeyli": "95-5", "moynoq_t": "95-6",
    "nukus_t": "95-7", "qanlikol": "95-8", "qongrot_t": "95-9",
    "qaraozak": "95-10", "shumanay": "95-11", "taxtakopir": "95-12",
    "tortkol_t": "95-13", "xojayli_t": "95-14", "nukus_s": "95-15",
    "beruniy_s": "95-16", "tortkol_s": "95-17", "xojayli_s": "95-18",
    "taxiatosh": "95-19", "qongrot_s": "95-20", "chimboy_s": "95-21",
    "moynoq_s": "95-22",
}


# ---------------------------------------------------------------------------
# Backward-compatible exports (used widely by routers/services for display).
#
# These are the same human-readable display strings that the rest of the code
# base still expects when rendering region names from ``client.region``.
# ---------------------------------------------------------------------------

UZBEKISTAN_REGIONS: Final[dict[str, str]] = {
    "toshkent_city":  "Toshkent shahri",
    "toshkent":       "Toshkent viloyati",
    "andijan":        "Andijon viloyati",
    "bukhara":        "Buxoro viloyati",
    "fergana":        "Fargona viloyati",
    "jizzakh":        "Jizzax viloyati",
    "kashkadarya":    "Qashqadaryo viloyati",
    "navoi":          "Navoiy viloyati",
    "namangan":       "Namangan viloyati",
    "samarkand":      "Samarkand viloyati",
    "sirdarya":       "Sirdaryo viloyati",
    "surkhandarya":   "Surxondaryo viloyati",
    "karakalpakstan": "Qoraqalpogiston viloyati",
    "khorezm":        "Xorazm viloyati",
}


# ---------------------------------------------------------------------------
# Deprecated shims — retained as empty mappings so legacy importers (notably
# ``infrastructure.database.dao.statistics.{client,financial}_stats``) keep
# loading without changes.  The new numeric ``REGIONS`` / ``DISTRICTS`` tables
# above are the source of truth.  Statistics modules will be updated to read
# from them in a follow-up phase.
# ---------------------------------------------------------------------------

AVIA_CODES: Final[dict[str, str]] = {}
REGION_PREFIX_TO_NAME: Final[dict[str, str]] = {}
TASHKENT_DISTRICT_CODE_TO_NAME: Final[dict[str, str]] = {}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _normalize(value: str | None) -> str:
    """Lowercase + strip + collapse whitespace for tolerant lookups."""
    if not value:
        return ""
    return " ".join(value.strip().lower().split())


def resolve_region_code(value: str | None) -> str | None:
    """Best-effort conversion of any region representation to its numeric code.

    Accepts: numeric code (``"01"``), legacy snake_case key (``"toshkent_city"``),
    or display name (``"Toshkent shahri"``).  Returns ``None`` if no match.
    """
    if not value:
        return None
    raw = value.strip()
    if raw in REGIONS:
        return raw
    norm = _normalize(raw)
    if norm in LEGACY_REGION_KEY_TO_CODE:
        return LEGACY_REGION_KEY_TO_CODE[norm]
    # Display-name fallback (compare against REGIONS values + UZBEKISTAN_REGIONS values)
    for code, name in REGIONS.items():
        if _normalize(name) == norm:
            return code
    for legacy_key, display in UZBEKISTAN_REGIONS.items():
        if _normalize(display) == norm:
            return LEGACY_REGION_KEY_TO_CODE.get(legacy_key)
    return None


def resolve_district_code(value: str | None) -> str | None:
    """Best-effort conversion of any district representation to ``{region}-{seq}``.

    Accepts: numeric district code (``"01-9"``), legacy snake_case key
    (``"uchtepa"``), or display name (``"Uchtepa"``, ``"Bektemir"``).
    """
    if not value:
        return None
    raw = value.strip()
    if raw in DISTRICTS:
        return raw
    norm = _normalize(raw)
    if norm in LEGACY_DISTRICT_KEY_TO_CODE:
        return LEGACY_DISTRICT_KEY_TO_CODE[norm]
    # Display-name fallback
    for code, info in DISTRICTS.items():
        if _normalize(info["name"]) == norm:
            return code
    return None


def get_region_name(region_code: str | None) -> str:
    """Resolve a region code (or any legacy variant) to its display name."""
    if not region_code:
        return ""
    code = resolve_region_code(region_code) or region_code
    return REGIONS.get(code, region_code)


def get_district_name(district_code: str | None) -> str:
    """Resolve a district code (or any legacy variant) to its display name."""
    if not district_code:
        return ""
    code = resolve_district_code(district_code) or district_code
    info = DISTRICTS.get(code)
    return info["name"] if info else district_code


def get_districts_by_region(region_code: str) -> dict[str, dict[str, str]]:
    """All districts belonging to ``region_code`` (numeric)."""
    code = resolve_region_code(region_code) or region_code
    return {k: v for k, v in DISTRICTS.items() if v["region_code"] == code}


def format_location(region: str | None, district: str | None) -> str:
    """Render ``"<region>, <district>"`` from any valid representation."""
    region_name = get_region_name(region)
    district_name = get_district_name(district)
    if region_name and district_name:
        return f"{region_name}, {district_name}"
    return region_name or district_name or ""


def decode_region_key(region_key: str) -> str:
    """Backward-compatible wrapper used by ``financial_stats_service``.

    The old implementation handled both 4-letter Tashkent district codes
    (``STCH``) and 2-letter region prefixes (``SS``).  Those identifiers no
    longer exist; the helper now operates on the new numeric codes while
    still falling back to the raw input for unknown values.
    """
    if not region_key:
        return ""
    code = resolve_district_code(region_key)
    if code:
        district = DISTRICTS[code]
        return f"{REGIONS[district['region_code']]}, {district['name']}"
    code = resolve_region_code(region_key)
    if code:
        return REGIONS[code]
    return region_key
