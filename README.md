# Fogo Bom Algarve

Sistema de gestão de fogo controlado — Django + GeoDjango/PostGIS + Leaflet.

## Estrutura

```
fogobom_full/
├── backend/
│   ├── core/           — autenticação, aprovação de utilizadores, dashboard, calendário, meteorologia (FiredPT)
│   ├── parcelas/       — parcelas (polígonos PostGIS, área, mapa Leaflet)
│   ├── operatives/     — operacionais
│   ├── fire_actions/   — pré-planos, planos de queima, relatório Word
│   └── fire_mgmt/      — settings, urls, wsgi
├── .github/workflows/  — testes automáticos (CI)
├── Dockerfile
└── requirements.txt
```

## Produção (Railway)

- **Deploy automático**: cada push para `main` no GitHub faz build do `Dockerfile` e deploy no Railway
  (projeto `zesty-bravery`, serviço `fogobom-algarve`, ambiente `production`).
- **Arranque**: o container corre `migrate`, `ensure_superuser` e depois `gunicorn`.
- **Base de dados**: serviço PostGIS no mesmo projeto Railway (com volume próprio).
- **Ficheiros carregados** (fotos, esquemas): ficam em `backend/media`, que deve estar montado num
  volume Railway (mount path `/app/backend/media`); sem volume perdem-se a cada deploy.
  Em alternativa, definir as variáveis `AWS_*` para usar S3/R2.

### Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `SECRET_KEY` | sim | Chave secreta do Django (a app não arranca sem ela com `DEBUG=false`) |
| `DEBUG` | não | `false` por omissão; `true` só em desenvolvimento |
| `ALLOWED_HOSTS` | sim | Domínios aceites, separados por vírgulas |
| `CSRF_TRUSTED_ORIGINS` | não | Origens adicionais para CSRF (ex.: `https://dominio`) |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | sim | Ligação PostGIS |
| `RESEND_API_KEY` | sim* | Envio de emails (SMTP Resend) — aprovação de utilizadores |
| `DEFAULT_FROM_EMAIL`, `ADMIN_EMAIL` | sim* | Remetente e destinatário dos avisos de novos registos |
| `DJANGO_SUPERUSER_USERNAME`, `_EMAIL`, `_PASSWORD` | não | Cria o superuser no primeiro arranque (não altera um existente) |
| `CARTO_API_KEY` | não | Chave dos mapas base CARTO (sem ela aparece marca d'água) |
| `MAPTILER_API_KEY` | não | Relevo/declive na página de Meteorologia |
| `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS` | não | HTTPS; por omissão `true` / `3600` quando `DEBUG=false` |
| `AWS_STORAGE_BUCKET_NAME`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_REGION_NAME`, `AWS_S3_ENDPOINT_URL`, `AWS_S3_CUSTOM_DOMAIN` | não | Guardar ficheiros em S3/R2 em vez do disco |

\* necessárias para os emails funcionarem.

Nunca colocar chaves no código nem no repositório — apenas nas variáveis do Railway.

## Utilizadores e permissões

- Novos utilizadores registam-se em `/login/` e ficam **pendentes** até um membro *staff* os aprovar em
  *Utilizadores Pendentes*.
- Utilizadores aprovados podem consultar, criar e editar; **apagar registos é reservado a staff**.
- Para tornar alguém staff: `/admin/` → Utilizadores → marcar *Estado de membro da equipa*.

## Testes

Os testes correm automaticamente no GitHub Actions a cada push (build da imagem Docker + PostGIS).
Para correr manualmente num ambiente com PostGIS:

```bash
cd backend
python manage.py test
```

## Desenvolvimento local

Requer PostgreSQL com PostGIS e as bibliotecas GDAL/GEOS (a versão do pacote Python `GDAL` em
`requirements.txt` tem de corresponder à `libgdal` instalada).

```bash
# 1. Base de dados
psql -U postgres -c "CREATE DATABASE firedb;"
psql -U postgres -d firedb -c "CREATE EXTENSION postgis;"
psql -U postgres -c "CREATE USER fireuser WITH PASSWORD 'firepass';"
psql -U postgres -c "GRANT ALL ON DATABASE firedb TO fireuser;"

# 2. Variáveis de ambiente (o Django não lê o .env sozinho)
cp .env.example .env          # editar valores
set -a; . ./.env; set +a

# 3. Dependências e arranque
pip install -r requirements.txt
cd backend
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver    # → http://localhost:8000
```

## URLs principais

| URL | Descrição |
|-----|-----------|
| `/` | Dashboard |
| `/login/` | Login / Registo |
| `/parcelas/` | Lista de parcelas |
| `/parcelas/nova/` | Nova parcela (desenho no mapa ou importação GeoJSON/KML) |
| `/operacionais/` | Lista de operacionais |
| `/preplan/` | Lista de pré-planos |
| `/preplan/burning/` | Lista de planos de queima (relatório Word em cada plano) |
| `/meteorologia/` | Meteorologia e humidade de combustíveis (FiredPT) |
| `/calendario/` | Calendário de queimas |
| `/utilizadores/pendentes/` | Aprovação de novos utilizadores (staff) |
| `/admin/` | Administração Django |
