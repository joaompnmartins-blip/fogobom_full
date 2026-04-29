# Fogo Bom Algarve

Sistema de gestão de fogo controlado — Django + HTMX + PostGIS.

## Estrutura

```
FogoBomAlgarve/
├── backend/
│   ├── core/           — auth, dashboard, calendário, FiredPT
│   ├── parcelas/       — CRUD parcelas + mapa Leaflet
│   ├── operatives/     — CRUD operacionais
│   ├── fire_actions/   — pré-planos, planos de queima, relatório Word
│   └── fire_mgmt/      — settings, urls, wsgi
├── Dockerfile
├── requirements.txt
└── render.yaml
```

## Arranque local

```bash
# 1. Criar base de dados PostgreSQL com PostGIS
psql -U postgres -c "CREATE DATABASE firedb;"
psql -U postgres -d firedb -c "CREATE EXTENSION postgis;"
psql -U postgres -c "CREATE USER fireuser WITH PASSWORD 'firepass';"
psql -U postgres -c "GRANT ALL ON DATABASE firedb TO fireuser;"

# 2. Copiar e preencher variáveis de ambiente
cp .env.example .env

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Migrations e arranque
cd backend
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
# → http://localhost:8000
```

## Deploy no Render

1. Push para GitHub
2. render.com → New → Blueprint → apontar para o repositório
3. O `render.yaml` cria o web service + base de dados automaticamente
4. Adicionar vars S3/R2 no dashboard se necessário para fotos persistentes

## URLs principais

| URL | Descrição |
|-----|-----------|
| `/` | Dashboard |
| `/login/` | Login / Registo |
| `/parcelas/` | Lista de parcelas |
| `/parcelas/nova/` | Nova parcela (com mapa draw) |
| `/operacionais/` | Lista de operacionais |
| `/preplan/` | Lista de pré-planos |
| `/preplan/burning/` | Lista de planos de queima |
| `/meteorologia/` | FiredPT integrado |
| `/calendario/` | Calendário de queimas |
| `/admin/` | Django admin |
