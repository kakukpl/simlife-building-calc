# 🏗️ OB Empire Manager

Aplikacja Streamlit do optymalizacji zakupu budynków w grze symulacyjnej.  
Oblicza maksymalną liczbę budynków, potrzebne zasoby i przewidywany zysk na podstawie aktualnego salda i planowanego czasu klikania.

---

## 🚀 Uruchomienie

### 1. Wymagania
- Python 3.9+
- pip

### 2. Instalacja zależności
```bash
pip install -r requirements.txt
```

### 3. Start aplikacji
```bash
streamlit run app.py
```

Aplikacja otworzy się automatycznie w przeglądarce pod adresem `http://localhost:8501`.

---

## 🖥️ Obsługa interfejsu

| Element | Opis |
|---|---|
| **Aktualne Saldo (PLN)** | Wpisz swoje bieżące saldo w grze |
| **Czas klikania (h)** | Przesuń suwak – ile godzin planujesz aktywnie klikać (0–12h, co 0.5h) |
| **Prognoza zarobku** | Automatycznie oblicza zarobek z pasywki i klikania |
| **Wynik zakupu** | Pokazuje maks. liczbę budynków i resztę na koncie |
| **Zysk po 10h** | Przewidywany przychód ze wszystkich kupionych budynków |
| **Tabela zakupów** | Gotowa lista zasobów dla autoklikera (sumy na wszystkie budynki) |

---

## ⚙️ Konfiguracja (edycja kodu)

Wszystkie stałe są zebrane na górze pliku `app.py` w wyraźnie oznaczonych sekcjach.

### Zmiana przychodów gracza
```python
PASSIVE_INCOME_PER_H  = 8_480_000      # PLN/h – Pasywka
CLICKING_INCOME_PER_H = 46_138_788     # PLN/h – Klikanie
```

### Dodanie nowego typu budynku (np. Suspension Bridge)
W sekcji `BUILDINGS` dodaj nowy słownik:

```python
BUILDINGS = [
    {
        "id": "ob",
        "name": "OB (Ordinary Building)",
        ...
    },
    {
        "id": "suspension_bridge",
        "name": "Suspension Bridge",
        "emoji": "🌉",
        "cost": 500_000,           # Uzupełnij koszt
        "revenue_10h": 700_000,    # Uzupełnij przychód
        "needs": {
            "Budowniczowie": (10, "os."),
            "Metal":         (3_000, "t"),
            "Kable":         (200, "szt."),
        },
    },
]
```

Po dodaniu drugiego budynku w interfejsie pojawi się automatycznie lista rozwijana do wyboru typu budynku.

---

## 📁 Struktura projektu

```
OB_Empire_Manager/
├── app.py            # Główna aplikacja Streamlit
├── requirements.txt  # Zależności Python
└── README.md         # Ta instrukcja
```

---

## 📝 Dane bazowe OB

| Parametr | Wartość |
|---|---|
| Koszt 1 OB | 161 596 PLN |
| Przychód 1 OB (po 10h) | 221 935,71 PLN |
| Budowniczowie | 5 os. |
| Metal | 1 200 t |
| Drewno | 1 000 m³ |
| Beton | 50 m³ |

---

*OB Empire Manager v1.0*
