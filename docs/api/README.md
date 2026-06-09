# API Documentation

> Placeholder — generate OpenAPI from gateway-service when routes are implemented.

## Base URL

- Development: `http://localhost:8000/api`
- Production: TBD (behind nginx)

## Service map

| Prefix | Owning service |
|--------|----------------|
| `/auth` | gateway-service |
| `/users` | gateway-service |
| `/meetings` | gateway-service → meeting-service |
| `/search` | gateway-service → search-service |
| `/analytics` | gateway-service |
| `/integrations` | gateway-service |

## TODO

- Publish OpenAPI 3.1 spec
- Add authentication examples
- Webhook documentation for integrations
