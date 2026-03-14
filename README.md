# a poor man's reddit api

---

## PL 🇵🇱

Własny scraper Reddita z REST API. Co godzinę pobiera posty i komentarze z wybranych subredditów i udostępnia je przez proste API w formacie JSON.

### Architektura

```
Scheduler (APScheduler)
    └── Scraper (Python/Playwright)
            │  scrapes old.reddit.com
            ↓
        RabbitMQ
            ↓
        Loader (Python)
            │  upserts posts + comments
            ↓
        PostgreSQL
            ↑
        API (Python/FastAPI)
            ↑
        HTTP clients
```

| Serwis | Rola |
|--------|------|
| `scraper` | Odpytuje old.reddit.com co godzinę przez Playwright, publikuje posty na kolejkę w RabbitMQ |
| `loader` | Odbiera wiadomości z Rabbita, zapisuje posty i komentarze do Postgresa |
| `api` | FastAPI na porcie 8080 |
| `postgres` | Persystencja postów i komentarzy |
| `rabbitmq` | Kolejka między scraperem a loaderem |

### Uruchomienie

Wymagany Docker i Docker Compose.

```bash
cp .env.example .env
docker compose up -d
```

Scraper uruchamia się od razu po starcie, a potem co godzinę. API dostępne pod `http://localhost:8080`.

### Konfiguracja

#### Subreddits

Edytuj `config/subreddits.yaml` — scraper przeładuje plik automatycznie, bez restartu:

```yaml
subreddits:
  - programming
  - golang
lookback_hours: 72
```

Możesz też ustawić zmienną środowiskową `SUBREDDITS` (wartości oddzielone przecinkami), która nadpisuje YAML:

```
SUBREDDITS=programming,golang,rust
```

#### Zmienne środowiskowe

Wszystkie serwisy konfigurowane są przez `.env`:

| Zmienna | Domyślna | Opis |
|---------|----------|------|
| `POSTGRES_DB` | `reddit` | Nazwa bazy danych |
| `POSTGRES_USER` | `reddit` | Użytkownik PostgreSQL |
| `POSTGRES_PASSWORD` | `reddit` | Hasło PostgreSQL |
| `POSTGRES_HOST` | `postgres` | Host PostgreSQL |
| `RABBITMQ_HOST` | `rabbitmq` | Host RabbitMQ |
| `RABBITMQ_USER` | `guest` | Użytkownik RabbitMQ |
| `RABBITMQ_PASSWORD` | `guest` | Hasło RabbitMQ |
| `RABBITMQ_EXCHANGE` | `reddit.posts` | Nazwa exchange w RabbitMQ |
| `RABBITMQ_QUEUE` | `posts.ingest` | Kolejka do ingestowania |
| `SUBREDDITS` | _(z YAML)_ | Lista subredditów oddzielona przecinkami |
| `LOOKBACK_HOURS` | `24` | Liczba godzin do update'owania wstecz postów przez scrapera|
| `CONFIG_PATH` | `/app/config/subreddits.yaml` | Konfig |
| `API_PORT` | `8080` | Port API |

### API

#### `GET /`

Health check. Zwraca `"OK"`.

---

#### `GET /r/{subreddit}`

Zwraca najnowsze posty z danego subreddita, od najnowszego.

**Parametry zapytania:**

| Parametr | Opis |
|----------|------|
| `after` | ID posta — zwraca starsze posty |
| `before` | ID posta — zwraca nowsze posty |
| `limit` | Liczba postów (1–100, domyślnie 25) |

**Przykład:**
```
GET /r/programming
GET /r/programming?after=1sdfgha&limit=10
```

**Odpowiedź:**
```json
{
  "posts": [
    {
      "id": "1sdfghj",
      "subreddit": "programming",
      "title": "Most annoying restrictions?",
      "body": "I'll go first...",
      "author": "mamaduck",
      "score": 42,
      "postType": "self",
      "linkUrl": "",
      "isGallery": false,
      "isPromoted": false,
      "flair": "Support",
      "createdAt": "2026-03-12T10:44:55+00:00",
      "scrapedAt": "2026-03-12T12:00:11+00:00",
      "permalink": "/r/programming/comments/1sdfghj",
      "url": "https://old.reddit.com/r/programming/comments/1sdfghj/..."
    }
  ],
  "pagination": {
    "after": "1sdfgha",
    "before": "1sdfgh6",
    "count": 25
  }
}
```

`flair` ma wartość `null` gdy post nie ma flary. Wartości `pagination.after` / `pagination.before` służą jako kursory do kolejnych zapytań.

---

#### `GET /r/{subreddit}/comments/{id}`

Zwraca pojedynczy post z pełnym drzewem komentarzy. ID posta może być podane z prefiksem `t3_` lub bez.

**Przykład:**
```
GET /r/programming/comments/1sdfghj
GET /r/programming/comments/t3_1sdfghj
```

**Odpowiedź:**
```json
{
  "post": { ...tak samo jak w listingu... },
  "comments": [
    {
      "id": "o9yp48e",
      "author": "Low-mama",
      "body": "The situation with your...",
      "score": 345,
      "createdAt": "2026-03-12T01:34:03+00:00",
      "isDeleted": false,
      "replies": [
        {
          "id": "o9yutkx",
          "author": "luckymamaduck",
          "body": "So funny...",
          "score": 103,
          "createdAt": "2026-03-12T02:06:58+00:00",
          "isDeleted": false,
          "replies": []
        }
      ]
    }
  ]
}
```

Komentarze zwracane są jako rekurencyjne drzewo. Usunięte komentarze mają puste `author` i `body` oraz `"isDeleted": true`.

### Baza danych

PostgreSQL z dwiema tabelami:

- **`posts`** — jeden wiersz na post; kolumna `data` zawiera pełny JSON posta (JSONB). Indeks na `(subreddit, timestamp DESC)`.
- **`comments`** — jeden wiersz na post; kolumna `data` zawiera pełne drzewo komentarzy. Powiązana z `posts` przez klucz obcy z kaskadowym usuwaniem.

Schemat tworzony jest automatycznie przy pierwszym uruchomieniu przez `db/init.sql`.

### Development

Logi:
```bash
docker compose logs -f scraper
docker compose logs -f api
```

Przebudowanie jednego serwisu po zmianie kodu:
```bash
docker compose up -d --build scraper
```

Połączenie z PostgreSQL:
```bash
docker compose exec postgres psql -U reddit -d reddit
```

Panel RabbitMQ: `http://localhost:15672` (domyślnie: `guest` / `guest`)

---

## EN 🇬🇧

A self-hosted Reddit scraper and REST API. Scrapes posts and comments from configured subreddits on an hourly schedule and serves them through a clean JSON API.

## Architecture

```
Scheduler (APScheduler)
    └── Scraper (Python/Playwright)
            │  scrapes old.reddit.com
            ↓
        RabbitMQ
            ↓
        Loader (Python)
            │  upserts posts + comments
            ↓
        PostgreSQL
            ↑
        API (Python/FastAPI)
            ↑
        HTTP clients
```

| Service | Role |
|---------|------|
| `scraper` | Scrapes old.reddit.com hourly using Playwright, publishes to RabbitMQ |
| `loader` | Consumes RabbitMQ messages, upserts posts and comments into PostgreSQL |
| `api` | FastAPI app serving the REST API on port 8080 |
| `postgres` | Persistent post and comment storage |
| `rabbitmq` | Message queue between scraper and loader |

## Getting Started

**Prerequisites:** Docker and Docker Compose.

```bash
cp .env.example .env   # or edit .env directly
docker compose up -d
```

The scraper runs immediately on startup, then every hour. The API is available at `http://localhost:8080`.

## Configuration

### Subreddits

Edit `config/subreddits.yaml`:

```yaml
subreddits:
  - programming
  - golang
lookback_hours: 72
```

The scraper watches this file and reloads it automatically — no restart needed.

Alternatively, set the `SUBREDDITS` environment variable (comma-separated) to override the YAML:

```
SUBREDDITS=programming,golang
```

### Environment Variables

All services are configured via `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_DB` | `reddit` | PostgreSQL database name |
| `POSTGRES_USER` | `reddit` | PostgreSQL user |
| `POSTGRES_PASSWORD` | `reddit` | PostgreSQL password |
| `POSTGRES_HOST` | `postgres` | PostgreSQL host |
| `RABBITMQ_HOST` | `rabbitmq` | RabbitMQ host |
| `RABBITMQ_USER` | `guest` | RabbitMQ user |
| `RABBITMQ_PASSWORD` | `guest` | RabbitMQ password |
| `RABBITMQ_EXCHANGE` | `reddit.posts` | RabbitMQ exchange name |
| `RABBITMQ_QUEUE` | `posts.ingest` | RabbitMQ ingest queue |
| `SUBREDDITS` | _(from YAML)_ | Comma-separated subreddit override |
| `LOOKBACK_HOURS` | `24` | How far back to scrape on each run |
| `CONFIG_PATH` | `/app/config/subreddits.yaml` | Path to subreddits config file |
| `API_PORT` | `8080` | Port the API listens on |

## API

### `GET /`

Health check. Returns `"OK"`.

---

### `GET /r/{subreddit}`

Returns the most recent posts for a subreddit, newest first.

**Query parameters:**

| Parameter | Description |
|-----------|-------------|
| `after` | Post ID cursor — returns older posts |
| `before` | Post ID cursor — returns newer posts |
| `limit` | Number of posts (1–100, default 25) |

**Example:**
```
GET /r/programming
GET /r/programming?after=1sdfgha&limit=10
```

**Response:**
```json
{
  "posts": [
    {
      "id": "1sdfghj",
      "subreddit": "programming",
      "title": "Most annoying restrictions?",
      "body": "I'll go first...",
      "author": "mamaduck",
      "score": 42,
      "postType": "self",
      "linkUrl": "",
      "isGallery": false,
      "isPromoted": false,
      "flair": "Support",
      "createdAt": "2026-03-12T10:44:55+00:00",
      "scrapedAt": "2026-03-12T12:00:11+00:00",
      "permalink": "/r/programming/comments/1sdfghj",
      "url": "https://old.reddit.com/r/programming/comments/1sdfghj/..."
    }
  ],
  "pagination": {
    "after": "1sdfgha",
    "before": "1sdfgh6",
    "count": 25
  }
}
```

`flair` is `null` when the post has no flair. Use `pagination.after` / `pagination.before` as cursor parameters in subsequent requests.

---

### `GET /r/{subreddit}/comments/{id}`

Returns a single post with its full comment tree. Accepts the post ID with or without the `t3_` prefix.

**Example:**
```
GET /r/programming/comments/1sdfghj
GET /r/programming/comments/t3_1sdfghj
```

**Response:**
```json
{
  "post": { ...same shape as listing... },
  "comments": [
    {
      "id": "o9yp48e",
      "author": "Low-mama",
      "body": "The situation with your...",
      "score": 345,
      "createdAt": "2026-03-12T01:34:03+00:00",
      "isDeleted": false,
      "replies": [
        {
          "id": "o9yutkx",
          "author": "luckymamaduck",
          "body": "So funny...",
          "score": 103,
          "createdAt": "2026-03-12T02:06:58+00:00",
          "isDeleted": false,
          "replies": []
        }
      ]
    }
  ]
}
```

Comments are returned as a recursive tree. Deleted comments have empty `author` and `body` with `"isDeleted": true`.

## Database

PostgreSQL with two tables:

- **`posts`** — one row per post; `data` column holds the full post JSON (JSONB). Indexed on `(subreddit, timestamp DESC)` for fast listing queries.
- **`comments`** — one row per post; `data` column holds the full comment tree JSON. Linked to `posts` via foreign key with cascade delete.

Schema is applied automatically on first run via `db/init.sql`.

## Development

View logs:
```bash
docker compose logs -f scraper
docker compose logs -f api
```

Rebuild and restart a single service after a code change:
```bash
docker compose up -d --build scraper
```

Connect to PostgreSQL:
```bash
docker compose exec postgres psql -U reddit -d reddit
```

RabbitMQ management UI: `http://localhost:15672` (default: `guest` / `guest`)
